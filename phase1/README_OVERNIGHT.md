# 隔夜策略重构说明

## 固定策略规格

- 初始资金：100,000元
- 最多持有3只，每只全部成本不得超过总权益的1/3
- T日14:49:59停止读取信号，14:50开始买入
- T+1日09:30进入连续竞价后卖出
- 成功标签：扣除全部费用后净收益不低于1%
- 佣金：0.025%双向、每笔最低5元
- 印花税：卖出0.05%
- 过户费：0.001%双向
- 基准滑点：买卖各0.05%；压力测试为各0.10%
- 排除科创板、北交所、ST/退市、5元以下、200元以上及尾盘已涨停股票

所有费用、滑点、仓位和净收益计算统一由项目根目录的
`strategy_spec.py` 提供。V3模拟账户和Phase1研究不再各自维护费率。

## 数据质量

现有 `data/daily/*.csv` 实际是60分钟K线，不是日线，也没有14:50
成交价。新数据集遵守以下原则：

1. 特征只使用14:49:59以前已经完成的K线；
2. 当前历史库使用15:00收盘价作为14:50买入代理，并明确标记为
   `close_proxy_15_00`；
3. 尾盘涨停、无法买入的股票不会进入交易；
4. 次日跌停无法卖出时，不再假设可以按开盘价成交；
5. 超出涨跌停范围的跳空标记为疑似除权或异常标签并排除；
6. 当前历史库没有历史ST状态和完整除权事件表，因此所有代理结果都只
   能用于研究，不能作为实盘验收结果。

从现在开始，可在交易日运行以下命令积累真实成交时点快照：

```powershell
# 14:49:00-14:49:59，冻结19个严格特征
python phase1/scripts/capture_signal_features.py

# 14:50:00-14:51:59，记录真实买入参考价
python phase1/scripts/capture_execution_snapshot.py buy

# 下一交易日09:30:00-09:35:00，记录连续竞价卖出参考价
python phase1/scripts/capture_execution_snapshot.py sell
```

当前已注册工作日任务：09:25推送早盘观察池，14:50:20推送尾盘确认；
14:49冻结信号、14:50采集买入盘口、09:30采集卖出盘口；09:36和14:53
另有只读健康巡检。15:10自动刷新当天归档、构建
下一开放交易日上下文、执行预检并重建执行标签，不训练或发布模型。采集
最多重试3次且只补抓缺失
代码，覆盖不足95%、行情时间在采集时间之后、行情超过30秒、离开规定窗口
或盘口不完整时均失败关闭。窗口外诊断只写入`diagnostic/`隔离目录，不会
进入严格样本。

严格买入参考价使用卖一价（`ask1`），严格卖出参考价使用买一价（`bid1`），
并记录一档挂单量。只有一档挂单量覆盖计划股数时，标签才满足流动性合同。
Sina成交量原始单位已经是“股”；历史文件已完成一次性x100纠偏，并由
`.volume_unit_contract.json`标记，未核验单位时采集上下文和模型准入都会锁定。

## 周末维护与下一交易日预检

周末没有实时成交窗口，但可以补齐上一交易日归档、构建严格特征上下文并
完成离线预检。以2026-08-03为例，在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe phase1\scripts\refresh_intraday_archive.py --trade-date 2026-08-03
.\.venv\Scripts\python.exe phase1\scripts\build_live_feature_context.py --trade-date 2026-08-03
.\.venv\Scripts\python.exe phase1\scripts\weekend_preflight.py --trade-date 2026-08-03
```

刷新脚本按时间戳合并并原子替换；空响应、缺少15:00完整柱、非法价格或
行数回退都不会覆盖原文件。上下文覆盖率和交易日历必须通过门槛，14:49
发布器才允许运行。`strict_capture_ready=true`只表示可以采集研究快照，
不表示模型准入，也不会解除`research_locked`。

任务注册脚本为`phase1/scripts/register_v4_snapshot_tasks.ps1`，统一使用项目
`.venv`解释器。运行身份为当前交互式用户并启用唤醒；电脑锁屏可运行，用户
注销后不会运行。看板由登录任务使用项目`.venv`启动。系统运行不需要任何
AI Agent或外部任务调度器。

两条PushPlus任务只读取`v3/.env`中的`PUSHPLUS_TOKEN`，代码和任务配置不得
硬编码令牌。09:25候选只是观察池，早盘不得买入；14:50:20会重新获取行情、
重新评分并经过V4研究门禁，只有Top1可能显示为确认候选。当前
`research_locked`期间两条推送都只能给出观察/空仓信息，不会自动买入。

## 研究流程

在项目根目录运行：

```powershell
# 1. 构建全市场时点数据集
python phase1/scripts/build_overnight_dataset.py

