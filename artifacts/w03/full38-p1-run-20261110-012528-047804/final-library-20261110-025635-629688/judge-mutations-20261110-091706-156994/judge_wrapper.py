"""Use the existing strict judge; allow two contract-valid missing-value responses."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path('/home/yang/FDE/w03-work/fde-agent-w03')
sys.path.insert(0,str(ROOT/'customer/w03'))
import judge as strict


def compare(expected,actual):
    if not isinstance(expected,dict):return strict.compare(expected,actual)
    allowed=expected.get('allowed_statuses')
    if allowed is None:return strict.compare(expected,actual)
    if expected.get('boundary_kind')!='nonexistent_filter_value' or set(allowed)!={'unsupported','clarify'} or len(allowed)!=2 or expected.get('status') not in allowed:
        return {'passed':False,'differences':[{'kind':'invalid_boundary_policy'}]}
    if not isinstance(actual,dict) or actual.get('status') not in allowed:
        return {'passed':False,'differences':[{'kind':'status_mismatch','expected_any':allowed,'actual':actual.get('status') if isinstance(actual,dict) else None}]}
    adjusted=deepcopy(expected);adjusted['status']=actual['status']
    result=strict.compare(adjusted,actual)
    if not isinstance(actual.get('reason'),str) or not actual['reason'].strip():
        result['differences'].append({'kind':'missing_boundary_reason'});result['passed']=False
    return result


def self_checks():
    expected=dict(status='unsupported',allowed_statuses=['unsupported','clarify'],boundary_kind='nonexistent_filter_value')
    for state in ['unsupported','clarify']:
        assert compare(expected,dict(status=state,reason='编号不在数据范围内'))['passed']
    for actual in [dict(status='ok',rows=[[0]]),dict(status='error'),dict(status='unsupported',reason=''),dict(status='clarify',reason='未知',rows=[[0]])]:
        assert not compare(expected,actual)['passed']
    assert not compare(dict(status='unsupported'),dict(status='clarify',reason='未知'))['passed']
    assert not compare({**expected,'boundary_kind':'undefined_metric'},dict(status='unsupported',reason='未知'))['passed']
    return 8


def main():
    try:
        payload=json.load(sys.stdin)
        result=compare(payload['expected'],payload['actual'])
    except Exception as exc:
        result={'passed':False,'differences':[{'kind':'judge_input_or_internal_error','reason':str(exc)}]}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
