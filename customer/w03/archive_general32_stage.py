"""Archive bounded stage evidence and custom runtime files without model calls."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, default=Path('.'))
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.workspace.resolve()
    paths = {
        'large_structured': 'artifacts/w03/test-general32-large-current-20261107-173736/metric_test_report.json',
        'answer_review': 'artifacts/w03/test-general32-large-current-20261107-173736/answer-review-findings.json',
        'answer_replay': 'artifacts/w03/answer-display-replay-20261107-210241/answer_replay_report.json',
        'end_to_end': 'artifacts/w03/test-answer-display-e2e-20261107-210405/metric_test_report.json',
    }
    raw = {k: (root/p).read_bytes() for k,p in paths.items()}
    data = {k: json.loads(v) for k,v in raw.items()}
    full, replay, e2e = (data[k] for k in ('large_structured', 'answer_replay', 'end_to_end'))
    for label, report, n in [('large',full,53),('end_to_end',e2e,2)]:
        if report.get('complete') is not True or report.get('passed')!=n or report.get('total')!=n or len(report['cases'])!=n or not all(c.get('comparison',{}).get('passed') is True for c in report['cases']):
            raise ValueError('REPORT_NOT_PASSED: '+label)
    if replay.get('complete') is not True or replay.get('generated')!=6 or replay.get('total')!=6 or replay.get('query_reexecuted') is not False or replay.get('source_report_unchanged') is not True:
        raise ValueError('REPLAY_STATUS_DIFFERS')
    if replay.get('source_report_sha256') != sha(raw['large_structured']):
        raise ValueError('REPLAY_SOURCE_HASH_DIFFERS')
    original = {c['id']: c for c in full['cases']}
    expected_e2e = {'single_discount_cents','single_first_order_count'}
    if {c['id'] for c in e2e['cases']}!=expected_e2e:
        raise ValueError('E2E_CASES_DIFFER')
    for c in e2e['cases']:
        old=original[c['id']]
        if c['question']!=old['question'] or c['expected']!=old['expected']:
            raise ValueError('E2E_EXPECTATIONS_CHANGED')
    for c in replay['cases']:
        if c.get('generation_status')!='ok':raise ValueError('REPLAY_GENERATION_FAILED')
        old=original[c['id']]['actual']
        if c.get('source_trace_id')!=old.get('trace_id'):
            raise ValueError('REPLAY_TRACE_MISMATCH')
        for field in ('intent','columns','rows','units','data_version','data_sha256','catalog_sha256'):
            if c['result'].get(field)!=old.get(field):raise ValueError('REPLAY_RESULT_CHANGED: '+field)
    metrics=sorted({m for c in full['cases'] if c['expected']['status']=='ok' for m in c['expected']['intent']['metrics']})
    if len(metrics)!=32:raise ValueError('EXPECTED_32_GENERAL_METRICS')
    runtime_files=['platform/fde_product/metrics/agent.py','platform/fde_product/metrics/intent_context.py',
                   'platform/fde_product/metrics/answer_display_facts.py','product/w03_intent_prompt.txt','product/w03_answer_prompt.txt']
    runtime_raw={p:(root/p).read_bytes() for p in runtime_files}
    # Tie current answer implementation to the replay; changes require new evidence.
    if sha(runtime_raw['product/w03_answer_prompt.txt'])!=replay['answer_prompt_sha256'] or sha(runtime_raw['platform/fde_product/metrics/answer_display_facts.py'])!=replay['helper_sha256']:
        raise ValueError('CURRENT_ANSWER_IMPLEMENTATION_DIFFERS_FROM_REPLAY')
    out=args.output.resolve()
    if not out.is_relative_to(root):raise ValueError('OUTPUT_MUST_BE_IN_WORKSPACE')
    out.mkdir(parents=True,exist_ok=False)
    for p,body in runtime_raw.items():
        dest=out/'runtime-customization'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body)
    record={
        'kind':'general32_stage_archive','status':'stage_archived_not_final_acceptance',
        'metrics':metrics,'general_metric_count':32,'paid_monthly_metric_count_completed':0,
        'large_structured':{'passed':53,'total':53,'scope':'original run before final answer-display patch'},
        'answer_replay':{'generated':6,'total':6,'query_reexecuted':False},
        'end_to_end':{'passed':2,'total':2,'scope':'discount_cents and first_order_count after answer-display patch'},
        'answer_review':{'method':'AI-assisted review of user-provided output in this conversation',
                        'original_material_issue_cases':['single_discount_cents','single_first_order_count'],
                        'six_replay_answers_reviewed':'no material discrepancy found in supplied output',
                        'two_end_to_end_answers_reviewed':'no material discrepancy found in supplied output',
                        'all_53_answers_regenerated_after_display_patch':False,
                        'not_an_automatic_semantic_judge':True},
        'evidence':{k:{'path':p,'sha256':sha(raw[k])} for k,p in paths.items()},
        'runtime_customization':{p:sha(body) for p,body in runtime_raw.items()},
        'unchanged_checksums':{p:sha((root/p).read_bytes()) for p in ['platform/fde_product/metrics/engine.py','customer/w03/judge.py']},
        'remaining':['六项付费月报日期端点、结束日组合、门店规则月报适用性依据',
                     '依据核查后更新模型，构建六项并merge定稿38项库',
                     '定稿库的小样本38项及关键边界校验、规模付费月报校验',
                     '最终证据索引、SOW进度与限制更新、打包和结构预检'],
        'model_called':False,'query_executed':False,
    }
    (out/'stage.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    note='''# 32 项通用指标阶段记录

状态：阶段证据已归档，W03 整体作业未完成，不代表正式验收。

规模数据原报告结构化校验 53/53。该报告的全部回答经 AI 辅助核对，发现优惠金额附加元值错误、首单计数对象错误两处实质性问题，以及少量额外换算/措辞问题。原报告及问题记录均保留。

回答展示补丁增加代码计算的单位与换算事实。之后用原结果回放六条回答（未重执行查询），本对话核对未发现实质性错误；再经完整入口重跑优惠金额和首单数两条，结构化 2/2 且所提供回答正确。这是分阶段证据链，不写成补丁后整套 53 条重新通过，也不将回放的生成成功当作自动语义校验通过。

五份自定义运行文件保存在 runtime-customization/ 下，保留原相对路径；原工程、customer/w03 下的补丁脚本及各补丁目录中的修改前文件/差异仍是复跑依据。此快照不是独立工程，不自动覆盖其他环境。

六项付费会员月报仍未完成。需要取得总部月报三个日期端点、两个结束日期的组合、门店规则月报适用性依据，不从字段名、门店单方说法或测试数值反推。任务书第5节允许因访谈遗漏或不稳定阻断时，由课程方按需要分发同源 MD/JSON 补充；取得后按课程方补充来源登记，不冒充本人访谈。

完整路径、哈希、当前范围与剩余项见 stage.json。结构正确、业务定义确认、角色核查意见、正式验收和收益实现分别记录。
'''
    (out/'README.md').write_text(note,encoding='utf-8')
    print(json.dumps({'status':record['status'],'general_metrics':32,'large_structured_passed':'53/53',
        'answer_replay_reviewed':6,'end_to_end_passed':'2/2','runtime_files_archived':len(runtime_raw),
        'model_called':False,'output':str(out)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
