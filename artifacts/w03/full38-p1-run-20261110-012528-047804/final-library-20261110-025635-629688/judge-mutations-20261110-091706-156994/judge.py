"""W03 deterministic result judge. stdin: expected/actual; stdout: decision.

No model, database, network, or generated SQL execution. Compare definitions
of expectations elsewhere; this module only compares the supplied payloads.
"""
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

ABS_TOL = Decimal('1e-8')
REL_TOL = Decimal('1e-9')
ALIASES = {'cents/order': 'cents_per_order', 'cents/account': 'cents_per_account',
           'orders/account': 'orders_per_account', 'items/order': 'items_per_order'}
EXACT_UNITS = {'count', 'cents'}
APPROX_UNITS = {'ratio', 'cents_per_order', 'cents_per_account',
                'orders_per_account', 'items_per_order'}
STATES = {'ok', 'unsupported', 'clarify', 'error'}


def unit(value):
    return ALIASES.get(value, value) if isinstance(value, str) else None


def names(value):
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError('Expected a list of nonempty names')
    if len(value) != len(set(value)):
        raise ValueError('Duplicate names')
    return sorted(value)


def filters(value):
    if not isinstance(value, list):
        raise ValueError('Filters must be a list')
    canonical = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {'field', 'op', 'value'}:
            raise ValueError('Malformed filter')
        if not isinstance(item['field'], str) or not item['field']:
            raise ValueError('Invalid filter field')
        if item['op'] == 'eq' and isinstance(item['value'], str):
            values = [item['value']]
        elif item['op'] == 'in' and isinstance(item['value'], list) and item['value']:
            if not all(isinstance(x, str) for x in item['value']):
                raise ValueError('Invalid IN filter values')
            values = sorted(set(item['value']))
        else:
            raise ValueError('Unsupported filter shape')
        canonical.append(json.dumps([item['field'], values], ensure_ascii=False))
    # AND ordering/repetition and eq versus single-value IN are equivalent.
    return sorted(set(canonical))


def intent_fields(value, required=True):
    if not isinstance(value, dict):
        raise ValueError('Intent must be an object')
    keys = ('metrics', 'start', 'end', 'group_by', 'filters')
    if required and any(k not in value for k in keys):
        raise ValueError('Incomplete successful intent')
    normalized = {}
    for k in keys:
        if k not in value:
            continue
        v = value[k]
        if k in ('metrics', 'group_by'):
            v = names(v)
        elif k == 'filters':
            v = filters(v)
        else:
            if not isinstance(v, str) or date.fromisoformat(v).isoformat() != v:
                raise ValueError('Intent dates must be YYYY-MM-DD')
        normalized[k] = v
    if required and (not normalized['metrics'] or normalized['start'] >= normalized['end']):
        raise ValueError('Invalid metric list or time window')
    return normalized


def number(value):
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('Not a number')
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Not a decimal number') from exc
    if not parsed.is_finite():
        raise ValueError('Non-finite number')
    return parsed


def group_value(field, value):
    if field == 'metric_time__month':
        if not isinstance(value, str):
            raise ValueError('Invalid month key')
        match = re.fullmatch(r'(\d{4}-\d{2})(?:-01(?:[ T]00:00:00(?:\.0+)?)?)?', value)
        if not match:
            raise ValueError('Month must be the first day at midnight')
        return date.fromisoformat(match[1] + '-01').isoformat()
    if field == 'metric_time__day':
        if not isinstance(value, str):
            raise ValueError('Invalid day key')
        match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:[ T]00:00:00(?:\.0+)?)?', value)
        if not match:
            raise ValueError('Invalid day key')
        return date.fromisoformat(match[1]).isoformat()
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError('Non-scalar group key')
    # Preserve types for categorical keys; ID 1 is not silently equal to "1".
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def table(payload, canonical_intent):
    metrics = canonical_intent['metrics']
    dims = canonical_intent['group_by']
    columns = payload.get('columns')
    if names(columns) != sorted(metrics + dims):
        raise ValueError('Columns differ from requested metrics and dimensions')
    if len(set(metrics + dims)) != len(metrics + dims):
        raise ValueError('Metric and dimension names overlap')
    raw_rows = payload.get('rows')
    if not isinstance(raw_rows, list):
        raise ValueError('Rows must be a list')
    if not dims and len(raw_rows) != 1:
        raise ValueError('Ungrouped result must have one row')
    units = payload.get('units')
    if not isinstance(units, dict) or set(units) != set(metrics):
        raise ValueError('Units must cover exactly the requested metrics')
    for metric in metrics:
        if unit(units[metric]) not in EXACT_UNITS | APPROX_UNITS:
            raise ValueError('Unsupported metric unit: ' + metric)
    rows = {}
    for values in raw_rows:
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError('Row width mismatch')
        row = dict(zip(columns, values))
        key = tuple(group_value(d, row[d]) for d in dims)
        if key in rows:
            raise ValueError('Duplicate group key')
        for metric in metrics:
            if row[metric] is not None:
                n = number(row[metric])
                if unit(units[metric]) in EXACT_UNITS and n != n.to_integral_value():
                    raise ValueError('Non-integer count or cents')
        rows[key] = row
    return rows


