# W03 青禾会员报表问数作业

本仓库提交第三周作业及整改记录：依据业务模型和构建 Skill 生成38项指标，用原始 CSV 独立核算期望，再通过运营 Agent 执行大小样本问数。

## 阅读入口

| 内容 | 文件 |
| --- | --- |
| 交付范围、验证结果和复跑方法 | [交付说明](docs/w03/submission_overview.txt) |
| 客户阶段范围、双方责任和验收依据 | [SOW](docs/w03/sow.md) |
| 老师意见与整改结果 | [整改核查](docs/w03/teacher_feedback_check.md) |
| 业务模型、变化及访谈 | [业务模型](docs/w03/business_model.md)、[模型更新](docs/w03/model_changes.md)、[访谈记录](docs/w03/interview_notes.md) |
| 指标口径与来源 | [指标核定记录](docs/w03/metric_decisions.md) |
| 构建方法 | [构建 Skill](customer/w03/build-metrics/SKILL.md) |
| 38项指标定稿库 | [library](artifacts/w03/library) |
| 用例、判定和报告入口 | [测试入口](customer/w03/test_entrypoints.txt)、[判定代码](customer/w03/judge_full38.py)、[正式报告](artifacts/w03/metric_test_report.json) |
| 六个运行文件的修改依据 | [框架修改说明](docs/w03/framework_changes.md) |

## 当前结果

- 38项：24项订单指标、8项会员指标、6项付费会员月报。
- 当前 Skill 完整构建，使用课程 `merge` 定稿。
- 独立CSV核对：小样本49/49、规模48/48，两套均覆盖38项。
- 正式库自然语言结构化结果：小样本69/69、规模67/67。小样本一处文字公式修正后另有9/9定向复测；原完整报告与补充报告分开保留。
- 判定器：10个正向对照通过，30个错误注入被拒且理由对应。
- 原聊天入口完成6个代表性场景检查，缺年份题在新会话澄清。
- 提交包解压后课程预检通过，文件清单和压缩完整性检查通过。

六项付费月报采用P1暂定口径，保留受访者尚未确认的总部沿用及规则细节。补充材料申请仍是待发送稿。以上工程结果不代表教师验收、业务核定或生产上线批准。

## 下载提交包

[下载38项作业ZIP（r1）](submission/w03-submit-38-20261110-201906-r1.zip) · [SHA256](submission/SHA256SUMS.txt) · [内容复查](submission/package_review.json)

ZIP约50.2MB，包含本轮成果及失败、修订和回归证据。仓库中的成果文件与ZIP按同一版本整理，README、Git配置和下载目录为仓库导航附件。历史32项目录用于追溯，当前结果以本页和交付说明为准。

## 复跑条件

这是课程工程的作业附件。另需准备原始c16工程、课程small/large数据、Python环境和自己的模型配置。将本仓库成果按相对路径放入课程工程工作副本，按[恢复说明](artifacts/w03/runtime-customization-current/RESTORE.txt)恢复六个运行文件，再按交付说明重新加载数据和测试。

不随作业提供虚拟环境、查询数据库、运行缓存或密钥。历史报告中的本机路径是当时运行位置；迁移后使用复跑说明中的相对路径重新加载。原W02模型作为来源附件保留。