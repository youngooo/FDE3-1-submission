"""Exercise judge.py via its actual stdin/stdout interface; no LLM/SQL.

Hand-authored comparison fixtures, not claimed as Qinghe query results.
Correct controls must pass; deliberate corruptions must fail with differences.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def fixture():
    return {
        'status': 'ok',
        'intent': {
            'metrics': ['order_count', 'valid_order_count', 'net_sales_cents', 'avg_order_value', 'cancel_rate'],
            'start': '2026-08-01', 'end': '2026-09-01', 'group_by': ['store'],
            'filters': [{'field': 'store__region', 'op': 'eq', 'value': '华东'},
                        {'field': 'order__channel', 'op': 'in', 'value': ['门店', '小程序']}],
        },
        'columns': ['store', 'order_count', 'valid_order_count', 'net_sales_cents', 'avg_order_value', 'cancel_rate'],
        'rows': [['S01', 4, 2, 10000, 5000, 0.25], ['S02', 2, 0, 0, None, 1.0]],
        'units': {'order_count': 'count', 'valid_order_count': 'count', 'net_sales_cents': 'cents',
                  'avg_order_value': 'cents_per_order', 'cancel_rate': 'ratio'},
        'data_version': 'judge-fixture-only', 'data_sha256': 'fixture-data', 'catalog_sha256': 'fixture-catalog',
    }


def build_cases():
    cases = []
    original = fixture()

    def add(name, category, expected=None, actual=None, should_pass=False):
        cases.append({'id': name, 'category': category, 'should_pass': should_pass,
                      'expected': deepcopy(original if expected is None else expected),
                      'actual': deepcopy(original if actual is None else actual)})

    def mutation(name, category, change):
        actual = deepcopy(original)
        change(actual)
        add(name, category, actual=actual)

    add('identity', 'positive_control', should_pass=True)
    reordered = deepcopy(original)
    order = [5, 3, 0, 4, 2, 1]
    reordered['columns'] = [original['columns'][i] for i in order]
    reordered['rows'] = [[row[i] for i in order] for row in reversed(original['rows'])]
    reordered['intent']['metrics'].reverse()
    reordered['intent']['filters'].reverse()
    reordered['intent']['filters'][0]['value'].reverse()
    add('rows_columns_metrics_filters_reordered', 'positive_control', actual=reordered, should_pass=True)
    alias = deepcopy(original)
    alias['units']['avg_order_value'] = 'cents/order'
    add('equivalent_unit_spelling', 'positive_control', actual=alias, should_pass=True)
    equiv_filter = deepcopy(original)
    equiv_filter['intent']['filters'][0].update(op='in', value=['华东'])
    add('eq_equals_singleton_in', 'positive_control', actual=equiv_filter, should_pass=True)
    close = deepcopy(original)
    close['rows'][0][5] += 1e-10
    add('ratio_within_tolerance', 'positive_control', actual=close, should_pass=True)
    month = deepcopy(original)
    month['intent']['group_by'] = ['metric_time__month']
    month['intent']['start'] = '2026-07-01'
    month['columns'][0] = 'metric_time__month'
    month['rows'][0][0], month['rows'][1][0] = '2026-07-01', '2026-08-01'
    month_actual = deepcopy(month)
    month_actual['rows'][0][0] = '2026-07-01 00:00:00'
    month_actual['rows'][1][0] = '2026-08-01T00:00:00'
    add('midnight_month_format', 'positive_control', expected=month, actual=month_actual, should_pass=True)
    refused = {'status': 'unsupported', 'intent': {
        'metrics': ['monthly_repeat_rate'], 'start': '2026-08-01', 'end': '2026-08-16',
        'group_by': [], 'filters': []}, 'reason': 'Fixture partial month'}
    refused_actual = deepcopy(refused)
    refused_actual['reason'] = 'Different wording, same unsupported intent'
    add('refusal_reason_not_word_for_word', 'positive_control', expected=refused,
        actual=refused_actual, should_pass=True)
    failure = {'status': 'error', 'code': 'FIXTURE_ERROR'}
    add('expected_error_state', 'positive_control', expected=failure, actual=failure, should_pass=True)

    mutation('wrong_metric', 'wrong_metric', lambda a: a['intent']['metrics'].__setitem__(0, 'paid_order_count'))
    mutation('wrong_start', 'wrong_date', lambda a: a['intent'].__setitem__('start', '2026-07-01'))
    mutation('wrong_end', 'wrong_date', lambda a: a['intent'].__setitem__('end', '2026-08-31'))
    mutation('wrong_filter_value', 'wrong_filter', lambda a: a['intent']['filters'][0].__setitem__('value', '华南'))
    mutation('missing_filter', 'wrong_filter', lambda a: a['intent']['filters'].pop())
    mutation('extra_filter', 'wrong_filter', lambda a: a['intent']['filters'].append(
        {'field': 'member__tier', 'op': 'eq', 'value': '金卡'}))
    mutation('wrong_group_dimension', 'wrong_group', lambda a: a['intent'].__setitem__('group_by', ['home_store']))
    mutation('missing_group', 'missing_group', lambda a: a['rows'].pop())
    mutation('duplicate_group', 'wrong_group', lambda a: a['rows'].append(deepcopy(a['rows'][0])))
    mutation('extra_group', 'wrong_group', lambda a: a['rows'].append(['S03', 1, 1, 100, 100, 0]))
    mutation('wrong_group_key', 'wrong_group', lambda a: a['rows'][0].__setitem__(0, 'S09'))
    mutation('cents_value_divided_by_100', 'yuan_cents', lambda a: a['rows'][0].__setitem__(3, 100))
    mutation('cents_unit_changed_to_yuan', 'yuan_cents', lambda a: a['units'].__setitem__('net_sales_cents', 'yuan'))
    mutation('ratio_value_times_100', 'ratio_percent', lambda a: a['rows'][0].__setitem__(5, 25))
    mutation('ratio_unit_changed_to_percent', 'ratio_percent', lambda a: a['units'].__setitem__('cancel_rate', 'percent'))
    mutation('null_changed_to_zero', 'null_zero', lambda a: a['rows'][1].__setitem__(4, 0))
    mutation('zero_changed_to_null', 'null_zero', lambda a: a['rows'][1].__setitem__(3, None))
    mutation('count_plus_one', 'tampered_value', lambda a: a['rows'][0].__setitem__(1, 5))
    mutation('ratio_outside_tolerance', 'tampered_value', lambda a: a['rows'][0].__setitem__(5, 0.2501))
    mutation('boolean_as_count', 'tampered_value', lambda a: a['rows'][0].__setitem__(1, True))
    mutation('nonfinite_ratio', 'tampered_value', lambda a: a['rows'][0].__setitem__(5, 'NaN'))
    mutation('noninteger_cents', 'tampered_value', lambda a: a['rows'][0].__setitem__(3, 10000.1))
    mutation('wrong_data_version', 'wrong_version', lambda a: a.__setitem__('data_sha256', 'other-data'))
    mutation('wrong_library_version', 'wrong_version', lambda a: a.__setitem__('catalog_sha256', 'other-catalog'))
    mutation('query_returns_error', 'error_as_ok', lambda a: a.__setitem__('status', 'error'))
    mutation('error_marker_retained_in_ok', 'error_as_ok', lambda a: a.__setitem__('error', 'DBT_FAILURE'))
    add('error_payload_status_relabelled_ok', 'error_as_ok',
        actual={'status': 'ok', 'reason': 'DBT_FAILURE'})
    add('expected_error_forged_as_success', 'error_as_ok', expected=failure, actual=original)
    add('unsupported_forged_as_success', 'wrong_status', expected=refused, actual=original)
    bad_refusal = deepcopy(refused)
    bad_refusal['intent']['end'] = '2026-09-01'
    add('refusal_wrong_time_window', 'wrong_date', expected=refused, actual=bad_refusal)
    mutation('contradictory_intent_status', 'wrong_status', lambda a: a['intent'].__setitem__('status', 'unsupported'))
    mutation('row_width_mismatch', 'wrong_group', lambda a: a['rows'][0].pop())
    mutation('duplicate_column', 'wrong_group', lambda a: a['columns'].__setitem__(1, 'store'))
    invalid_month = deepcopy(month)
    invalid_month['rows'][0][0] = '2026-07-02 00:00:00'
    add('wrong_month_boundary_key', 'wrong_group', expected=month, actual=invalid_month)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--judge', type=Path, default=Path(__file__).with_name('judge.py'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    judge_path = args.judge.resolve()
    if not judge_path.is_file():
        raise SystemExit('Judge script not found')
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    for case in build_cases():
        payload = {'expected': case['expected'], 'actual': case['actual']}
        error = None
        verdict = None
        try:
            run = subprocess.run([sys.executable, str(judge_path)],
                                 input=json.dumps(payload, ensure_ascii=False),
                                 text=True, encoding='utf-8', capture_output=True, timeout=20)
            if run.returncode != 0:
                raise ValueError(f'Judge process failed: {run.returncode} {run.stderr}')
            verdict = json.loads(run.stdout)
            if type(verdict.get('passed')) is not bool or not isinstance(verdict.get('differences'), list):
                raise ValueError('Invalid judge output schema')
            if verdict['passed'] != (not verdict['differences']):
                raise ValueError('Contradictory judge output')
            if any(d.get('kind') == 'judge_input_or_internal_error' for d in verdict['differences']):
                raise ValueError('Internal error is not successful corruption detection')
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
        passed = error is None and verdict['passed'] == case['should_pass']
        record = {**case, 'verdict': verdict, 'harness_error': error, 'passed': passed}
        (args.output / (case['id'] + '.json')).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        checks.append({k: record[k] for k in ('id', 'category', 'should_pass', 'passed', 'verdict', 'harness_error')})
        print(('PASS ' if passed else 'FAIL ') + case['id'], flush=True)
    negatives = [c for c in checks if not c['should_pass']]
    positives = [c for c in checks if c['should_pass']]
    required = {'wrong_metric', 'wrong_date', 'wrong_filter', 'wrong_group', 'missing_group',
                'yuan_cents', 'ratio_percent', 'null_zero', 'tampered_value', 'error_as_ok'}
    category_coverage = required <= {c['category'] for c in negatives if c['passed']}
    report = {
        'kind': 'deterministic_judge_error_injection',
        'fixture_basis': 'Hand-authored comparator fixtures; not Qinghe business results or query-derived expectations',
        'judge_path': str(judge_path),
        'judge_sha256': hashlib.sha256(judge_path.read_bytes()).hexdigest(),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'python': sys.version, 'model_called': False, 'query_executed': False,
        'positive_controls_passed': sum(c['passed'] for c in positives),
        'positive_controls_total': len(positives),
        'mutations_rejected': sum(c['passed'] for c in negatives),
        'mutations_total': len(negatives), 'required_categories_covered': category_coverage,
        'complete': True, 'passed': all(c['passed'] for c in checks) and category_coverage,
        'cases': checks,
    }
    path = args.output / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in (
        'passed', 'positive_controls_passed', 'positive_controls_total',
        'mutations_rejected', 'mutations_total', 'model_called', 'query_executed')}, indent=2))
    print('report: ' + str(path.resolve()))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
