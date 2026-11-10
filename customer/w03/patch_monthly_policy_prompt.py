"""Documented product intent-prompt fix; leaves engine/SQL/metric definitions unchanged."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path


MARKER = '[W03_POLICY_EXPLANATION_V1]'
ADDITION = '''
[W03_POLICY_EXPLANATION_V1]
维度说明必须区分结构上可关联的候选维度与指标查询策略实际允许的维度。available_dimensions 不能覆盖 catalog 中的 query_policy 或 constraints。先检查所选全部指标的策略，再检查维度路径；向用户推荐替代问法时也必须通过同样的策略检查。
对于任一所选指标 query_policy.full_month_only=true，按当前产品执行约束处理：日期须为完整自然月边界；filters 必须为空；group_by 只允许空列表（单月汇总）或 metric_time__month（按月展示）；跨多月必须按月展示。会员归属门店、归属地区、会员等级、会员账户、成交门店、渠道等非月份分组都不允许，即使这些维度出现在结构上的候选列表中。不得建议把一种被禁止的分组改成另一种同样被禁止的分组。
用户明确要求这些不支持的分组或筛选时，返回 unsupported，在 reason 中用业务语言说明当前指标仅支持完整自然月的全范围汇总或按月展示，不支持用户要求的拆分。必要时可建议单月全范围汇总或多月按月展示，但不能擅自替换原请求并计算，也不要先宣称其他候选维度“可用”。日期和已识别指标保留原请求；拒绝输出的 group_by 可以为空，不因它为空而宣称用户没有提出分组要求。
上述规则仅适用于设置 full_month_only 的指标，不限制其他指标已有的合法分组与筛选能力。解释当前实现限制时不要虚构客户新增规则，不向用户罗列内部字段 ID。
[/W03_POLICY_EXPLANATION_V1]
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def plan(root, cases_dir):
    prompt = root / 'product/w03_intent_prompt.txt'
    engine = root / 'platform/fde_product/metrics/engine.py'
    agent = root / 'platform/fde_product/metrics/agent.py'
    old = prompt.read_bytes()
    text = old.decode('utf-8')
    engine_bytes, agent_bytes = engine.read_bytes(), agent.read_bytes()
    engine_text, agent_text = engine_bytes.decode('utf-8'), agent_bytes.decode('utf-8')
    guards = [".get('full_month_only')", "or filters or set(group)-{'metric_time__month'}",
              "delta!=1 and group!=['metric_time__month']"]
    if not all(g in engine_text for g in guards):
        raise ValueError('ENGINE_POLICY_DIFFERS: review the local engine before applying this patch')
    if "ROOT/'product/w03_intent_prompt.txt'" not in agent_text:
        raise ValueError('AGENT_PROMPT_LOADING_DIFFERS')
    if MARKER in text:
        raise ValueError('PATCH_ALREADY_PRESENT: do not apply repeatedly; inspect existing patch record')
    if 'full_month_only' not in text or 'available_dimensions' not in text:
        raise ValueError('UNEXPECTED_INTENT_PROMPT')
    new = old + (b'' if old.endswith(b'\n') else b'\n') + ADDITION.encode('utf-8')
    full_path = cases_dir / 'tests-general32.json'
    refusal_path = cases_dir / 'tests-group-refusal.json'
    full_raw, refusal_raw = full_path.read_bytes(), refusal_path.read_bytes()
    full, refusals = json.loads(full_raw), json.loads(refusal_raw)
    if len(refusals) != 4 or any(c['expected']['status'] != 'unsupported' for c in refusals):
        raise ValueError('EXPECTED_FOUR_REFUSAL_CASES')
    positive_ids = {'aug_trio_by_home_store', 'monthly_jul_aug', 'single_monthly_repeat_rate',
                    'reject_partial_month', 'reject_outside_coverage'}
    controls = [c for c in full if c['id'] in positive_ids]
    if len(controls) != len(positive_ids):
        raise ValueError('REGRESSION_CONTROLS_MISSING')
    cases = refusals + controls
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('DUPLICATE_REGRESSION_CASE_IDS')
    return {
        'prompt': prompt, 'old': old, 'new': new, 'cases': cases,
        'engine_path': engine, 'engine_sha256': sha(engine_bytes),
        'agent_path': agent, 'agent_sha256': sha(agent_bytes),
        'cases_source_sha256': {str(full_path.resolve()): sha(full_raw),
                                str(refusal_path.resolve()): sha(refusal_raw)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path('.'))
    parser.add_argument('--cases-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    root = args.workspace.resolve()
    prepared = plan(root, args.cases_dir)
    if args.check_only:
        print(json.dumps({'status': 'preflight_ok', 'prompt': str(prepared['prompt']),
                          'regression_cases': len(prepared['cases']), 'model_called': False,
                          'files_modified': False}, ensure_ascii=False, indent=2))
        return
    if args.output is None:
        parser.error('--output is required when applying')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'intent_prompt.before.txt').write_bytes(prepared['old'])
    (args.output / 'intent_prompt.after.txt').write_bytes(prepared['new'])
    diff = ''.join(difflib.unified_diff(
        prepared['old'].decode('utf-8').splitlines(keepends=True),
        prepared['new'].decode('utf-8').splitlines(keepends=True),
        fromfile='product/w03_intent_prompt.txt (before)', tofile='product/w03_intent_prompt.txt (after)'))
    (args.output / 'intent_prompt.diff').write_text(diff, encoding='utf-8')
    (args.output / 'regression-cases.json').write_text(
        json.dumps(prepared['cases'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if prepared['prompt'].read_bytes() != prepared['old']:
        raise ValueError('PROMPT_CHANGED_DURING_PREFLIGHT: original prompt not modified')
    prepared['prompt'].write_bytes(prepared['new'])
    if prepared['prompt'].read_bytes() != prepared['new']:
        raise ValueError('PROMPT_WRITE_VERIFICATION_FAILED')
    for key in ('engine', 'agent'):
        if sha(prepared[key + '_path'].read_bytes()) != prepared[key + '_sha256']:
            raise ValueError(key.upper() + '_CHANGED_DURING_PATCH')
    record = {
        'status': 'applied', 'kind': 'product_intent_prompt_policy_explanation_fix',
        'prompt': str(prepared['prompt']), 'prompt_before_sha256': sha(prepared['old']),
        'prompt_after_sha256': sha(prepared['new']),
        'engine_sha256': prepared['engine_sha256'], 'agent_sha256': prepared['agent_sha256'],
        'cases_source_sha256': prepared['cases_source_sha256'],
        'script_sha256': sha(Path(__file__).read_bytes()),
        'regression_cases': len(prepared['cases']), 'model_called': False,
        'query_executed': False, 'engine_modified': False, 'judge_modified': False,
        'metric_definitions_modified': False, 'regression_status': 'not_run',
        'reason': 'Do not advertise structurally reachable dimensions prohibited by full_month_only policy.',
        'submission_note': 'Preserve this product prompt diff and declare the customization; it is not a metric-definition repair.',
    }
    (args.output / 'patch.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
