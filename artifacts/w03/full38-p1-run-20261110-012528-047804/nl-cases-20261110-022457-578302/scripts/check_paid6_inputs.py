"""Read-only input checks for W03 P1; not qualification or metric acceptance."""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = {
    'members': ['member_id', 'registered_at', 'home_store_id', 'tier'],
    'stores': ['store_id', 'region', 'store_name'],
    'cards': ['card_id', 'member_id', 'card_type', 'valid_from', 'valid_until', 'ended_at', 'card_paid_cents'],
    'orders': ['order_id', 'member_id', 'store_id', 'ordered_at', 'status', 'gross_cents', 'paid_cents', 'refund_cents', 'quantity', 'channel'],
}
KEYS = {'members': 'member_id', 'stores': 'store_id', 'cards': 'card_id', 'orders': 'order_id'}
CARD_TYPES = {'悦享年卡', '家庭季卡', '异业联名卡', '体验卡'}


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('expected YYYY-MM-DD')
    return date.fromisoformat(value)


def card_date_issues(row):
    issues = []
    dates = {}
    for field in ('valid_from', 'valid_until', 'ended_at'):
        value = row.get(field)
        if value == '' and field == 'ended_at':
            dates[field] = None
        else:
            try:
                dates[field] = parse_date(value)
            except (ValueError, TypeError):
                issues.append('MISSING_OR_INVALID_' + field.upper())
    if 'valid_from' in dates and 'valid_until' in dates and dates['valid_from'] >= dates['valid_until']:
        issues.append('P1_UNTIL_NOT_AFTER_FROM')
    if dates.get('ended_at') is not None:
        if 'valid_from' in dates and dates['ended_at'] <= dates['valid_from']:
            issues.append('P1_ENDED_NOT_AFTER_FROM')
        if 'valid_until' in dates and dates['ended_at'] >= dates['valid_until']:
            issues.append('P1_ENDED_NOT_BEFORE_UNTIL')
    return issues


def audit(data):
    manifest_path = data / 'manifest.json'
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw.decode('utf-8-sig'))
    report = {'data_path': str(data.resolve()), 'dataset': manifest.get('id'),
              'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
              'files': {}, 'issue_counts': {}, 'examples': [], 'stats': {}}
    errors = Counter()
    def issue(code, table, row=None):
        errors[code] += 1
        if len(report['examples']) < 20:
            report['examples'].append({'code': code, 'table': table, 'record': row})
    if manifest.get('synthetic') is not True or manifest.get('timezone') != 'Asia/Shanghai':
        issue('MANIFEST_SCOPE_MISMATCH', 'manifest')
    try:
        start, end = map(parse_date, manifest['coverage'])
        if not start < end:
            raise ValueError('invalid coverage')
    except (KeyError, ValueError, TypeError):
        raise ValueError('manifest coverage invalid')
    ids = {}
    account_cards = Counter()
    card_types = Counter()
    ended_blank = 0
    observed_hashes = {}
    for table in ('stores', 'members', 'cards', 'orders'):
        source = data / (table + '.csv')
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        observed_hashes[source.name] = digest
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        header = reader.fieldnames or []
        header_ok = len(header) == len(set(header)) and set(header) == set(SCHEMA[table])
        if not header_ok:
            issue('SCHEMA_MISMATCH', table, {'header': header})
        if manifest.get('sha256', {}).get(source.name) != digest:
            issue('MANIFEST_HASH_MISMATCH', table)
        seen = set()
        n = 0
        for n, row in enumerate(reader, 1):
            if not header_ok:
                continue
            if None in row or any(v is None for v in row.values()):
                issue('CSV_ROW_WIDTH', table, {'row': n + 1})
                continue
            pk = row[KEYS[table]]
            if not pk or pk.strip() != pk:
                issue('MISSING_OR_PADDED_PRIMARY_KEY', table, row)
            elif pk in seen:
                issue('DUPLICATE_PRIMARY_KEY', table, row)
            seen.add(pk)
            if table in ('cards', 'orders') and row['member_id'] not in ids['members']:
                issue('MISSING_MEMBER_REFERENCE', table, row)
            if table == 'members' and row['home_store_id'] not in ids['stores']:
                issue('MISSING_HOME_STORE_REFERENCE', table, row)
            if table == 'orders' and row['store_id'] not in ids['stores']:
                issue('MISSING_ORDER_STORE_REFERENCE', table, row)
            if table == 'cards':
                card_types[row['card_type']] += 1
                account_cards[row['member_id']] += 1
                ended_blank += row['ended_at'] == ''
                if row['card_type'] not in CARD_TYPES:
                    issue('UNKNOWN_CARD_TYPE', table, row)
                for code in card_date_issues(row):
                    issue(code, table, row)
            if table in ('members', 'orders'):
                field = 'registered_at' if table == 'members' else 'ordered_at'
                try:
                    day = parse_date(row[field])
                    if table == 'orders' and not start <= day < end:
                        issue('ORDER_OUTSIDE_COVERAGE', table, row)
                except (ValueError, TypeError):
                    issue('INVALID_' + field.upper(), table, row)
            if table == 'orders':
                if row['status'] not in {'paid', 'cancelled'}:
                    issue('UNKNOWN_ORDER_STATUS', table, row)
                if row['channel'] not in {'门店', '小程序'}:
                    issue('UNKNOWN_CHANNEL', table, row)
                try:
                    fields = ['gross_cents', 'paid_cents', 'refund_cents', 'quantity']
                    if any(not re.fullmatch(r'-?\d+', row[k]) for k in fields):
                        raise ValueError('not integer')
                    gross, paid, refund, quantity = [int(row[k]) for k in fields]
                    if min(gross, paid, refund) < 0 or refund > paid or quantity <= 0:
                        issue('ORDER_AMOUNT_OR_QUANTITY', table, row)
                    if row['status'] == 'cancelled' and paid != 0:
                        issue('CANCELLED_NONZERO_PAYMENT', table, row)
                except ValueError:
                    issue('ORDER_NONINTEGER_NUMBER', table, row)
        ids[table] = seen
        if manifest.get('counts', {}).get(table) != n:
            issue('MANIFEST_COUNT_MISMATCH', table)
        report['files'][source.name] = {'rows': n, 'sha256': digest, 'header': header,
                                        'schema_matches': header_ok}
    # Recheck source bytes so a report cannot silently span an in-flight edit.
    for name, digest in observed_hashes.items():
        if hashlib.sha256((data / name).read_bytes()).hexdigest() != digest:
            issue('SOURCE_CHANGED_DURING_CHECK', name)
    if manifest_path.read_bytes() != manifest_raw:
        issue('MANIFEST_CHANGED_DURING_CHECK', 'manifest')
    report['issue_counts'] = dict(errors)
    report['passed'] = not errors
    report['stats'] = {'card_types': dict(card_types), 'ended_at_blank': ended_blank,
                       'accounts_with_multiple_cards': sum(n > 1 for n in account_cards.values()),
                       'independent_card_status_field': 'status' in report['files']['cards.csv']['header']}
    return report


