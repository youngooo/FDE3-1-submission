"""Add metric querying to the existing Agent conversation, without a second UI."""
from pathlib import Path
import json,hashlib
from ..agent import Agent
from .agent import MetricsAgent
from .common import read

class UpgradedAgent(Agent):
 def __init__(self,*args,metrics_project=None,**kwargs):
  super().__init__(*args,**kwargs)
  self.metrics=MetricsAgent(metrics_project,self.home/'metric-runs',self.model)
  self.customer_label=self.metrics.scope.get('customer','当前客户')
  self.prompt='你是标准会员运营 Agent。当前已加载指标库，用中文回答。查询任务通过 query_metrics 获取证据，不能自行编造 SQL、数字或成功结果。以下旧样例规则只在用户明确要求松果生活样例任务时适用，不要求一般指标查询提供两个比较时段。\n<legacy_sample_rules>\n'+self.prompt+'\n</legacy_sample_rules>\n本产品已增加指标问数能力。当前指标客户：'+self.customer_label+'。现有 describe_business、compare_spending、member_history 和标签动作仅属于松果生活独立样例；不能用样例结果回答当前客户问题。查询报表数值、指标定义范围、月度表现等需求时调用 query_metrics，把用户的原始问题和必要的澄清上下文一起传入，不自行改写时间或补指标含义。即使问题含糊也可交给 query_metrics 返回澄清。只有明确需要松果样例消费比较或样例动作时才使用原工具。当前指标库不支持客户自然语言圈选、营销执行或收益归因，不能用松果工具假装实现。\n当前指标目录：'+json.dumps([{'id':x['id'],'name':x['name'],'aliases':x.get('aliases',[])} for x in self.metrics.catalog],ensure_ascii=False)
  self.prompt_hash=hashlib.sha256(self.prompt.encode()).hexdigest()
 def schemas(self,action_mode):
  return super().schemas(action_mode)+[{'type':'function','function':{'name':'query_metrics','description':'查询当前客户指标；缺信息时返回澄清，支持的查询实际编译并执行。不会执行营销动作。','parameters':{'type':'object','properties':{'question':{'type':'string','minLength':1,'maxLength':6000}},'required':['question'],'additionalProperties':False}}}]
 def tool_node(self,state):
  calls=state['messages'][-1].get('tool_calls',[])
  metric_calls=[c for c in calls if c.get('function',{}).get('name')=='query_metrics']
  if not metric_calls:return super().tool_node(state)
  # A query is a complete read-only task; do not execute unrelated simultaneous action proposals.
  messages=list(state['messages']);observations=list(state['observations'])
  for c in calls:
   if c not in metric_calls:result={'status':'error','code':'SEPARATE_TASK_REQUIRED'}
   else:
    try:
     args=json.loads(c['function']['arguments'])
     if set(args)!={'question'}:raise ValueError()
     history=[{'role':m['role'],'content':m.get('content','')} for m in state['messages'][:-1] if m.get('role') in ['user','assistant'] and not m.get('tool_calls')]
     result=self.metrics.ask(args['question'],history)
    except (ValueError,TypeError,KeyError):result={'status':'error','code':'INVALID_ARGUMENTS'}
   observations.append({'name':c['function']['name'],'result':result,'call_id':c.get('id','invalid')})
   messages.append({'role':'tool','tool_call_id':c.get('id','invalid'),'content':json.dumps(result,ensure_ascii=False)})
  usage=dict(state.get('usage',{}))
  for observation in observations[len(state['observations']):]:
   for key,value in observation['result'].get('model_usage',{}).items():
    if isinstance(value,(int,float)) and not isinstance(value,bool):usage[key]=usage.get(key,0)+value
  return {'messages':messages,'observations':observations,'draft':None,'usage':usage}
 def model_node(self,state):
  evidence=[x['result'] for x in state.get('observations',[]) if x['name']=='query_metrics']
  if not evidence:return super().model_node(state)
  actual=evidence[-1];status={'ok':'completed','clarify':'clarification','unsupported':'refused','error':'incomplete'}.get(actual.get('status'),'incomplete')
  result={'status':status,'summary':actual.get('answer') or actual.get('reason') or actual.get('code','查询未完成'),'recommendations':[],'evidence_ids':[actual['trace_id']] if actual.get('trace_id') else [],'metric_query':actual}
  return {'result':result,'time_options':[],'time_options_token':'','messages':state['messages']+[{'role':'assistant','content':json.dumps(result,ensure_ascii=False)}]}

def active_project(home):
 path=Path(home)/'metrics-binding.json'
 if not path.exists():return None
 data=read(path);project=Path(data['project'])
 if not (project/'dataset.json').exists():raise ValueError('METRICS_PROJECT_NOT_FOUND: reload the library for this product home')
 return project
