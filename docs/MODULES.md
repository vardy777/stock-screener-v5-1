# V4 模块清单

| 阶段 | 模块 | 契约与当前状态 | 待验收 |
|---|---|---|---|
| P1 | `market_contracts.py`, `market_gateway.py`, `market.py` | 唯一网关、不可变快照、时区与市场状态血缘；离线通过 | 真实四窗口 |
| P2 | `decision_production.py`, `candidate_journal.py`, `decision_contracts.py` | 母池/确认唯一事实源；逐标的盘口阻断；离线通过 | 真实 09:25/14:50 |
| P3 | `p3_account.py`, `p3_execution.py`, `p3_production.py` | 唯一模拟账户；费用、滑点、T+1、幂等、锁、恢复；已接生产 | 首次真实买入/次日卖出 |
| P4 | `production_task_runner.py`, `push.py`, `notification_contracts.py` | 九任务唯一调度；不可变尝试、详细进程工件与通知实体；已接生产 | 连续真实闭环与漏跑恢复 |
| P5 | `p5_sources.py`, `p5_read_model.py`, `p5_dashboard.py` | 8898 只读三视图；当日状态投影；已接生产 | 真实实体视觉验收 |
| P6 | `p6_research_audit.py`, `phase1/overnight/` | 严格数据、WF、压力门禁；失败关闭 | ≥500 严格样本 |
| P7 | `model_registry.py`, `p7_release_audit.py` | 模型/策略/报告哈希与原子发布审计 | P6 全部门禁通过 |
| P8 | `p8_backup.py` | 内容寻址备份、校验和隔离恢复 | 当前 V4 生产数据演练、历史表面归档 |

## 强制实体

- `MarketSnapshotV1`、`MarketStateV1`
- `MorningPoolV1`、`ConfirmationDecisionV1`
- `PaperOrderIntentV1`、`PaperFillV1`、`PaperRoundTripV1`
- `TaskOutputV1`、`NotificationReceiptV1`

实体落盘后不可就地修改；派生视图可以重建。核心模块不得直接访问 `DataFetcher`。通知验收只读取不可变 `NotificationReceiptV1`，`push_receipts.json` 仅为旧兼容索引。

## 当前生产入口

```text
v4/scripts/p4_task_adapter.py
v4/scripts/decision_job.py
v4/scripts/morning_push.py
v4/scripts/afternoon_push.py
v4/p3_production.py
python -m v4.p5_dashboard --port 8898 --data-dir v4/data
```

旧 `paper_scheduler.py`、`dashboard.py`、`simulation.py`、`sim_engine.py` 不属于当前生产架构。
