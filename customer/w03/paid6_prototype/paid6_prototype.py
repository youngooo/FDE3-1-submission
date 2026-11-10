"""Development-only paid monthly aggregation; no card eligibility algorithm.

Input eligibility is a COMPLETE account x month ledger, with boolean eligibility.
The caller must declare the covered data interval and all member IDs.
This module neither reads cards nor registers metrics with the product.
"""
from collections import Counter
from datetime import date

METRICS = (
    'monthly_paid_buyer_count', 'monthly_paid_order_count',
    'monthly_paid_sales_cents', 'monthly_paid_repeat_buyer_count',
    'monthly_paid_repeat_rate', 'monthly_paid_avg_order_value',
)
UNITS = dict(zip(METRICS, ('count', 'count', 'cents', 'count', 'ratio', 'cents_per_order')))


def next_month(value):
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def aggregate(orders, member_ids, eligibility, start, end, coverage):
    """Aggregate full months, all stores/channels, using supplied eligibility.

    eligibility rows: {'month':'YYYY-MM-01','member_id':str,'eligible':bool}.
    No default false: missing, duplicate or unknown qualification fails closed.
    Counts use distinct accounts; order IDs must be globally unique.
    """
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    low, high = map(date.fromisoformat, coverage)
    if start.day != 1 or end.day != 1 or start >= end:
        raise ValueError('FULL_MONTH_RANGE_REQUIRED')
    if low >= high or start < low or end > high:
        raise ValueError('OUTSIDE_DECLARED_COVERAGE')
    members = set(member_ids)
    if len(members) != len(member_ids) or any(not isinstance(x, str) or not x for x in members):
        raise ValueError('INVALID_MEMBER_KEYS')
    months = []
    cursor = start
    while cursor < end:
        months.append(cursor.isoformat())
        cursor = next_month(cursor)
    expected_keys = {(m, member) for m in months for member in members}
    decisions = {}
    for row in eligibility:
        key = (row['month'], row['member_id'])
        if key not in expected_keys:
            raise ValueError('UNEXPECTED_ELIGIBILITY_KEY')
        if key in decisions:
            raise ValueError('DUPLICATE_ACCOUNT_MONTH_ELIGIBILITY')
        if type(row['eligible']) is not bool:
            raise ValueError('ELIGIBILITY_UNRESOLVED')
        decisions[key] = row['eligible']
    if set(decisions) != expected_keys:
        raise ValueError('ELIGIBILITY_INCOMPLETE')

    seen = set()
    counts = {m: Counter() for m in months}
    sales = {m: 0 for m in months}
    for order in orders:
        oid = order['order_id']
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ValueError('INVALID_OR_DUPLICATE_ORDER_ID')
        seen.add(oid)
        member = order['member_id']
        if member not in members:
            raise ValueError('UNKNOWN_ORDER_ACCOUNT')
        when = date.fromisoformat(order['ordered_at'])
        if not low <= when < high:
            raise ValueError('ORDER_OUTSIDE_DECLARED_COVERAGE')
        paid, refund = order['paid_cents'], order['refund_cents']
        if type(paid) is not int or type(refund) is not int or not 0 <= refund <= paid:
            raise ValueError('INVALID_CENTS')
        if order['status'] not in {'paid', 'cancelled'}:
            raise ValueError('INVALID_ORDER_STATUS')
        if order['status'] == 'cancelled' and (paid != 0 or refund != 0):
            raise ValueError('INVALID_CANCELLED_AMOUNT')
        if not start <= when < end:
            continue
        month = when.replace(day=1).isoformat()
        net = paid - refund
        if decisions[(month, member)] and order['status'] == 'paid' and net > 0:
            counts[month][member] += 1
            sales[month] += net

    results = []
    for month in months:
        buyer_count = len(counts[month])
        order_count = sum(counts[month].values())
        repeat_count = sum(n >= 2 for n in counts[month].values())
        values = (buyer_count, order_count, sales[month], repeat_count,
                  repeat_count / buyer_count if buyer_count else None,
                  sales[month] / order_count if order_count else None)
        results.append({'month': month, **dict(zip(METRICS, values))})
    return {
        'kind': 'paid6_aggregation_prototype',
        'eligibility_calculated_by_module': False,
        'business_eligibility_verified': False,
        'start': start.isoformat(), 'end': end.isoformat(),
        'coverage': [low.isoformat(), high.isoformat()],
        'units': UNITS, 'rows': results,
    }
