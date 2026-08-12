# A 股隔夜研究与模拟系统 V4

V4 可在本机独立运行，不依赖 Hermes、Codex、ChatGPT 或 V3。当前为 `research_locked` 的研究工程 Beta，不连接券商，也不保证盈利。

## 每日生产流程

| 时间 | P4 任务 | 结果 |
|---|---|---|
| 09:25:00 | `morning_decision` | 全市场 V4 观察母池 |
| 09:25:20 | `morning_push` | 必需 PushPlus 通知 |
| 09:30:20 | `paper_sell` | 到期持仓卖出或空批次 |
| 14:49:00 | `feature_freeze` | 严格因果特征 |
| 14:50:20 | `confirmation_decision` | 母池内最终决策 |
| 14:50:30 | `confirmation_push` | 必需 PushPlus 通知 |
| 14:50:40 | `paper_buy` | 本地模拟买入或空批次 |
| 14:53:00 | `health_check` | 当日捕获健康 |
| 15:10:00 | `maintenance` | 次日上下文与标签维护 |

P2 观察快照不因单只封板/停牌而整批失败；每只股票独立阻断。P3 只对最终合格 Top1 创建要求卖一和挂单量的严格成交快照。

## 看板

```powershell
\.venv\Scripts\python.exe -X utf8 -m v4.p5_dashboard --port 8898 --data-dir v4/data
```

- `/?view=beginner`：当前阶段和行动建议。
- `/?view=research`：候选、账户和证据。
- `/?view=ops`：任务、通知、时钟、实体与告警。
- `/?mode=chase`：兼容地址，只是自动总览，不强制追涨策略。

看板只允许 GET；不会抓行情、选股、推送或交易。

## 研究准入

严格样本最低 500 笔，并要求：无代理交易、完整盘口与流动性、交易日历和逐日股票池审计、胜率 95% 下限高于 50%、PF≥1.20、盈利窗口≥70%、最大回撤≤12%、双倍滑点压力仍盈利、数据/报告/模型哈希一致。当前严格配对样本为 0，模型未发布。

规则分只是因果横截面排序，不是胜率或上涨概率。过热与流动性阈值属于冻结风险控制，必须依靠未来严格样本评估，禁止根据少量结果反复调参。

## 验收

```powershell
\.venv\Scripts\python.exe -m pytest -q
\.venv\Scripts\python.exe scripts\offline_acceptance.py --run-tests
\.venv\Scripts\python.exe scripts\daily_operations_acceptance.py --trade-date YYYY-MM-DD
```
