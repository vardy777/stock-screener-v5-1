# P4 隔离离线开发验收

更新：2026-08-08。P4仅获准隔离离线开发；P1/P2真实窗口仍待验，P3/P4生产接入均冻结。

## 强制边界

- 不注册、修改或启用Windows任务；
- 不调用现有`paper_scheduler.py`、`SimulationEngine`、真实推送脚本或P3成交链路；
- 不读取PushPlus token，不发出网络请求；
- 所有状态写入测试提供的临时目录；
- 不标记P4阶段完成；P1/P2真实窗口失败时立即暂停并优先修复。

## 第一检查点（已通过）

| 能力 | 离线验收事实 |
|---|---|
| 任务契约 | `TaskSpecV1`冻结窗口、SLA、最大尝试和补偿政策 |
| 不可变回执 | `TaskReceiptV1`携带稳定run ID、尝试、状态、原因码、计划与记录时间、内容哈希 |
| 状态机 | STARTED后才允许终态；成功后禁止再次执行；重复终态和非法迁移fail-closed |
| 审计日志 | 有序事件链、跨进程锁、原子提交、内容篡改检测 |
| 两次推送 | 默认只编排09:25 morning和14:50 confirmation，不包含P3 paper任务 |
| 重试 | 失败、超时最多3次；成功后跨重启幂等 |
| 补偿与SLA | 原窗口漏跑但SLA前允许补偿；SLA后形成不可变漏跑事件和告警投影 |
| 并发 | 两进程同时触发同一任务只形成一条STARTED→SUCCEEDED运行链 |
| 心跳 | 只读心跳报告ALIVE、离线标识、回执数量和最后回执ID |
| 推送隔离 | `FakeNotificationAdapter`覆盖接受、拒绝、超时，不访问网络或真实token |
| 架构隔离 | 现有调度、推送和脚本入口不导入P4模块；P4不导入生产推送、模拟账户或看板 |

P4专项20项、全量自动测试206项通过。

## 第二检查点（已通过）

- 生成只读Windows通知任务清单，固定09:25与14:50:20；`apply_allowed=false`；
- 静态审计现有注册与runner脚本：Limited权限、项目venv、隐藏进程、决策先于通知、与dashboard进程解耦；不执行注册；
- 多交易日扫描对过期通知只写`SLA_MISSED`，绝不补发旧选股；只有规格显式授权的审计任务可历史补偿；
- 原子日志权限/写入故障保留原状态；进程终止在STARTED后，重启识别为中断尝试并从下一attempt继续；
- 心跳超时为CRITICAL、SLA漏跑为ERROR、失败/超时为WARNING，输出稳定原因码；
- `FrozenNotificationProjector`只接受`MorningPoolV1`和`ConfirmationDecisionV1`，通知负载强制携带母池/决策ID、快照ID、市场状态ID、排序版本和候选子集；
- 生产脚本仍未导入P4，真实PushPlus、Windows注册和P3生产链路仍未调用。

## 后续离线工作

用户要求的10项离线优化已全部纳入第三检查点。生产任务解耦、真实PushPlus回执和实际Windows调度验证仍未授权。

## 第三检查点（10项优化全部通过）

1. 完整任务DAG覆盖早盘决策→推送、14:49冻结→确认决策→推送，以及保持禁用的paper/健康/维护节点；依赖失败时下游不执行。
2. `ControlledSubprocessExecutor`使用显式argv和`shell=False`，记录退出码与输出哈希；超时强制终止并验证不会后台补写。
3. 进程崩溃矩阵覆盖STARTED前、STARTED后、外部成功但回执前、SUCCEEDED后；不确定外部结果进入`OUTCOME_UNKNOWN`，人工/外部证据确认前禁止重试。
4. 冻结实体payload哈希、稳定传输请求ID与`TaskReceipt`自动绑定并逐字段一致。
5. 心跳持久化到独立监控存储；隔离守护进程在看板不存在时可执行、重启恢复并继续写心跳。
6. 告警具有稳定ID、去重、出现次数、自动升级和RECOVERED生命周期；连续3次失败自动升级ERROR。
7. 60个交易日、120条漏跑事件重复扫描幂等；过期通知零发送。
8. 并发竞争被投影为NOOP/CONTENDED语义，不形成重复成功链或上层系统故障。
9. 完整9节点Windows部署清单全部`enabled=false`、`apply_allowed=false`，携带依赖、工作目录、Limited权限和离线门禁。
10. `OfflineDaemonHarness`完成独立进程一次运行、持久化心跳、重启恢复和成功任务去重。

以上只代表P4计划内离线工程验收通过；在真实窗口和生产授权前，P4仍不得标记整体完成或连接现有生产入口。
