"""Natural language -> validated intent -> native SQL -> executed evidence."""
import json,uuid,time,threading
from pathlib import Path
from .common import read,dump,call_json
from .answer_display_facts import build_answer_display_facts
from .intent_context import prepare_intent_context
ROOT=Path(__file__).resolve().parents[3]
class MetricsAgent:
 def __init__(self,project,out=None,model=None):
  self.project=Path(project).resolve();self.catalog=read(self.project/'catalog.json');self.scope=read(self.project/'scope.json');self.data=read(self.project/'dataset.json')
  self.out=Path(out) if out else self.project/'runs';self.model=model
 def ask(self,question,history=None):
  if not isinstance(question,str) or not question.strip() or len(question)>6000:raise ValueError('QUESTION_INVALID')
  from .engine import query_worker
  folder=self.out/str(uuid.uuid4());folder.mkdir(parents=True,exist_ok=False);start=time.monotonic()
  dimensions_full=read(self.project/'dimensions.json')
  dimensions,values,context_summary=prepare_intent_context(question,(history or [])[-6:],dimensions_full)
  dump(folder/'intent-context-summary.json',context_summary)
  try:
   intent=call_json((ROOT/'product/w03_intent_prompt.txt').read_text(),{'question':question,'history':(history or [])[-6:],'customer_context':self.scope,'data_context':self.data,'catalog':self.catalog,'filter_values':values,'filter_value_metadata':context_summary['fields'],'available_dimensions':dimensions},folder/'intent-trace.json',model=self.model)
   if intent.get('status') in ['clarify','unsupported']:
    if not isinstance(intent.get('reason'),str) or not intent['reason'].strip():raise ValueError('INTENT_REASON_REQUIRED')
    result={'status':intent['status'],'reason':intent['reason'],'intent':intent}
   elif intent.get('status')=='query':
    intent={k:intent.get(k,[]) for k in ['metrics','start','end','group_by','filters']};result=query_worker(self.project,intent);result.setdefault('intent',intent)
    if result['status']=='ok':
     answer=call_json((ROOT/'product/w03_answer_prompt.txt').read_text(),{'question':question,'customer_context':self.scope,'data_context':self.data,'result':{k:v for k,v in result.items() if k!='sql'},'definitions':[x for x in self.catalog if x['id'] in intent['metrics']],'answer_display_facts':build_answer_display_facts(result,[x for x in self.catalog if x['id'] in intent['metrics']])},folder/'answer-trace.json',model=self.model)
     if not isinstance(answer.get('answer'),str):raise ValueError('ANSWER_TEXT_REQUIRED')
     result['answer']=answer['answer']
   else:raise ValueError('INTENT_STATUS_INVALID')
  except Exception as exc:
   result={'status':'error','code':getattr(exc,'code',str(exc) if isinstance(exc,ValueError) else type(exc).__name__),'reason':'本次调用未完成，请查看运行记录；不能把失败当成零。'}
  usage={};accounted=0
  for trace in folder.glob('*-trace.json'):
   observation=read(trace).get('usage',{})
   if observation:accounted+=1
   for key in ('prompt_tokens','completion_tokens','total_tokens'):
    value=observation.get(key)
    if isinstance(value,(int,float)) and not isinstance(value,bool):usage[key]=usage.get(key,0)+value
  result.update(question=question,trace_id=folder.name,elapsed_seconds=round(time.monotonic()-start,3),model_usage=usage,model_calls_with_usage=accounted);dump(folder/'result.json',result);return result
