# V4 真实窗口审计（2026-08-13）

结论：**当天生产闭环未通过，继续保持 `research_locked`。** 不得把本报告解释为策略有效、可盈利或模型准入。

## 已取得的不可变事实

- 09:25 `morning_decision` 成功；行情新鲜覆盖率仅 78.77%，低于 95% 硬门槛，因此母池为空。
- 09:25 PushPlus 为真实 HTTP 200 / ACCEPTED，通知 ID `notification1-be376e19362e585f661d8967`。
- 09:30 `paper_sell` 成功；账户无持仓、无成交。
- 14:49 `feature_freeze` 成功，实体 `fc1-5dd4f6ec321c19d0bf52830552dd4b7acf2322721540a4b035aeb36f271d708f`。
- 14:50 `confirmation_decision`、PushPlus 和 `paper_buy` 均按时返回成功；确认池为空、无模拟买入。
- 14:50 PushPlus 为真实 HTTP 200 / ACCEPTED，通知 ID `notification1-4578261e836306613e855f7c`。
- 14:53 `health_check` 成功。
- Windows Time 正常，阿里云 NTP 三次测量最大绝对偏差 0.2142152 秒。
- 九项生产任务静态审计通过，旧任务保持 Disabled，看板只读且受任务监督。

## 阻断项

1. `confirmation_decision` 的不可变任务输出未携带14:49 `FeatureContextV1` 输入 ID，任务输出链审计失败。根因是空早盘母池路径沿用了早盘 lineage。代码已修复：下一交易日无论母池是否为空，确认决策都必须加载当日 `FeatureContextV1` 并写入 `feature_context_id`；缺失或日期不符将失败关闭。历史实体未回写。
2. 15:10 `maintenance` 的 Task Scheduler 结果为 `0x41306`（任务被终止），未生成维护或进程工件。18:26人工诊断已超过16:30业务窗口，运行器正确生成 `OUTSIDE_TASK_WINDOW` 阻断证据，没有补造维护成功。该项必须在下一真实15:10窗口复验。
3. 严格14:50/次日09:30完整样本仍为0，P3模拟账户没有有效完整往返，策略有效性没有得到证明。

## 验证

- `daily_operations_acceptance`：FAIL（维护缺失、确认到特征输入血缘缺失）。
- P5/P2/P4相关回归：38项通过。
- 全量测试：245项通过，0项失败。
- 生产任务静态审计：PASS。

## 下一步

- 下一交易日09:25验证重试后的全市场新鲜覆盖率是否达到95%。
- 下一交易日14:49/14:50验证确认实体与任务输出均绑定同日 `FeatureContextV1`。
- 下一交易日15:10监测维护进程工件、退出码和最终 `MaintenanceReportV1`。
- 继续自然积累严格14:50/次日09:30样本；不得降低门槛、补写历史或解除 `research_locked`。
