"""Disambiguate ordinary and paid repeat-rate explanations; retain historical evidence."""
import argparse
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path('/home/yang/FDE/w03-work/fde-agent-w03')
FINAL=ROOT/'artifacts/w03/full38-p1-run-20261110-012528-047804/final-library-20261110-025635-629688'
PROMPT=ROOT/'product/w03_answer_prompt.txt'
POINTER=FINAL/'regression_plan.json'
REPORT=FINAL/'nl-small-full-20261110-030115-607746/results/metric_test_report.json'
OLD_SHA='2df23fb50a2e1af0ba0eedc525a76db13283ca43e7ab799964803f0973c1e8cc'
OLD_RULE='月内复购率的分子为月内复购会员数，分母为同月月内购买会员数；不把注册人数、跨月合计或相反的比值作为分母或公式。'
NEW_RULE='''仅当本轮选中“月内复购率”时，其分子为月内复购会员数，分母为同月月内购买会员数。若本轮选中的是“月末付费会员复购率”，必须按其definitions写为“月末付费会员复购人数÷月末付费会员购买人数”，分子和分母都限定为月末符合付费资格的账户，不能套用普通月内复购率公式，也不能省略“月末付费”后让读者误认为全体会员。两类指标同时返回时，分别标明各自的分子、分母和资格范围。月末付费会员订单均额同样写为“月末付费会员净销售额÷月末付费会员有效订单数”，不能与普通订单均额混用。上述口径仍以本轮实际definitions为依据；不把注册人数、跨月合计或相反的比值作为分母或公式。'''
sys.path.insert(0,str(ROOT/'platform'))
from fde_product.metrics.common import library_digest


def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def prepare():
    old=PROMPT.read_bytes();pointer_raw=POINTER.read_bytes();pointer=json.loads(pointer_raw)
    assert sha(old)==OLD_SHA and old.decode().count(OLD_RULE)==1
    plan_path=Path(pointer['plan']);plan=read(plan_path)
    assert sha(plan_path.read_bytes())==pointer['plan_sha256'] and plan['answer_prompt_sha256']==OLD_SHA
    libhash=library_digest(ROOT/'artifacts/w03/library')
    assert libhash==plan['library_sha256']=='3726e776ada7b75ed778b3d6c49f42bff2a766d560dbf96036ffa61cd2953402'
    report=read(REPORT)
    assert report['complete'] and report['passed']==report['total']==69
    cases={c['id']:c for c in report['cases']}
    assert len(cases)==69
    assert '复购率按“月内复购会员数 ÷ 同月月内购买会员数”计算' in cases['paid_pair']['actual']['answer']
    catalog={c['id']:c for c in read(ROOT/'artifacts/w03/library/catalog.json')}
    assert any('月末付费会员复购人数除以月末付费会员购买人数' in s['quote'] for s in catalog['monthly_paid_repeat_rate']['sources'])
    new=old.decode().replace(OLD_RULE,NEW_RULE).encode('utf-8')
    protected_paths=[REPORT,plan_path,ROOT/'customer/w03/build-metrics/SKILL.md',ROOT/'docs/w03/business_model.md',
        ROOT/'product/w03_intent_prompt.txt',ROOT/'customer/w03/judge.py',ROOT/'.runtime/product/metrics-binding.json']
    for e in plan['entries']:
        protected_paths += [Path(e['cases']),Path(e['smoke'])]
    protected={str(p):sha(p.read_bytes()) for p in protected_paths}
    review=dict(kind='ai_assisted_answer_review',report=str(REPORT),report_sha256=sha(REPORT.read_bytes()),
        structured_passed=69,structured_total=69,answer_passed=68,answer_needs_fix=1,human_signoff=False,
        issue=dict(id='paid_pair',numeric_result_correct=True,
            actual_excerpt='复购率按“月内复购会员数 ÷ 同月月内购买会员数”计算',
            expected='月末付费会员复购人数÷月末付费会员购买人数',
            diagnosis='回答提示仅举普通月内复购率公式，未明确区分付费指标；现按实际选中定义分别说明。'),
        cases=[dict(id=cid,status='needs_fix' if cid=='paid_pair' else 'pass',
            actual_text_sha256=sha((c['actual'].get('answer') or c['actual'].get('reason') or '').encode())) for cid,c in cases.items()],
        nonblocking_notes=[dict(ids=['single_cancelled_order_count','single_avg_buyer_value','single_discount_rate','registration_home_store','paid_paraphrase'],note='部分日期范围未明确右端点不含，查询月份与数值正确。'),
            dict(ids=['orders_by_member__tier'],note='末尾有未请求的人数统计单位说明，表格仍正确使用订单数和金额。')],
        business_confirmation='pending',final_acceptance=False,retest_required=True)
    return old,new,pointer_raw,plan_path,plan,protected,review,libhash


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');args=p.parse_args()
    old,new,pointer_raw,plan_path,plan,protected,review,libhash=prepare()
    print('预检通过：正式库小样本结构化69/69，文字68条通过、1条付费复购率公式需修正。')
    print('拟更新回答提示：'+sha(new)+'；指标库及数值期望不变。')
    if not args.apply:
        print('只读预检完成；未修改工程或调用模型。');return
    dest=FINAL/('answer-paid-formula-fix-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f'))
    dest.mkdir(exist_ok=False)
    for name,raw in [('answer_prompt.before.txt',old),('answer_prompt.after.txt',new),('regression_plan.before.json',pointer_raw),('fix_script.py',Path(__file__).read_bytes())]:
        (dest/name).write_bytes(raw)
    (dest/'answer_prompt.diff').write_text(''.join(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),fromfile='before/product/w03_answer_prompt.txt',tofile='after/product/w03_answer_prompt.txt')),encoding='utf-8')
    save(dest/'answer_review.json',review)
    revised={**plan,'answer_prompt_sha256':sha(new),'execution_status':'not_run',
        'prompt_revision_of':str(plan_path),'prompt_revision_of_sha256':sha(plan_path.read_bytes()),
        'prompt_revision_reason':'Distinguish ordinary monthly and month-end paid member formula scopes; cases and numerical expectations unchanged.'}
    save(dest/'plan.json',revised)
    assert PROMPT.read_bytes()==old and POINTER.read_bytes()==pointer_raw
    PROMPT.write_bytes(new)
    save(POINTER,dict(plan=str(dest/'plan.json'),plan_sha256=sha((dest/'plan.json').read_bytes()),library_sha256=libhash))
    assert PROMPT.read_bytes()==new and read(POINTER)['plan_sha256']==sha((dest/'plan.json').read_bytes())
    assert library_digest(ROOT/'artifacts/w03/library')==libhash
    assert all(sha(Path(f).read_bytes())==h for f,h in protected.items())
    save(dest/'change.json',dict(status='applied',prompt_before_sha256=sha(old),prompt_after_sha256=sha(new),
        protected_sha256=protected,old_plan=str(plan_path),new_plan=str(dest/'plan.json'),
        model_called=False,query_executed=False,library_rebuild_required=False,retest_required=True))
    print('核查记录、提示备份及新版计划：'+str(dest))
    print('回答提示与计划索引已更新；原始报告、用例、判定器、正式库和聊天绑定未修改。')
    print('无需重建指标库；尚未调用模型，需复测付费与普通会员公式。')


if __name__=='__main__':main()
