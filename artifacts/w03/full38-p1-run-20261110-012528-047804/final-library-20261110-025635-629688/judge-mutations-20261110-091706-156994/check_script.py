"""Exercise the final judge over copies of real results, with exact rejection reasons."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import run_w03_full38_nl_20261110 as runner

ROOT,FINAL=runner.ROOT,runner.FINAL_RUN
SOURCES={
    'small':FINAL/'nl-small-paid-formula-20261110-031651-683666/results/metric_test_report.json',
    'large':FINAL/'nl-large-full-20261110-031957-483250/results/metric_test_report.json',
}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def prepare():
    runner.RUN=FINAL;runner.PLAN=Path(read(FINAL/'regression_plan.json')['plan'])
    plan,entry,_,_,judge,hashes=runner.prepare(SimpleNamespace(dataset='large',stage='full',final_library=True))
    rows={size:{c['id']:c for c in read(path)['cases']} for size,path in SOURCES.items()}
    fixtures=[]
    def add(cid,size,base,edit=None,kind=None,detail=None):
        c=rows[size][base];actual=deepcopy(c['actual'])
        if edit:edit(actual)
        fixtures.append(dict(id=cid,source_dataset=size,source_case=base,expected=deepcopy(c['expected']),actual=actual,
            should_pass=kind is None,required_difference=None if kind is None else dict(kind=kind,**(detail or {}))))
    def setvalue(a,metric,value,row=0):a['rows'][row][a['columns'].index(metric)]=value
    def altervalue(metric,f):
        def edit(a):
            idx=a['columns'].index(metric);a['rows'][0][idx]=f(a['rows'][0][idx])
        return edit
    for size,base in [('large','paid_pair'),('large','paid_coverage'),('small','paid_zero_month'),
        ('large','orders_store_filter'),('large','nonexistent_filter'),('large','reject_undefined_metric'),('large','clarify_year')]:
        add('control_'+base,size,base)
    add('control_reordered_rows','large','paid_pair',lambda a:a['rows'].reverse())
    add('control_equivalent_unit','large','paid_pair',lambda a:a['units'].__setitem__('monthly_paid_avg_order_value','cents/order'))
    def clarify(a):
        a['status']='clarify';a['intent']['status']='clarify'
    add('control_missing_filter_clarify','large','nonexistent_filter',clarify)
    count='monthly_paid_buyer_count';sales='monthly_paid_sales_cents';rate='monthly_paid_repeat_rate';avg='monthly_paid_avg_order_value'
    for cid,metric,change in [('paid_count_plus_one',count,lambda v:v+1),('paid_cents_plus_one',sales,lambda v:v+1),
        ('paid_ratio_times_100',rate,lambda v:v*100),('paid_average_divided_100',avg,lambda v:v/100)]:
        add(cid,'large','paid_pair',altervalue(metric,change),'value_mismatch',{'metric':metric})
    add('paid_cents_labelled_yuan','large','paid_pair',lambda a:a['units'].__setitem__(sales,'yuan'),'invalid_actual_table',{'reason':'Unsupported metric unit: '+sales})
    add('paid_ratio_labelled_count','large','single_monthly_paid_repeat_rate',lambda a:a['units'].__setitem__(rate,'count'),'invalid_actual_table',{'reason':'Non-integer count or cents'})
    add('paid_average_wrong_supported_unit','large','paid_pair',lambda a:a['units'].__setitem__(avg,'cents_per_account'),'unit_mismatch',{'metric':avg})
    add('zero_ratio_forged','small','paid_zero_month',lambda a:setvalue(a,rate,0),'value_mismatch',{'metric':rate})
    add('zero_sales_changed_null','small','paid_zero_month',lambda a:setvalue(a,sales,None),'value_mismatch',{'metric':sales})
    add('count_boolean','large','paid_pair',lambda a:setvalue(a,count,True),'invalid_actual_table',{'reason':'Not a number'})
    add('ratio_nan','large','paid_pair',lambda a:setvalue(a,rate,'NaN'),'invalid_actual_table',{'reason':'Non-finite number'})
    add('cents_fractional','large','paid_pair',altervalue(sales,lambda v:v+0.1),'invalid_actual_table',{'reason':'Non-integer count or cents'})
    add('missing_month','large','paid_coverage',lambda a:a['rows'].pop(),'group_mismatch')
    add('duplicate_month','large','paid_pair',lambda a:a['rows'].append(deepcopy(a['rows'][0])),'invalid_actual_table',{'reason':'Duplicate group key'})
    add('invalid_month_day','large','paid_pair',lambda a:a['rows'][0].__setitem__(0,'2026-05-02'),'invalid_actual_table',{'reason':'Month must be the first day at midnight'})
    add('wrong_start','large','paid_pair',lambda a:a['intent'].__setitem__('start','2026-04-01'),'intent_mismatch',{'field':'start'})
    add('wrong_end','large','paid_pair',lambda a:a['intent'].__setitem__('end','2026-08-01'),'intent_mismatch',{'field':'end'})
    add('wrong_metric','large','paid_pair',lambda a:a['intent']['metrics'].__setitem__(0,'buyer_count'),'intent_mismatch',{'field':'metrics'})
    add('wrong_dimension','large','paid_pair',lambda a:a['intent'].__setitem__('group_by',['home_store']),'intent_mismatch',{'field':'group_by'})
    add('missing_filter','large','orders_store_filter',lambda a:a['intent'].__setitem__('filters',[]),'intent_mismatch',{'field':'filters'})
    add('wrong_filter_value','large','orders_store_filter',lambda a:a['intent']['filters'][0].__setitem__('value','S01'),'intent_mismatch',{'field':'filters'})
    for field in ['data_version','data_sha256','catalog_sha256']:
        add('wrong_'+field,'large','paid_pair',lambda a,f=field:a.__setitem__(f,'injected-wrong-version'),'version_mismatch',{'field':field})
    add('query_error','large','paid_pair',lambda a:a.__setitem__('status','error'),'status_mismatch')
    add('error_marker_in_success','large','paid_pair',lambda a:a.__setitem__('error','injected error'),'error_markers_in_ok_result')
    add('undefined_metric_clarify','large','reject_undefined_metric',clarify,'status_mismatch')
    add('missing_filter_returns_rows','large','nonexistent_filter',lambda a:a.__setitem__('rows',[[0]]),'unexpected_rows_for_non_ok')
    add('missing_filter_no_reason','large','nonexistent_filter',lambda a:a.__setitem__('reason',''),'missing_boundary_reason')
    add('missing_year_defaulted','large','clarify_year',lambda a:a.__setitem__('status','ok'),'status_mismatch')
    judge_path=Path(plan['judge_script'])
    results=[]
    for fixture in fixtures:
        proc=subprocess.run([sys.executable,'-B',str(judge_path)],input=json.dumps(dict(expected=fixture['expected'],actual=fixture['actual']),ensure_ascii=False,allow_nan=False),
            text=True,encoding='utf-8',capture_output=True,timeout=20,cwd=ROOT)
        assert proc.returncode==0,fixture['id']
        verdict=json.loads(proc.stdout)
        assert isinstance(verdict.get('passed'),bool) and isinstance(verdict.get('differences'),list)
        assert verdict['passed']==(not verdict['differences'])
        assert not any(d['kind'] in {'judge_input_or_internal_error','invalid_expected','invalid_expected_intent','invalid_expected_table'} for d in verdict['differences'])
        wanted=fixture['required_difference']
        matched=verdict['passed'] if wanted is None else (not verdict['passed'] and all(all(d.get(k)==v for k,v in wanted.items()) for d in verdict['differences']))
        results.append({**fixture,'verdict':verdict,'rejection_reason_matches_mutation':matched,'passed':matched})
    assert all(r['passed'] for r in results),json.dumps([dict(id=r['id'],required=r['required_difference'],verdict=r['verdict']) for r in results if not r['passed']],ensure_ascii=False)
    hashes.update({str(p):sha(p) for p in SOURCES.values()})
    hashes[str(Path(__file__))]=sha(Path(__file__))
    assert all(sha(Path(p))==digest for p,digest in hashes.items())
    return results,hashes,judge_path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');args=p.parse_args()
    results,hashes,judge_path=prepare()
    positives=sum(r['should_pass'] for r in results);negatives=len(results)-positives
    print(f'检查通过：正向对照{positives}/{positives}；错误注入{negatives}/{negatives}被拒，理由均匹配改动字段。')
    if not args.apply:
        print('只读检查完成，未保存报告、未查询或调用模型。');return
    dest=FINAL/('judge-mutations-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    for r in results:save(dest/(r['id']+'.json'),r)
    report=dict(kind='final38_judge_mutation_review',passed=True,complete=True,positive_controls_passed=positives,positive_controls_total=positives,
        mutations_rejected=negatives,mutations_total=negatives,reasons_match=True,library_sha256=runner.FINAL_HASH,
        judge=str(judge_path),source_reports={size:str(p) for size,p in SOURCES.items()},input_sha256=hashes,
        method='Each mutation changes only a copy of an actual final-library result; independent expected values unchanged; judge called via stdin/stdout.',
        model_called=False,query_executed=False,limitations=['只验证结构化判定；文字语义另行逐条核查','错误变体不是新的业务问数结果'],
        cases=[{k:r[k] for k in ['id','source_dataset','source_case','should_pass','required_difference','verdict','passed']} for r in results])
    save(dest/'report.json',report)
    (dest/'check_script.py').write_bytes(Path(__file__).read_bytes())
    (dest/'judge_wrapper.py').write_bytes(judge_path.read_bytes())
    (dest/'judge.py').write_bytes((ROOT/'customer/w03/judge.py').read_bytes())
    assert read(dest/'report.json')==report and all(sha(Path(p))==d for p,d in hashes.items())
    print('错误注入证据已保存并回读核验：'+str(dest))
    print('未修改判定器、期望、原报告、指标库或聊天绑定；未调用模型。')


if __name__=='__main__':main()
