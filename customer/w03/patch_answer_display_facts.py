"""Install answer-only display grounding, with backups and offline verification."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
from answer_display_facts import self_check

MARKER = '[W03_DISPLAY_FACTS_V1]'
RULES = '''
[W03_DISPLAY_FACTS_V1]
answer_display_facts 是由本次真实执行结果用代码计算的展示事实；同一行的 group 与 metrics 对应，不能串行或串组。金额、数量和单位直接使用其中 display_value、display_unit；有 display_rounded 时可以说明约数。若用户要求保留分、分/单、分/账户或小数比例，只展示该单位，不额外附加元或百分比；用户明确要求换算时才能引用 optional_yuan_conversion 或 optional_percent_conversion 的已算好数值，不自行心算、改数字或只改单位。
计数对象逐指标区分，不能把 customer_context 的 CRM 账户粒度套到所有计数：创建、支付、有效、取消、退款、部分退款、全额退款、观测期首单和后续订单数均是订单，单位单；购买、退款、注册、首购、月内购买、月内复购会员数是账户；成交门店数是门店；有效订单商品件数是件。首购会员数和首单数在本测试可能数值相同，也不能混用对象和单位。
展示事实不增加查询范围，不是独立正确性证明。口径说明继续以 definitions 为准，不能额外算未请求指标或编造数值。若某列没有确定的业务计数单位，按定义核对，不从客户范围推断。最终逐项核对回答中所有数字、换算和单位是否与展示事实一致。
[/W03_DISPLAY_FACTS_V1]
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_agent(raw):
    text = raw.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    text = text.replace('\r\n', '\n')
    if 'build_answer_display_facts' in text:
        raise ValueError('DISPLAY_AGENT_PATCH_ALREADY_PRESENT')
    replacements = {
        'from .common import read,dump,call_json\n': 'from .common import read,dump,call_json\nfrom .answer_display_facts import build_answer_display_facts\n',
        "'definitions':[x for x in self.catalog if x['id'] in intent['metrics']]": "'definitions':[x for x in self.catalog if x['id'] in intent['metrics']],'answer_display_facts':build_answer_display_facts(result,[x for x in self.catalog if x['id'] in intent['metrics']])",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError('AGENT_SOURCE_DIFFERS: inspect answer payload')
        text = text.replace(old, new)
    compile(text, 'agent.py', 'exec')
    return text.replace('\n', newline).encode('utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, default=Path('.'))
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.workspace.resolve()
    checks = self_check()
    agent = root / 'platform/fde_product/metrics/agent.py'
    helper = agent.with_name('answer_display_facts.py')
    prompt = root / 'product/w03_answer_prompt.txt'
    old_a, old_p = agent.read_bytes(), prompt.read_bytes()
    if '[W03_ANSWER_FIDELITY_V1]' not in old_p.decode('utf-8') or 'prepare_intent_context' not in old_a.decode('utf-8'):
        raise ValueError('PRIOR_FIXES_MISSING')
    if MARKER in old_p.decode('utf-8') or helper.exists():
        raise ValueError('DISPLAY_PATCH_ALREADY_PRESENT_OR_HELPER_EXISTS')
    new_a = patch_agent(old_a)
    new_p = old_p + (b'' if old_p.endswith(b'\n') else b'\n') + RULES.encode('utf-8')
    helper_raw = Path(__file__).with_name('answer_display_facts.py').read_bytes()
    compile(helper_raw.decode('utf-8'), str(helper), 'exec')
    protected = [root / 'product/w03_intent_prompt.txt', agent.with_name('engine.py'), root / 'customer/w03/judge.py']
    hashes = {str(p): sha(p.read_bytes()) for p in protected}
    args.output.mkdir(parents=True, exist_ok=False)
    for label, before, after in [('agent', old_a, new_a), ('answer_prompt', old_p, new_p)]:
        (args.output / (label+'.before.txt')).write_bytes(before)
        (args.output / (label+'.after.txt')).write_bytes(after)
        diff = ''.join(difflib.unified_diff(before.decode('utf-8').splitlines(True), after.decode('utf-8').splitlines(True), fromfile=label+' before', tofile=label+' after'))
        (args.output / (label+'.diff')).write_text(diff, encoding='utf-8')
    (args.output / 'answer_display_facts.py').write_bytes(helper_raw)
    record = {'status': 'prepared', 'offline_checks': checks, 'model_called': False,
              'query_executed': False, 'protected_sha256': hashes,
              'agent_before_sha256': sha(old_a), 'agent_after_sha256': sha(new_a),
              'answer_prompt_before_sha256': sha(old_p), 'answer_prompt_after_sha256': sha(new_p),
              'helper_sha256': sha(helper_raw), 'script_sha256': sha(Path(__file__).read_bytes())}
    def save():
        (args.output / 'patch.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    if agent.read_bytes()!=old_a or prompt.read_bytes()!=old_p:
        raise ValueError('SOURCE_CHANGED_DURING_PREPARATION')
    helper.write_bytes(helper_raw);agent.write_bytes(new_a);prompt.write_bytes(new_p)
    if any(sha(Path(p).read_bytes())!=h for p,h in hashes.items()):
        raise ValueError('PROTECTED_SOURCE_CHANGED')
    if agent.read_bytes()!=new_a or prompt.read_bytes()!=new_p or helper.read_bytes()!=helper_raw:
        raise ValueError('WRITE_VERIFICATION_FAILED')
    record['status']='applied';save()
    print(json.dumps({'status':'applied','offline_checks':len(checks),'model_called':False,'intent_prompt_changed':False,'output':str(args.output.resolve())},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
