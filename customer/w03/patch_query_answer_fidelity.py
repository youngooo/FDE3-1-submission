"""Append audited intent/answer rules and select unchanged regression cases."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

INTENT_MARKER = '[W03_QUERY_FIDELITY_V1]'
ANSWER_MARKER = '[W03_ANSWER_FIDELITY_V1]'
INTENT_RULES = '''
[W03_QUERY_FIDELITY_V1]
先区分用户请求的指标与展示格式要求。用户明确“只查询”某项或列举若干指标时，metrics 仅包含这些指标；“金额保留分”“均额使用分/单”“复购率保留小数比例”等格式说明本身不构成新增指标请求。不要因为格式句提到某指标就顺带查询，也不要为解释分母而自行增加指标。用户明确同时请求另一指标时才纳入。
对指标策略允许的、结构可用且取值已知的筛选，保留用户筛选交由执行层计算。指标内部的 paid、有效订单等计算条件，与用户按订单状态等筛选分析是不同层次；筛选后可能得到零或零分母，不因此认定筛选非法。零分母的比率或均额返回未定义（null）仍是可执行查询，不是整条请求 unsupported；覆盖范围外、明确策略禁止或结构不可用才按相应限制处理。
普通订单比率的分子、分母在同一合法筛选范围内分别聚合，不能擅自移除筛选或改用筛选外的分母。不得把“全部订单”擅自解释成忽略用户所有合法筛选的全局订单；如指标定义确实指定不同范围，则按定义而非本条默认处理。首购仍先按全覆盖有效历史确定再筛选；full_month_only 的整月、分组与筛选限制保持原样，不能被本段覆盖。
[/W03_QUERY_FIDELITY_V1]
'''
ANSWER_RULES = '''
[W03_ANSWER_FIDELITY_V1]
回答前对照实际结果的每列数值、单位和本轮 definitions。用户明确要求分、分/单、分/账户或小数比例时，优先按其指定单位展示，不能擅自只改成元或百分数。整数金额保留整数分；均额可以有小数，不能套用整数金额的要求。若用户指定原始单位，不额外换算其他单位。
单位 cents 是分；cents/order 和 cents_per_order 是分/单；cents/account 和 cents_per_account 是分/账户。这些单位改为元、元/单、元/账户时，数值必须先除以100，不能只替换单位文字，也不能声称已换算而保留原数值。ratio 是小数比例；仅当展示百分数时乘以100并加百分号。四舍五入不改变数量级。未明确要求换算且无法可靠核对时保留执行结果原单位，不做换算。
解释比率时直接写出分子、分母的完整业务名称，严格使用 definitions 中的定义；不要使用容易倒置的“前者除以后者”等指代。月内复购率的分子为月内复购会员数，分母为同月月内购买会员数；不把注册人数、跨月合计或相反的比值作为分母或公式。仅有比率而未返回人数时，可以说明公式，不能编造人数。
零、null 和拒绝不同：执行成功的零如实展示；null 写“未定义”，依定义解释零分母，不把整条查询说成失败。部分列未定义时仍展示其他已返回列。不要从未返回列猜测具体数值，不添加未请求指标。回答只包含实际范围、数值及必要口径，逐项核对文字中的单位和公式后输出。
[/W03_ANSWER_FIDELITY_V1]
'''
CASE_IDS = [
    'single_monthly_repeat_buyer_count', 'aug_cancelled_zero_denominator',
    'single_avg_buyer_value', 'monthly_jul_aug', 'single_cancel_rate',
    'covered_empty_day', 'aug_trio_by_store',
    'reject_partial_month', 'reject_outside_coverage',
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, body):
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def select_cases(source, report):
    ids = [c['id'] for c in source]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_SOURCE_IDS')
    index = {c['id']: c for c in source}
    observed = {c['id']: c for c in report['cases']}
    if len(observed) != len(report['cases']) or set(observed) != set(index):
        raise ValueError('REPORT_SOURCE_IDS_DIFFER')
    for key, c in observed.items():
        if any(c.get(k) != index[key].get(k) for k in ('question', 'expected')):
            raise ValueError('REPORT_SOURCE_CONTENT_DIFFERS: ' + key)
    if any(key not in index for key in CASE_IDS):
        raise ValueError('REGRESSION_CASE_MISSING')
    return [index[key] for key in CASE_IDS]


def plan(root, source, report):
    cases = select_cases(source, report)
    intent = root / 'product/w03_intent_prompt.txt'
    answer = root / 'product/w03_answer_prompt.txt'
    intent_old, answer_old = intent.read_bytes(), answer.read_bytes()
    it, at = intent_old.decode('utf-8'), answer_old.decode('utf-8')
    if INTENT_MARKER in it or ANSWER_MARKER in at:
        raise ValueError('PATCH_ALREADY_PRESENT: inspect prior patch record')
    if not all(marker in it for marker in ('[W03_POLICY_EXPLANATION_V1]', '[W03_BOUNDED_ENUMS_V1]')):
        raise ValueError('PRIOR_POLICY_OR_CONTEXT_PROMPT_MISSING')
    agent = root / 'platform/fde_product/metrics/agent.py'
    agent_text = agent.read_text(encoding='utf-8')
    if not all(s in agent_text for s in ("ROOT/'product/w03_intent_prompt.txt'", "ROOT/'product/w03_answer_prompt.txt'", 'prepare_intent_context')):
        raise ValueError('AGENT_LOADING_OR_CONTEXT_DIFFERS')
    if not all(s in at for s in ('answer', 'used_metrics', 'citations')):
        raise ValueError('ANSWER_CONTRACT_DIFFERS')
    changes = []
    for path, old, addition in ((intent, intent_old, INTENT_RULES), (answer, answer_old, ANSWER_RULES)):
        new = old + (b'' if old.endswith(b'\n') else b'\n') + addition.encode('utf-8')
        changes.append((path, old, new))
    return changes, cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, default=Path('.'))
    ap.add_argument('--cases', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.workspace.resolve()
    source_raw, report_raw = args.cases.read_bytes(), args.report.read_bytes()
    source, report = json.loads(source_raw), json.loads(report_raw)
    changes, cases = plan(root, source, report)
    protected_paths = [root / 'platform/fde_product/metrics' / name for name in ('agent.py', 'engine.py', 'intent_context.py')]
    protected_paths.append(root / 'customer/w03/judge.py')
    protected = {str(p): sha(p.read_bytes()) for p in protected_paths}
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for path, old, new in changes:
        (args.output / (path.stem + '.before.txt')).write_bytes(old)
        (args.output / (path.stem + '.after.txt')).write_bytes(new)
        diff = ''.join(difflib.unified_diff(old.decode('utf-8').splitlines(keepends=True), new.decode('utf-8').splitlines(keepends=True), fromfile=str(path)+' (before)', tofile=str(path)+' (after)'))
        (args.output / (path.stem + '.diff')).write_text(diff, encoding='utf-8')
        records.append({'file': str(path), 'before_sha256': sha(old), 'after_sha256': sha(new)})
    save(args.output / 'regression-cases.json', cases)
    save(args.output / 'prior-failures.json', [c for c in report['cases'] if not c.get('comparison', {}).get('passed')])
    save(args.output / 'answer-review-required.json', {
        'automatic_answer_semantic_validation': False,
        'cases': {
            'single_avg_buyer_value': '按分/账户展示实际值；不能原数值直接标元/账户。',
            'monthly_jul_aug': '明确复购人数除以购买人数；按月展示小数比例。',
            'single_monthly_repeat_buyer_count': '只查询并回答请求的复购人数，不追加复购率。',
            'aug_cancelled_zero_denominator': '按原合法筛选执行，展示零/null/取消率，不能拒绝或改分母范围。',
            'aug_trio_by_store': '用户要求金额保留分时，各门店金额按分展示。',
        },
        'note': 'Judge checks structured results; successful comparison alone does not certify answer prose.',
    })
    record = {'status': 'prepared', 'model_called': False, 'query_executed': False,
              'regression_cases': len(cases), 'expected_values_changed': False,
              'source_cases': str(args.cases.resolve()), 'source_cases_sha256': sha(source_raw),
              'source_report': str(args.report.resolve()), 'source_report_sha256': sha(report_raw),
              'source_passed': report.get('passed'), 'source_total': report.get('total'),
              'prompt_changes': records, 'protected_sha256': protected,
              'script_sha256': sha(Path(__file__).read_bytes()),
              'answer_review_status': 'pending_real_regression_and_manual_review'}
    save(args.output / 'patch.json', record)
    if any(path.read_bytes() != old for path, old, _ in changes):
        raise ValueError('PROMPT_CHANGED_DURING_PREPARATION')
    for path, _, new in changes:
        path.write_bytes(new)
    if any(path.read_bytes() != new for path, _, new in changes):
        raise ValueError('PROMPT_WRITE_VERIFICATION_FAILED')
    if any(sha(Path(p).read_bytes()) != h for p, h in protected.items()):
        raise ValueError('PROTECTED_CODE_CHANGED')
    record['status'] = 'applied'
    save(args.output / 'patch.json', record)
    print(json.dumps({k: record[k] for k in ('status', 'regression_cases', 'model_called', 'expected_values_changed', 'answer_review_status')}, ensure_ascii=False, indent=2))
    print('output: ' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
