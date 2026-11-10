"""Back up old library and use course merge to publish the validated full38 build."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path('/home/yang/FDE/w03-work/fde-agent-w03').resolve()
RUN = ROOT/'artifacts/w03/full38-p1-run-20261110-012528-047804'
SOURCE = RUN/'build'
TARGET = ROOT/'artifacts/w03/library'
OLD_HASH = 'b7dcfba9dc5046dcf60a8a8668ce2aa4cb5d23f9a0670930c020c21bc5894e62'
SOURCE_HASH = '47b7b147de84852f44e67a530d38c13bb141e9def4a5f2d36daa2956fa01cf39'
sys.path.insert(0, str(ROOT/'platform'))
from fde_product.metrics.common import library_digest
from fde_product.metrics.builder import verify_library


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def tree(p):
    return {str(f.relative_to(p)): sha(f) for f in p.rglob('*') if f.is_file()}


def prepare():
    for p in [SOURCE,TARGET]:
        if p.is_symlink() or not p.is_dir() or not p.resolve().is_relative_to(ROOT/'artifacts/w03'):
            raise ValueError('UNEXPECTED_LIBRARY_PATH')
    if library_digest(TARGET) != OLD_HASH or library_digest(SOURCE) != SOURCE_HASH:
        raise ValueError('LIBRARY_VERSION_CHANGED')
    targets = {t['id'] for t in read(ROOT/'customer/w03/targets.json')}
    assert len(targets) == 38 and set(verify_library(SOURCE)['metric_ids']) == targets
    assert verify_library(TARGET)['metrics'] == 32
    assert read(SOURCE/'validation.json')['passed'] and read(SOURCE/'source_check.json')['passed']
    provenance = read(SOURCE/'provenance.json')
    assert not provenance['unresolved']
    assert sha(ROOT/'customer/w03/build-metrics/SKILL.md') == provenance['skill_sha256']
    assert sha(ROOT/'docs/w03/business_model.md') == provenance['input_hashes']['business_model.md']
    numeric = read(RUN/'numeric-verification-20261110-014924-111593/summary.json')
    nl_path = RUN/'nl-verification-20261110-025351-904391/summary.json'
    nl = read(nl_path)
    assert numeric['library_sha256'] == nl['library_sha256'] == SOURCE_HASH
    assert numeric['passed'] and numeric['total_cases'] == 97
    assert nl['current_spec_offline_rejudgment'] == dict(passed=136,total=136)
    assert nl['latest_prompt_targeted_execution'] == dict(passed=16,total=16)
    assert sha(Path(nl['archive'])) == nl['archive_sha256']
    data = ROOT/'materials/data/small'
    for name,digest in read(data/'manifest.json')['sha256'].items():
        assert sha(data/name) == digest
    protected = [ROOT/'customer/w03/build-metrics/SKILL.md', ROOT/'docs/w03/business_model.md',
        ROOT/'customer/w03/tests.json', ROOT/'artifacts/w03/metric_test_report.json',
        ROOT/'.runtime/product/metrics-binding.json', ROOT/'product/w03_answer_prompt.txt',
        ROOT/'product/w03_intent_prompt.txt', ROOT/'customer/w03/judge.py']
    for p in (ROOT/'platform/fde_product/metrics').glob('*.py'):
        protected.append(p)
    hashes = {str(p): sha(p) for p in protected if p.is_file()}
    return targets, hashes, tree(TARGET), tree(SOURCE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    targets, protected, old_tree, source_tree = prepare()
    print('预检通过：旧正式库32项；构建库38项，数值与自然语言证据已归档。', flush=True)
    print('将备份旧library，再调用课程merge单输入定稿；不调用模型。', flush=True)
    if not args.apply:
        print('只读预检完成，未修改任何WSL文件。')
        return 0
    dest = RUN/('final-library-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    backup = dest/'library-before'
    assert backup.resolve().is_relative_to(RUN) and TARGET.resolve() == ROOT/'artifacts/w03/library'
    (dest/'finalize_script.py').write_bytes(Path(__file__).read_bytes())
    save(dest/'old_library_manifest.json',old_tree)
    command = [sys.executable,'-B',str(ROOT/'tools/w03.py'),'merge','--inputs',str(SOURCE),
        '--data',str(ROOT/'materials/data/small'),'--output',str(TARGET)]
    summary = dict(status='started', command=command, source=str(SOURCE), source_sha256=SOURCE_HASH,
        old_library_sha256=OLD_HASH, backup=str(backup), protected_sha256=protected,
        model_called=False, business_confirmation='pending', final_acceptance=False)
    save(dest/'summary.json',summary)
    tick=time.monotonic()
    TARGET.rename(backup)
    try:
        assert tree(backup)==old_tree
        print('旧库已完整备份；开始官方merge及加载校验。',flush=True)
        with (dest/'merge.log').open('w',encoding='utf-8') as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError('MERGE_FAILED: '+str(dest/'merge.log'))
        assert set(verify_library(TARGET)['metric_ids'])==targets
        for name in ['validation.json','grain_check.json','dimension_check.json','metricflow_check.json']:
            assert read(TARGET/name)['passed'] is True, name
        identical = [p.name for p in SOURCE.glob('*.sql')]+['metrics.yml','catalog.json','scope.json','dimension_targets.json','grain_contract.json','unresolved.json']
        assert all((SOURCE/name).read_bytes()==(TARGET/name).read_bytes() for name in identical)
        assert read(TARGET/'provenance.json') == {'batches':[read(SOURCE/'provenance.json')]}
        assert tree(SOURCE)==source_tree and tree(backup)==old_tree
        assert all(sha(Path(p))==digest for p,digest in protected.items())
        summary.update(status='merged38_pending_final_library_regression',library=str(TARGET),
            library_sha256=library_digest(TARGET),metric_count=38,
            executable_inputs_byte_identical=identical, reload_and_retest_required=True,
            prior_build_reports_relabelled=False,chat_binding_changed=False)
    except BaseException as exc:
        if TARGET.exists():
            TARGET.rename(dest/'failed-merge-output')
        backup.rename(TARGET)
        assert tree(TARGET)==old_tree
        summary.update(status='failed_old_library_restored',exception_type=type(exc).__name__,reason=str(exc))
        raise
    finally:
        summary['elapsed_seconds']=round(time.monotonic()-tick,3)
        save(dest/'summary.json',summary)
    print('官方merge定稿完成：38项；执行定义与原构建逐字节一致。')
    print('新库SHA256：'+summary['library_sha256'])
    print('备份及定稿记录：'+str(dest))
    print('下一步需从正式库新建加载项目并重跑最终回归；旧报告和聊天绑定未修改。')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
