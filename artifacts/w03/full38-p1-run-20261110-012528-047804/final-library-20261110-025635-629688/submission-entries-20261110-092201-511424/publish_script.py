"""Publish byte-identical final cases/report and portable reproduction entrypoints."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import run_w03_full38_nl_20261110 as runner
from types import SimpleNamespace

ROOT,FINAL=runner.ROOT,runner.FINAL_RUN
EVIDENCE=FINAL/'regression-verification-20261110-090359-069796'
MUTATIONS=FINAL/'judge-mutations-20261110-091706-156994/report.json'
REPORTS={'small':FINAL/'nl-small-full-20261110-030115-607746/results/metric_test_report.json',
         'large':FINAL/'nl-large-full-20261110-031957-483250/results/metric_test_report.json'}
RETEST=FINAL/'nl-small-paid-formula-20261110-031651-683666/results/metric_test_report.json'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def encoded(obj):return (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def relative(p):return str(p.relative_to(ROOT))


def prepare():
    runner.RUN=FINAL;runner.PLAN=Path(read(FINAL/'regression_plan.json')['plan'])
    plan=read(runner.PLAN)
    evidence=read(EVIDENCE/'summary.json')
    assert evidence['library_sha256']==runner.FINAL_HASH
    assert sha(Path(evidence['archive']).read_bytes())==evidence['archive_sha256']
    mutations=read(MUTATIONS)
    assert mutations['passed'] and mutations['positive_controls_passed']==10 and mutations['mutations_rejected']==30 and mutations['reasons_match']
    inputs={};output={};entries=[]
    def stage(rel,raw):
        path=ROOT/rel
        assert path.resolve().is_relative_to(ROOT)
        inputs[rel]=path.read_bytes() if path.exists() else None
        output[rel]=raw
    source_judge=Path(plan['judge_script']).read_text()
    root_line="ROOT=Path('/home/yang/FDE/w03-work/fde-agent-w03')"
    assert source_judge.count(root_line)==1
    portable_judge=source_judge.replace(root_line,'ROOT=Path(__file__).resolve().parents[2]')
    namespace={'__file__':str(ROOT/'customer/w03/judge_full38.py'),'__name__':'preview_full38_judge'}
    exec(compile(portable_judge,namespace['__file__'],'exec'),namespace)
    assert namespace['self_checks']()==8
    protected={}
    for size in ['small','large']:
        _,entry,_,cases,judge,hashes=runner.prepare(SimpleNamespace(dataset=size,stage='full',final_library=True))
        protected.update(hashes)
        report=read(REPORTS[size]);by_id={c['id']:c for c in cases}
        assert report['complete'] and report['passed']==report['total']==len(cases)
        for c in report['cases']:
            assert c['question']==by_id[c['id']]['question'] and c['expected']==by_id[c['id']]['expected']
            assert namespace['compare'](c['expected'],c['actual'])==c['comparison']
        cases_raw=Path(entry['cases']).read_bytes()
        stage('customer/w03/tests-'+size+'.json',cases_raw)
        if size=='large':stage('customer/w03/tests.json',cases_raw)
        entries.append(dict(dataset=size,cases='customer/w03/tests-'+size+'.json',cases_sha256=sha(cases_raw),cases_total=len(cases),
            project=relative(Path(entry['project'])),execution_report=relative(REPORTS[size]),execution_report_sha256=sha(REPORTS[size].read_bytes()),
            execution_passed=len(cases),data_version=read(Path(entry['project'])/'dataset.json')['id'],
            answer_review=relative(EVIDENCE/'answer_reviews.json'),
            answer_state='full_review_passed_with_notes' if size=='large' else 'one_original_formula_explanation_corrected_and_retested',
            correction_retest=None if size=='large' else relative(RETEST),status='executed'))
    for c in read(RETEST)['cases']:
        assert namespace['compare'](c['expected'],c['actual'])==c['comparison']
    for c in mutations['cases']:
        payload=read(MUTATIONS.parent/(c['id']+'.json'))
        assert namespace['compare'](payload['expected'],payload['actual'])==payload['verdict']
    stage('customer/w03/judge_full38.py',portable_judge.encode('utf-8'))
    stage('artifacts/w03/metric_test_report.json',REPORTS['large'].read_bytes())
    merged_plan=dict(kind='official_merged38_regression_plan',library='artifacts/w03/library',library_sha256=runner.FINAL_HASH,
        metrics=38,default_dataset='large',canonical_cases='customer/w03/tests.json',canonical_report='artifacts/w03/metric_test_report.json',
        judge='customer/w03/judge_full38.py',judge_sha256=sha(portable_judge.encode()),base_judge_sha256=sha((ROOT/'customer/w03/judge.py').read_bytes()),
        answer_prompt_sha256=plan['answer_prompt_sha256'],intent_prompt_sha256=plan['intent_prompt_sha256'],
        entries=entries,business_confirmation='pending',final_38_acceptance=False)
    stage('customer/w03/merged_regression_plan.json',encoded(merged_plan))
    metadata={**merged_plan,'kind':'official38_test_entrypoints',
        'canonical_report_selection_reason':'Latest-prompt full large run, all67 structured pass and answers reviewed; copied byte-for-byte.',
        'evidence':relative(EVIDENCE),'judge_mutations':relative(MUTATIONS),
        'small_latest_prompt_scope':'9 unchanged cases rerun after formula explanation correction; not a second full69 run.',
        'publication_calls_model':False,'publication_runs_queries':False}
    stage('customer/w03/test_entrypoints.json',encoded(metadata))
    note='''正式入口：38项官方merge库，六项付费指标为P1暂定试算，总部适用性待书面确认。
tests.json与tests-large.json均为规模集67条；tests-small.json为小样本69条。两套各覆盖38项，问句和月份有变化。
artifacts/w03/metric_test_report.json原样复制最新提示下的规模集67/67报告；原始文件及回答未改写。
小样本原始69/69报告中发现一处付费复购率公式解释错误，修正提示后9/9定向复测通过；原报告与补充复测分别保留，不拼接。
具体版本、项目、时间和报告见test_entrypoints.json及merged_regression_plan.json。
只读预检：.venv/bin/python -B customer/w03/run_merged_regression.py --dataset small（或large）
真实复跑：上面命令加 --run，将调用模型；输出新目录，不覆盖历史报告。
更换工作目录后，先依课程README用正式库和对应CSV加载新项目，再更新计划的项目路径；不能沿用不匹配的项目或数据。
总部确认、框架改动说明、SOW整理与聊天绑定仍须单独处理。预检通过不是客户验收。
'''
    stage('customer/w03/test_entrypoints.txt',note.encode('utf-8'))
    old_runner=(ROOT/'customer/w03/run_merged_regression.py').read_text()
    # Keep the existing portable course test wrapper; update version and judge selection guards.
    new_runner=old_runner.replace("default='small'","default='large'")
    new_runner=new_runner.replace('    args=parser.parse_args()',"    parser.add_argument('--run',action='store_true')\n    args=parser.parse_args()")
    new_runner=new_runner.replace('    if missing:', '    if args.run and missing:')
    anchor="    out=root/('artifacts/w03/test-merged-'"
    assert anchor in new_runner
    checks="""    judge_path=root/plan['judge']
    assert hashlib.sha256(judge_path.read_bytes()).hexdigest()==plan['judge_sha256'],'JUDGE_CHANGED'
    assert hashlib.sha256((root/'customer/w03/judge.py').read_bytes()).hexdigest()==plan['base_judge_sha256'],'BASE_JUDGE_CHANGED'
    for field,filename in [('answer_prompt_sha256','w03_answer_prompt.txt'),('intent_prompt_sha256','w03_intent_prompt.txt')]:
        assert hashlib.sha256((root/'product'/filename).read_bytes()).hexdigest()==plan[field],'PROMPT_CHANGED'
    assert json.loads((root/entry['project']/'validation.json').read_text())['passed'],'PROJECT_NOT_VALIDATED'
    for p in [(root/plan['library'])/'metrics.yml',*(root/plan['library']).glob('*.sql')]:
        assert p.read_bytes()==(root/entry['project']/'models'/p.name).read_bytes(),'PROJECT_MODEL_CHANGED'
    manifest=json.loads((root/'materials/data'/args.dataset/'manifest.json').read_text())
    assert dataset['sha256']==manifest['sha256'],'DATA_MANIFEST_CHANGED'
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((root/'materials/data'/args.dataset/name).read_bytes()).hexdigest()==digest,'RAW_DATA_CHANGED'
    if not args.run:
        print('只读预检通过：'+args.dataset+'，'+str(len(cases))+'条；加--run才调用模型。')
        return 0
