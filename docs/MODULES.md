# V5 模块清单

| 模块 | 职责 | 当前状态 | 尚待真实验收 |
|---|---|---|---|
| `calendar.py`, `clock_gate.py`, `preflight.py` | 交易日、NTP、股票池和传输准备 | 已接循环生产 | 完整交易日08:30 |
| `universe_refresh.py`, `universe.py` | 5215量级沪深A股独立股票池 | 真实数据通过 | 连续稳定性 |
| `sina_source.py`, `tencent_source.py` | 独立全市场报价 | 2026-08-21严格14:49覆盖99.808%、一致99.770%通过 | 连续09:25与14:49 |
| `market_snapshot.py`, `data_production.py` | 版本化快照、覆盖/时效/价格共识 | 严格14:49真实窗口通过 | 09:25窗口与连续稳定性 |
| `market_state.py`, `funnel.py` | 市场风险、逐标的过滤、可解释排名 | 工程完成 | 因子与阈值效果 |
| `decision_flow.py`, `jobs.py` | 母池、冻结、确认和血缘 | 工程完成 | 同日完整母池→确认 |
| `notification.py`, `alerts.py` | V5业务推送和故障告警 | 8月18日早盘200/ACCEPTED | 同日两次成功 |
| `paper.py`, `paper_production.py` | V5唯一模拟账本、费用、T+1和恢复 | 已切换单写者；375测试通过 | 首次买入和次日卖出 |
| `task_runner.py`, 循环任务 | 11任务窗口、依赖、失败传播和重试 | 静态生产审计通过 | 完整交易日无漏跑 |
| `performance.py`, `live_acceptance.py` | 往返绩效、基线和日验收 | 工程完成 | 严格往返样本 |
| `proxy_backtest.py` | 小时级历史代理、无泄漏母池/确认/Top1基线研究 | 20日代理完成，结果负面且非严格证据 | 仅用于诊断，不进入准入样本 |
| `challenger_context.py`, `challenger.py` | 因果5/10日量价上下文、同快照挑战者母池/确认、独立影子账本 | 2026-08-24上下文覆盖98.10%、独立参考匹配98.83%；离线隔离验收通过 | 09:25/14:49/14:50/次日09:30完整窗口 |
| `sources.py`, `product_read_model.py`, `dashboard.py` | 8899只读产品看板 | HTTP 200、V5-only | 当日完整事实视觉验收 |
| `independence_audit.py` | 禁止V4/phase1运行依赖 | 全部通过 | 持续回归 |

## 当前未完成事实

- 尚无一个完整V5严格交易日。
- 尚无严格完整模拟往返，无法评价胜率或盈利能力。
- 今天错过的09:25不能补写；13:01恢复观察不属于策略样本。
- 公共行情源没有商业SLA；任何覆盖、时效或一致性失败都必须空仓。
- 规则因子权重、流动性阈值和市场状态阈值仍需严格样本与基线比较验证。
