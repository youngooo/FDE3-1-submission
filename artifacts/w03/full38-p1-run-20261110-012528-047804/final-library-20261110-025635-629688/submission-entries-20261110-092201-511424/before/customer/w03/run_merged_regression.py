"""Run real stage regression against the prepared, hash-bound merged library."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'platform'))
from fde_product.metrics.common import library_digest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',choices=['small','large'],default='small')
    args=parser.parse_args()
    missing=[name for name in ['FDE_MODEL_URL','FDE_MODEL_NAME','FDE_MODEL_KEY'] if not os.getenv(name)]
    if missing:
        print(json.dumps({'status':'not_started','missing_environment_names':missing,'model_called':False},ensure_ascii=False))
        return 2
    plan=json.loads((root/'customer/w03/merged_regression_plan.json').read_text())
    entry=next(e for e in plan['entries'] if e['dataset']==args.dataset)
    assert library_digest(root/plan['library'])==plan['library_sha256'],'LIBRARY_CHANGED_REGENERATE_PLAN'
    casesfile=root/entry['cases'];raw=casesfile.read_bytes();cases=json.loads(raw)
    assert hashlib.sha256(raw).hexdigest()==entry['cases_sha256'],'CASES_CHANGED'
    dataset=json.loads((root/entry['project']/'dataset.json').read_text())
    assert dataset['library_sha256']==plan['library_sha256'],'PROJECT_LIBRARY_CHANGED'
    out=root/('artifacts/w03/test-merged-'+args.dataset+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    print('实际回归开始：'+args.dataset+'，'+str(len(cases))+'条；将调用模型。',flush=True)
    print('运行目录：'+str(out),flush=True)
    # Write CLI output directly to a separate log; the test framework retains
    # each query's trace and incrementally writes metric_test_report.json.
    log=out.with_suffix('.console.log')
    with log.open('w',encoding='utf-8') as stream:
        proc=subprocess.run([sys.executable,'tools/w03.py','test','--project',entry['project'],
          '--cases',entry['cases'],'--output',str(out),'--judge-command',sys.executable,
          'customer/w03/judge.py'],cwd=root,stdout=stream,stderr=subprocess.STDOUT)
    reportpath=out/'metric_test_report.json'
    if not reportpath.exists():
        print(json.dumps({'status':'failed_before_report','returncode':proc.returncode,'log':str(log)},ensure_ascii=False))
        return 1
    report=json.loads(reportpath.read_text())
    actualcases=report.get('cases',[])
    inputs={c['id']:c for c in cases}
    identities=len(actualcases)==len(cases) and len({c['id'] for c in actualcases})==len(cases) and all(
       c['id'] in inputs and c['question']==inputs[c['id']]['question'] and c['expected']==inputs[c['id']]['expected'] for c in actualcases)
    hashes=[c['actual'].get('catalog_sha256') for c in actualcases if c['actual'].get('status')=='ok' or 'catalog_sha256' in c['actual']]
    binding=bool(hashes) and all(h==plan['library_sha256'] for h in hashes)
    failed=[{'id':c['id'],'status':c['actual'].get('status'),'code':c['actual'].get('code'),
             'comparison':c.get('comparison')} for c in actualcases if not c.get('comparison',{}).get('passed')]
    passed=proc.returncode==0 and report.get('complete') is True and identities and binding and not failed and report.get('passed')==len(cases)
    result={'status':'stage_regression_passed' if passed else 'needs_review','dataset':args.dataset,
        'report':str(reportpath),'complete':report.get('complete'),'passed':report.get('passed'),
        'total':report.get('total'),'inputs_match':identities,'report_matches_current_library':binding,
        'library_sha256':plan['library_sha256'],'failed_cases':failed,'final_38_acceptance':False,
        'answer_text_review_required':True,'canonical_report_updated':False}
    (out/'binding_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
