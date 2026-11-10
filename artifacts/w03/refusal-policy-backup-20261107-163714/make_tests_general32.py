"""Generate W03 natural-language cases from independent original-CSV oracles.

Run beside check_base16.py, check_orders24.py, check_member8.py and judge.py.
No LLM, query execution, generated SQL, or actual result files are read.
"""
import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

import check_base16 as base
import check_orders24 as financial
import check_member8 as member
import judge


GENERAL = tuple(financial.METRICS) + ('new_member_count',) + tuple(member.FIRST) + tuple(member.MONTHLY)
UNITS = {**financial.UNITS, **member.UNITS}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs(data, targets_path):
    manifest = base.read_json(data / 'manifest.json')
    if manifest.get('timezone') != 'Asia/Shanghai':
        raise ValueError('UNEXPECTED_TIMEZONE')
    if manifest['coverage'] != ['2024-09-01', '2026-09-01']:
        raise ValueError('CASE_DATES_REQUIRE_COURSE_COVERAGE')
    hashes = {}
    for name in ('orders.csv', 'members.csv', 'stores.csv', 'cards.csv'):
        hashes[name] = digest(data / name)
        if hashes[name] != manifest['sha256'].get(name):
            raise ValueError('RAW_DATA_HASH_MISMATCH: ' + name)
        rows = base.read_csv(data / name)
        table = name[:-4]
        key = {'orders': 'order_id', 'members': 'member_id', 'stores': 'store_id', 'cards': 'card_id'}[table]
        if len(rows) != manifest['counts'][table] or len({r[key] for r in rows}) != len(rows):
            raise ValueError('RAW_COUNT_OR_PRIMARY_KEY_MISMATCH: ' + name)
    oracle = member.Oracle(data)
    for row in oracle.orders:
        if row['member_id'] not in oracle.members or row['store_id'] not in oracle.stores:
            raise ValueError('ORDER_FOREIGN_KEY_MISSING')
    for row in oracle.members.values():
        if row['home_store_id'] not in oracle.stores:
            raise ValueError('MEMBER_HOME_STORE_MISSING')
    targets = base.read_json(targets_path)
    names = {item['id']: item['name'] for item in targets}
    if len(names) != len(targets) or not set(GENERAL) <= names.keys():
        raise ValueError('TARGETS_MISSING_OR_DUPLICATED')
    return manifest, hashes, oracle, names


