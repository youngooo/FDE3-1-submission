"""Five targeted live checks; independent CSV expectations; no prompt dumping."""
import argparse, csv, hashlib, json, sys
from pathlib import Path
from collections import Counter, defaultdict

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--output',required=True)
 parser.add_argument('--project')
 parser.add_argument('--data',default='materials/data/small')
 args=parser.parse_args()
 root=Path(__file__).resolve().parents[2]
 sys.path.insert(0,str(root/'platform'))
 sys.path.insert(0,str(root/'customer/w03'))
 from fde_product.metrics.agent import MetricsAgent
 from fde_product.metrics.common import configured_model
 import judge
 out=Path(args.output).resolve()
 if out.exists():raise SystemExit('OUTPUT_ALREADY_EXISTS: use a new directory')
 project=Path(args.project).resolve() if args.project else Path(json.loads((root/'.runtime/product/metrics-binding.json').read_text())['project'])
 dataset=json.loads((project/'dataset.json').read_text())
 assert dataset['reference_date']=='2026-09-01','本次相对时间对照要求参考日2026-09-01'
 data=Path(args.data).resolve(); orders=data/'orders.csv'
 digest=hashlib.sha256(orders.read_bytes()).hexdigest()
 assert digest==dataset['sha256']['orders.csv'],'期望CSV与项目版本不一致'
 activity=defaultdict(Counter)
 with orders.open(encoding='utf-8-sig',newline='') as f:
  for row in csv.DictReader(f):
   if row['status']=='paid' and int(row['paid_cents'])>int(row['refund_cents']):
    activity[row['ordered_at'][:7]][row['member_id']]+=1
 def rate(month):
  counts=activity[month]
  return sum(v>=2 for v in counts.values())/len(counts) if counts else None
 def expected(months):
  grouped=len(months)>1
  return {'status':'ok','intent':{'metrics':['monthly_repeat_rate'],'start':months[0]+'-01','end':'2026-09-01','group_by':['metric_time__month'] if grouped else [],'filters':[]},'columns':(['metric_time__month'] if grouped else [])+['monthly_repeat_rate'],'rows':[[m+'-01 00:00:00',rate(m)] if grouped else [rate(m)] for m in months],'units':{'monthly_repeat_rate':'ratio'},'data_version':dataset['id'],'data_sha256':dataset.get('data_sha256',None) or None}
 def clean_expected(months):
  value=expected(months)
  # Engine computes the dataset digest from the manifest; avoid guessing its key.
  value.pop('data_sha256',None)
  return value
 q='青禾7月和8月的月内复购率分别是多少？'
 cases=[
  {'id':'missing_year_empty_history','question':q,'history':[],'expected':{'status':'clarify'}},
  {'id':'assistant_year_is_not_confirmation','question':q,'history':[{'role':'user','content':q},{'role':'assistant','content':'2026年7月为9.09%，8月为80.00%。'}],'expected':{'status':'clarify'}},
  {'id':'explicit_year','question':'青禾2026年7月和8月的月内复购率分别是多少？','history':[],'expected':clean_expected(['2026-07','2026-08'])},
  {'id':'user_year_context','question':q,'history':[{'role':'assistant','content':'请问查询哪一年？'},{'role':'user','content':'2026年。'}],'expected':clean_expected(['2026-07','2026-08'])},
  {'id':'relative_previous_month','question':'青禾上个月的月内复购率是多少？','history':[],'expected':clean_expected(['2026-08'])},
 ]
 # Configuration is checked before creating a misleading test report.
 model=configured_model()
 out.mkdir(parents=True)
 (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
 report={'kind':'time_context_targeted_regression','complete':False,'passed':0,'total':len(cases),'project':str(project),'expected_basis':'材料03/05，原始orders.csv独立按账户月统计；不从实际结果反填','source_sha256':{'orders.csv':digest},'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'prompt_sha256':hashlib.sha256((root/'product/w03_intent_prompt.txt').read_bytes()).hexdigest(),'cases':[]}
 agent=MetricsAgent(project,out/'traces',model=model)
 for c in cases:
  actual=agent.ask(c['question'],c['history'])
  comparison=judge.compare(c['expected'],actual)
  if c['expected']['status']=='clarify':
   differences=[]
   intent=actual.get('intent',{})
   if intent.get('start') or intent.get('end'):differences.append({'kind':'invented_date_in_clarification'})
   if actual.get('sql') or actual.get('rows'):differences.append({'kind':'unexpected_query_on_missing_year'})
   if differences:
    comparison={'passed':False,'differences':comparison.get('differences',[])+differences}
  report['cases'].append({**c,'actual':actual,'comparison':comparison})
  report['passed']+=int(comparison['passed'])
  (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print(('PASS ' if comparison['passed'] else 'FAIL ')+c['id'],flush=True)
  if actual.get('status')=='error':
   print('STOP',actual.get('code'),'remaining cases not run',flush=True)
   break
 report['complete']=len(report['cases'])==len(cases)
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'complete':report['complete'],'passed':report['passed'],'total':report['total'],'report':str(out/'report.json')},ensure_ascii=False,indent=2))
 return 0 if report['complete'] and report['passed']==report['total'] else 1

if __name__=='__main__':
 raise SystemExit(main())
