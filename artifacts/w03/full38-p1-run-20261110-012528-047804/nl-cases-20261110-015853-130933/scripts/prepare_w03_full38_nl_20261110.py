"""Prepare fresh natural-language cases from original CSV; no model or actual results."""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path('/home/yang/FDE/w03-work/fde-agent-w03')
RUN=ROOT/'artifacts/w03/full38-p1-run-20261110-012528-047804'
sys.path.insert(0,str(ROOT/'customer/w03'))
sys.path.insert(0,str(ROOT/'platform'))
import make_tests_general32 as general
import check_orders24 as financial
import check_member8 as member
import check_paid6_inputs as preflight
import check_w03_paid6_csv_20261110 as paid
import judge_w03_full38_20261110 as judge
from fde_product.metrics.common import library_digest


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def generate(size,libhash):
    data=ROOT/'materials/data'/size;project=RUN/('project-'+size)
    manifest,hashes,oracle,names=general.load_inputs(data,ROOT/'customer/w03/targets.json')
    check=preflight.audit(data)
    if not check['passed']:raise ValueError('P1_INPUT_BLOCKED')
    dataset=read(project/'dataset.json')
    if dataset['library_sha256']!=libhash or not read(project/'validation.json')['passed']:raise ValueError('PROJECT_BINDING')
    for field in ['id','coverage','sha256','counts']:
        if dataset[field]!=manifest[field]:raise ValueError('DATASET_MISMATCH')
    versions=dict(data_version=dataset['id'],data_sha256=hashlib.sha256(json.dumps({k:v for k,v in dataset.items() if k!='library_sha256'},sort_keys=True).encode()).hexdigest(),catalog_sha256=libhash)
    paid_values,_=paid.monthly_oracle(paid.rows(data/'cards.csv'),oracle.orders,*manifest['coverage'])
    units={**financial.UNITS,**member.UNITS,**paid.UNITS};cases=[]
    base_month=8 if size=='small' else 6
    begin=f'2026-{base_month:02d}-01';end=f'2026-{base_month+1:02d}-01';prev=f'2026-{base_month-1:02d}-01'
    when=f'2026年{base_month}月';pair=f'2026年{base_month-1}月和{base_month}月'
    def wording(small,large):return small if size=='small' else large
    def add(cid,family,metrics,question,start=begin,stop=end,groups=None,filters=None,status='ok',omit_group=False,review=None):
        intent=dict(metrics=list(metrics),start=start,end=stop,group_by=groups or [],filters=filters or [])
        expected=dict(status=status,intent=deepcopy(intent))
        if omit_group:expected['intent'].pop('group_by')
        if status=='ok':
            if family=='orders':values=financial.expectations(oracle.orders,oracle.members,oracle.stores,intent)
            elif family=='paid':values={(m,) if groups else ():v for m,v in paid_values.items() if start<=m<stop}
            else:values=getattr(oracle,family)(intent)
            if family=='paid' and not groups and member.next_month(date.fromisoformat(start)).isoformat()!=stop:
                raise ValueError('PAID_MULTI_MONTH_WITHOUT_GROUPING')
            columns=intent['group_by']+list(metrics)
            expected.update(columns=columns,rows=[list(k)+[v[m] for m in metrics] for k,v in sorted(values.items())],units={m:units[m] for m in metrics},**versions)
        materials=['01_订单日报说明.md','02_财务邮件.md','05_数据字典.md'] if family=='orders' else ['03_会员运营周报.md','05_数据字典.md']
        if family=='paid':materials=['04_本期统计确认邮件.md','09_付费月报补访原文.md','business_model.md:R11(P1)']
        case=dict(id=cid,question=question,expected=expected,expected_source=dict(materials=materials,
            method='Original CSV independent oracle; whole-history first-order ranking; paid qualification under provisional P1; no generated SQL or actual results used.',
            family=family),answer_review_requirements=review or ['回答数值、单位、分组、日期与执行结果一致'])
        if family=='paid':case['answer_review_requirements']+=['保留P1暂定试算及总部适用性待书面确认，不把试算称为已确认总部制度']
        if omit_group:case['requested_intent']=intent
        cases.append(case)
    ids=[x['id'] for x in read(ROOT/'customer/w03/targets.json')]
    for i,metric in enumerate(ids):
        month=8 if size=='small' else [4,5,6][i%3]
        start=f'2026-{month:02d}-01';stop=f'2026-{month+1:02d}-01'
        family='orders' if metric in financial.METRICS else 'first' if metric in member.FIRST else 'registration' if metric=='new_member_count' else 'monthly' if metric in member.MONTHLY else 'paid'
        question=(f'请只查询青禾2026年{month}月的{names[metric]}，全门店汇总，不分组。' if size=='small' else
            [f'核对青禾2026年{month}月整月报表：只返回{names[metric]}的全门店合计，不拆维度。',
             f'青禾2026年{month}月，{names[metric]}是多少？仅这一项，汇总全部门店。',
             f'帮我查青禾2026年{month}月的{names[metric]}，我需要整月全门店总数，不需要分组明细。'][i%3])
        unit=units[metric]
        if unit=='cents':question+='金额按分返回。'
        elif unit=='ratio':question+='结果使用小数比例。'
        elif unit=='cents_per_order':question+='结果单位分/单。'
        elif unit=='cents_per_account':question+='结果单位分/账户。'
        if family=='first':question+='首单先在完整测试覆盖历史的有效订单中确定，再筛选查询月份。'
        if family=='registration':question+='时间按账户注册日期归属。'
        if family=='paid':question+='按现有P1暂定试算口径，月末选账户，统计整月全渠道订单，并注明待确认。'
        add('single_'+metric,family,[metric],question,start,stop)
    trio=['order_count','valid_order_count','net_sales_cents']
    add('order_trio','orders',trio,wording(f'青禾{when}创建订单数、有效订单数、净销售额各是多少？全门店汇总，金额保留分。',f'核对青禾{when}全门店三项合计：创建订单数、有效订单数和净销售额，金额用分。'))
    add('order_paraphrase','orders',trio,wording(f'青禾{when}一共创建多少笔订单，其中支付后扣退款仍为正的有多少笔，paid订单实付减退款合计多少分？取消单也计入创建数。',f'把青禾{when}所有门店订单放在一起看：创建总笔数、已支付且扣退款后仍有余额的笔数，以及paid订单实付减退款之和分别多少？金额按分。'))
    for dim,label in [('store','订单成交门店编号'),('home_store','会员归属门店编号'),('order__status','订单状态'),('order__channel','订单渠道'),('member__tier','会员等级')]:
        add('orders_by_'+dim,'orders',trio,wording(f'青禾{when}按{label}分组列出创建订单数、有效订单数、净销售额，金额分。',f'我想比较青禾{when}不同{label}：逐组给出创建订单数、有效订单数、净销售额，金额保持分。'),groups=[dim])
    add('orders_two_regions','orders',trio,wording(f'青禾{when}同时按成交门店地区与会员归属门店地区分组，列出创建订单数、有效订单数、净销售额，金额分。',f'给青禾{when}做交叉明细，以成交门店地区和会员归属门店地区同时分组，三项分别为创建订单数、有效订单数、净销售额（分）。'),groups=['store__region','home_store__region'])
    store=sorted(oracle.stores)[0 if size=='small' else 1]
    add('orders_store_filter','orders',trio,wording(f'青禾{when}只看成交门店编号{store}，汇总创建订单数、有效订单数和净销售额，金额分。',f'限定青禾成交门店编号{store}，查{when}创建订单数、有效订单数、净销售额合计，不分组，金额分。'),filters=[dict(field='store',op='eq',value=store)])
    add('cancelled_zero_denominator','orders',['valid_order_count','net_sales_cents','avg_order_value','cancel_rate'],wording(f'青禾{when}筛选cancelled状态订单，给出有效订单数、净销售额、有效订单均额和取消率；分、分/单和小数比例。',f'青禾{when}只分析已取消的订单（status为cancelled）：有效订单数、净销售额、有效订单均额及取消率是多少？金额分，均额分/单，比例小数。'),filters=[dict(field='order__status',op='eq',value='cancelled')])
    add('first_home_store','first',member.FIRST,wording(f'青禾{when}按会员归属门店编号列出观测期首购会员数、观测期首单净销售额、观测期首单数、观测期后续购买订单数；完整有效历史先排序，金额分。',f'比较青禾{when}各会员归属门店编号的观测期首购会员数、首单净销售额、首单数、后续购买订单数。先在全覆盖有效历史确定首单，金额使用分。'),groups=['home_store'])
    for dim,label in [('home_store','会员归属门店编号'),('member__tier','会员等级')]:
        add('registration_'+dim,'registration',['new_member_count'],wording(f'按注册日期统计青禾{when}注册会员数，按{label}分组。',f'青禾{when}新注册CRM账户有多少？以注册日期筛选，分{label}列出。'),groups=[dim])
    add('monthly_pair','monthly',member.MONTHLY,wording(f'青禾{pair}分别列出月内购买会员数、月内复购会员数、月内复购率，全门店按月，不合并，比例小数。',f'做青禾{pair}的月度对比：逐月给出月内购买会员数、月内复购会员数和月内复购率，全门店，小数比例。'),prev,end,['metric_time__month'])
    paid_names='、'.join(names[m] for m in paid.METRICS)
    add('paid_pair','paid',paid.METRICS,wording(f'按P1暂定口径查询青禾{pair}的{paid_names}，全渠道全门店，按月分别列出，金额分、均额分/单、比例小数。',f'请用现有P1试算规则对比青禾{pair}：按月展示{paid_names}，纳入全部门店渠道，金额分，均额分/单，比例小数，保留待确认说明。'),prev,end,['metric_time__month'])
    add('paid_coverage','paid',paid.METRICS,wording(f'青禾2024年9月至2026年8月，每个自然月分别列出{paid_names}，按现有P1暂定试算，全门店全渠道，金额分、均额分/单、比例小数。',f'把青禾测试覆盖期2024-09-01含至2026-09-01不含做成逐月表：{paid_names}。使用现有P1试算规则，全部门店渠道，金额分、均额分/单、比例小数。'),*manifest['coverage'],['metric_time__month'])
    add('paid_paraphrase','paid',paid.METRICS,wording(f'青禾{when}，按P1在月末挑出有资格账户，再看他们整月全渠道全门店的有效购买：买过的账户数、订单笔数、净额、至少买两次的账户数、后者占购买账户的比例、每单平均净额是多少？金额分、均额分/单。',f'核对青禾{when}P1付费会员月报：用月底资格选账户，回看整月所有渠道门店的有效订单，统计购买账户数、有效单数、净销售额、复购账户数、复购人数占购买人数的比例和每单净额。金额用分，均额分/单。'))
    occupied={o['ordered_at'] for o in oracle.orders};empty=date.fromisoformat(manifest['coverage'][0]);limit=date.fromisoformat(manifest['coverage'][1])
    while empty<limit and empty.isoformat() in occupied:empty+=timedelta(days=1)
    if empty<limit:
        add('empty_day','orders',['order_count','net_sales_cents','avg_order_value'],wording(f'青禾{empty.isoformat()}当天创建订单数、净销售额、有效订单均额是多少？全门店，金额分、均额分/单。',f'核对日期{empty.isoformat()}这一天青禾所有门店的创建订单数、净销售额及有效订单均额，单位分和分/单。'),empty.isoformat(),(empty+timedelta(days=1)).isoformat())
    occupied_months={o['ordered_at'][:7] for o in oracle.valid};d=date.fromisoformat(manifest['coverage'][0])
    while d<limit and d.strftime('%Y-%m') in occupied_months:d=member.next_month(d)
    if d<limit:add('empty_month','monthly',member.MONTHLY,f'青禾{d.year}年{d.month}月全门店月内购买会员数、月内复购会员数、月内复购率是多少？完整自然月汇总，比例小数。',d.isoformat(),member.next_month(d).isoformat())
    zero=next((m for m,v in paid_values.items() if v[paid.METRICS[0]]==0),None)
    if zero:add('paid_zero_month','paid',paid.METRICS,f'青禾{zero[:7]}整月按P1暂定试算的{paid_names}是多少？全门店全渠道，金额分、均额分/单、比例小数。',zero,member.next_month(date.fromisoformat(zero)).isoformat())
    add('reject_partial_month','monthly',['monthly_repeat_rate'],wording(f'青禾{when}1日至15日的月内复购率是多少？只统计这15天。',f'我只要青禾{when}上半月（1日至15日含）的月内复购率，不能改成整月。'),begin,f'2026-{base_month:02d}-16',status='unsupported',review=['说明整月限制，不擅自替换日期或给出数字'])
    add('reject_monthly_store_group','monthly',['monthly_repeat_rate'],wording(f'请把青禾{when}月内复购率按成交门店编号分别列出。',f'青禾{when}完整自然月的月内复购率，给我各成交门店编号的分组明细。'),groups=['store'],status='unsupported',omit_group=True,review=['拒绝不支持的门店分组，不推荐其他同样禁止的分组'])
    add('reject_paid_partial','paid',['monthly_paid_buyer_count'],wording(f'青禾{when}2日至月底的月末付费会员购买人数是多少？只要这个非整月范围。',f'按P1试算青禾{when}，排除1日，仅查2日至月末的月末付费会员购买人数。'),f'2026-{base_month:02d}-02',end,status='unsupported')
    add('reject_paid_filter','paid',['monthly_paid_order_count'],wording(f'青禾{when}按P1的月末付费会员有效订单数，只筛选订单渠道为门店，不包括小程序。',f'查询青禾{when}P1月末付费会员有效订单数，但仅限门店渠道，排除小程序渠道。'),filters=[dict(field='order__channel',op='eq',value='门店')],status='unsupported')
    add('reject_paid_group','paid',['monthly_paid_repeat_rate'],wording(f'青禾{when}P1月末付费会员复购率按会员归属门店编号分组。',f'我想比较青禾{when}不同会员归属门店的P1月末付费会员复购率，请按归属门店编号列出。'),groups=['home_store'],status='unsupported',omit_group=True)
    add('reject_paid_multimonth','paid',['monthly_paid_buyer_count'],wording(f'青禾{pair}P1月末付费会员购买人数合并成一个数，不按月展示。',f'把青禾{pair}的P1月末付费会员购买人数汇总成一行，我不要逐月结果。'),prev,end,status='unsupported')
    add('reject_outside_coverage','orders',trio,wording('青禾2026年9月创建订单数、有效订单数、净销售额是多少？','核对青禾2026年10月的创建订单数、有效订单数与净销售额合计。'),'2026-09-01' if size=='small' else '2026-10-01','2026-10-01' if size=='small' else '2026-11-01',status='unsupported')
    for cid,question,status,review in [
        ('reject_undefined_metric',wording(f'青禾{when}的净利润是多少？我要利润，不是净销售额。',f'核对青禾{when}扣除所有成本后的净利润金额，不能用销售额代替。'),'unsupported','指出净利润指标未定义，不替换成净销售额或推算成本'),
        ('nonexistent_filter',wording(f'青禾{when}仅查成交门店编号S999999的创建订单数，不替换门店。',f'限定青禾成交门店编号S888888，给我{when}创建订单数；不要猜成其他编号。'),'unsupported','说明该门店编号无法定位或不在本次范围，不能返回零或猜ID'),
        ('clarify_time',wording('青禾的净销售额是多少？','帮我查一下青禾净销售额，时间还没指定。'),'clarify','询问时间，不默认窗口'),
        ('clarify_year',wording('青禾7月和8月按月列出月内复购率。','青禾5月与6月的月内复购率分别是多少？'),'clarify','新会话没有年份，不能默认参考年')]:
        expected=dict(status=status)
        if cid=='nonexistent_filter':expected.update(allowed_statuses=['unsupported','clarify'],boundary_kind='nonexistent_filter_value',reason='编号无法定位')
        cases.append(dict(id=cid,question=question,expected=expected,expected_source=dict(method='Contract boundary decided before execution; no numeric answer authorized'),answer_review_requirements=[review]))
    known_ids=set(oracle.stores)
    if {'S999999','S888888'} & known_ids:raise ValueError('NONEXISTENT_STORE_FIXTURE_EXISTS')
    for case in cases:
        example=deepcopy(case['expected'])
        if 'allowed_statuses' in example:example['reason']='编号无法定位'
        verdict=judge.compare(case['expected'],example)
        if not verdict['passed']:raise ValueError('INVALID_EXPECTED '+case['id']+' '+json.dumps(verdict,ensure_ascii=False))
    if len({c['id'] for c in cases})!=len(cases) or len({c['question'] for c in cases})!=len(cases):raise ValueError('DUPLICATE_CASE')
    covered={m for c in cases if c['expected']['status']=='ok' for m in c['expected']['intent']['metrics']}
    if covered!=set(ids):raise ValueError('METRIC_COVERAGE_INCOMPLETE')
    smoke_ids={'single_valid_order_items','first_home_store','paid_coverage','paid_paraphrase','reject_paid_group','reject_undefined_metric','nonexistent_filter','clarify_year'}
    return cases,[c for c in cases if c['id'] in smoke_ids],dict(dataset=size,project=str(project),data=str(data),**versions,
        cases_total=len(cases),metrics_covered=sorted(covered),source_sha256=hashes,manifest_sha256=sha(data/'manifest.json'),
        successful_cases=sum(c['expected']['status']=='ok' for c in cases),model_called=False,query_executed=False,actual_results_read=False,
        units=units)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if judge.self_checks()!=8:raise ValueError('JUDGE_SELF_CHECK_FAILED')
    libhash=library_digest(RUN/'build');prepared={size:generate(size,libhash) for size in ['small','large']}
    overlap={c['question'] for c in prepared['small'][0]} & {c['question'] for c in prepared['large'][0]}
    if overlap:raise ValueError('CROSS_DATASET_DUPLICATE_QUESTIONS: '+str(overlap))
    print('预检通过：两套用例各覆盖38项；期望全部来自原始CSV；大小样本无完全相同问句。',flush=True)
    for size,(cases,smoke,_) in prepared.items():print(f'{size}: {len(cases)}条完整用例，{len(smoke)}条冒烟用例。',flush=True)
    print('不存在筛选值允许拒答或澄清；未定义指标拒答；数值/单位/分组/版本仍严格核对。',flush=True)
    if not args.apply:
        print('只读预检完成，未写入用例、未查询或调用模型。');return 0
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f')
    dest=RUN/('nl-cases-'+stamp);dest.mkdir(exist_ok=False)
    scripts=[Path(__file__),Path(judge.__file__),Path(judge.strict.__file__),Path(paid.__file__),Path(general.__file__),Path(financial.__file__),Path(member.__file__),Path(member.base.__file__),Path(preflight.__file__)]
    snapshot=dest/'scripts';snapshot.mkdir();script_hashes={}
    for path in scripts:
        raw=path.read_bytes();(snapshot/path.name).write_bytes(raw);script_hashes[path.name]=hashlib.sha256(raw).hexdigest()
    entries=[]
    for size,(cases,smoke,info) in prepared.items():
        folder=dest/size;folder.mkdir();save(folder/'tests.json',cases);save(folder/'tests-smoke.json',smoke)
        info.update(cases_sha256=sha(folder/'tests.json'),smoke_sha256=sha(folder/'tests-smoke.json'),script_sha256=script_hashes)
        save(folder/'generation.json',info)
        entries.append(dict(dataset=size,project=info['project'],cases=str(folder/'tests.json'),cases_sha256=info['cases_sha256'],
            smoke=str(folder/'tests-smoke.json'),smoke_sha256=info['smoke_sha256'],cases_total=len(cases),smoke_total=len(smoke)))
    save(dest/'plan.json',dict(kind='full38_natural_language_regression_plan',library=str(RUN/'build'),library_sha256=libhash,entries=entries,
        judge_script=str(snapshot/'judge_w03_full38_20261110.py'),judge_sha256=script_hashes['judge_w03_full38_20261110.py'],
        base_judge_sha256=sha(ROOT/'customer/w03/judge.py'),judge_self_checks=8,cross_dataset_identical_questions=0,
        model_called=False,query_executed=False,actual_results_read=False,business_confirmation='pending',
        execution_status='not_run',answer_review_required=True))
    for entry in entries:
        if sha(Path(entry['cases']))!=entry['cases_sha256'] or sha(Path(entry['smoke']))!=entry['smoke_sha256']:raise ValueError('READBACK_MISMATCH')
    print(f'自然语言用例与计划已生成：{dest}',flush=True)
    print('未覆盖旧tests.json、旧回归报告、指标库或聊天绑定；尚未调用模型。')
    return 0


if __name__=='__main__':raise SystemExit(main())
