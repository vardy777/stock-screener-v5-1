# P1离线验收报告

验收日期：2026-08-08

结论：离线工程验收通过；真实09:25、14:49、14:50和次日09:30窗口仍待交易日验证，不能据此完成P1整体实盘验收。

已验证：

- 行情提供方只能通过 `MarketDataGateway` 进入V4核心；AST门禁禁止其他模块访问 `DataFetcher` 或 `batch_fetch_quotes`。
- `market`、`selection`、`runtime` 只接受版本化 `MarketSnapshotV1`。
- MarketSnapshotV1采用内容寻址不可变存储，读取时校验schema、内容哈希、文件名、覆盖率和代码计数。
- MarketStateV1携带snapshot_id和market_state_id。
- naive datetime输入不自动补时区；V4禁止无时区 `datetime.now()`、隐式本地 `astimezone()`和时区注入。
- 严格快照与paper-only证据 cohort 分区。
- 全量自动测试142项通过。

待真实窗口验证：09:25、14:49、14:50、次日09:30的提供方时间、覆盖率、批次时长、盘口和落盘链路。
