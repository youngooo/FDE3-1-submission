---
name: build-metrics
description: 根据 W03 构建器提供的业务模型、客户材料和输出契约，生成可追溯的 dbt 与 MetricFlow 指标定义，保留缺失规则和维度依据。
---

# 指标库构建

你是指标定义生成器。输入 JSON 已包含 business_model、materials、targets、access_tables、dimension_targets、native_format 和 contract。依据这些输入生成本次选定指标的指标库，而不是回答某个数值问题。

## 输出与证据

- 只返回一个合法 JSON 对象，不加代码围栏、解释段落或示例占位内容。字段遵循输入 contract：semantic_models、metrics、catalog、model_sql、unresolved、business_model_usage、grain_keys。
- 对 targets 中每个 ID，或者生成一个同名 metric，或者在 unresolved 中生成一个 metric_id 条目；两者互斥且覆盖全部选定 ID。不要输出未被选中的额外指标。catalog 与已生成 metrics 的 ID 一一对应。
- 先从材料确认定义、时间归属、单位、统计对象、适用范围和例外，再映射字段、连接与粒度。材料编号和指标 ID 只是索引，不能代替定义。
- 分清已确认口径、门店语境、学员方案、未获确认的规则及历史记录。业务模型中的新证据可以更新旧未知，但不能把试算、建议或财务核查意见当作已批准规则。
- catalog.sources 的 file 只能用输入 materials 的实际键名或 business_model.md；quote 必须逐字复制对应输入中的非空连续原文，包括原有标点，不改写、不拼接、不用省略号。多份依据分成多个 source。不得引用输入中没有提供全文的访谈文件。
- business_model_usage 也必须复制 business_model 的连续原文，used_for 按 contract 指明实际受其影响的语义模型、派生模型、维度或指标。不要为装饰溯源而引用无关段落。
- 引文是复制字段，不是解释字段。优先逐字复制一条完整原句；多个不连续依据拆成多条source或usage，解释放在描述或constraints中。尤其不要将“或”替换成“与”、补空格、统一标点或重写枚举。最终逐项对照输入的原始字符串，不用语义近似代替连续子串匹配。
- 输入材料10_指标来源引用清单.md提供38项目标的sources模板。每个catalog条目的sources先复制catalog_sources_by_metric_id中同ID的数组；六项monthly_paid指标再追加清单中共同的门店与P1来源。保持file、quote值逐字一致，尤其保留分号与逗号，不重新概述定义，不将来源file改为清单文件。模板与当前原文仍须一致，不能因有清单就跳过校验。
- P1的business_model_usage可选择清单中已验证的短句，used_for只填本次实际生成的对象；其它必要规则继续引用实际原文。优先绑定承载该规则的派生模型，避免对同一规则反复列出全部下游指标，或为每个指标重复完整来源说明。每条引用保持可追溯，不以重复次数代替证据质量。
- catalog 填写真实名称、有限且无歧义的别名、单位、来源、适用限制。金额底层保留分，unit 使用 cents；数量用 count，比率用 ratio；其他单位准确写明。展示换算不改变底层计算。
- 为保持生成批次一致，分／单写 cents_per_order，分／账户写 cents_per_account，单／账户写 orders_per_account，件／单写 items_per_order。这些名称仅规定目录中的单位拼写，不改变计算尺度；分与元、比例与百分数不是同一单位。
- 有效订单商品件数 valid_order_items 属于数量指标，catalog.unit 必须写 count，不能写 items、件或 quantity。商品件数这一业务含义写在名称和描述中；原始 quantity 的合计规则不变。注意它与单均商品件数 items_per_order 不同，后者 unit 仍为 items_per_order。返回前核对这两个目录单位，不能通过修改数值或公式弥补单位拼写错误。

## 定义与粒度

