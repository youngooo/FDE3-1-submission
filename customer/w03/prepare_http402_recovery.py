"""Preserve HTTP 402 evidence and prepare unchanged retry cases; no API calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report, source = read(args.report), read(args.cases)
    if report.get('complete') is not True:
        raise SystemExit('SOURCE_RUN_INCOMPLETE: inspect before preparing this recovery')
    original = {c['id']: c for c in source}
    if len(original) != len(source):
        raise SystemExit('DUPLICATE_SOURCE_CASE_IDS')
    run_cases = report['cases']
    if len(run_cases) != len(source) or {c['id'] for c in run_cases} != set(original):
        raise SystemExit('SOURCE_CASES_DO_NOT_MATCH_REPORT')
    retries = []
    failures = []
    for item in run_cases:
        case = original[item['id']]
        if item['question'] != case['question'] or item['expected'] != case['expected']:
            raise SystemExit('QUESTION_OR_EXPECTATION_CHANGED: ' + item['id'])
        if item['comparison']['passed']:
            continue
        actual = item['actual']
        failures.append({'id': item['id'], 'status': actual.get('status'),
                         'code': actual.get('code'), 'trace_id': actual.get('trace_id')})
        if actual.get('status') == 'error' and actual.get('code') == 'MODEL_HTTP_402':
            retries.append(case)
    if not retries:
        raise SystemExit('NO_HTTP_402_CASES')
    probe = next((c for c in retries if c['expected']['status'] == 'ok'), None)
    if probe is None:
        raise SystemExit('NO_SUCCESS_EXPECTED_CASE_FOR_NATIVE_PROBE')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / 'retry-cases.json', retries)
    save(args.output / 'model-probe-case.json', [probe])
    save(args.output / 'native-probe-query.json', probe['expected']['intent'])
    save(args.output / 'native-probe-expected.json', probe['expected'])
    record = {
        'status': 'prepared_not_retried',
        'source_report': str(args.report.resolve()), 'source_report_sha256': sha(args.report),
        'source_cases': str(args.cases.resolve()), 'source_cases_sha256': sha(args.cases),
        'script_sha256': sha(Path(__file__)),
        'total_cases': len(source), 'source_passed': sum(c['comparison']['passed'] for c in run_cases),
        'retry_cases': len(retries), 'native_probe_case': probe['id'],
        'failure_code_counts': dict(Counter(str(f['code']) for f in failures)),
        'failures': failures,
        'expectations_modified': False, 'model_called': False, 'query_executed': False,
        'billing_cause': 'Provider returned HTTP 402; exact account/billing state must be checked with the configured provider.',
        'resume_condition': 'Resolve provider billing/access first; then run the single model probe before the pending retry batch.',
    }
    save(args.output / 'recovery.json', record)
    print(json.dumps({k: record[k] for k in (
        'status', 'source_passed', 'total_cases', 'retry_cases', 'native_probe_case',
        'failure_code_counts', 'expectations_modified', 'model_called')}, ensure_ascii=False, indent=2))
    print('output: ' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
