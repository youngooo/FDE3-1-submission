"""Independent raw-CSV oracle for W03 paid6 under provisional P1.

Default: offline preflight and hand-fixed oracle self-checks only.
--run: query the loaded project, preserving expectations before each query.
Never changes the library, source CSV, or business confirmation status.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/home/yang/FDE/w03-work/fde-agent-w03')
LIBRARY = ROOT / 'artifacts/w03/full38-p1-run-20261109-234602-844810/build'
sys.path.insert(0, str(ROOT / 'customer/w03'))
sys.path.insert(0, str(ROOT / 'platform'))
from check_paid6_inputs import audit
from fde_product.metrics.common import library_digest

METRICS = ['monthly_paid_buyer_count', 'monthly_paid_order_count',
           'monthly_paid_sales_cents', 'monthly_paid_repeat_buyer_count',
           'monthly_paid_repeat_rate', 'monthly_paid_avg_order_value']
UNITS = dict(zip(METRICS, ['count', 'count', 'cents', 'count', 'ratio', 'cents_per_order']))
SCOPE = {'悦享年卡', '家庭季卡'}
ABS_TOL, REL_TOL = Decimal('1e-8'), Decimal('1e-9')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def next_month(day):
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


def monthly_oracle(cards, orders, start, end):
    """P1, already preflighted normal dates only. No generated SQL is read."""
    current, stop = date.fromisoformat(start), date.fromisoformat(end)
    if current.day != 1 or stop.day != 1 or current >= stop:
        raise ValueError('FULL_MONTH_RANGE_REQUIRED')
    orders_by_month = defaultdict(list)
    for order in orders:
        if start <= order['ordered_at'] < end:
            orders_by_month[order['ordered_at'][:7] + '-01'].append(order)
    result, ledger = {}, {}
    while current < stop:
        month = current.isoformat()
        cutoff = (next_month(current) - timedelta(days=1)).isoformat()
        active = defaultdict(list)
        for card in cards:
            if (card['card_type'] in SCOPE and card['valid_from'] <= cutoff
                    and cutoff < card['valid_until']
                    and (not card['ended_at'] or cutoff < card['ended_at'])):
                active[card['member_id']].append(card['card_id'])
        counts, cents, order_ids = Counter(), 0, []
        for order in orders_by_month[month]:
            net = int(order['paid_cents']) - int(order['refund_cents'])
            if order['member_id'] in active and order['status'] == 'paid' and net > 0:
                counts[order['member_id']] += 1
                cents += net
                order_ids.append(order['order_id'])
        buyers, total = len(counts), sum(counts.values())
        repeat = sum(n >= 2 for n in counts.values())
        result[month] = dict(zip(METRICS, [buyers, total, cents, repeat,
            str(Decimal(repeat) / Decimal(buyers)) if buyers else None,
            str(Decimal(cents) / Decimal(total)) if total else None]))
        ledger[month] = {'qualification_day': cutoff,
                         'eligible_account_cards': dict(sorted(active.items())),
                         'valid_order_ids': sorted(order_ids),
                         'orders_per_buyer': dict(sorted(counts.items()))}
        current = next_month(current)
    return result, ledger


def self_checks():
    def card(cid, member, begin='2026-01-01', until='2026-09-01', ended='', kind='悦享年卡'):
        return dict(card_id=cid, member_id=member, valid_from=begin,
                    valid_until=until, ended_at=ended, card_type=kind)
    cards = [card('A1','A',begin='2026-08-31'), card('A2','A',kind='家庭季卡'),
             card('B','B',until='2026-08-31'), card('C','C',ended='2026-08-31'),
             card('D','D',kind='体验卡'), card('E','E',begin='2026-09-01',until='2026-10-01'),
             card('F1','F',ended='2026-08-15'), card('F2','F',begin='2026-08-20'),
             card('G','G')]
    def order(oid, member, paid, refund=0, day='2026-08-01', status='paid'):
        return dict(order_id=oid, member_id=member, paid_cents=str(paid),
                    refund_cents=str(refund), ordered_at=day, status=status)
    orders = [order('a1','A',1000), order('a2','A',1000,500,day='2026-08-31'),
              order('f','F',500), order('b','B',900), order('c','C',800),
              order('d','D',700), order('e','E',600), order('g','G',400,400),
              order('cancel','A',0,status='cancelled'), order('outside','A',999,day='2026-09-01')]
    actual, ledger = monthly_oracle(cards, orders, '2026-08-01', '2026-09-01')
    wanted = dict(zip(METRICS, [2, 3, 2000, 1, '0.5', str(Decimal(2000)/3)]))
    assert actual['2026-08-01'] == wanted, 'HAND_FIXED_AGGREGATE_FAILED'
    assert set(ledger['2026-08-01']['eligible_account_cards']) == {'A','F','G'}
    assert ledger['2026-08-01']['valid_order_ids'] == ['a1','a2','f']
    empty, _ = monthly_oracle(cards, [], '2026-08-01', '2026-09-01')
    assert list(empty['2026-08-01'].values()) == [0,0,0,0,None,None]
    return ['month_end_boundaries_and_card_scope', 'multiple_cards_account_dedup',
            'orders_before_card_start_included', 'expired_card_with_another_valid_card',
            'partial_refund_net_cancelled_full_refund_exclusion', 'empty_zero_counts_null_ratios']


def make_cases(coverage, oracle, stores):
    cases = []
    def add(cid, start='2026-08-01', end='2026-09-01', group=None, filters=None,
            status='ok', reason=None, metrics=None):
        cases.append({'id':cid, 'expected_status':status, 'reason_contains':reason,
            'intent':dict(metrics=METRICS if metrics is None else metrics,
                          start=start,end=end,group_by=group or [],filters=filters or [])})
    for name, start, end in [('aug','2026-08-01','2026-09-01'),
                              ('jul','2026-07-01','2026-08-01'),
                              ('jun','2026-06-01','2026-07-01')]:
        add('paid_'+name,start,end)
    add('paid_jul_aug','2026-07-01','2026-09-01',['metric_time__month'])
    add('paid_all_covered_months',*coverage,['metric_time__month'])
    empty = next((m for m,v in oracle.items() if v[METRICS[0]] == 0), None)
    if empty:
        add('paid_zero_buyers',empty,next_month(date.fromisoformat(empty)).isoformat())
    add('reject_partial_start',start='2026-08-02',status='unsupported',reason='完整自然月')
    add('reject_partial_end',end='2026-08-31',status='unsupported',reason='完整自然月')
    for suffix, group in [('day','metric_time__day'),('store','store'),('channel','order__channel')]:
        add('reject_group_'+suffix,group=[group],status='unsupported',reason='完整自然月')
    for suffix, field, value in [('store','store',stores[0]['store_id']),('channel','order__channel','门店')]:
        add('reject_paid_filter_'+suffix,filters=[dict(field=field,op='eq',value=value)],
            status='unsupported',reason='全门店全渠道')
    add('reject_multimonth_total',start='2026-07-01',status='unsupported',reason='按月展示')
    before=(date.fromisoformat(coverage[0])-timedelta(days=1)).replace(day=1).isoformat()
    add('reject_outside_coverage',start=before,end=coverage[0],status='unsupported',reason='超出数据覆盖')
    add('clarify_missing_start',start=None,status='clarify',reason='明确时间范围')
    add('reject_undefined_metric',metrics=['w03_undefined_metric_probe'],status='unsupported',reason='指标未定义')
    missing='__W03_NONEXISTENT_STORE__'
    assert missing not in {s['store_id'] for s in stores}
    add('reject_nonexistent_filter_value',metrics=['order_count'],
        filters=[dict(field='store',op='eq',value=missing)],status='unsupported',reason='筛选值不在')
    return cases


def numeric_equal(metric, actual, expected):
    if expected is None:
        return actual is None
    if actual is None or isinstance(actual,bool):
        return False
    try:
        a,e=Decimal(str(actual)),Decimal(str(expected))
        if not a.is_finite() or not e.is_finite():
            return False
        return a == e if metric in METRICS[:4] else abs(a-e)<=max(ABS_TOL,abs(e)*REL_TOL)
    except (InvalidOperation,ValueError):
        return False


def compare(actual, expected, case, dataset, data_hash):
    errors=[]
    if actual.get('status') != case['expected_status']:
        return [dict(kind='status_mismatch',expected=case['expected_status'],actual=actual)]
    if case['expected_status'] != 'ok':
        if case['reason_contains'] not in actual.get('reason',''):
            errors.append(dict(kind='rejection_reason_mismatch',actual=actual.get('reason')))
        return errors
    intent=case['intent']
    if actual.get('intent') != intent:
        errors.append(dict(kind='intent_mismatch'))
    wanted=intent['group_by']+intent['metrics']
    columns=actual.get('columns',[])
    if len(columns)!=len(set(columns)) or set(columns)!=set(wanted):
        return errors+[dict(kind='columns_mismatch',actual=columns)]
    got={}
    for values in actual.get('rows',[]):
        if len(values)!=len(columns):
            errors.append(dict(kind='row_width_mismatch'));continue
        row=dict(zip(columns,values))
        key=intent['start']
        if intent['group_by']:
            try:
                dt=datetime.fromisoformat(str(row['metric_time__month']))
                if dt.day!=1 or any((dt.hour,dt.minute,dt.second,dt.microsecond)):
                    raise ValueError('month boundary')
                key=dt.date().isoformat()
            except (TypeError,ValueError):
                errors.append(dict(kind='invalid_month_key'));continue
        if key in got:
            errors.append(dict(kind='duplicate_group',month=key))
        got[key]=row
    for month in sorted(set(got)|set(expected)):
        if month not in got or month not in expected:
            errors.append(dict(kind='group_mismatch',month=month));continue
        for metric in intent['metrics']:
            if not numeric_equal(metric,got[month][metric],expected[month][metric]):
                errors.append(dict(kind='value_mismatch',month=month,metric_id=metric,
                    expected=expected[month][metric],actual=got[month][metric]))
    for metric in intent['metrics']:
        unit=actual.get('units',{}).get(metric)
        canonical='cents_per_order' if unit=='cents/order' else unit
        if canonical!=UNITS[metric]:
            errors.append(dict(kind='unit_mismatch',metric_id=metric,expected=UNITS[metric],actual=unit))
    for field,value in [('data_version',dataset['id']),('data_sha256',data_hash),
                         ('catalog_sha256',dataset['library_sha256'])]:
        if actual.get(field)!=value:
            errors.append(dict(kind='version_mismatch',field=field))
    return errors


def prepare(args):
    checks=self_checks()
    data_report=audit(args.data)
    if not data_report['passed']:
        raise ValueError('P1_INPUT_BLOCKED: '+json.dumps(data_report['issue_counts']))
    dataset=read(args.project/'dataset.json')
    manifest=read(args.data/'manifest.json')
    if any(dataset[k]!=manifest[k] for k in ('id','coverage','sha256','counts')):
        raise ValueError('PROJECT_DATA_MISMATCH')
    if read(args.project/'validation.json').get('passed') is not True:
        raise ValueError('PROJECT_NOT_VALIDATED')
    if dataset['library_sha256']!=library_digest(args.library):
        raise ValueError('PROJECT_LIBRARY_MISMATCH')
    for path in [args.library/'metrics.yml', *args.library.glob('*.sql')]:
        if path.read_bytes()!=(args.project/'models'/path.name).read_bytes():
            raise ValueError('PROJECT_MODEL_CHANGED: '+path.name)
    if (args.library/'catalog.json').read_bytes()!=(args.project/'catalog.json').read_bytes():
        raise ValueError('PROJECT_CATALOG_CHANGED')
    catalog=read(args.project/'catalog.json')
    if not set(METRICS)<={m['id'] for m in catalog}:
        raise ValueError('PAID6_NOT_IN_PROJECT')
    oracle,ledger=monthly_oracle(rows(args.data/'cards.csv'),rows(args.data/'orders.csv'),*manifest['coverage'])
    cases=make_cases(manifest['coverage'],oracle,rows(args.data/'stores.csv'))
    data_hash=hashlib.sha256(json.dumps({k:v for k,v in dataset.items() if k!='library_sha256'},sort_keys=True).encode()).hexdigest()
    tracked=[Path(__file__), ROOT/'customer/w03/check_paid6_inputs.py',
             ROOT/'platform/fde_product/metrics/engine.py',ROOT/'tools/w03.py',
             ROOT/'docs/w03/business_model.md',ROOT/'customer/w03/build-metrics/SKILL.md',
             *sorted((ROOT/'materials/w03').glob('*.md')),args.data/'manifest.json',
             *sorted(args.data.glob('*.csv')),args.project/'dataset.json',args.project/'catalog.json',
             args.project/'models/metrics.yml',*sorted((args.project/'models').glob('*.sql'))]
    return checks,data_report,dataset,data_hash,oracle,ledger,cases,{str(p):sha(p) for p in tracked}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--library',type=Path,default=LIBRARY,
                        help='Bind checks to this library; default is the first full38 build.')
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    args.project=args.project.resolve();args.data=args.data.resolve();args.output=args.output.resolve()
    args.library=args.library.resolve()
    if args.output.exists():
        raise ValueError('OUTPUT_EXISTS: use a new path')
    started=time.monotonic()
    checks,preflight,dataset,data_hash,oracle,ledger,cases,hashes=prepare(args)
    print(f'预检通过：P1输入正常，项目绑定本轮38项库；独立核算器自检 {len(checks)}/{len(checks)}。',flush=True)
    print(f'已准备 {len(cases)} 个场景；数值期望独立来自原始CSV，未读取生成SQL计算期望。',flush=True)
    if not args.run:
        print('只读预检完成，未查询项目、未写入报告、未调用模型。')
        return 0
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'expected_months.json',oracle)
    save(args.output/'account_month_ledger.json',ledger)
    save(args.output/'cases.json',cases)
    save(args.output/'input_preflight.json',preflight)
    report=dict(kind='paid6_independent_csv_p1',business_confirmation='pending',model_called=False,
        expected_basis='materials04 + P1 date rule and card scope; original CSV; hand-checked oracle',
        project=str(args.project),library=str(args.library),data_version=dataset['id'],catalog_sha256=dataset['library_sha256'],
        input_sha256=hashes,self_checks=checks,started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        environment=dict(python=sys.version,platform=platform.platform(),
            packages={p:importlib.metadata.version(p) for p in ['duckdb','dbt-core','dbt-metricflow']}),
        comparison_policy=dict(integer='exact',null='strict',absolute_tolerance=str(ABS_TOL),relative_tolerance=str(REL_TOL),
            unit_aliases={'cents/order':'cents_per_order'}),
        limitations=['P1总部适用性待确认','异常卡由前置检查阻断，本次不验证未决异常业务处理',
                     '结构化查询核验不替代自然语言回归与解释核查'],cases=[],complete=False,passed=False)
    save(args.output/'report.json',report)
    for case in cases:
        folder=args.output/case['id'];folder.mkdir()
        intent=case['intent']
        expected={m:v for m,v in oracle.items() if intent['start']<=m<intent['end']} if case['expected_status']=='ok' else {}
        save(folder/'query.json',intent)
        save(folder/'expected.json',dict(status=case['expected_status'],months=expected,reason_contains=case['reason_contains']))
        print('RUN '+case['id'],flush=True)
        tick=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'tools/w03.py'),'query','--project',str(args.project),
                '--input',str(folder/'query.json'),'--output',str(folder/'actual.json')],cwd=ROOT,
                capture_output=True,text=True,encoding='utf-8',timeout=240)
            (folder/'query.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
            actual=read(folder/'actual.json') if (folder/'actual.json').exists() else {}
            errors=compare(actual,expected,case,dataset,data_hash)
            if proc.returncode:
                errors.append(dict(kind='process_failed',returncode=proc.returncode))
        except (subprocess.TimeoutExpired,OSError,ValueError,KeyError,TypeError) as exc:
            errors=[dict(kind='execution_or_comparison_error',reason=str(exc))]
        item=dict(id=case['id'],passed=not errors,checked_metrics=intent['metrics'],
                  elapsed_seconds=round(time.monotonic()-tick,3),errors=errors)
        save(folder/'comparison.json',item);report['cases'].append(item)
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        save(args.output/'report.json',report)
        print(('PASS ' if item['passed'] else 'FAIL ')+case['id'],flush=True)
    report['input_changed_during_run']=[p for p,digest in hashes.items() if sha(Path(p))!=digest]
    report['complete']=len(report['cases'])==len(cases)
    report['passed']=report['complete'] and all(c['passed'] for c in report['cases']) and not report['input_changed_during_run']
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    report['finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    save(args.output/'report.json',report)
    print(json.dumps(dict(passed=report['passed'],cases_passed=sum(c['passed'] for c in report['cases']),
        cases_total=len(cases),paid_metrics=6,elapsed_seconds=report['elapsed_seconds'],
        report=str(args.output/'report.json'),business_confirmation='pending'),ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
