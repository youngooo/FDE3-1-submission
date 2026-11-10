"""Hand-authored fixture checks, NOT Qinghe acceptance tests or a production oracle."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from paid6_prototype import aggregate, METRICS

MEMBERS = ['A', 'B', 'C', 'D', 'E']
def order(oid, member, day, paid, refund=0, status='paid', store='X', channel='门店'):
    return dict(order_id=oid, member_id=member, ordered_at=day, paid_cents=paid,
                refund_cents=refund, status=status, store_id=store, channel=channel)

ORDERS = [
    order('J1','A','2026-07-31',300), order('J2','C','2026-07-01',100),
    order('A1','A','2026-08-01',1000),
    order('A2','A','2026-08-31',1500,500,store='Y',channel='小程序'),
    order('B1','B','2026-08-10',500), order('C1','C','2026-08-15',900),
    order('D1','D','2026-08-16',0,status='cancelled'),
    order('D2','D','2026-08-17',600,600),
    order('S1','A','2026-09-01',999),
]
QUALIFIED = {'2026-07-01': {'C'}, '2026-08-01': {'A','B','D','E'}}
LEDGER = [dict(month=m, member_id=a, eligible=a in allowed)
          for m, allowed in QUALIFIED.items() for a in MEMBERS]
COVERAGE = ['2026-07-01','2026-10-01']


def run(args):
    dest=Path(args.output)
    if dest.exists():
        raise SystemExit('OUTPUT_ALREADY_EXISTS: use a new output directory')
    dest.mkdir(parents=True)
    checks=[]
    def numeric(cid, ledger, start, end, expected):
        try:
            actual=aggregate(ORDERS,MEMBERS,ledger,start,end,COVERAGE)
            wanted=[{'month':m, **dict(zip(METRICS,values))} for m,values in expected]
            differences=[]
            if len(actual['rows'])!=len(wanted): differences.append('row_count')
            for a,e in zip(actual['rows'],wanted):
                for k,value in e.items():
                    observed=a.get(k)
                    if value is None: ok=observed is None
                    elif isinstance(value,float): ok=type(observed) in (int,float) and math.isclose(observed,value,rel_tol=1e-9,abs_tol=1e-8)
                    else: ok=type(observed) is type(value) and observed==value
                    if not ok: differences.append({'field':k,'expected':value,'actual':observed})
            passed=not differences
            checks.append(dict(id=cid,passed=passed,expected=wanted,actual=actual,differences=differences))
        except Exception as exc:
            checks.append(dict(id=cid,passed=False,error=repr(exc)))
    def rejects(cid, code, **kwargs):
        params=dict(orders=ORDERS,member_ids=MEMBERS,eligibility=LEDGER,
                    start='2026-07-01',end='2026-09-01',coverage=COVERAGE)
        params.update(kwargs)
        try:
            aggregate(**params)
            actual='NO_ERROR'
        except ValueError as exc:
            actual=str(exc)
        except Exception as exc:
            actual=repr(exc)
        checks.append(dict(id=cid,expected_error=code,actual_error=actual,passed=actual==code))

    # Fixed expected results derived by hand, not from the function's output:
    # July C: one order, 100 cents. August A: 2 orders / 2000 cents;
    # B: 1 / 500; C excluded; D cancelled/full-refunded; E has no orders.
    numeric('two_months_separate_all_stores_channels',LEDGER,'2026-07-01','2026-09-01',[
        ('2026-07-01',[1,1,100,0,0.0,100.0]),
        ('2026-08-01',[2,3,2500,1,0.5,2500/3]),
    ])
    august=[d for d in LEDGER if d['month']=='2026-08-01']
    numeric('august_full_month_includes_first_and_last_day',august,'2026-08-01','2026-09-01',[
        ('2026-08-01',[2,3,2500,1,0.5,2500/3])])
    none=[{**d,'eligible':False} for d in august]
    numeric('known_no_eligible_accounts_zero_counts_null_ratios',none,'2026-08-01','2026-09-01',[
        ('2026-08-01',[0,0,0,0,None,None])])
    only_d=[{**d,'eligible':d['member_id']=='D'} for d in august]
    numeric('eligible_account_cancelled_and_full_refund_only',only_d,'2026-08-01','2026-09-01',[
        ('2026-08-01',[0,0,0,0,None,None])])
    rejects('missing_eligibility_not_false','ELIGIBILITY_INCOMPLETE',eligibility=LEDGER[:-1])
    unknown=deepcopy(LEDGER); unknown[0]['eligible']=None
    rejects('unknown_eligibility_not_false','ELIGIBILITY_UNRESOLVED',eligibility=unknown)
    rejects('duplicate_card_like_account_rows_rejected','DUPLICATE_ACCOUNT_MONTH_ELIGIBILITY',eligibility=LEDGER+[LEDGER[0]])
    rejects('duplicate_orders_not_silently_summed','INVALID_OR_DUPLICATE_ORDER_ID',orders=ORDERS+[ORDERS[0]])
    rejects('partial_month_rejected','FULL_MONTH_RANGE_REQUIRED',start='2026-07-02')
    rejects('outside_coverage_not_zero','OUTSIDE_DECLARED_COVERAGE',start='2026-06-01')
    bad=deepcopy(ORDERS); bad[0]['refund_cents']=301
    rejects('refund_above_payment_rejected','INVALID_CENTS',orders=bad)
    rejects('no_qualification_ledger_not_zero','ELIGIBILITY_INCOMPLETE',eligibility=[])
    fixture={'kind':'hand_authored_test_fixture_not_customer_confirmation','member_ids':MEMBERS,
             'orders':ORDERS,'eligibility':LEDGER,'coverage':COVERAGE,
             'note':'资格布尔值由测试作者指定，不来自青禾卡规则；无卡类型、端点或结束日组合算法。'}
    (dest/'fixture.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ['paid6_prototype.py','check_paid6_prototype.py']}
    report={'kind':'paid6_aggregation_fixture_check','passed':all(c['passed'] for c in checks),
            'cases_passed':sum(c['passed'] for c in checks),'cases_total':len(checks),
            'scope':'人工账户月资格夹具下六项聚合，不验证青禾资格规则，不是最终38项验收',
            'expected_basis':'手工列示订单及预先固定算术期望，不使用实际结果倒填',
            'model_called':False,'production_query_executed':False,'eligibility_rules_verified':False,
            'script_sha256':hashes,'cases':checks}
    (dest/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for c in checks: print(('PASS ' if c['passed'] else 'FAIL ')+c['id'])
    print(json.dumps({k:v for k,v in report.items() if k not in ['cases','script_sha256']},ensure_ascii=False,indent=2))
    print('report:',dest/'report.json')
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    raise SystemExit(run(parser.parse_args()))
