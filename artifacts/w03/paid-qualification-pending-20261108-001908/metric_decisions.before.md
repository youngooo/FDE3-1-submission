# 指标核定与未决项

更新日期：2026-11-08。AI 协助根据已有材料、访谈及实际报告整理，供学员复核。当前采用32项通用指标阶段库；六项付费会员月报未完成。本记录不是38项最终验收结论。

## 采用依据

阶段库：[build-general32-normalized-20261107-023808](../../artifacts/w03/build-general32-normalized-20261107-023808/catalog.json)。原生定义见该目录 `metrics.yml`，派生模型、粒度及来源检查保留在同一目录。此目录尚不是最终 `artifacts/w03/library/`。

业务范围以 [当前业务模型](business_model.md)、`materials/w03/01`至`05`对应客户文件为依据：本期合成测试库，CRM账户粒度，Asia/Shanghai，覆盖 `[2024-09-01, 2026-09-01)`。材料不是生产就绪或自然人身份统一证明。

| 指标族及目标ID | 采用口径与来源 | 字段、粒度和适用限制 |
| --- | --- | --- |
| 订单状态7项：order_count、paid_order_count、valid_order_count、cancelled_order_count、refund_order_count、partial_refund_order_count、full_refund_order_count | 材料01《订单日报说明》、02《财务邮件》；创建包含取消，支付包含后来全退，有效为paid且实付大于累计退款 | 一行一订单；按ordered_at归属。部分退款为paid且0<refund_cents<paid_cents；全退为paid且paid_cents>0且退款等于实付 |
| 金额5项：payment_cents、refund_cents、net_sales_cents、gross_cents、discount_cents | 材料01、02；仅paid订单；净额为实付减退款，优惠为原价减实付，退款不冲减原优惠 | 整数分；退款按原订单日期归属，不当作退款现金发生日；购卡金额不混入订单收入 |
| 账户、门店与件数4项：buyer_count、refund_buyer_count、selling_store_count、valid_order_items | 材料01、05；购买账户与成交门店基于有效订单；退款账户基于paid且退款大于零订单；件数为有效订单原始quantity | 账户和门店分别去重；件数不是退款后的净销量；成交门店与会员归属门店分开 |
| 比值8项：avg_order_value、avg_buyer_value、purchase_frequency、refund_amount_rate、cancel_rate、refund_order_rate、discount_rate、items_per_order | 材料02；依次为净额/有效单、净额/购买账户、有效单/购买账户、退款/实付、取消单/创建单、退款单/支付单、优惠/支付单原价、有效件数/有效单 | 同一窗口和筛选条件先聚合再除；零分母未定义；均额为分/单或分/账户，比例按小数。原生ratio依赖metric而非measure |
| 注册1项：new_member_count | 材料03《会员运营周报》、05《数据字典》 | 按registered_at统计CRM账户，可按会员归属门店及等级；不按订单日期统计 |
| 首购与后续4项：first_buyer_count、first_order_sales_cents、first_order_count、repeat_order_count | 材料03；全覆盖历史内有效订单按日期、订单号排序；第一笔与后续购买分开 | 先确定全覆盖首次，再按窗口筛选；首单是订单，首购人数是账户；不代表终身首购，不在当前窗口或门店子集重新认定首次 |
| 月内购买与复购3项：monthly_buyer_count、monthly_repeat_buyer_count、monthly_repeat_rate | 材料03当前定义替代旧草稿“全部注册会员”分母；同月有效订单>=1为购买、>=2为复购；复购账户/购买账户 | 完整自然月、全门店；多月按月分别展示，不能加总月去重人数；零分母未定义 |

准确来源引文及逐指标登记见阶段库 `catalog.json`。本期月内复购定义已经明确，不因付费资格缺口重新列为未知。

工程核定：订单事实保持订单粒度；会员归属门店通过账户关联引入，避免混同成交门店；门店语义模型以实际唯一门店键声明primary实体。首购派生先处理全覆盖有效订单；月活动派生按账户、自然月形成活动信息，避免原始订单行直接充当月复购人数。

原32项构建曾把ratio的分子分母误写成 `m_` measure 名称，导致dbt解析失败。保留 [原失败日志](../../artifacts/w03/build-general32-20261107-022839/validation-project/build.log)，经 `customer/w03/normalize_ratio_refs.py` 修正18处引用、涉及9个比值指标，生成当前新目录；该修复没有调用模型。它修复依赖引用，不是另行改业务公式。

## 冲突、未决与不支持

### 六项付费会员月报

