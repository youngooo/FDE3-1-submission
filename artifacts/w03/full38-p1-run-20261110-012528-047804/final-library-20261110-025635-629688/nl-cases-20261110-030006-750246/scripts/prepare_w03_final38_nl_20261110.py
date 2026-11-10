"""Independently recompute final-library NL expectations from the original CSV."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import prepare_w03_full38_nl_20261110 as source

ROOT = source.ROOT
BUILD_RUN = source.RUN
FINAL = BUILD_RUN/'final-library-20261110-025635-629688'
LIBRARY = ROOT/'artifacts/w03/library'
LIBHASH = '3726e776ada7b75ed778b3d6c49f42bff2a766d560dbf96036ffa61cd2953402'
PROMPT_HASH = '2df23fb50a2e1af0ba0eedc525a76db13283ca43e7ab799964803f0973c1e8cc'
PRIOR_PLAN = BUILD_RUN/'nl-cases-20261110-022457-578302/plan.json'
POINTER = FINAL/'regression_plan.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def prepare():
    if POINTER.exists():
        raise ValueError('FINAL_PLAN_ALREADY_EXISTS: '+str(POINTER))
    if source.library_digest(LIBRARY) != LIBHASH:
        raise ValueError('FINAL_LIBRARY_CHANGED')
    assert sha(ROOT/'product/w03_answer_prompt.txt') == PROMPT_HASH
    merge = read(FINAL/'summary.json')
    assert merge['status'] == 'merged38_pending_final_library_regression'
    assert merge['library_sha256'] == LIBHASH
    for name in merge['executable_inputs_byte_identical']:
        assert (LIBRARY/name).read_bytes() == (BUILD_RUN/'build'/name).read_bytes()
    assert source.judge.self_checks() == 8
    # Only the project base changes; all CSV oracle logic and question generation are reused unchanged.
    source.RUN = FINAL
    prepared = {size: source.generate(size, LIBHASH) for size in ['small','large']}
    previous = read(PRIOR_PLAN)
    for size,(cases,smoke,info) in prepared.items():
        project = FINAL/('project-'+size)
        for p in [LIBRARY/'metrics.yml', *LIBRARY.glob('*.sql')]:
            assert p.read_bytes() == (project/'models'/p.name).read_bytes()
        assert (LIBRARY/'catalog.json').read_bytes() == (project/'catalog.json').read_bytes()
        entry = next(e for e in previous['entries'] if e['dataset'] == size)
        assert sha(Path(entry['cases'])) == entry['cases_sha256']
        old = read(Path(entry['cases']))
        assert len(cases) == len(old)
        for current, prior in zip(cases,old):
            normalized = deepcopy(current)
            if normalized['expected']['status'] == 'ok':
                normalized['expected']['catalog_sha256'] = previous['library_sha256']
            assert normalized == prior, current['id']
        assert len(smoke) == 8
    assert not ({c['question'] for c in prepared['small'][0]} & {c['question'] for c in prepared['large'][0]})
    protected_paths = [Path(__file__),Path(source.__file__),PRIOR_PLAN,ROOT/'product/w03_answer_prompt.txt',
        ROOT/'product/w03_intent_prompt.txt',ROOT/'customer/w03/tests.json',ROOT/'artifacts/w03/metric_test_report.json',
        ROOT/'.runtime/product/metrics-binding.json']
    protected = {str(p):sha(p) for p in protected_paths if p.is_file()}
    scripts = [Path(__file__),Path(source.__file__),Path(source.judge.__file__),Path(source.judge.strict.__file__),
        Path(source.paid.__file__),Path(source.general.__file__),Path(source.financial.__file__),Path(source.member.__file__),
        Path(source.member.base.__file__),Path(source.preflight.__file__)]
    return prepared,protected,scripts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    prepared,protected,scripts=prepare()
    print('预检通过：正式库38项，两套新项目绑定一致；期望已从原始CSV重新独立计算。',flush=True)
    print('小样本69条、规模67条；与前版相比仅库版本变化，问句、数值期望、边界判定保持一致。',flush=True)
    print('大小样本无完全相同问句；当前回答提示包含P1说明和首单排序修正。',flush=True)
    if not args.apply:
        print('只读预检完成；未写入用例、查询或调用模型。')
        return
    dest=FINAL/('nl-cases-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    snapshot=dest/'scripts';snapshot.mkdir()
    script_hashes={}
    for path in scripts:
        raw=path.read_bytes();target=snapshot/path.name
        if target.exists():
            assert target.read_bytes()==raw
        else:
            target.write_bytes(raw)
        assert target.read_bytes()==raw
        script_hashes[path.name]=sha(path)
    entries=[]
    for size,(cases,smoke,info) in prepared.items():
        folder=dest/size;folder.mkdir()
        save(folder/'tests.json',cases);save(folder/'tests-smoke.json',smoke)
        assert read(folder/'tests.json')==cases and read(folder/'tests-smoke.json')==smoke
        info.update(cases_sha256=sha(folder/'tests.json'),smoke_sha256=sha(folder/'tests-smoke.json'),script_sha256=script_hashes)
        save(folder/'generation.json',info)
        entries.append(dict(dataset=size,project=info['project'],cases=str(folder/'tests.json'),cases_sha256=info['cases_sha256'],
            smoke=str(folder/'tests-smoke.json'),smoke_sha256=info['smoke_sha256'],cases_total=len(cases),smoke_total=len(smoke)))
    plan=dict(kind='final38_natural_language_regression_plan',library=str(LIBRARY),library_sha256=LIBHASH,entries=entries,
        judge_script=str(snapshot/'judge_w03_full38_20261110.py'),judge_sha256=script_hashes['judge_w03_full38_20261110.py'],
        base_judge_sha256=sha(ROOT/'customer/w03/judge.py'),judge_self_checks=8,cross_dataset_identical_questions=0,
        model_called=False,query_executed=False,actual_results_read=False,actual_results_used_to_compute_expectations=False,
        answer_prompt_sha256=PROMPT_HASH,intent_prompt_sha256=sha(ROOT/'product/w03_intent_prompt.txt'),
        prior_plan=str(PRIOR_PLAN),prior_plan_sha256=sha(PRIOR_PLAN),csv_expectations_recomputed=True,
        business_confirmation='pending',execution_status='not_run',answer_review_required=True,final_acceptance=False)
    save(dest/'plan.json',plan)
    assert read(dest/'plan.json')==plan
    assert source.library_digest(LIBRARY)==LIBHASH
    assert all(sha(Path(p))==digest for p,digest in protected.items())
    save(POINTER,dict(plan=str(dest/'plan.json'),plan_sha256=sha(dest/'plan.json'),library_sha256=LIBHASH))
    assert read(POINTER)['plan_sha256']==sha(dest/'plan.json')
    print('正式库最终回归用例已生成：'+str(dest))
    print('计划索引：'+str(POINTER))
    print('旧用例、历史报告、指标库与聊天绑定未修改；尚未调用模型。')


if __name__=='__main__':
    main()
