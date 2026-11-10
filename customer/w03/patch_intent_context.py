"""Install audited bounded enum context and prepare two independent query probes."""
import argparse
from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path

import check_base16 as base
import judge
from check_intent_context import run_checks
from intent_context import prepare_intent_context

MARKER = '[W03_BOUNDED_ENUMS_V1]'
PROMPT_ADDITION = '''
[W03_BOUNDED_ENUMS_V1]
filter_values 是本轮提供的筛选候选值，available_dimensions 只描述维度、字段含义和指标关联，不再重复包含 values。filter_value_metadata 说明每个枚举的总量、是否完整以及是否发生候选截断。
enumeration_complete=true 时，filter_values 是该维度完整的已知值；false 时，仅提供从完整本地枚举中与本次问题或近期对话明确文字匹配的已知值，绝不是完整名单或随机样例。不得依据这个局部列表推断业务总人数、认为所有未列出值都不存在，或把列表内容自动当成用户已提出的筛选。只有问题或有效上下文明示筛选才添加过滤条件；当前问题优先，不能沿用已经被当前问题取消的历史筛选。
对于明确的编号筛选，使用已提供的精确匹配值，不补全或猜测其他编号；无法定位用户所指对象时澄清，明显无法支持的请求说明限制。selection_truncated=true 时，不得将截断的候选子集冒充用户要求的完整集合，应请求缩小或明确范围。执行层仍会用完整本地取值校验请求。
所有维度与筛选仍须符合指标 query_policy 和 constraints；精简枚举不增加权限或业务能力，也不改变 full_month_only 的限制。
[/W03_BOUNDED_ENUMS_V1]
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, body):
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def patch_agent(raw):
    text = raw.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    text = text.replace('\r\n', '\n')
    if 'prepare_intent_context' in text:
        raise ValueError('AGENT_CONTEXT_PATCH_ALREADY_PRESENT')
    replacements = {
        'from .common import read,dump,call_json\n':
        'from .common import read,dump,call_json\nfrom .intent_context import prepare_intent_context\n',
        "  dimensions=read(self.project/'dimensions.json')\n  values={k:v['values'] for k,v in dimensions['dimensions'].items() if v['kind']!='time'}\n":
        "  dimensions_full=read(self.project/'dimensions.json')\n  dimensions,values,context_summary=prepare_intent_context(question,(history or [])[-6:],dimensions_full)\n  dump(folder/'intent-context-summary.json',context_summary)\n",
        "'filter_values':values,'available_dimensions':dimensions":
        "'filter_values':values,'filter_value_metadata':context_summary['fields'],'available_dimensions':dimensions",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError('AGENT_SOURCE_DIFFERS: expected one context-building anchor')
        text = text.replace(old, new)
    compile(text, 'agent.py', 'exec')
    return text.replace('\n', newline).encode('utf-8')


def make_probes(data, dataset, dimensions, source_cases):
    manifest = base.read_json(data / 'manifest.json')
    if any(dataset[k] != manifest[k] for k in ('id', 'coverage', 'sha256')):
        raise ValueError('PROJECT_DATASET_MISMATCH')
    for name, expected_hash in manifest['sha256'].items():
        if sha((data / name).read_bytes()) != expected_hash:
            raise ValueError('CSV_HASH_MISMATCH: ' + name)
    versions = {'data_version': dataset['id'], 'catalog_sha256': dataset['library_sha256'],
                'data_sha256': sha(json.dumps({k: v for k, v in dataset.items() if k != 'library_sha256'}, sort_keys=True).encode())}
    first = deepcopy(next(c for c in source_cases if c['id'] == 'single_valid_order_items'))
    for key, value in versions.items():
        if first['expected'].get(key) != value:
            raise ValueError('CASE_PROJECT_VERSION_MISMATCH: ' + key)
    orders = base.read_csv(data / 'orders.csv')
    start, end = first['expected']['intent']['start'], first['expected']['intent']['end']
    selected = [r for r in orders if start <= r['ordered_at'] < end]
    if base.calculate(selected)['valid_order_items'] != first['expected']['rows'][0][0]:
        raise ValueError('AGGREGATE_EXPECTATION_DIFFERS_FROM_RAW_CSV')
    active_members = sorted({r['member_id'] for r in selected
                             if r['status'] == 'paid' and int(r['paid_cents']) > int(r['refund_cents'])})
    if not active_members:
        raise ValueError('NO_ACTIVE_ACCOUNT_FOR_FILTER_PROBE')
    member_id = active_members[-1]
    if member_id not in dimensions['dimensions']['member']['values']:
        raise ValueError('PROBE_MEMBER_MISSING_FROM_FULL_VALUES')
    values = base.calculate([r for r in selected if r['member_id'] == member_id])
    metrics = ['order_count', 'valid_order_count', 'net_sales_cents']
    intent = {'metrics': metrics, 'start': start, 'end': end, 'group_by': [],
              'filters': [{'field': 'member', 'op': 'eq', 'value': member_id}]}
    expected = {'status': 'ok', 'intent': intent, 'columns': metrics,
                'rows': [[values[m] for m in metrics]],
                'units': {'order_count': 'count', 'valid_order_count': 'count', 'net_sales_cents': 'cents'}, **versions}
    second = {
        'id': 'explicit_member_filter_after_context_reduction',
        'question': f'青禾{start}含至{end}不含，只筛选CRM会员账户ID为{member_id}的订单，汇总创建订单数、有效订单数和净销售额；金额保留分，不分组。',
        'expected': expected,
        'expected_source': {'materials': ['materials/w03/01_订单日报说明.md', 'materials/w03/05_数据字典.md'],
                            'method': 'Select the last sorted account with valid orders in this window; calculate its original orders.csv rows independently.',
                            'member_id': member_id, 'source_sha256': manifest['sha256'],
                            'oracle_sha256': sha(Path(base.__file__).read_bytes())},
    }
    for case in (first, second):
        if not judge.compare(case['expected'], case['expected'])['passed']:
            raise ValueError('PROBE_EXPECTED_SCHEMA_INVALID')
    return [first, second]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path('.'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--source-trace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checks = run_checks()
    root = args.workspace.resolve()
    agent_path = root / 'platform/fde_product/metrics/agent.py'
    helper_path = agent_path.with_name('intent_context.py')
    engine_path = agent_path.with_name('engine.py')
    prompt_path = root / 'product/w03_intent_prompt.txt'
    agent_old, prompt_old = agent_path.read_bytes(), prompt_path.read_bytes()
    engine_hash = sha(engine_path.read_bytes())
    dimensions_path = args.project / 'dimensions.json'
    dimensions_raw = dimensions_path.read_bytes()
    dimensions = json.loads(dimensions_raw)
    dataset = base.read_json(args.project / 'dataset.json')
    if MARKER in prompt_old.decode('utf-8'):
        raise ValueError('CONTEXT_PROMPT_PATCH_ALREADY_PRESENT')
    if '[W03_POLICY_EXPLANATION_V1]' not in prompt_old.decode('utf-8'):
        raise ValueError('MONTHLY_POLICY_PATCH_MISSING: review current product prompt first')
    helper_raw = Path(__file__).with_name('intent_context.py').read_bytes()
    compile(helper_raw.decode('utf-8'), 'intent_context.py', 'exec')
    if helper_path.exists() and helper_path.read_bytes() != helper_raw:
        raise ValueError('EXISTING_DIFFERENT_CONTEXT_HELPER')
    helper_existed = helper_path.exists()
    agent_new = patch_agent(agent_old)
    prompt_new = prompt_old + (b'' if prompt_old.endswith(b'\n') else b'\n') + PROMPT_ADDITION.encode('utf-8')
    source_trace = base.read_json(args.source_trace)
    user_messages = [m for m in source_trace['messages'] if m.get('role') == 'user']
    if len(user_messages) != 1:
        raise ValueError('SOURCE_TRACE_PAYLOAD_AMBIGUOUS')
    original_payload = json.loads(user_messages[0]['content'])
    if original_payload['available_dimensions'] != dimensions:
        raise ValueError('TRACE_PROJECT_DIMENSIONS_DIFFER')
    compact, values, summary = prepare_intent_context(
        original_payload['question'], original_payload.get('history', []), dimensions)
    preview = deepcopy(original_payload)
    preview.update(available_dimensions=compact, filter_values=values, filter_value_metadata=summary['fields'])
    probes = make_probes(args.data, dataset, dimensions, base.read_json(args.cases))
    for case in probes:
        _, chosen, _ = prepare_intent_context(case['question'], [], dimensions)
        for f in case['expected']['intent']['filters']:
            if f['value'] not in chosen[f['field']]:
                raise ValueError('KNOWN_FILTER_NOT_RETAINED_IN_PROBE_CONTEXT')
    # All guards, hashes, independent expectations and offline checks precede edits.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, raw in [('agent.before.py', agent_old), ('agent.after.py', agent_new),
                      ('intent_prompt.before.txt', prompt_old), ('intent_prompt.after.txt', prompt_new),
                      ('intent_context.py', helper_raw)]:
        (args.output / name).write_bytes(raw)
    for label, before, after in [('agent', agent_old, agent_new), ('intent_prompt', prompt_old, prompt_new)]:
        diff = ''.join(difflib.unified_diff(before.decode('utf-8').splitlines(keepends=True),
                                         after.decode('utf-8').splitlines(keepends=True),
                                         fromfile=label + ' (before)', tofile=label + ' (after)'))
        (args.output / (label + '.diff')).write_text(diff, encoding='utf-8')
    save(args.output / 'offline_checks.json', {'passed': True, 'checks_total': len(checks), 'checks': checks, 'model_called': False})
    save(args.output / 'context-summary.json', summary)
    save(args.output / 'intent-payload-preview.json', preview)
    save(args.output / 'probe-cases.json', probes)
    record = {
        'status': 'prepared', 'kind': 'bounded_model_enum_context',
        'project': str(args.project.resolve()), 'source_trace': str(args.source_trace.resolve()),
        'source_trace_sha256': sha(args.source_trace.read_bytes()),
        'source_cases_sha256': sha(args.cases.read_bytes()),
        'dataset_sha256': sha((args.project / 'dataset.json').read_bytes()),
        'dimensions_sha256': sha(dimensions_raw), 'engine_sha256': engine_hash,
        'agent_before_sha256': sha(agent_old), 'agent_after_sha256': sha(agent_new),
        'prompt_before_sha256': sha(prompt_old), 'prompt_after_sha256': sha(prompt_new),
        'helper_sha256': sha(helper_raw), 'helper_previously_existed': helper_existed,
        'patch_script_sha256': sha(Path(__file__).read_bytes()),
        'offline_checks': len(checks), 'probe_cases': len(probes),
        'payload_chars_before': len(json.dumps(original_payload, ensure_ascii=False)),
        'payload_chars_after': len(json.dumps(preview, ensure_ascii=False)),
        'historical_intent_usage': source_trace.get('usage'),
        'model_called': False, 'query_executed': False, 'engine_modified': False,
        'full_dimension_file_modified': False, 'actual_token_saving': 'not_measured_until_real_probe',
        'scope_note': 'Product context and prompt customization; metric definitions and independent expected values unchanged.',
    }
    save(args.output / 'patch.json', record)
    if agent_path.read_bytes() != agent_old or prompt_path.read_bytes() != prompt_old:
        raise ValueError('SOURCE_CHANGED_DURING_PATCH: no product files modified')
    helper_path.write_bytes(helper_raw)
    agent_path.write_bytes(agent_new)
    prompt_path.write_bytes(prompt_new)
    if any((p.read_bytes() != raw) for p, raw in (
        (helper_path, helper_raw), (agent_path, agent_new), (prompt_path, prompt_new))):
        raise ValueError('PATCH_WRITE_VERIFICATION_FAILED')
    if sha(engine_path.read_bytes()) != engine_hash or dimensions_path.read_bytes() != dimensions_raw:
        raise ValueError('ENGINE_OR_FULL_DIMENSIONS_CHANGED')
    record['status'] = 'applied'
    save(args.output / 'patch.json', record)
    print(json.dumps({k: record[k] for k in ('status', 'offline_checks', 'probe_cases',
        'payload_chars_before', 'payload_chars_after', 'model_called', 'engine_modified',
        'full_dimension_file_modified')}, ensure_ascii=False, indent=2))
    print('output: ' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