def self_check():
    normal = {'valid_from': '2026-01-01', 'valid_until': '2026-09-01', 'ended_at': ''}
    cases = [
        ('正常空提前终止', normal, set()),
        ('正常提前终止', {**normal, 'ended_at': '2026-08-15'}, set()),
        ('提前终止晚于到期', {**normal, 'ended_at': '2026-09-02'}, {'P1_ENDED_NOT_BEFORE_UNTIL'}),
        ('提前终止等于到期待核', {**normal, 'ended_at': '2026-09-01'}, {'P1_ENDED_NOT_BEFORE_UNTIL'}),
        ('提前终止早于开始', {**normal, 'ended_at': '2025-12-31'}, {'P1_ENDED_NOT_AFTER_FROM'}),
        ('提前终止等于开始待核', {**normal, 'ended_at': '2026-01-01'}, {'P1_ENDED_NOT_AFTER_FROM'}),
        ('结束早于开始', {**normal, 'valid_until': '2025-12-31'}, {'P1_UNTIL_NOT_AFTER_FROM'}),
        ('缺少结束日期', {**normal, 'valid_until': ''}, {'MISSING_OR_INVALID_VALID_UNTIL'}),
        ('不合法日历日期', {**normal, 'ended_at': '2026-02-30'}, {'MISSING_OR_INVALID_ENDED_AT'}),
        ('有时分秒不当日期', {**normal, 'valid_from': '2026-01-01T00:00:00'}, {'MISSING_OR_INVALID_VALID_FROM'}),
    ]
    for label, row, expected in cases:
        actual = set(card_date_issues(row))
        if actual != expected:
            raise AssertionError((label, actual, expected))
    return [label for label, _, _ in cases]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, action='append', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise SystemExit('输出文件已存在，请用新路径。')
    checks = self_check()
    inputs = {}
    for rel in ['docs/w03/business_model.md', 'customer/w03/build-metrics/SKILL.md',
                'materials/w03/09_付费月报补访原文.md', 'customer/w03/build.json', 'customer/w03/targets.json']:
        inputs[rel] = hashlib.sha256((args.workspace / rel).read_bytes()).hexdigest()
    reports = [audit(path.resolve()) for path in args.data]
    passed = all(r['passed'] for r in reports)
    report = {'kind': 'w03_paid6_p1_input_preflight', 'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
              'passed': passed, 'business_confirmation': 'pending', 'metric_validation': 'not_run',
              'python': sys.version, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'input_sha256': inputs, 'date_guard_self_checks': checks, 'datasets': reports,
              'limitations': ['只检查数据前提，不计算资格或六项指标，不替代独立期望和回归。',
                             '日期等日或倒序列为P1不适用的待核输入，不宣称其业务上永久非法。',
                             '本版保守阻断任何卡的未决异常；并未实现异常卡与正常卡并存时的影响分析。',
                             '数据或规则改变后，构建/加载前必须重跑。单独运行本脚本不会自动拦截其他CLI命令。']}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(f'日期检查器自检：{len(checks)}/{len(checks)} 通过')
    for result in reports:
        counts = ', '.join(f'{k[:-4]}={v["rows"]}' for k, v in result['files'].items())
        print(f'{result["dataset"]}: {"PASS" if result["passed"] else "BLOCKED"}；{counts}')
        print('问题计数：' + json.dumps(result['issue_counts'], ensure_ascii=False))
    print('数据前置检查：' + ('通过' if passed else '未通过，停止后续构建/加载'))
    if args.output:
        print(f'报告：{args.output.resolve()}')
    print('总部业务确认仍待完成；本次未构建指标或调用模型。')
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
