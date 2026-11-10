"""Run the prepared natural-language suite through the course Agent, explicitly."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT=Path('/home/yang/FDE/w03-work/fde-agent-w03')
RUN=ROOT/'artifacts/w03/full38-p1-run-20261110-012528-047804'
PLAN=RUN/'nl-cases-20261110-022457-578302/plan.json'
FINAL_RUN=RUN/'final-library-20261110-025635-629688'
FINAL_HASH='3726e776ada7b75ed778b3d6c49f42bff2a766d560dbf96036ffa61cd2953402'
FIRST_ORDER_CASES = [
    'single_first_order_sales_cents', 'single_first_buyer_count',
    'single_first_order_count', 'single_repeat_order_count', 'first_home_store',
    'single_valid_order_items', 'paid_coverage', 'paid_paraphrase',
]
FIRST_ORDER_PROMPT_SHA = '2df23fb50a2e1af0ba0eedc525a76db13283ca43e7ab799964803f0973c1e8cc'
sys.path.insert(0,str(ROOT/'platform'))
from fde_product.metrics.common import library_digest


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def build_command(entry,casepath,output,judgepath):
    # argparse nargs='+' treats '-B' inside judge-command as a CLI option.
    # Suppress child bytecode via environment instead of a nested Python flag.
    return [sys.executable,'-u','-B',str(ROOT/'tools/w03.py'),'test','--project',entry['project'],
        '--cases',str(casepath),'--output',str(output),'--cwd',str(ROOT),
        '--judge-command',sys.executable,str(judgepath)]


def prepare(args):
    plan=read(PLAN);entry=next(e for e in plan['entries'] if e['dataset']==args.dataset)
    if getattr(args,'final_library',False):
        pointer=read(FINAL_RUN/'regression_plan.json')
        if sha(PLAN)!=pointer['plan_sha256'] or plan['library_sha256']!=FINAL_HASH or pointer['library_sha256']!=FINAL_HASH:
            raise ValueError('FINAL_PLAN_VERSION_CHANGED')
        if plan['kind']!='final38_natural_language_regression_plan' or Path(plan['library'])!=ROOT/'artifacts/w03/library':
            raise ValueError('NOT_FINAL_LIBRARY_PLAN')
        if sha(ROOT/'product/w03_answer_prompt.txt')!=plan['answer_prompt_sha256'] or sha(ROOT/'product/w03_intent_prompt.txt')!=plan['intent_prompt_sha256']:
            raise ValueError('FINAL_PLAN_PROMPTS_CHANGED')
    key='smoke' if args.stage=='smoke' else 'cases';casepath=Path(entry[key]);cases=read(casepath)
    library=Path(plan['library']);project=Path(entry['project'])
    if sha(casepath)!=entry[key+'_sha256'] or len(cases)!=entry[key+'_total']:raise ValueError('CASES_CHANGED')
    if len({c['id'] for c in cases})!=len(cases):raise ValueError('CASE_IDS_DUPLICATED')
    if library_digest(library)!=plan['library_sha256']:raise ValueError('LIBRARY_CHANGED')
    dataset=read(project/'dataset.json')
    if dataset['library_sha256']!=plan['library_sha256'] or not read(project/'validation.json')['passed']:
        raise ValueError('PROJECT_BINDING_INVALID')
    for p in [library/'metrics.yml',*library.glob('*.sql')]:
        if p.read_bytes()!=(project/'models'/p.name).read_bytes():raise ValueError('PROJECT_MODEL_CHANGED')
    if (library/'catalog.json').read_bytes()!=(project/'catalog.json').read_bytes():raise ValueError('PROJECT_CATALOG_CHANGED')
    data=ROOT/'materials/data'/args.dataset;manifest=read(data/'manifest.json')
    if dataset['sha256']!=manifest['sha256'] or dataset['id']!=manifest['id']:raise ValueError('PROJECT_DATA_CHANGED')
    for name,digest in dataset['sha256'].items():
        if sha(data/name)!=digest:raise ValueError('RAW_DATA_CHANGED')
    judgepath=Path(plan['judge_script'])
    if sha(judgepath)!=plan['judge_sha256'] or sha(ROOT/'customer/w03/judge.py')!=plan['base_judge_sha256']:
        raise ValueError('JUDGE_CHANGED')
    spec=importlib.util.spec_from_file_location('full38_suite_judge',judgepath)
    judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)
    if judge.self_checks()!=8:raise ValueError('JUDGE_SELF_CHECK_FAILED')
    for case in cases:
        if not judge.compare(case['expected'],case['expected'])['passed']:raise ValueError('EXPECTED_CONTRACT_INVALID')
    full=read(Path(entry['cases']));full_by_id={c['id']:c for c in full}
    if sha(Path(entry['cases']))!=entry['cases_sha256'] or any(full_by_id.get(c['id'])!=c for c in cases):
        raise ValueError('SELECTED_CASES_NOT_BOUND_TO_FULL_SUITE')
    targets={t['id'] for t in read(ROOT/'customer/w03/targets.json')}
    if {m for c in full if c['expected']['status']=='ok' for m in c['expected']['intent']['metrics']}!=targets or len(targets)!=38:
        raise ValueError('FULL_SUITE_NOT_38_METRICS')
    if args.stage == 'first-order':
        if sha(ROOT/'product/w03_answer_prompt.txt') != FIRST_ORDER_PROMPT_SHA:
            raise ValueError('FIRST_ORDER_PROMPT_VERSION_CHANGED')
        cases = [full_by_id[cid] for cid in FIRST_ORDER_CASES]
        if len(cases) != 8 or len({c['id'] for c in cases}) != 8:
            raise ValueError('FIRST_ORDER_SELECTION_INVALID')
    tracked=[Path(__file__),PLAN,casepath,Path(entry['cases']),judgepath,ROOT/'customer/w03/judge.py',
        ROOT/'tools/w03.py',project/'dataset.json',project/'catalog.json',project/'models/metrics.yml',
        *project.glob('models/*.sql'),*sorted((ROOT/'platform/fde_product/metrics').glob('*.py')),
        ROOT/'product/w03_intent_prompt.txt',ROOT/'product/w03_answer_prompt.txt']
    hashes={str(p):sha(p) for p in tracked}
    if getattr(args,'final_library',False):
        hashes[str(FINAL_RUN/'regression_plan.json')]=sha(FINAL_RUN/'regression_plan.json')
    return plan,entry,casepath,cases,judge,hashes


def main():
    global RUN,PLAN
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',choices=['small','large'],required=True)
    parser.add_argument('--stage',choices=['smoke','full','first-order'],required=True)
    parser.add_argument('--final-library',action='store_true',help='Use the separately prepared official merged-library plan')
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.final_library:
        RUN=FINAL_RUN
        PLAN=Path(read(FINAL_RUN/'regression_plan.json')['plan'])
        if not PLAN.resolve().is_relative_to(FINAL_RUN.resolve()):
            raise ValueError('FINAL_PLAN_OUTSIDE_FINAL_RUN')
    plan,entry,casepath,cases,judge,hashes=prepare(args)
    print(f'预检通过：{args.dataset}/{args.stage}，{len(cases)}条；用例、判定器、数据与38项库绑定一致。',flush=True)
    if args.final_library:
        print('本轮使用正式merge库：'+plan['library_sha256'],flush=True)
    if not args.run:
        print('只读预检完成；未检查用户终端模型配置，未写入或调用模型。');return 0
    missing=[k for k in ['FDE_MODEL_URL','FDE_MODEL_NAME','FDE_MODEL_KEY'] if not os.environ.get(k)]
    if missing:
        print('缺少模型环境变量名：'+', '.join(missing)+'；请勿粘贴密钥。');return 2
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f')
    session=RUN/f'nl-{args.dataset}-{args.stage}-{stamp}';session.mkdir(exist_ok=False)
    output=session/'results';reportpath=output/'metric_test_report.json'
    if args.stage == 'first-order':
        source_casepath = casepath
        casepath = session/'selected-cases.json'
        save(casepath, cases)
        if read(casepath) != cases:
            raise ValueError('SELECTED_CASES_READBACK_MISMATCH')
        hashes[str(casepath)] = sha(casepath)
        save(session/'selection.json', dict(source_cases=str(source_casepath),
            source_sha256=sha(source_casepath), selected_ids=FIRST_ORDER_CASES,
            expected_values_changed=False, purpose='Retest first-order explanation and existing answer behavior after prompt correction',
            prompt_sha256=FIRST_ORDER_PROMPT_SHA, full_suite_rerun=False))
    command=build_command(entry,casepath,output,plan['judge_script'])
    save(session/'environment.json',dict(python=sys.version,platform=platform.platform(),
        model_name=os.environ['FDE_MODEL_NAME'],command=command,input_sha256=hashes,
        library_sha256=plan['library_sha256'],project=entry['project'],plan=str(PLAN)))
    (session/'runner.py').write_bytes(Path(__file__).read_bytes())
    summary=dict(status='running',dataset=args.dataset,stage=args.stage,total=len(cases),
        started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),business_confirmation='pending',
        answer_review_required=True,final_acceptance=False,report=str(reportpath),
        official_merged_library=args.final_library,library_sha256=plan['library_sha256'])
    save(session/'run_summary.json',summary)
    print(f'运行目录：{session}',flush=True)
    print('开始真实问数，将调用模型；每完成一条打印进度。',flush=True)
    tick=time.monotonic();seen=0
    def progress():
        nonlocal seen
        try:items=read(reportpath).get('cases',[])
        except (OSError,ValueError):return
        for c in items[seen:]:
            seen+=1
            print(f'[{seen}/{len(cases)}] '+('PASS ' if c.get('comparison',{}).get('passed') else 'FAIL ')+c['id'],flush=True)
    try:
        with (session/'console.log').open('w',encoding='utf-8') as log:
            child_env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
            with subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=child_env) as proc:
                try:
                    while proc.poll() is None:
                        progress();time.sleep(1)
                    code=proc.wait();progress()
                except BaseException:
                    proc.terminate()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                    raise
        summary['exit_code']=code
        if not reportpath.exists():
            summary['status']='failed_before_report';return 2
        report=read(reportpath);observed=report.get('cases',[]);inputs={c['id']:c for c in cases}
        identities=(len(observed)==len(cases) and len({c['id'] for c in observed})==len(cases)
                    and all(c['id'] in inputs and c['question']==inputs[c['id']]['question'] and c['expected']==inputs[c['id']]['expected'] for c in observed))
        rechecks=[dict(id=c['id'],comparison=judge.compare(c['expected'],c['actual'])) for c in observed]
        save(session/'rejudged.json',rechecks)
        binding=all(c['actual'].get('catalog_sha256')==plan['library_sha256'] for c in observed if c['actual'].get('status')=='ok')
        failed=[dict(id=c['id'],status=c['actual'].get('status'),code=c['actual'].get('code'),comparison=rechecks[i]['comparison'])
                for i,c in enumerate(observed) if not rechecks[i]['comparison']['passed']]
        changed=[p for p,digest in hashes.items() if sha(Path(p))!=digest]
        if library_digest(plan['library'])!=plan['library_sha256']:changed.append(plan['library'])
        consistent=all(c.get('comparison')==rechecks[i]['comparison'] for i,c in enumerate(observed))
        passed=code==0 and report.get('complete') is True and identities and binding and consistent and not failed and not changed and report.get('passed')==len(cases)
        summary.update(status='structured_passed_pending_answer_review' if passed else 'needs_review',
            passed=sum(r['comparison']['passed'] for r in rechecks),complete=report.get('complete'),
            inputs_match=identities,result_library_binding=binding,rejudge_consistent=consistent,
            input_changed_during_run=changed,failed_cases=failed)
        return 0 if passed else 1
    except BaseException as exc:
        summary['status']='interrupted' if isinstance(exc,KeyboardInterrupt) else 'runner_failed'
        summary['exception_type']=type(exc).__name__;raise
    finally:
        summary['elapsed_seconds']=round(time.monotonic()-tick,3)
        summary['finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        save(session/'run_summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
        print(f'运行摘要：{session / "run_summary.json"}',flush=True)


if __name__=='__main__':raise SystemExit(main())