尚未构建为可验收指标：monthly_paid_buyer_count、monthly_paid_order_count、monthly_paid_sales_cents、monthly_paid_repeat_buyer_count、monthly_paid_repeat_rate、monthly_paid_avg_order_value。

已知部分：材料04要求月末判断账户资格，再统计该账户当月全渠道、全门店有效订单，不要求订单当天已具备资格；只支持完整自然月，多月分月展示。小林 MSG-04152 确认只纳入悦享年卡、家庭季卡，不用会员等级或购卡金额推断；账户不因多卡重复计算。

| 缺口 | 现有证据及状态 | 影响与下一步 |
| --- | --- | --- |
| 开始日、计划结束日、提前终止日当天是否有效 | 小林MSG-04154、04166无法确认；陈姐MSG-04164给出门店规则，但未确认总部月报采用 | 月底资格不能完整确定；取得适用于总部月报的权益说明或明确确认 |
| 两个结束日期同时存在如何组合 | 小林未确认，老周缺可核对说明；学员提出的同时满足两个条件未获确认 | 不擅自使用min结束日期或AND条件；补明确规则及月底边界例子 |
| 门店规则对总部月报的适用性 | 陈姐说明门店日期及任一卡有效的资格逻辑；小林不能确认其月报适用性 | 补充业务适用依据；字段物理结构不能替代业务确认 |

提前终止字段为空的含义在陈姐原文中有说明，但其独立核查状态和本期月报适用性也需落实，不应将空值解释为无限有效。

规则依据由项目组协调运营；IT老周配合字段及记录，陈姐提供门店办理依据；具体最终确认人尚未落实。可按任务书“卡住以后”向课程方申请与访谈事实一致的MD及同源JSON补充材料，标明课程方来源，不冒充本人访谈。取得新证据后更新模型与Skill，再生成六项定义和独立期望。

当前构建只选择32项，故其 `unresolved.json` 为空不表示全部38项目标无缺口。六项不得用零值、猜测资格或拒答用例冒充成功覆盖。SOW中的交付影响与责任见 [当前SOW](sow.md)。

### 查询限制与错误分类

- 覆盖外请求应说明不支持，不能返回零；零分母应保留null/未定义，不能伪造0。
- 月内购买与复购的本期产品入口执行完整月、全范围汇总或按月展示限制，不接受门店及其他会员属性拆分、筛选。结构上存在关联维度不等于本期产品允许使用；除材料明确的业务限制外，其余是当前实现支持边界，不冒充新增客户制度。见 [月报拒答核查](monthly_refusal_review.md)。
- 对拒答用例保留原请求；是否已执行SQL和是否正确解释限制分别检查，不以拒答代替指标数值验收。
- MODEL_HTTP_402属于模型调用未完成，不是业务零值或SQL计算错误；保留失败报告和恢复证据。
- 机器提出的角色冲突按人工反馈处理为职责转介与最终确认责任未落实，不认定已有互斥业务公式。

## 解释人工核查

规模53例结构化判定通过后另核查回答文字，记录见 [逐例解释检查](../../artifacts/w03/test-general32-large-current-20261107-173736/answer-review-findings.json)。这是AI辅助逐例阅读记录，不能由结构化passed自动推导解释无误。

| 用例／范围 | 客户与口径核查 | 发现与处理 | 结论边界 |
| --- | --- | --- | --- |
| single_discount_cents | 青禾、2026年8月、paid订单原价减实付；原数63492599分正确 | 旧回答额外换算元出错；修复后保留63492599分 | 回答重放和真实入口回归均核对正确 |
| single_first_order_count | 观测期首单结果15正确 | 旧回答把计数单位说成账户；修复后明确15单，全覆盖有效订单先定首次 | 回答重放和真实入口回归均核对正确 |
| single_first_buyer_count、single_avg_buyer_value | 首购15个CRM账户；人均31139.20分/账户 | 重放核对计数对象、金额单位及观察范围 | 仅回答重放，未重新执行查询 |
| monthly_jul_aug | 两个完整月分列；复购分母为当月购买账户 | 7月16436/7388，8月16504/7302；比例为复购/购买，人数不跨月加总 | 重放解释核对正确 |
| aug_cancelled_zero_denominator | 取消单筛选保留；有效单0、净额0、均额null、取消率1.0 | 区分零与未定义，未因零分母拒绝合法请求 | 重放解释核对正确 |
| 原53例中的其余回答 | 详见逐例检查 | 另记净额额外元展示、取消率额外百分数及措辞问题；未发现另外的实质数值／单位错误 | 人工阅读结论仅覆盖该批实际回答，不保证未来输出 |

