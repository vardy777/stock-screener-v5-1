# A股隔夜交易系统 V4

## 当前生产入口（2026-08-09）

- P3：`v4/p3_production.py`，只接受最终 P2 决策和 `MarketSnapshotV1`，写入 `v4/data/p3`。
- P4：九个 Windows 任务统一调用 `v4/scripts/p4_task_adapter.py`，最终输出写入 `v4/data/p4/outputs`。
- P5：`python -m v4.p5_dashboard --port 8898 --data-dir v4/data`，仅允许 GET，POST 返回 405。
- 旧定时任务已禁用并保留为回滚资源；`research_locked` 和模型发布门禁保持不变。

## P2 decision publication boundary

Decision production and notification projection are separate. The preserved
Windows push runner invokes `v4/scripts/decision_job.py` before invoking the
morning or confirmation push consumer. Dashboard, push and paper execution
read immutable entities from `candidate_journal`; they do not regenerate or
reinterpret candidates.

Offline replay starts from repository-validated immutable snapshots through
`v4.snapshot_replay.replay_frozen_chain`. Freshness and window checks use each
snapshot's capture time, and replay does not overwrite live market/runtime
caches. Replay also requires a content-addressed `FeatureContextV1`; mutable
live context and feature-store files are never replay inputs.

V4 是一套可在本机独立运行的研究与模拟系统。Codex、Hermes 或其他 AI Agent 只参与开发，均不属于运行依赖。行情、候选、账户、推送、看板和本地调度的实体实现全部位于 `v4/`；V4 代码禁止导入 `v3.*`。

## 当前架构边界

- `v4/selection.py`：对完整合格 A 股池生成 V4 候选。研究锁定时使用固定、透明、无未来数据的因果基线排序；生产模型发布后，在 14:50 自动切换为模型排序。
- `v4/market.py`：生成全市场状态、宽度、成交额、情绪和展示用板块观测。
- `v4/runtime.py`：统一候选来源校验、模型阈值、市场风险、Top1、行情时效、交易时钟和研究准入门禁。
- `v4/candidate_journal.py`：按交易日原子保存09:25母池与14:50确认链路，尾盘候选必须是早盘推荐的子集。
- `v4/paper_scheduler.py`：由8898本地服务托管研究模拟买卖调度，并写入每日幂等回执。
- `v4/feature_store.py`：接收 14:49 冻结特征，禁止使用未来或过期特征。
- `v4/model_registry.py`：只加载经过严格准入并原子发布的生产模型。
- `v4/snapshots.py`：保存真实 14:50 买一价和次日 09:30 卖一价及一档挂单量。
- `v4/readiness.py`：检查严格样本、Walk-Forward、压力测试、模型发布和数据血缘。
- `v4/data.py`：V4 独立行情接入。
- `v4/sim_engine.py` 与 `v4/simulation.py`：V4 独立账户、仓位、买卖与状态编排。
- `v4/push.py`：V4 独立 PushPlus 传输和卡片。
- `v4/dashboard.py`：独立 8898 HTTP 看板，直接使用 `python -m v4.dashboard` 启动。

## 两次必要推送

- 09:25：V4 使用当日新鲜行情与上一交易日冻结上下文生成早盘观察池。它不是买入指令。
- 14:50–14:51:59：V4 重新抓取行情，只在当日09:25母池内重排并且只接受 14:49 冻结特征。缺少母池或任一数据/风险门禁失败时，明确空仓。
- 若14:49全市场严格特征未达95%，该数据仍禁止进入训练集；研究模拟可仅对早盘母池使用14:50当时行情与上一交易日冻结上下文进行因果确认，并标记为 `paper_only`，不会解锁生产交易。
- 14:50:40：符合条件的链路确认 Top1 写入 V4 独立研究模拟账户；次个交易日09:30:20后使用新鲜连续竞价行情平仓。不会发送券商委托。

生产运行入口为：

```text
v4/scripts/morning_push.py
v4/scripts/afternoon_push.py
v4/scripts/paper_trade.py
python -m v4.dashboard
```

PushPlus Token 只保存在被 Git 忽略的 `v4/.env`，不得提交到仓库。

## 研究准入状态

系统当前必须保持 `research_locked`。截至 2026-08-02：

- 严格 14:50/次日 09:30 配对样本为 0，最低要求为 500；
- 历史 15:00 代理数据不能代替真实 14:50 决策数据；
- 代理 Walk-Forward 只有 56 笔且窗口稳定性不足；
- 因此不得声明或保证盈利，也不得发布生产模型或开放实盘买入。只允许与生产门禁分离的研究模拟观测。

研究锁定只限制生产执行。看板中的 V4 研究分是横截面排序分，不是胜率、盈利概率或模型预测。

## 模型发布顺序

只有严格数据达到要求后，才依次运行：

```powershell
.\.venv\Scripts\python.exe phase1\scripts\build_overnight_dataset.py
.\.venv\Scripts\python.exe phase1\scripts\walk_forward.py --dataset-mode strict
.\.venv\Scripts\python.exe phase1\scripts\walk_forward.py --dataset-mode strict --stress
.\.venv\Scripts\python.exe phase1\scripts\train_model.py --dataset-mode strict
```

生产训练只能读取 `strict_dataset.csv.gz`。普通 Walk-Forward、压力测试、窗口策略、严格数据集和最终模型的哈希血缘必须一致；诊断产物永远不能写入生产发布清单。只有有效的 `published_model.json` 原子发布后，V4 才会在 14:50 使用模型对完整合格股票池排序 Top1。

## 看板语义

P5 保留 `http://localhost:8898/`，并按使用者任务拆分为三个只读视图：

- `/?view=beginner`：默认新手首页，先回答当前阶段、数据是否可信、现在怎么做；
- `/?view=research`：候选链路、模拟账户、严格证据和四窗口验收；
- `/?view=ops`：告警、心跳、P4 任务、实体 ID 与来源哈希。

历史候选不会伪装成今日候选；过期或覆盖不足的行情不会输出方向性市场情绪；候选评分只是同截面排序分，不是上涨概率。

`http://localhost:8898/?mode=chase` 保留原地址，但 `chase` 只表示 V4 自动总览视图，不代表强制追高策略；`mode=pullback` 只是查看 V4 回撤修复候选的展示过滤器，不控制执行。

看板严格隔离 V4 严格前向样本、V4 独立研究模拟账户与15:00代理 Walk-Forward。只有第一类证据可以决定生产准入。