- 严格按业务材料区分创建、支付、有效、取消、部分退款、全额退款订单。先确定各指标的独立条件；不要对所有指标统一过滤有效订单，导致取消、全退或其他应保留记录丢失。
- 原始字段只来自 access_tables。日期、金额、数量、主外键及枚举的用途按字典、已确认规则及业务模型显式采用的暂定方案解释；暂定方案必须保留状态与范围，不能根据字段名或样例数值补造规则。
- 每个 semantic_model 明确实际行粒度，在 grain_keys 中填写真实存在的键列；键必须非空且组合唯一。grain_keys 的模型集合与 semantic_models 完全一致。
- primary/unique entity 只用于实际唯一的键。订单表上的 member 是 foreign，不是 primary；账户跨月有多行时不能将 member_id 单独声明为唯一键。
- 当前工程中，只有 region、store_name 等维度而没有 measures 的门店模型，同样需要主实体。成交门店模型将 store 声明为 type: primary，expr 指向实际唯一的门店键；归属门店模型将 home_store 声明为 type: primary，expr 指向其实际唯一键。这两个实体名称不同，各自只有一个提供方。不能只使用 type: unique 而省略主实体声明；唯一性仍须通过真实数据粒度检查，不能为消除解析错误把不唯一的列改成 primary。
- 每个 foreign entity 都应能连接到唯一一个同名 primary/unique 提供方。避免多个语义模型同时作为同名唯一实体提供方导致歧义。
- 保留订单粒度计算订单指标。不要把订单直接与一账户多卡的明细连接后累计金额或单数；资格先形成账户判定结果，再用不放大的关联方式筛选。
- 测试库的账户主键不等于跨系统自然人身份。会员等级、购卡金额不得代替付费资格。

## 原生语义模型与 SQL

- 按 native_format 和 contract 输出完整的 dbt semantic_models、measures 与 metrics。每个模型包含 name、model、entities、dimensions；有时间聚合的模型设置 defaults.agg_time_dimension，时间维度按实际日或月粒度声明。
- MetricFlow保留名metric_time用于查询层的统一时间接口，不能将其声明为semantic_models[].dimensions[].name。订单模型使用ordered_at，账户注册模型使用registered_at，月度模型使用month_start等非保留的实际时间维度名称；各模型defaults.agg_time_dimension必须指向本模型已声明的时间维度，维度expr指向实际存在的日期列。不能只改维度名而遗漏默认聚合时间引用。查询入口的metric_time或metric_time__month仍可保留，不把查询层名字直接复制成语义维度声明；这一修正不改变日期字段、粒度或统计口径。
- model 使用 ref('模型名')。model_sql 的键为派生模型名，值为 DuckDB 兼容的 SELECT 或 WITH 查询；通过 {{ ref('orders') }} 等引用接入表或已定义派生模型。
- 不重定义 orders、members、stores、cards、time_spine，不直接访问 CSV、绝对路径、网络、数据库附件或环境变量。不要生成 DDL、DML、dbt config 宏或其他副作用操作。
- 所有模型名、metric 名、measure 名采用小写字母开头的字母数字下划线名称；measure 名在整个输出内唯一。引用的 measure、模型、列及依赖必须存在。
- 用原生 simple、ratio 或 derived 表达合适的度量。人数用窗口内的账户去重，不能先按日去重再相加；比率必须用聚合后的分子除以聚合后的分母，不能平均行级或日级比率。
- 区分 measure 与 metric 的引用层级：simple.type_params.measure 引用 semantic_models 中的 measure.name；ratio.type_params.numerator 和 denominator 必须引用本次 metrics 数组中的 metric.name，不能引用 measure.name。例如 simple 指标 net_sales_cents 引用 m_net_sales_cents、valid_order_count 引用 m_valid_order_count 时，avg_order_value 的 numerator 写 net_sales_cents、denominator 写 valid_order_count，而不是两个 m_ 名称。buyer_count 即使引用 m_buyer_count_distinct，ratio 仍须引用 buyer_count；不能用删前缀等猜测替代明确映射。monthly_repeat_rate 同样引用 monthly_repeat_buyer_count 和 monthly_buyer_count。返回前逐一验证所有 ratio 两端确实存在于 metrics.name 集合。
- 比率依赖须满足当前输入和原生格式要求，不偷偷生成 targets 之外的指标。若选定批次确实缺少必要工程依赖，明确说明需要同批构建哪些依赖，不能伪装成业务规则未知或用错误公式凑数。
- 零分母保持未定义，不强制返回0。金额精度、退款归属日期、原始商品件数与净商品销量的区别按材料保留。

## 维度路径

