"""Record a full-suite answer review and fix first-order explanation guidance."""
import argparse
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/home/yang/FDE/w03-work/fde-agent-w03')
RUN = ROOT/'artifacts/w03/full38-p1-run-20261110-012528-047804'
REPORT = RUN/'nl-large-full-20261110-023201-558608/results/metric_test_report.json'
PROMPT = ROOT/'product/w03_answer_prompt.txt'
OLD_SHA = '4a29ed83b4a401f2eb8fef756f16c79fb7356a99310dfe880bc549b322b53405'
BAD_ID = 'single_first_order_sales_cents'
BAD_TEXT = '按订单号顺序确定每个账户的第一笔有效订单'
RULES = '''

[W03_FIRST_ORDER_EXPLANATION_V1]
当本轮选中指标的definitions涉及观测期首购、首单或后续订单时，口径说明必须忠实于其来源原文。若定义要求“按日期、订单号排序”或“相同日期按订单号排序”，完整含义是：先在全测试覆盖期的有效订单中，按每个CRM账户的下单日期升序排列，同一天再按订单号排序，确定首笔及后续有效订单；随后按相应订单日期筛选查询窗口。不能简写成只按订单号排序，也不能先筛选查询月份再找首单；覆盖期首单不代表终身首购。
如需简短说明，可写“先在全测试覆盖期内按日期、同日订单号确定账户首笔有效订单，再筛选查询月份”。解释首单净销售额时，说明汇总这些首单的净销售额；解释后续购买订单数时，说明统计全覆盖期内第二笔及以后、且订单日期落入查询窗口的有效订单，不是月内复购账户数。上述说明仅适用于本轮实际选中的相关定义，不向无关指标附加首单口径，不改变任何结果数值、单位、筛选或分组。
[/W03_FIRST_ORDER_EXPLANATION_V1]
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def prepare():
    old = PROMPT.read_bytes()
    if sha(old) != OLD_SHA:
        raise ValueError('PROMPT_VERSION_CHANGED')
    raw = REPORT.read_bytes()
    report = json.loads(raw)
    assert report['complete'] and report['passed'] == report['total'] == 67
    by_id = {c['id']: c for c in report['cases']}
    assert len(by_id) == 67 and all(c['comparison']['passed'] for c in by_id.values())
    bad = by_id[BAD_ID]['actual']
    assert BAD_TEXT in bad['answer'] and bad['rows'] == [[26191665]]
    catalog = json.loads((RUN/'build/catalog.json').read_text())
    entry = next(c for c in catalog if c['id'] == 'first_order_sales_cents')
    assert any('相同日期按订单号排序' in s['quote'] for s in entry['sources'])
    new = old + RULES.encode('utf-8')
    protected = [p for p in (RUN/'build').rglob('*') if p.is_file()]
    protected += [p for p in (ROOT/'materials/data').rglob('*') if p.is_file()]
    protected += [p for p in (ROOT/'platform/fde_product/metrics').rglob('*.py')]
    protected += [REPORT, ROOT/'customer/w03/build-metrics/SKILL.md', ROOT/'docs/w03/business_model.md', ROOT/'customer/w03/judge.py', ROOT/'product/w03_intent_prompt.txt']
    hashes = {str(p): sha(p.read_bytes()) for p in protected}
    review = dict(kind='ai_assisted_answer_review', report=str(REPORT), report_sha256=sha(raw),
        structured_passed=67, structured_total=67, answer_passed=66, answer_needs_fix=1,
        reviewed_by='assistant; all 67 actual answers/reasons and structured results read',
        human_signoff=False, business_confirmation='pending', final_acceptance=False,
        issue=dict(id=BAD_ID, actual_excerpt=BAD_TEXT,
            expected='按下单日期排序，同一天再按订单号排序；先定全覆盖首单，再筛窗口。',
            numeric_result_correct=True, defect='ordering explanation omits the primary date key'),
        nonblocking_notes=[dict(ids=['single_cancelled_order_count', 'orders_by_member__tier', 'reject_outside_coverage'],
            note='部分日期范围未明确右端点不含；查询月份或超覆盖结论正确。')],
        cases=[dict(id=cid, status='needs_fix' if cid == BAD_ID else 'pass',
            actual_text_sha256=sha((c['actual'].get('answer') or c['actual'].get('reason') or '').encode()))
            for cid, c in by_id.items()],
        retest_required=True, model_called=False)
    return old, new, hashes, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    old, new, hashes, review = prepare()
    print('预检通过：结构化67/67；文字66条通过、1条首单排序解释需修正。')
    print('目录原文已核对：相同日期按订单号排序；实际回答漏掉日期优先。')
    print('拟更新：product/w03_answer_prompt.txt；SHA256='+sha(new))
    if not args.apply:
        print('只读预检完成，未修改WSL工程或调用模型。')
        return
    dest = RUN/('answer-first-order-fix-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    (dest/'answer_prompt.before.txt').write_bytes(old)
    (dest/'answer_prompt.after.txt').write_bytes(new)
    (dest/'fix_script.py').write_bytes(Path(__file__).read_bytes())
    (dest/'answer_prompt.diff').write_text(''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile='before/product/w03_answer_prompt.txt', tofile='after/product/w03_answer_prompt.txt')), encoding='utf-8')
    save(dest/'answer_review.json', review)
    if PROMPT.read_bytes() != old:
        raise ValueError('CONCURRENT_PROMPT_CHANGE')
    PROMPT.write_bytes(new)
    assert PROMPT.read_bytes() == new
    assert all(sha(Path(p).read_bytes()) == digest for p, digest in hashes.items())
    save(dest/'change.json', dict(status='applied', prompt_before_sha256=sha(old), prompt_after_sha256=sha(new), protected_sha256=hashes, model_called=False, retest_required=True))
    print('文字核查记录、备份与差异：'+str(dest))
    print('仅更新回答提示；指标库、Skill、框架代码、判定器、原始数据与历史报告未修改，无需重建指标库。')
    print('尚未调用模型；下一步需真实复测首单及相关回答。')


if __name__ == '__main__':
    main()
