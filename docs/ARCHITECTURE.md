# 系统架构

## 边界

V4 是一个本地单机系统。外部依赖只有行情网络接口、PushPlus 和 Windows
Task Scheduler；AI Agent 不属于运行时。`v3/`、`v2/` 和根目录旧脚本是历史
资产，不得被 `v4/` 导入。

## 目标分层（P1/P2重构边界）

```text
唯一行情网关
  ↓
MarketSnapshotV1（唯一核心行情输入）
  ↓
MarketStateV1（携带快照血缘的市场状态）
  ↓
09:25 母池生成 ───────→ PushPlus早盘观察
  ↓ candidate journal（候选/决策唯一事实源）
14:49 严格特征冻结
  ↓
14:50 母池内确认 ─────→ PushPlus尾盘确认
  ↓ decision record
14:50:40 研究模拟买入
  ↓ paper account
次交易日09:30:20 模拟卖出
  ↓
逐笔交易、资金曲线、胜率与证据面板
```

## 核心状态机

```text
WAITING_MORNING
  → MORNING_POOL_RECORDED
  → CONFIRMATION_RECORDED
  → PAPER_BUY_FILLED | PAPER_EMPTY | PAPER_BLOCKED
  → PAPER_SELL_FILLED | PAPER_SELL_RETRY
  → SETTLED
```

每个状态必须具有交易日、生成时间、输入快照标识、市场状态标识、排序版本、策略/政策版本、原因码和幂等键。看板、推送和执行必须读取同一份最终决策记录，只能做展示或传输投影，不能使用当前时钟、行情缓存或策略重新推导门禁。

## 三类证据

| 证据 | 用途 | 能否解锁生产 |
|---|---|---|
| 严格14:50/次日09:30配对样本 | 模型训练、Walk-Forward、压力测试 | 可以，但须满足全部门槛 |
| V4研究模拟账户 | 验证自动链路和策略行为 | 不可以 |
| 15:00代理历史回测 | 诊断和提出假设 | 不可以 |

## 当前已知架构债务（阻断P3）

1. 核心选择、市场、运行和模拟流程仍能直接接收松散 DataFrame/字典行情，唯一行情网关尚未建立；
2. 时间新鲜度路径仍可能为 naive datetime 自动补上海时区，无法证明时间语义；
3. 市场状态仍是无版本、无稳定标识的派生字典；
4. 候选事实同时散落在 candidate journal、dashboard/runtime JSON、模拟器内存和候选缓存文件；
5. 看板仍会使用当前时钟、市场缓存与策略现场重算已落盘决策的可交易性；
6. 最终实体尚未强制包含输入快照、排序、策略/政策和市场状态的完整血缘；
7. 现有回放起点是候选字典，不是冻结的 MarketSnapshotV1；
8. 独立调度、历史代码归档等后续债务属于 P4/P8，不能用来绕过当前 P1/P2 验收。

这些债务按路线图处理，禁止通过降低生产门禁临时规避。