修复通过确定性 `answer_display_facts.py` 提供单位、计数对象与展示值，提示词据此解释。六例 [回答重放](../../artifacts/w03/answer-display-replay-20261107-210241/answer_replay_report.json) 保留原SQL结果、未重新查询、未修改原报告；两例 [真实入口回归](../../artifacts/w03/test-answer-display-e2e-20261107-210405/metric_test_report.json) 重新执行意图、查询和回答并通过。不能表述为最后一次展示修复后53例已全部重跑。

## 测试与回归记录

独立期望由 `customer/w03/check_base16.py`、`check_orders24.py`、`check_member8.py` 及用例生成程序依据客户材料直接读取原始CSV计算，不从模型实际查询结果反填。`judge.py` 用确定性程序比较指标、窗口、筛选、分组、数值、单位、null及数据／库版本；整数精确，比值允许报告中约定的浮点误差。

| 阶段／报告 | 事实与错误来源 | 修订与验证结论 |
| --- | --- | --- |
| [32项库中的基础24项重判](../../artifacts/w03/rejudge-general32-base24-20261107-025040/report.json) | 单位等价拼写的判定问题 | 11例通过；重判不等于重新查询 |
| [新增会员8项独立校验](../../artifacts/w03/check-general32-member8-20261107-024543/report.json) | 独立CSV期望与32项小库对照 | complete=true、passed=true，共20例 |
| [判定器正例与错误注入](../../artifacts/w03/judge-mutations-20261107-161649/report.json) | 检验比较器是否识别错误 | 8个正向控制接受、34个错误变体拒绝；包含任务书九类错误，不是42个真实查询 |
| [小样本全批](../../artifacts/w03/test-general32-full-20261107-162320/metric_test_report.json) | 53/54；拒答后的group_by与期望不一致，并有错误的可用维度解释 | 保留原失败；调整拒答判定范围并修正产品解释 |
| [月报策略回归](../../artifacts/w03/test-policy-regression-20261107-164103/metric_test_report.json) | 拒答与合法查询对照 | 9/9，不据此改写原全批报告为54/54 |
| [规模首轮](../../artifacts/w03/test-general32-large-20261107-164818/metric_test_report.json) | 37次MODEL_HTTP_402 | 保留失败；先验证原生查询与单例模型恢复，再处理大枚举上下文 |
| [上下文压缩回归](../../artifacts/w03/test-context-reduction-20261107-171050/metric_test_report.json) | 30000账户ID重复进入上下文 | 聚合查询及显式M29998筛选2/2；引擎完整取值保留，不把截断枚举当完整范围 |
| [规模当前53例](../../artifacts/w03/test-general32-large-current-20261107-173736/metric_test_report.json) | 恢复后重新生成对应版本独立期望，执行全批 | complete=true，53/53；已报告总用量711231 tokens，不等于实际费用或业务收益 |
| [展示修复重放](../../artifacts/w03/answer-display-replay-20261107-210241/answer_replay_report.json) | 结构化结果正确而文字有误 | 6/6生成完成并逐条核对；未重新执行SQL |
| [展示修复真实入口](../../artifacts/w03/test-answer-display-e2e-20261107-210405/metric_test_report.json) | 验证优惠金额及首单数解释修复 | 2/2；不宣称最后版已重跑全53例 |

版本绑定：小样本 `qinghe-w03-20260923-small`，data_sha256=`8a295969ec24556ebd7f818506633919e71f840fc86488d53efc185f9768cfe6`，上述32项小库catalog_sha256=`3e6e2b195d000badb5b36b215c4857c6ae11c7643ec0ab865f4faafba8ca9635`。规模 `qinghe-w03-20260923-large`，data_sha256=`0074e7f764c63e836617aecb0e217aa3b5cc0cf9ede557179ad46b077dcf8ba8`，catalog_sha256=`2778ddc8e0fbaff9a3a8ca86b3cd59167cf6ca0d64f764c7eca452e7283b333f`。两套报告分别绑定自己的项目版本，不混用期望。

后续完成条件：取得付费资格依据并核查入模；Skill生成包含六项的新候选并审阅；编写不依赖实际输出的资格边界和六指标期望；生成一致的38项定稿库并重新加载；补齐正式大小样本用例入口，执行与该库绑定的完整回归及解释核查。最后再整理正式报告与提交包。当前的32项阶段库和53例报告均不能替代38项最终交付。
