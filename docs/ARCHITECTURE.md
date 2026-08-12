# V4 系统架构

## 产品边界

V4 是本机独立运行的 A 股隔夜研究与模拟交易系统。外部依赖只有行情供应商、PushPlus、Windows Task Scheduler 和 NTP；Codex、ChatGPT 与 Hermes 均不属于运行时。系统不连接券商，始终保持 `research_locked`，直到严格数据、Walk-Forward、压力测试和模型发布门禁全部通过。

## 当前生产所有权

| 职责 | 唯一所有者 | 生产入口 |
|---|---|---|
| 行情契约 | P1 | `v4.market_gateway.MarketDataGateway` |
| 候选与决策 | P2 | `v4.decision_production.P2DecisionProducer` |
| 模拟账户与成交 | P3 | `v4.p3_production` |
| 调度与通知 | P4 | `v4.production_task_runner` / 九个 Windows 任务 |
| 只读看板 | P5 | `python -m v4.p5_dashboard --port 8898 --data-dir v4/data` |

P3/P4/P5 已于 2026-08-09 获授权切换。旧任务保持 Disabled；旧 `dashboard.py`、`simulation.py`、`sim_engine.py` 和根目录脚本只作为历史兼容表面保留，不得进入生产叶子。

## 因果数据流

```text
行情供应商 → MarketDataGateway → MarketSnapshotV1
  → MarketStateV1
  → 09:25 MorningPoolV1 → 早盘 PushPlus
  → 14:49 FeatureContextV1
  → 14:50 ConfirmationDecisionV1 → 尾盘 PushPlus
  → P3 严格 Top1 成交快照 → PaperOrderIntent/Fill
  → 下一交易日 09:30 严格卖出快照 → PaperRoundTrip
  → 严格标签/数据集 → P6 审计 → P7 模型发布门禁
```

观察快照允许母池内个别股票停牌、涨跌停或盘口不可成交；这些股票在策略层逐标的阻断。只有最终可执行 Top1 才创建要求卖一盘口的严格买入快照。任何窗口外、未来时间、覆盖不足或时钟偏差过大的数据均失败关闭。

## 唯一事实源

- 候选与决策：`v4/data/candidate_journal/YYYY-MM-DD.json`。
- 行情：内容寻址 `MarketSnapshotV1`。
- 模拟账户：P3 不可变事件账本。
- 任务：P4 不可变尝试与最终输出。
- 通知：`v4/data/notifications/<message-key-hash>.json` 的 `NotificationReceiptV1`。
- 看板：只读投影上述实体；不得抓行情、选股、推送或写账户。
- `runtime_state.json` 仅为可删除诊断；兼容索引不得用于业务验收。

## 三类证据

| 证据 | 用途 | 可否解锁模型 |
|---|---|---|
| 严格 14:49/14:50/次日 09:30 配对样本 | 训练、Walk-Forward、压力测试 | 满足全部门禁后可以 |
| P3 模拟账户 | 工程闭环和策略行为观察 | 不可以 |
| 历史 15:00 代理回测 | 假设与诊断 | 不可以 |

## 当前状态

离线架构、冻结回放和故障矩阵已通过。Windows Time 已自动启动并以 NTP 实测偏差门禁校验。仍待真实窗口完成 09:25、14:49、14:50、次日 09:30 闭环；严格配对样本尚为 0，模型未发布，不能评价盈利有效性。
