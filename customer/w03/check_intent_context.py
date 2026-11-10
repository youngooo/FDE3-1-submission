"""Offline assertions for enum-context reduction; no network or model."""
from copy import deepcopy
import json
from intent_context import prepare_intent_context, _literal_match


def run_checks():
    records = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        records.append(name)

    full = {'dimensions': {
        'member': {'kind': 'entity', 'name': '会员账户', 'values': [f'M{i:06d}' for i in range(30000)]},
        'store': {'kind': 'entity', 'name': '成交门店', 'values': ['S01', 'S02', 'S03']},
        'member__tier': {'kind': 'categorical', 'values': ['普通', '银卡', '金卡']},
        'metric_time__month': {'kind': 'time', 'values': []},
    }, 'per_metric': {'order_count': {'member': 'member', 'store': 'store'}}}
    original = deepcopy(full)
    dims, values, audit = prepare_intent_context('2026年8月创建订单数', [], full)
    check('aggregate_sends_no_member_enumeration', values['member'] == [])
    check('source_dimensions_unchanged', full == original)
    check('dimension_paths_preserved', dims['per_metric'] == full['per_metric'])
    check('small_enums_complete', values['store'] == full['dimensions']['store']['values'])
    check('chinese_small_enum_preserved', values['member__tier'] == ['普通', '银卡', '金卡'])
    check('no_duplicate_value_lists', all('values' not in d for d in dims['dimensions'].values()))
    check('time_dimensions_not_filters', 'metric_time__month' not in values)
    check('large_enum_marked_incomplete', audit['fields']['member']['enumeration_complete'] is False)
    check('large_context_reduced', audit['context_chars_after'] < audit['context_chars_before'] / 20)
    _, selected, _ = prepare_intent_context('请查M029999的订单，另查M000010', [], full)
    check('explicit_ids_outside_first_128_preserved', set(selected['member']) == {'M029999', 'M000010'})
    check('prefix_not_false_match', not _literal_match('M001', 'M0010') and not _literal_match('M001', 'XM001'))
    check('chinese_adjacent_identifier_matches', _literal_match('M001', '会员M001的金额'))
    check('case_not_silently_changed', not _literal_match('M001', 'm001'))
    _, selected, _ = prepare_intent_context('会员M999999的订单', [], full)
    check('unknown_identifier_not_invented', selected['member'] == [])
    _, selected, _ = prepare_intent_context('这个会员的8月订单', [{'role': 'user', 'content': '会员M029999'}], full)
    check('recent_history_explicit_id_retained', selected['member'] == ['M029999'])
    many = '、'.join(f'M{i:06d}' for i in range(200))
    _, selected, audit = prepare_intent_context(many, [], full)
    check('matched_enum_size_bounded', len(selected['member']) == 128)
    check('selection_overflow_explicit', audit['fields']['member']['selection_truncated'] is True
          and audit['fields']['member']['known_literal_matches'] == 200)
    tiny = deepcopy(full)
    tiny['dimensions']['member']['values'] = ['M01', 'M02']
    _, selected, audit = prepare_intent_context('汇总订单', [], tiny)
    check('small_dataset_members_stay_complete', selected['member'] == ['M01', 'M02']
          and audit['fields']['member']['enumeration_complete'] is True)
    return records


if __name__ == '__main__':
    checks = run_checks()
    print(json.dumps({'passed': True, 'checks': checks, 'checks_total': len(checks),
                      'model_called': False, 'query_executed': False}, ensure_ascii=False, indent=2))
