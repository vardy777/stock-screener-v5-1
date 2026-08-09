# 模块清单与契约

> 运行现状（2026-08-09）：P3 已接管本地模拟账户，P4 九任务已注册并替代旧活动任务，P5 已接管 8898；旧实现仅作为禁用回滚资源保留。真实四窗口验证仍待完成，生产模型仍未发布。

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
| 模拟账户 | `v4/p3_contracts.py`, `v4/p3_account.py`, `v4/p3_execution.py`, `v4/p3_production.py` | 订单意图、成交、往返、现金、持仓与费用 | P3 已接管生产模拟账户；单写者、事件链、T+1、恢复和对账离线通过 | 真实14:50/次日09:30验收 |
| 决策生产 | `v4/decision_production.py`, `v4/scripts/decision_job.py` | 从版本化快照生成P2最终实体 | 已脱离账户与`SimulationEngine`兼容外壳 | 真实09:25/14:50验收 |
| 调度器 | `v4/production_task_runner.py`, `v4/scripts/p4_task_adapter.py` | 九任务DAG、不可变尝试、重试、心跳、实体投影 | P4 已接管生产调度；旧任务Disabled | 真实任务/SLA/恢复验收 |
| 推送 | `v4/push.py`, `v4/notification_contracts.py`, `v4/scripts/` | 冻结实体通知投影、负载/请求/响应哈希与父ID血缘 | 两个生产通知已接入P4；离线接受/拒绝/超时/重试通过 | 真实PushPlus送达回执验收 |
| 看板 | `v4/p5_read_model.py`, `v4/p5_sources.py`, `v4/p5_dashboard.py` | 唯一只读读模型、当日链路、账户、证据、市场、任务、来源哈希和降级状态 | P5 已接管 8898，并按每个 GET 请求读取最新实体；POST 固定 405 | 等待真实四窗口实体观测 |
| 研究评估 | `phase1/overnight/`, `v4/p6_research_audit.py` | 数据集、WF、压力测试、严格审计 | 离线门禁完整；真实严格样本不足 | 积累样本后运行全市场WF/压力验收 |
| 模型注册 | `v4/model_registry.py`, `v4/p7_release_audit.py` | 发布清单、推理、报告血缘终审 | 离线发布包审计通过；模型未发布 | 仅在P6全部门禁通过后发布 |
| 备份恢复 | `v4/p8_backup.py` | 内容寻址备份、损坏检测、隔离恢复 | 离线灾备契约通过；未操作生产数据或历史资产 | 获授权后进行真实数据演练与历史归档 |
| 切换准备 | `v4/live_window_acceptance.py`, `v4/cutover_readiness.py`, `v4/offline_rehearsal.py`, `v4/operations_preflight.py` | 四窗口证据、任务差异、单写者、切换/回滚、统一验收 | 全部只读或显式隔离输出，`apply_allowed=false` | 等待真实窗口填充证据 |

## 统一业务实体（P2离线契约已验收，真实窗口待验）

- `MorningPool`: 交易日、候选、全市场状态、输入快照、排序版本；
- `ConfirmationDecision`: 母池成员、确认排序、买/空仓/阻断、原因码；
- `PaperOrderIntent`: 决策ID、参考价、预算、股数、幂等键；
- `PaperFill`: 成交价、费用、时间、行情来源；
- `PaperRoundTrip`: 买卖配对、净收益、持有交易日；
- `TaskReceipt`: 任务、计划时间、开始/结束、结果、重试次数。

实体一旦落盘不可就地改写；派生视图可以重建。

候选业务事实只允许存在于 `candidate_journal`。`dashboard_state.json` 不得承载候选或决策业务语义；`runtime_state.json` 只允许保存可删除、可重建的诊断数据。任何消费者不得以当前时钟、缓存行情或自适应策略重新解释已经落盘的最终实体。