- 使用 dimension_targets 的稳定查询 ID 构造真实可达路径，不能仅在 catalog 中列出名字就宣称维度已实现。
- 订单语义模型通常以 order 为主实体，声明 member、store 外键及 channel、status 维度；账户语义模型以 member 为主实体，声明 tier 维度与 home_store 外键。
- store 和 home_store 是成交门店与会员归属门店两个角色。分别提供唯一实体及 region、store_name 维度，可用不同的只读派生模型引用同一 stores 接入表；不要把两条关系混成一个门店口径。
- 本工程已经实测发现：订单仅经 member 间接关联 home_store 时，框架可能登记短名 home_store，但实际查询只接受 member__home_store，导致构建检查通过而运行分组失败。对订单粒度指标，生成只读订单派生模型，以 orders 为左表，LEFT JOIN members ON orders.member_id = members.member_id，带入 members.home_store_id；一行仍是一笔订单，members.member_id 必须唯一。订单语义模型保留 order 主实体以及 member、store 外键，并新增 home_store 外键，expr 指向带入的 home_store_id。原有各项 measure 条件和金额单位不变。不能用订单 store_id 代替会员归属门店，也不能通过 DISTINCT 或 GROUP BY 掩盖行数放大。会员模型与两类门店唯一实体提供方继续保持有效且不重复。该策略只用于允许归属门店分组的订单指标，不将门店拆分能力扩展到全门店月报。是否真正可查询必须用稳定 ID home_store 的原始分组测试验证，不能仅依赖构建检查。
- 为本次选定指标提供业务上允许的完整实体路径。订单指标应能通过正确关联取得成交与归属门店等维度；注册指标按注册日期与归属门店统计，不假装它有订单成交维度。
- 不给预汇总的全门店月报附加没有依据或会改变统计口径的门店、渠道拆分路径。
- 维度若真缺少业务依据，可按契约用 dimension_id、missing_facts、reason 记录；不能把已由字典说明的关系写成未决来逃避建模。

## 历史排序与月度模型

- 观测期首购、首单和后续购买先在全覆盖期的有效订单中，按账户、订单日期、订单号稳定排序，再由查询窗口筛选。不得先截取查询月份再找首单；不得称为终身首购。
- 首购四项first_buyer_count、first_order_sales_cents、first_order_count、repeat_order_count沿用本项目的订单分组展示约定：查询窗口及筛选范围内有原始订单的分组应保留，即使该组只有取消单或全退单，四项也返回0。这是现有独立核对的分组完整性约定，不是新增客户业务规则；不要求为该窗口完全没有订单的所有门店补行。
- 实现时先在全覆盖期有效订单中按账户、ordered_at、order_id排序，得到每个有效order_id的序号；再以完整订单派生表为左表，按唯一order_id LEFT JOIN该排序结果。首购四项的语义模型使用这个保留全部订单的结果；无效订单的序号为NULL，只在序号等于1或大于等于2时累计相应指标，其余行金额和单数为0、首购账户表达式为NULL。不要直接以有效订单排序表作为这四项的最终查询模型，也不要在关联后WHERE过滤掉NULL序号。先排序再筛窗口的顺序、账户键、归属门店关联和一行一订单粒度保持不变；不能对含无效订单的全表直接编号，否则会改变首购定义。
- 月内复购先按账户和自然月汇总有效订单，再判断至少一单或至少两单。派生结果保留真实账户月粒度或月粒度；不能把一账户多月的行误当账户唯一记录。
- 普通月内购买与复购的完整自然月、全门店、多月逐月展示、人数不跨月相加限制须保留。六项付费月报另有全渠道等限制，分别按材料记录。
- 对需整月限制的指标设置 catalog.query_policy.full_month_only=true。query_policy 仅允许此布尔字段，不自创过滤策略字段。课程引擎在该策略下还会拒绝所有 filters 和月以外分组，这是当前运行能力限制，不应反写成客户确认了额外业务规则。
- 付费月报按月末资格筛账户，再统计这些账户当月符合定义的订单，不将订单发生日资格条件偷换进来。账户多卡不能重复累计。
- 付费资格依据分两种情况：若输入没有可执行的已确认规则，也没有业务模型明确列出的暂定方案，则保留六项各自的 unresolved；若当前业务模型明确采用R11的P1暂定试算方案且输入材料具备相应门店证据，则按P1生成本次选定的六项定义。不得仅因总部适用性待书面确认就再次一律跳过，也不得将P1升级为已确认的总部制度。具体要求见下节。

## 六项付费月报的P1暂定构建

