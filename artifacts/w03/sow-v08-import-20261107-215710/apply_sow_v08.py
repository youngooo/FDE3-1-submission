"""Apply a progress-only SOW update after base/evidence checks; no model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',type=Path,default=Path('.'))
    args=ap.parse_args()
    root=args.workspace.resolve();bundle=Path(__file__).resolve().parent
    if not (root/'tools/w03.py').is_file():raise SystemExit('NOT_W03_WORKSPACE')
    meta_raw=(bundle/'sow-v08-update.json').read_bytes();meta=json.loads(meta_raw)
    new=(bundle/'sow.v0.8-progress.md').read_bytes()
    if sha(new)!=meta['new_sha256']:raise SystemExit('NEW_SOW_HASH_MISMATCH')
    sow=root/'docs/w03/sow.md';old=sow.read_bytes()
    if old==new:
        print(json.dumps({'status':'already_applied','sow':str(sow),'model_called':False},ensure_ascii=False));return
    if sha(old.decode('utf-8').replace('\r\n','\n').encode('utf-8'))!=meta['base_normalized_sha256']:
        raise SystemExit('SOW_BASE_DIFFERS: 当前SOW与已审阅v0.7不同，未覆盖；请保留当前文件并提供差异。')
    evidence={}
    def read_report(relative):
        path=root/relative;raw=path.read_bytes()
        evidence[relative]={'sha256':sha(raw)}
        return json.loads(raw)
    def check_report(relative,passed,total):
        r=read_report(relative)
        if r.get('complete') is not True or r.get('passed')!=passed or r.get('total')!=total or len(r.get('cases',[]))!=total:
            raise SystemExit('REPORT_SUMMARY_DIFFERS: '+relative)
        if sum(c.get('comparison',{}).get('passed') is True for c in r['cases'])!=passed:
            raise SystemExit('REPORT_CASE_COUNTS_DIFFER: '+relative)
        return r
    mutation=read_report('artifacts/w03/judge-mutations-20261107-161649/report.json')
    if mutation.get('passed') is not True or any(mutation.get(k)!=v for k,v in {'positive_controls_passed':8,'positive_controls_total':8,'mutations_rejected':34,'mutations_total':34}.items()):
        raise SystemExit('MUTATION_REPORT_DIFFERS')
    check_report('artifacts/w03/test-general32-full-20261107-162320/metric_test_report.json',53,54)
    check_report('artifacts/w03/test-policy-regression-20261107-164103/metric_test_report.json',9,9)
    initial=read_report('artifacts/w03/test-general32-large-20261107-164818/metric_test_report.json')
    if sum(c.get('actual',{}).get('code')=='MODEL_HTTP_402' for c in initial.get('cases',[]))!=37:
        raise SystemExit('HTTP402_COUNT_DIFFERS')
    context=check_report('artifacts/w03/test-context-reduction-20261107-171050/metric_test_report.json',2,2)
    prior=check_report('artifacts/w03/test-large-model-recovery-20261107-170218/metric_test_report.json',1,1)
    def prompt_usage(report):
        return next(c['actual']['model_usage']['prompt_tokens'] for c in report['cases'] if c['id']=='single_valid_order_items')
    if (prompt_usage(prior),prompt_usage(context))!=(311442,11766):raise SystemExit('CONTEXT_USAGE_DIFFERS')
    full_path='artifacts/w03/test-general32-large-current-20261107-173736/metric_test_report.json'
    full=check_report(full_path,53,53)
    metric_ids={m for c in full['cases'] if c['expected']['status']=='ok' for m in c['expected']['intent']['metrics']}
    if len(metric_ids)!=32:raise SystemExit('GENERAL_METRIC_COVERAGE_DIFFERS')
    usage={k:sum((c.get('actual',{}).get('model_usage') or {}).get(k,0) for c in full['cases']) for k in ('prompt_tokens','completion_tokens','total_tokens')}
    if usage!={'prompt_tokens':659284,'completion_tokens':51947,'total_tokens':711231}:raise SystemExit('LARGE_RUN_USAGE_DIFFERS')
    versions=('qinghe-w03-20260923-large','0074e7f764c63e836617aecb0e217aa3b5cc0cf9ede557179ad46b077dcf8ba8','2778ddc8e0fbaff9a3a8ca86b3cd59167cf6ca0d64f764c7eca452e7283b333f')
    for c in full['cases']:
        a=c['actual']
        if a['status']=='ok' and tuple(a.get(k) for k in ('data_version','data_sha256','catalog_sha256'))!=versions:
            raise SystemExit('LARGE_VERSION_DIFFERS')
    review=read_report('artifacts/w03/test-general32-large-current-20261107-173736/answer-review-findings.json')
    if review.get('material_issue_cases')!=2 or len(review.get('cases',[]))!=53:raise SystemExit('ANSWER_REVIEW_DIFFERS')
    replay=read_report('artifacts/w03/answer-display-replay-20261107-210241/answer_replay_report.json')
    if replay.get('complete') is not True or replay.get('generated')!=6 or replay.get('total')!=6 or replay.get('query_reexecuted') is not False or replay.get('source_report_sha256')!=evidence[full_path]['sha256']:
        raise SystemExit('ANSWER_REPLAY_DIFFERS')
    e2e=check_report('artifacts/w03/test-answer-display-e2e-20261107-210405/metric_test_report.json',2,2)
    if {c['id'] for c in e2e['cases']}!={'single_discount_cents','single_first_order_count'}:raise SystemExit('E2E_CASES_DIFFER')
    runtime=['platform/fde_product/metrics/agent.py','platform/fde_product/metrics/intent_context.py',
             'platform/fde_product/metrics/answer_display_facts.py','product/w03_intent_prompt.txt','product/w03_answer_prompt.txt']
    snapshots={p:(root/p).read_bytes() for p in runtime}
    if sha(snapshots['product/w03_answer_prompt.txt'])!=replay['answer_prompt_sha256'] or sha(snapshots['platform/fde_product/metrics/answer_display_facts.py'])!=replay['helper_sha256']:
        raise SystemExit('CURRENT_ANSWER_CODE_DIFFERS_FROM_REPLAY')
    audit=root/'artifacts/w03/sow-progress-v08'
    pending=sow.with_name('sow.v08.pending.md')
    if audit.exists() or pending.exists():raise SystemExit('UPDATE_DESTINATION_EXISTS: 未覆盖已有归档或临时文件')
    # All checks precede writes. Preserve the exact current bytes as the backup.
    audit.mkdir(parents=True,exist_ok=False)
    (audit/'sow.v0.7-before.md').write_bytes(old)
    (audit/'sow.v0.8-progress.md').write_bytes(new)
    (audit/'sow-v08-update.json').write_bytes(meta_raw)
    for name in ('sow.v0.7-to-v0.8.diff','apply_sow_v08.py'):
        (audit/name).write_bytes((bundle/name).read_bytes())
    for relative,raw in snapshots.items():
        dest=audit/'runtime-customization'/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    record={'status':'prepared','version':'v0.8-draft','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'sow':str(sow),'backup':str(audit/'sow.v0.7-before.md'),
            'old_sha256':sha(old),'new_sha256':sha(new),'verified_reports':evidence,
            'runtime_snapshot_sha256':{p:sha(raw) for p,raw in snapshots.items()},
            'answer_semantics_review_basis':'AI-assisted review of user-supplied outputs, separately from structured checks',
            'new_customer_confirmation':False,'model_called':False,'query_executed':False,'workflow_restarted':False}
    def save():
        (audit/'update_record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    if sow.read_bytes()!=old:raise SystemExit('SOW_CHANGED_DURING_PREPARATION: 当前SOW未覆盖')
    with pending.open('xb') as stream:stream.write(new)
    pending.replace(sow)
    if sow.read_bytes()!=new:raise SystemExit('SOW_WRITE_VERIFICATION_FAILED')
    record['status']='updated';save()
    print(json.dumps({k:record[k] for k in ('status','version','sow','backup','new_customer_confirmation','model_called','workflow_restarted')},ensure_ascii=False,indent=2))
    print('audit: '+str(audit))


if __name__=='__main__':
    main()
