# 模块清单与契约

| 模块 | 当前实现 | 责任 | 当前状态 | 下一阶段 |
|---|---|---|---|---|
| 配置与密钥 | `v4/config.py` | 本地路径、环境配置 | 可用 | P0校验 |
| 交易日与时间 | `v4/calendar.py`, `v4/execution.py` | 交易日、窗口、时效 | P1离线通过：naive datetime统一fail-closed | 真实四窗口验收 |
| 行情接入 | `v4/data.py`, `v4/market_contracts.py`, `v4/market_gateway.py` | 新浪/东财行情、版本化点时契约 | P1离线通过：唯一网关与MarketSnapshotV1不可变存储 | 真实覆盖率、延迟与盘口验收 |
| 市场状态 | `v4/market.py`, `v4/market_contracts.py` | 宽度、成交额、风险模式 | P1离线通过：MarketStateV1具备快照血缘和稳定身份 | 真实窗口市场状态核对 |
| 上下文与特征 | `v4/feature_store.py`, `phase1/overnight/` | 点时特征、严格归档 | 研究锁定 | P1/P6 |
| 候选选择 | `v4/selection.py` | 早盘基础分、尾盘固定确认增量 | P2离线通过：只由生产作业生成并写最终实体 | 真实母池与确认子集验收 |
| 决策门禁 | `v4/runtime.py`, `v4/paper_policy.py` | 生产门禁与无偏paper完整性政策 | P2离线通过：消费者只投影最终决策 | 真实阻断原因与窗口验收 |
| 候选日志 | `v4/candidate_journal.py`, `v4/decision_contracts.py` | 不可变早盘母池与最终确认决策 | P2离线通过：唯一事实源、完整血缘、冻结输入回放 | 真实同ID链路验收 |
| 模拟账户 | `v4/p3_contracts.py`, `v4/p3_account.py`；旧生产实现`v4/sim_engine.py` | 订单意图、成交、往返、现金、持仓与费用 | P3第一离线检查点通过：不可变实体和隔离事件账本；禁止生产接入 | 部分失败、节假日顺延和完整对账回放 |
| 流程编排 | `v4/simulation.py` | 抓取、筛选、买卖 | 职责过重 | P2/P3拆分 |
| 调度器 | `v4/paper_scheduler.py` | 买卖定时与回执 | 依赖看板常驻 | P4 |
| 推送 | `v4/push.py`, `v4/scripts/` | 两次必要推送 | 可运行 | P4 |
| 看板 | `v4/dashboard.py` | 8898控制台 | 可运行，单文件过大 | P5拆分 |
| 研究评估 | `phase1/overnight/` | 数据集、WF、压力测试 | 样本不足 | P6 |
| 模型注册 | `v4/model_registry.py` | 发布清单、推理 | 未发布 | P7 |

## 统一业务实体（P2离线契约已验收，真实窗口待验）

- `MorningPool`: 交易日、候选、全市场状态、输入快照、排序版本；
- `ConfirmationDecision`: 母池成员、确认排序、买/空仓/阻断、原因码；
- `PaperOrderIntent`: 决策ID、参考价、预算、股数、幂等键；
- `PaperFill`: 成交价、费用、时间、行情来源；
- `PaperRoundTrip`: 买卖配对、净收益、持有交易日；
- `TaskReceipt`: 任务、计划时间、开始/结束、结果、重试次数。

实体一旦落盘不可就地改写；派生视图可以重建。

候选业务事实只允许存在于 `candidate_journal`。`dashboard_state.json` 不得承载候选或决策业务语义；`runtime_state.json` 只允许保存可删除、可重建的诊断数据。任何消费者不得以当前时钟、缓存行情或自适应策略重新解释已经落盘的最终实体。