def generate(oracle, manifest, names, versions):
    cases = []
    coverage_start, coverage_end = manifest['coverage']
    aug = ('2026-08-01', '2026-09-01')
    units_hint = '金额的查询结果保留整数分，均额使用分/单或分/账户，比率保留小数比例。'

    def add(case_id, family, metrics, question, start, end, groups=None, filters=None, status='ok'):
        intent = {'metrics': list(metrics), 'start': start, 'end': end,
                  'group_by': list(groups or []), 'filters': list(filters or [])}
        expected = {'status': status, 'intent': intent}
        if status == 'ok':
            if family == 'orders':
                values = financial.expectations(oracle.orders, oracle.members, oracle.stores, intent)
            else:
                values = getattr(oracle, family)(intent)
            columns = intent['group_by'] + intent['metrics']
            expected.update(columns=columns, rows=[
                list(key) + [row[m] for m in intent['metrics']]
                for key, row in sorted(values.items())
            ], units={m: UNITS[m] for m in intent['metrics']}, **versions)
        if family == 'orders':
            sources = ['materials/w03/01_订单日报说明.md', 'materials/w03/02_财务邮件.md',
                       'materials/w03/05_数据字典.md']
            method = 'Filter original orders by requested window/dimensions; calculate distinct accounts/stores, order conditions, cents and ratios independently.'
        else:
            sources = ['materials/w03/03_会员运营周报.md', 'materials/w03/05_数据字典.md']
            method = {'first': 'Rank effective orders over full coverage by ordered_at/order_id per account before applying query window and filters.',
                      'registration': 'Count original member registrations by registered_at, home store and tier.',
                      'monthly': 'Group original effective orders by month and account; count >=1 and >=2 orders, then divide with strict null denominator.',
                      'coverage': 'Compare requested half-open dates against manifest coverage; outside coverage is unsupported.'}[family]
        if status != 'ok':
            method += ' Expected refusal is a rule-based boundary decision, not an empty numeric result.'
        case = {'id': case_id, 'question': question, 'expected': expected,
                'expected_source': {'materials': sources, 'method': method,
                                    'source_csv': 'original CSV only; hashes in generation.json'}}
        check = judge.compare(expected, expected)
        if not check['passed']:
            raise ValueError('INVALID_EXPECTATION ' + case_id + ': ' + json.dumps(check, ensure_ascii=False))
        cases.append(case)

    # One question per target makes the 32-item coverage explicit and reviewable.
    for metric in GENERAL:
        family = ('orders' if metric in financial.METRICS else 'registration' if metric == 'new_member_count'
                  else 'first' if metric in member.FIRST else 'monthly')
        question = f'请只查询青禾2026年8月（2026-08-01含至2026-09-01不含）的{names[metric]}，全门店，不按维度分组。'
        if family == 'orders':
            question += '按原订单下单日期归属。' + units_hint
        elif family == 'first':
            question += '首单在完整测试覆盖历史内按有效订单确定，再筛选到8月；金额保留分。'
        elif family == 'registration':
            question += '按账户注册日期统计。'
        else:
            question += '按完整自然月统计，人数按CRM账户去重，复购率保留小数比例。'
        add('single_' + metric, family, [metric], question, *aug)

    trio = ['order_count', 'valid_order_count', 'net_sales_cents']
    add('aug_order_trio', 'orders', trio,
        '青禾2026年8月的创建订单数、有效订单数和净销售额分别是多少？按下单日期统计，全门店汇总，净销售额保留分。', *aug)
    add('aug_order_trio_paraphrase', 'orders', trio,
        '看青禾2026年8月：一共创建了多少笔订单，其中扣除退款后仍有正金额的已支付订单多少笔，净销售额合计多少分？取消单也算创建订单，全门店汇总。', *aug)
    for dim, wording in (
        ('store', '订单成交门店编号'), ('home_store', '会员归属门店编号'),
        ('order__status', '订单状态'), ('order__channel', '订单渠道'), ('member__tier', '会员等级'),
    ):
        add('aug_trio_by_' + dim, 'orders', trio,
            f'青禾2026年8月按{wording}分组，分别列出创建订单数、有效订单数、净销售额；按下单日期统计，金额保留分。',
            *aug, groups=[dim])
    add('aug_two_region_groups', 'orders', trio,
        '青禾2026年8月，同时按订单成交门店地区和会员归属门店地区分组，列出创建订单数、有效订单数、净销售额，金额保留分。',
        *aug, groups=['store__region', 'home_store__region'])
    add('aug_store_s01_filter', 'orders', trio,
        '青禾2026年8月只看订单成交门店编号S01，汇总创建订单数、有效订单数、净销售额，金额保留分，不再分组。',
        *aug, filters=[{'field': 'store', 'op': 'eq', 'value': 'S01'}])
    add('aug_cancelled_zero_denominator', 'orders', ['valid_order_count', 'net_sales_cents', 'avg_order_value', 'cancel_rate'],
        '青禾2026年8月，仅筛选订单状态cancelled（取消），汇总有效订单数、净销售额、有效订单均额及取消率。金额保留分，均额分/单，比率保留小数。',
        *aug, filters=[{'field': 'order__status', 'op': 'eq', 'value': 'cancelled'}])

    occupied = {r['ordered_at'] for r in oracle.orders}
    empty = date.fromisoformat(coverage_start)
    limit = date.fromisoformat(coverage_end)
    while empty < limit and empty.isoformat() in occupied:
        empty += timedelta(days=1)
    if empty < limit:
        end = empty + timedelta(days=1)
        add('covered_empty_day', 'orders', ['order_count', 'net_sales_cents', 'avg_order_value', 'refund_amount_rate'],
            f'青禾在{empty.isoformat()}当天（{empty.isoformat()}含至{end.isoformat()}不含），创建订单数、净销售额、有效订单均额、退款金额占比分别是多少？全门店，金额保留分、均额分/单，比率保留小数。',
            empty.isoformat(), end.isoformat())

    add('first_aug_store_filter', 'first', member.FIRST,
        '青禾2026年8月只看成交门店编号S01，列出观测期首购会员数、观测期首单数、观测期首单净销售额、观测期后续购买订单数。先在完整覆盖历史内确定各账户首笔有效订单，再按日期和成交门店筛选；金额保留分。',
        *aug, filters=[{'field': 'store', 'op': 'eq', 'value': 'S01'}])
    add('first_full_coverage', 'first', member.FIRST,
        f'青禾在{coverage_start}含至{coverage_end}不含的测试覆盖期内，观测期首购会员数、观测期首单数、观测期首单净销售额、观测期后续购买订单数分别是多少？全门店汇总，金额保留分。',
        coverage_start, coverage_end)
    for dim, wording in (('home_store', '会员归属门店编号'), ('member__tier', '会员等级')):
        add('registration_by_' + dim, 'registration', ['new_member_count'],
            f'青禾在{coverage_start}含至{coverage_end}不含，按注册日期统计注册会员数，并按{wording}分组。',
            coverage_start, coverage_end, groups=[dim])
    add('monthly_jul_aug', 'monthly', member.MONTHLY,
        '青禾2026年7月和8月两个完整自然月（2026-07-01含至2026-09-01不含），全门店按月分别列出月内购买会员数、月内复购会员数、月内复购率，不合并月份，复购率保留小数比例。',
        '2026-07-01', '2026-09-01', groups=['metric_time__month'])
    add('monthly_aug_paraphrase', 'monthly', member.MONTHLY,
        '青禾2026年8月全门店：当月至少买过一次的账户有多少，至少买过两次的有多少，后者占前者的比例是多少？购买仅计有效订单，按完整自然月统计。', *aug)
    busy_months = {o['ordered_at'][:7] for o in oracle.valid}
    empty_month = date.fromisoformat(coverage_start)
    while empty_month < limit and empty_month.strftime('%Y-%m') in busy_months:
        empty_month = member.next_month(empty_month)
    if empty_month < limit:
        end = member.next_month(empty_month)
        add('covered_empty_month', 'monthly', member.MONTHLY,
            f'青禾{empty_month.year}年{empty_month.month}月完整自然月（{empty_month.isoformat()}含至{end.isoformat()}不含），全门店的月内购买会员数、月内复购会员数及月内复购率分别是多少？不分组，比率保留小数。',
            empty_month.isoformat(), end.isoformat())
    add('reject_partial_month', 'monthly', ['monthly_repeat_rate'],
        '青禾2026年8月1日至8月15日（含15日）的月内复购率是多少？全门店，只要这15天的范围。',
        '2026-08-01', '2026-08-16', status='unsupported')
    add('reject_monthly_store_group', 'monthly', ['monthly_repeat_rate'],
        '请将青禾2026年8月完整自然月的月内复购率按订单成交门店编号分组返回。',
        *aug, groups=['store'], status='unsupported')
    add('reject_outside_coverage', 'coverage', trio,
        '青禾2026年9月的创建订单数、有效订单数和净销售额分别是多少？全门店汇总。',
        '2026-09-01', '2026-10-01', status='unsupported')
    cases.append({'id': 'clarify_missing_time',
                  'question': '青禾的净销售额是多少？', 'expected': {'status': 'clarify'},
                  'expected_source': {'materials': ['W03作业任务书：明确时段才查'],
                                      'method': 'Fresh standalone question supplies no date; no default reporting window is authorized.'}})
    assert len({c['id'] for c in cases}) == len(cases)
    covered = {m for c in cases if c['expected']['status'] == 'ok' for m in c['expected']['intent']['metrics']}
    assert covered == set(GENERAL)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('materials/data/small'))
    parser.add_argument('--targets', type=Path, default=Path('customer/w03/targets.json'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest, hashes, oracle, names = load_inputs(args.data, args.targets)
    dataset = base.read_json(args.project / 'dataset.json')
    for key in ('id', 'coverage', 'timezone'):
        if dataset.get(key) != manifest.get(key):
            raise ValueError('PROJECT_DATASET_MISMATCH: ' + key)
    if dataset.get('sha256') != manifest['sha256']:
        raise ValueError('PROJECT_CSV_HASH_MISMATCH')
    library_hash = dataset.get('library_sha256')
    if not isinstance(library_hash, str) or len(library_hash) != 64:
        raise ValueError('PROJECT_LIBRARY_HASH_REQUIRED')
    versions = {
        'data_version': dataset['id'],
        'data_sha256': hashlib.sha256(json.dumps(
            {k: v for k, v in dataset.items() if k != 'library_sha256'}, sort_keys=True).encode()).hexdigest(),
        'catalog_sha256': library_hash,
    }
    cases = generate(oracle, manifest, names, versions)
    smoke_ids = {'aug_order_trio', 'first_aug_store_filter', 'monthly_jul_aug',
                 'reject_partial_month', 'reject_outside_coverage'}
    smoke = [c for c in cases if c['id'] in smoke_ids]
    args.output.mkdir(parents=True, exist_ok=False)
    base.save(args.output / 'tests-general32.json', cases)
    base.save(args.output / 'tests-smoke.json', smoke)
    scripts = [Path(__file__), Path(base.__file__), Path(financial.__file__), Path(member.__file__), Path(judge.__file__)]
    target_ids = set(names)
    report = {
        'kind': 'independent_csv_natural_language_case_generation',
        'project': str(args.project.resolve()), 'data': str(args.data.resolve()),
        **versions, 'source_sha256': hashes,
        'manifest_sha256': digest(args.data / 'manifest.json'),
        'targets_sha256': digest(args.targets),
        'script_sha256': {p.name: digest(p) for p in scripts},
        'model_called': False, 'query_executed': False, 'actual_results_read': False,
        'cases_total': len(cases), 'smoke_cases_total': len(smoke),
        'metrics_covered': sorted(GENERAL), 'metrics_covered_count': len(GENERAL),
        'not_covered': sorted(target_ids - set(GENERAL)),
        'coverage_note': '32 general metrics only; six monthly paid metrics remain blocked by missing confirmed qualification rules.',
        'status': 'generated_not_executed',
    }
    base.save(args.output / 'generation.json', report)
    print(json.dumps({
        'status': report['status'], 'cases': len(cases), 'smoke_cases': len(smoke),
        'metrics_covered': len(GENERAL), 'not_covered': report['not_covered'],
        'output': str(args.output.resolve()), 'model_called': False,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