"""
    new_runner=new_runner.replace(anchor,checks+anchor)
    assert "'customer/w03/judge.py'],cwd=root" in new_runner
    new_runner=new_runner.replace("'customer/w03/judge.py'],cwd=root","str(judge_path)],cwd=root")
    new_runner=new_runner.replace("'stage_regression_passed'","'structured_passed_pending_answer_review'")
    compile(new_runner,str(ROOT/'customer/w03/run_merged_regression.py'),'exec')
    stage('customer/w03/run_merged_regression.py',new_runner.encode('utf-8'))
    assert read(REPORTS['large'])['passed']==67
    return inputs,output,protected,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    old,new,protected,metadata=prepare()
    print('预检通过：正式库38项；两套用例、完整报告、文字修复证据及10+30判定器检查一致。')
    print('拟设置默认提交为规模集67条；小样本69条与9条修复复测单列保留。')
    print('可移植判定器仅调整项目根路径；145条原结果及40条注入对照判定保持一致。')
    if not args.apply:
        print('只读预检完成，未更新提交入口或调用模型。');return
    dest=FINAL/('submission-entries-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    for rel,raw in old.items():
        if raw is not None:
            p=dest/'before'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    applied=[]
    try:
        for rel,raw in new.items():
            p=ROOT/rel
            assert (p.read_bytes() if p.exists() else None)==old[rel]
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);applied.append(rel)
            assert p.read_bytes()==raw
        changed_paths={str(ROOT/rel) for rel in new}
        assert all(sha(Path(p).read_bytes())==h for p,h in protected.items() if p not in changed_paths)
        assert runner.library_digest(ROOT/'artifacts/w03/library')==runner.FINAL_HASH
    except BaseException:
        for rel in reversed(applied):
            if old[rel] is None:(ROOT/rel).unlink()
            else:(ROOT/rel).write_bytes(old[rel])
        raise
    record=dict(status='applied',library_sha256=runner.FINAL_HASH,canonical_dataset='large',
        canonical_report_source=relative(REPORTS['large']),canonical_report_byte_identical=True,
        files={rel:dict(before_sha256=sha(old[rel]) if old[rel] is not None else None,after_sha256=sha(raw)) for rel,raw in new.items()},
        model_called=False,query_executed=False,chat_binding_changed=False,business_confirmation='pending',final_acceptance=False)
    (dest/'change.json').write_bytes(encoded(record));(dest/'publish_script.py').write_bytes(Path(__file__).read_bytes())
    assert read(dest/'change.json')==record
    print('正式提交入口已更新并回读核验；旧入口备份：'+str(dest))
    print('规模集67条原始报告按字节复制；小样本与修复复测分开保留；未改变指标库或聊天绑定。')


if __name__=='__main__':main()
