# 模块清单与契约

| 模块 | 当前实现 | 责任 | 当前状态 | 下一阶段 |
|---|---|---|---|---|
| 配置与密钥 | `v4/config.py` | 本地路径、环境配置 | 可用 | P0校验 |
| 交易日与时间 | `v4/calendar.py`, `v4/execution.py` | 交易日、窗口、时效 | P1重开：仍存在naive datetime自动补时区 | 禁止自动补时区并全路径验收 |
| 行情接入 | `v4/data.py`, `v4/market_contracts.py`, `v4/snapshots.py` | 新浪/东财行情、版本化点时契约 | P1重开：核心仍可接收松散DataFrame并绕过快照 | 建立唯一行情网关，核心只接受MarketSnapshotV1 |
| 市场状态 | `v4/market.py` | 宽度、成交额、风险模式 | P1重开：当前为派生字典，缺少稳定身份和血缘 | 建立MarketStateV1契约 |
| 上下文与特征 | `v4/feature_store.py`, `phase1/overnight/` | 点时特征、严格归档 | 研究锁定 | P1/P6 |
| 候选选择 | `v4/selection.py` | 早盘基础分、尾盘固定确认增量 | P2重开：仍有内存/JSON候选旁路 | 只写候选日志最终实体 |
| 决策门禁 | `v4/runtime.py`, `v4/paper_policy.py` | 生产门禁与无偏paper完整性政策 | P2重开：消费者仍会现场重算状态 | 只消费最终决策实体 |
| 候选日志 | `v4/candidate_journal.py`, `v4/decision_contracts.py` | 不可变早盘母池与最终确认决策 | P2重开：尚非唯一事实源且血缘不完整 | 唯一事实源、强制完整血缘、快照起点回放 |
| 模拟账户 | `v4/sim_engine.py` | 现金、持仓、费用、历史 | 可运行 | P3 |
| 流程编排 | `v4/simulation.py` | 抓取、筛选、买卖 | 职责过重 | P2/P3拆分 |
| 调度器 | `v4/paper_scheduler.py` | 买卖定时与回执 | 依赖看板常驻 | P4 |
| 推送 | `v4/push.py`, `v4/scripts/` | 两次必要推送 | 可运行 | P4 |
| 看板 | `v4/dashboard.py` | 8898控制台 | 可运行，单文件过大 | P5拆分 |
| 研究评估 | `phase1/overnight/` | 数据集、WF、压力测试 | 样本不足 | P6 |
| 模型注册 | `v4/model_registry.py` | 发布清单、推理 | 未发布 | P7 |

## 统一业务实体（P2强制目标，尚未验收）

- `MorningPool`: 交易日、候选、全市场状态、输入快照、排序版本；
- `ConfirmationDecision`: 母池成员、确认排序、买/空仓/阻断、原因码；
- `PaperOrderIntent`: 决策ID、参考价、预算、股数、幂等键；
- `PaperFill`: 成交价、费用、时间、行情来源；
- `PaperRoundTrip`: 买卖配对、净收益、持有交易日；
- `TaskReceipt`: 任务、计划时间、开始/结束、结果、重试次数。

实体一旦落盘不可就地改写；派生视图可以重建。

候选业务事实只允许存在于 `candidate_journal`。`dashboard_state.json` 不得承载候选或决策业务语义；`runtime_state.json` 只允许保存可删除、可重建的诊断数据。任何消费者不得以当前时钟、缓存行情或自适应策略重新解释已经落盘的最终实体。
