# 模块清单与契约

| 模块 | 当前实现 | 责任 | 当前状态 | 下一阶段 |
|---|---|---|---|---|
| 配置与密钥 | `v4/config.py` | 本地路径、环境配置 | 可用 | P0校验 |
| 交易日与时间 | `v4/calendar.py`, `v4/execution.py` | 交易日、窗口、时效 | P1契约化中 | P1 |
| 行情接入 | `v4/data.py`, `v4/market_contracts.py` | 新浪/东财行情、版本化点时契约 | QuoteV1/MarketSnapshotV1已建立，入口待切换 | P1 |
| 市场状态 | `v4/market.py` | 宽度、成交额、风险模式 | 可运行，需契约化 | P1 |
| 上下文与特征 | `v4/feature_store.py`, `phase1/overnight/` | 点时特征、严格归档 | 研究锁定 | P1/P6 |
| 候选选择 | `v4/selection.py` | 早盘池、尾盘母池内重排 | 可运行，有分数口径债务 | P2 |
| 决策门禁 | `v4/runtime.py` | 生产与研究模拟门禁 | 可运行，原因状态会重算 | P2 |
| 候选日志 | `v4/candidate_journal.py` | 早盘/尾盘关联审计 | 可运行，非最终决策实体 | P2 |
| 模拟账户 | `v4/sim_engine.py` | 现金、持仓、费用、历史 | 可运行 | P3 |
| 流程编排 | `v4/simulation.py` | 抓取、筛选、买卖 | 职责过重 | P2/P3拆分 |
| 调度器 | `v4/paper_scheduler.py` | 买卖定时与回执 | 依赖看板常驻 | P4 |
| 推送 | `v4/push.py`, `v4/scripts/` | 两次必要推送 | 可运行 | P4 |
| 看板 | `v4/dashboard.py` | 8898控制台 | 可运行，单文件过大 | P5拆分 |
| 研究评估 | `phase1/overnight/` | 数据集、WF、压力测试 | 样本不足 | P6 |
| 模型注册 | `v4/model_registry.py` | 发布清单、推理 | 未发布 | P7 |

## 统一业务实体（P2目标）

- `MorningPool`: 交易日、候选、全市场状态、输入快照、排序版本；
- `ConfirmationDecision`: 母池成员、确认排序、买/空仓/阻断、原因码；
- `PaperOrderIntent`: 决策ID、参考价、预算、股数、幂等键；
- `PaperFill`: 成交价、费用、时间、行情来源；
- `PaperRoundTrip`: 买卖配对、净收益、持有交易日；
- `TaskReceipt`: 任务、计划时间、开始/结束、结果、重试次数。

实体一旦落盘不可就地改写；派生视图可以重建。