def compare(expected, actual):
    differences = []

    def add(kind, **detail):
        differences.append({'kind': kind, **detail})

    def finish():
        return {'passed': not differences, 'differences': differences}

    if not isinstance(expected, dict) or expected.get('status') not in STATES:
        add('invalid_expected', reason='Missing or invalid expected status')
        return finish()
    if not isinstance(actual, dict):
        add('invalid_actual', reason='Actual result is not an object')
        return finish()
    state = expected['status']
    if actual.get('status') != state:
        add('status_mismatch', expected=state, actual=actual.get('status'))
        return finish()
    for key in ('data_version', 'data_sha256', 'catalog_sha256'):
        if key in expected and actual.get(key) != expected[key]:
            add('version_mismatch', field=key, expected=expected[key], actual=actual.get(key))
    expected_intent = {}
    if state == 'ok' or 'intent' in expected:
        try:
            expected_intent = intent_fields(expected.get('intent'), required=state == 'ok')
        except (ValueError, TypeError) as exc:
            add('invalid_expected_intent', reason=str(exc))
            return finish()
        try:
            actual_intent = intent_fields(actual.get('intent'), required=state == 'ok')
            for field, wanted in expected_intent.items():
                if actual_intent.get(field) != wanted:
                    add('intent_mismatch', field=field, expected=wanted, actual=actual_intent.get(field))
        except (ValueError, TypeError) as exc:
            add('invalid_actual_intent', reason=str(exc))
    if state != 'ok':
        # A refusal/error is not allowed to carry numeric rows masquerading as an answer.
        if actual.get('rows') not in (None, []):
            add('unexpected_rows_for_non_ok')
        if 'code' in expected and actual.get('code') != expected['code']:
            add('error_code_mismatch')
        return finish()
    if isinstance(actual.get('intent'), dict) and actual['intent'].get('status', 'ok') != 'ok':
        add('contradictory_intent_status')
    if any(actual.get(k) not in (None, '', [], {}) for k in ('error', 'code')):
        add('error_markers_in_ok_result')
    try:
        expected_rows = table(expected, expected_intent)
    except (ValueError, TypeError) as exc:
        add('invalid_expected_table', reason=str(exc))
        return finish()
    try:
        actual_rows = table(actual, expected_intent)
    except (ValueError, TypeError) as exc:
        add('invalid_actual_table', reason=str(exc))
        return finish()
    for metric in expected_intent['metrics']:
        if unit(expected['units'][metric]) != unit(actual['units'][metric]):
            add('unit_mismatch', metric=metric, expected=expected['units'][metric], actual=actual['units'][metric])
    for key in sorted(set(expected_rows) | set(actual_rows)):
        if key not in expected_rows or key not in actual_rows:
            add('group_mismatch', group=list(key), expected=key in expected_rows, actual=key in actual_rows)
            continue
        for metric in expected_intent['metrics']:
            wanted, got = expected_rows[key][metric], actual_rows[key][metric]
            if wanted is None or got is None:
                equal = wanted is None and got is None
            else:
                e, a = number(wanted), number(got)
                equal = a == e if unit(expected['units'][metric]) in EXACT_UNITS else (
                    abs(a - e) <= max(ABS_TOL, abs(e) * REL_TOL))
            if not equal:
                add('value_mismatch', group=list(key), metric=metric, expected=wanted, actual=got)
    return finish()


def main():
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON constant: ' + value)
        payload = json.load(sys.stdin, parse_constant=invalid_constant)
        verdict = compare(payload['expected'], payload['actual'])
    except Exception as exc:
        verdict = {'passed': False, 'differences': [
            {'kind': 'judge_input_or_internal_error', 'reason': str(exc)}]}
    # A mismatch is a valid judgement, not a process failure (course contract).
    print(json.dumps(verdict, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
