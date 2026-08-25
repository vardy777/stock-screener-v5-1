# V5 第三轮独立复验修复记录（2026-08-26）

## 本轮边界

- 只修复 `amount_percentile`、严格因子标签证据链和指数大跌事实口径。
- 未修改 baseline 选股、确认、仓位、费用或滑点参数。
- 保持 `research_locked`，未发送券商订单，未补写历史严格窗口。

## 修复结果

1. 正式研究因子由原始 `amount` 改为同一 09:25 合格横截面内的 `amount_percentile`。采用并列平均秩除以 `n-1`，范围 `[0,1]`；单样本定义为 `0.5`。原始成交额继续作为审计字段。
2. 新增严格标签生产入口 `v5/scripts/build_factor_labels.py`。它只读取内容校验通过的 09:25 诊断、机会/配对、模拟订单和成交事件，生成内容寻址的 strict label 与 labelled cohort。没有严格退出时合法落盘 `INSUFFICIENT_STRICT_LABELS`。
3. 指数大跌预注册为沪深300（`000300`）点时涨跌幅不高于 `-2%`。事实必须来自两个独立来源、时差不超过 15 秒、涨跌幅差不超过 0.2 个百分点；两源都达到阈值才记 `VERIFIED_DECLINE`。没有严格指数事实时为 `UNKNOWN`，不能计入晋升覆盖。
4. 股票横截面 `median_change` 不再参与指数大跌判定。

## 验收

- 针对性测试：58 passed。
- 标准根目录测试：484 passed。
- 生产架构静态审计：passed，issues 为空。
- baseline 冻结校验：True。
- `compileall v5` 与 `git diff --check`：通过。

## 仍待真实窗口

- 真实 09:25 全截面 `amount_percentile` 事实。
- 真实严格买入及次日 09:30 退出后自动生成的 factor label/cohort。
- 真实双独立来源沪深300点时事实，以及跨市场状态的自然样本积累。
