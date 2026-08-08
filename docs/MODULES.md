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
| 模拟账户 | `v4/p3_contracts.py`, `v4/p3_account.py`, `v4/p3_execution.py`；旧生产实现`v4/sim_engine.py` | 订单意图、成交、往返、现金、持仓与费用 | P3离线核心终审通过：订单日志、事件链、防删除重排、T+1、失败隔离、故障恢复和对账；阶段仍未完成且禁止生产接入 | 等待P1/P2真实窗口门禁，继续非阻塞压力测试 |
| 流程编排 | `v4/simulation.py` | 抓取、筛选、买卖 | 职责过重 | P2/P3拆分 |
| 调度器 | `v4/p4_contracts.py`, `v4/p4_journal.py`, `v4/p4_orchestrator.py`, `v4/p4_deployment.py`, `v4/p4_runtime.py`；旧生产实现`v4/paper_scheduler.py` | DAG、不可变回执、幂等、子进程超时、多日补偿、崩溃恢复、SLA、持久化心跳、告警和部署审计 | P4计划内10项离线优化通过；生产仍依赖看板且未改接 | 等待真实窗口和生产接入授权 |
| 推送 | `v4/p4_projection.py`与离线`FakeNotificationAdapter`；生产`v4/push.py`, `v4/scripts/` | 冻结实体通知投影、payload/请求/回执哈希绑定及明确传输结果 | 完整血缘、接受/拒绝/超时/重试和不确定结果门禁通过；真实PushPlus未调用 | 等待真实回执验证与原子切换授权 |
| 看板 | P5离线`v4/p5_read_model.py`, `v4/p5_sources.py`, `v4/p5_dashboard.py`；现有生产`v4/dashboard.py` | 唯一只读读模型、当日链路、账户、证据、市场、任务、来源哈希和降级状态 | P5全部可离线部分通过：真实文件零写入适配、故障场景、资金流、往返、权益/回撤及桌面/移动验收；8898未改接 | 等待真实实体观测和单独原子切换授权 |
| 研究评估 | `phase1/overnight/`, `v4/p6_research_audit.py` | 数据集、WF、压力测试、严格审计 | 离线门禁完整；真实严格样本不足 | 积累样本后运行全市场WF/压力验收 |
| 模型注册 | `v4/model_registry.py`, `v4/p7_release_audit.py` | 发布清单、推理、报告血缘终审 | 离线发布包审计通过；模型未发布 | 仅在P6全部门禁通过后发布 |
| 备份恢复 | `v4/p8_backup.py` | 内容寻址备份、损坏检测、隔离恢复 | 离线灾备契约通过；未操作生产数据或历史资产 | 获授权后进行真实数据演练与历史归档 |

## 统一业务实体（P2离线契约已验收，真实窗口待验）

- `MorningPool`: 交易日、候选、全市场状态、输入快照、排序版本；
- `ConfirmationDecision`: 母池成员、确认排序、买/空仓/阻断、原因码；
- `PaperOrderIntent`: 决策ID、参考价、预算、股数、幂等键；
- `PaperFill`: 成交价、费用、时间、行情来源；
- `PaperRoundTrip`: 买卖配对、净收益、持有交易日；
- `TaskReceipt`: 任务、计划时间、开始/结束、结果、重试次数。

实体一旦落盘不可就地改写；派生视图可以重建。

候选业务事实只允许存在于 `candidate_journal`。`dashboard_state.json` 不得承载候选或决策业务语义；`runtime_state.json` 只允许保存可删除、可重建的诊断数据。任何消费者不得以当前时钟、缓存行情或自适应策略重新解释已经落盘的最终实体。