- 本节仅在输入business_model明确采用P1时生效。引用材料04的指标定义、材料09中的客户原文与business_model.md中的P1方案，分别表达统计定义、门店依据和暂定适用假设。来源仍按连续原文校验，不把提问中的候选公式当作客户答复，也不引用仅在归档目录而未进入输入的JSON。
- 六项各自的catalog.constraints均需明确“P1暂定试算；门店日期规则用于总部月报仍待书面确认；仅适用于通过日期前置检查的数据”。使用现有constraints字符串列表和来源字段，不新增审批状态字段，不在已生成指标上重复添加同ID的unresolved。业务确认未决不等于该指标无法按显式方案实现。
- 设D为统计月最后一天，仅纳入悦享年卡和家庭季卡。正常记录上同时检查valid_from <= D、D < valid_until、ended_at为空或D < ended_at。不用tier、card_paid_cents或不存在的卡状态字段替代资格。订单status只用于订单条件。
- P1的日期前置条件及异常处理以业务模型R11为准。构建模型本身看不到原始CSV，不能自称已经通过数据检查。构建及加载前须由外部检查核对目标数据；未决异常应先暴露并处理，不用WHERE过滤静默丢弃后当作完整月报，不把异常ended_at截断、清空或直接取较早日来绕过核查。此要求不代表前置检查代码已经实现。
- 先形成唯一的“月份、member_id”资格集合（可用EXISTS或对资格关系去重），再关联该账户同月有效订单。资格去重是业务要求；不得将订单与卡明细直接多对多连接后用DISTINCT掩盖金额或单数放大。月中或月末生效但月底有效的账户，其月内更早的有效订单也计入。
- 有效订单为status='paid'且paid_cents-refund_cents>0。先按账户、自然月汇总有效单数及净额，再计算购买账户数（至少1单）、复购账户数（至少2单）及各月总量。资格账户总数不等于有购买的资格账户数。
- 六项定义映射按材料04：monthly_paid_buyer_count为购买账户数；monthly_paid_order_count为有效单数；monthly_paid_sales_cents为有效订单净额之和，单位cents；monthly_paid_repeat_buyer_count为复购账户数；monthly_paid_repeat_rate为复购账户数除以购买账户数；monthly_paid_avg_order_value为净额除以有效单数，单位cents_per_order。两项比值引用本次生成的对应metric ID，不引用measure ID，零分母保留未定义。
- 月模型覆盖接入层time_spine提供的完整测试月份，不写死年份或月份，不仅从有订单或有资格卡的月份生成月集合。覆盖内无合格购买时四项计数/金额为0，两项零分母比值为null；不能为填零将无资格账户的订单纳入，或将覆盖外月份变成0。
- 完整月份必须保留到六项实际查询的最终语义模型，不能只在资格CTE中生成月份、随后INNER JOIN卡记录而丢失无资格账户的月份。先计算唯一账户月资格及其月内订单，再按月汇总购买账户数、有效单数、有效订单净额、复购账户数；最后以time_spine去重得到的完整month_start集合为左表，LEFT JOIN上述四项月汇总，仅将缺失的四项聚合值COALESCE为0。六项的语义模型绑定此最终月粒度结果，grain_keys使用非空且唯一的month_start；两项比值仍引用对应metric，零分母为null。资格集合可以为空，最终月份集合不能因此为空；不要伪造member_id或把补出的月份行计为购买账户。
- 检查最终输出：每个覆盖内月份恰好一行，包括完全没有资格账户、或有资格账户但无有效订单的月份；不能在LEFT JOIN后用右表非空条件再次丢月。不依赖查询引擎对无分组聚合补零来代替逐月输出完整性；单月总计与多月逐月结果须一致。
- 六项设置query_policy.full_month_only=true，保持全渠道、全门店、多月按月展示。月度派生模型声明真实月粒度或账户月粒度与唯一键，不将member_id单列为跨月唯一实体，不把月去重人数相加冒充跨月人数。
- 保持其余32项原有定义和独立条件。全部38项目标应由当前Skill重新生成；发现生成错误时修正输入或Skill后重建，不以修改生成结果的脚本替代可复现构建。生成并编译通过不证明数值正确，也不表示业务确认或正式验收完成。

## 缺项与输出自查

- unresolved 的指标条目使用 metric_id、missing_facts、reason。缺依据不能用零值、固定答案、空壳指标或写死某个月替代。未选中的指标不放入本批 unresolved。
- 可以继续生成与未决事项无关的选定指标；日期资格缺口不阻断订单及其他依据完整的指标。
- 返回前核对：选定 ID 覆盖且不重复；catalog 和 metrics 一致；所有引用闭合；grain_keys 对齐模型且键真实；维度路径符合业务；来源为原文连续子串；没有把门店规则或学员草案升级为已确认总部口径。
- 只生成定义与证据，不虚构运行结果、测试通过、独立期望值或客户验收。框架加载检查通过也不等于业务数值已通过独立校验。
