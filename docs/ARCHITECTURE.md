# V5 系统架构

## 产品边界

V5是本机独立运行的A股隔夜研究与严格模拟系统。外部依赖仅包括东方财富市场目录、新浪/腾讯实时行情、PushPlus、Windows任务计划程序和NTP。系统不连接券商并保持 `research_locked`。

## 唯一生产数据流

```text
08:30 交易日历/因果时钟/股票池/传输预检
  → 09:25:05 双源MarketSnapshotV1
  → MarketStateV1 + CandidateFunnelV1 + MorningPoolV5
  → 09:25:50 V5早盘PushPlus
  → 09:30:10 到期持仓严格模拟卖出
  → 14:49 双源快照与冻结指针
  → 14:50 ConfirmationV5（只能是同日母池子集）
  → 14:50:30 V5尾盘PushPlus
  → 14:50:40 Top1本地模拟买入
  → 14:53健康检查 → 15:10维护 → 15:20全日验收
```

## 所有权

| 职责 | 唯一所有者 | 权威入口/事实 |
|---|---|---|
| 股票池 | V5 | `v5.universe_refresh` / `v5/data/universes` |
| 实时行情 | V5 | `SinaRealtimeSource` + `TencentRealtimeSource` |
| 候选与决策 | V5 | `v5.task_runner` / V5不可变实体 |
| 通知 | V5 | `v5.notification` / 200-ACCEPTED回执 |
| 模拟账户 | V5 | `v5.paper`事件链，单写者 |
| 调度 | V5 | 11项循环Windows任务 |
| 看板 | V5 | 8899只读投影 |

所有兼容CLI必须委托 `v5.task_runner` 或 `v5.preflight`，不得绕过任务窗口、依赖、时钟或日历门禁。

## 时间与质量模型

- `exchange_time`：单只股票最后行情时间，用于逐标的120秒陈旧过滤。
- `provider_time`：该批响应的接收时间，用于全市场批次新鲜度。
- `batch_started_at/batch_completed_at`：全市场采集耗时和实体因果边界。
- 单只冷门股不会拖垮全市场，但陈旧股票不能进入候选。
- 双源必须各自覆盖≥95%，共同匹配和一致比例均≥95%；不合并两个残缺源凑覆盖。

## 执行与证据隔离

- 模拟买入仅使用14:49冻结卖一、盘口深度、滑点、费用、100股整手和总资金三分之一上限。
- 模拟卖出仅使用下一交易日09:30后的新双源买一，并遵守T+1。
- 严格往返、可比Top1基线和非严格恢复观察分开保存。
- 看板只读取实体，不抓行情、不选股、不推送、不写账本。
- `research_locked`、禁止券商订单和禁止历史严格补写是不可绕过的硬边界。