# 2. 无AI、可解释的规则基线
python phase1/scripts/backtest.py

# 3. 真正按日期滚动训练和测试
python phase1/scripts/walk_forward.py --model auto

# 交易成本压力测试（买卖滑点各0.10%）
python phase1/scripts/walk_forward.py --model auto --stress

# 4. 只有全市场Walk-Forward通过准入门槛后才训练最终模型
python phase1/scripts/train_model.py --model auto
```

`auto` 会在安装LightGBM时使用LightGBM；否则使用项目内置的确定性岭回归
基线。模型分别预测预期净收益、净盈利概率、净收益达到1%的概率和大亏
概率，避免用单一平均收益掩盖低胜率或尾部风险。

Walk-Forward默认使用：

- 12个月训练；
- 3个月测试；
- 训练与测试之间保留1个交易日隔离；
- 每个窗口重新训练，测试数据永远不会参与模型拟合；
- 在训练窗口尾部单独留出验证区间，只允许Top1并选择市场环境和置信阈值；
- 验证区间没有稳健正期望时，后续测试窗口直接空仓；
- risk-off市场状态空仓，模拟执行默认只新增Top1；
- 输出 `precision_coverage.csv`，分开统计净盈利胜率和净收益达到1%的命中率。

## 输出目录

```text
data/overnight/dataset.csv.gz       全市场时点数据集
data/overnight/live_feature_context.csv.gz  下一交易日14:49特征上下文
data/overnight/weekend_preflight.json       离线预检结果
data/overnight/daily_maintenance_report.json 每日下一交易日维护审计
data/overnight/rule_report/         规则基线报告
data/overnight/wf_report/           Walk-Forward报告
data/overnight/wf_report_stress/    加倍滑点压力报告
data/overnight/model/               最终模型与训练说明
data/execution_snapshots/           向前积累的真实14:50/09:30快照
data/execution_snapshots/health/    定时采集健康巡检结果
```

带 `smoke` 名称的文件和目录是300只股票的工程烟雾验证，不代表完整市场
策略表现。

## 实盘准入门槛

必须同时满足以下条件，才进入60至90个交易日模拟盘：

- 使用真实14:50和09:30数据，不再使用15:00代理；
- 14:49严格特征、14:50买价与次日09:30卖价均为全市场至少95%覆盖；
- 买入使用卖一、卖出使用买一，且一档挂单量覆盖计划股数；
- 成交量单位已经核验为“股”，不存在历史x100放大；
- 使用已核验的交易所日历，且标签严格配对到下一开放交易日；
- 样本外交易至少500笔，净盈利胜率95%置信下限高于50%；
- Profit Factor不低于1.20，最大回撤不高于12%；
- 至少70%的Walk-Forward窗口盈利；
- 扣除基准成本后总体期望为正；
- 双倍滑点压力下仍保持正期望；
- 收益不是由少量涨停或单一月份贡献；
- 跌停延迟卖出、停牌、除权和ST历史状态均已纳入。

所有生产任务均位于Windows Task Scheduler，名称以`AStock-V4-`开头。
`python main.py v3-cron-list`可查看本地任务状态；不再读取任何外部Agent配置。

## 当前研究结论（2026-08-02）

- 全市场历史代理数据2,614,305行，严格14:50样本0行；
- 规则基线639笔，胜率25.98%，累计收益-97.08%；加倍滑点后618笔、
  胜率25.40%、累计收益-97.26%；
- Top1 Walk-Forward代理样本56笔，胜率58.93%，95%置信下限45.88%，
  7个窗口仅2个盈利且4个无交易；压力结果同样未通过；
- 以上数据全部使用15:00代理，不能声明盈利，也不能解除`research_locked`。
