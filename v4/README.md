# A股隔夜交易系统 V4

V4 是一套可在本机独立运行的研究与模拟系统。Codex、Hermes 或其他 AI Agent 只参与开发，均不属于运行依赖。Windows 定时任务仍调用旧名称的 `v3/` 脚本和 `main.py` 命令，以保持现有任务、8898 看板地址和 PushPlus 传输链兼容；这些旧路径现在只是外壳，不再拥有候选生成或当前市场分析逻辑。

## 当前架构边界

- `v4/selection.py`：对完整合格 A 股池生成 V4 候选。研究锁定时使用固定、透明、无未来数据的因果基线排序；生产模型发布后，在 14:50 自动切换为模型排序。
- `v4/market.py`：生成全市场状态、宽度、成交额、情绪和展示用板块观测。
- `v4/runtime.py`：统一候选来源校验、模型阈值、市场风险、Top1、行情时效、交易时钟和研究准入门禁。
- `v4/feature_store.py`：接收 14:49 冻结特征，禁止使用未来或过期特征。
- `v4/model_registry.py`：只加载经过严格准入并原子发布的生产模型。
- `v4/snapshots.py`：保存真实 14:50 买一价和次日 09:30 卖一价及一档挂单量。
- `v4/readiness.py`：检查严格样本、Walk-Forward、压力测试、模型发布和数据血缘。
- `v3/simulation.py`：兼容外壳；负责旧模拟账户 I/O、行情抓取适配和调用 V4，不再调用 V3 追高、回调、因子或评分器。
- `v3/dashboard.py`：兼容 8898 地址的展示外壳；当前候选、市场、情绪和板块数据均读取 V4 状态。旧模拟账户和旧交易记录只作为明确分离的迁移旁证。

## 两次必要推送

- 09:25：V4 使用当日新鲜行情与上一交易日冻结上下文生成早盘观察池。它不是买入指令。
- 14:50–14:51:59：V4 重新抓取全市场行情，只接受 14:49 冻结特征。冻结特征缺失、全市场覆盖不足或任一门禁失败时，明确推送空仓。

兼容入口仍为：

```text
v3/scripts/morning_push.py
v3/scripts/afternoon_push.py
main.py v3-morning
main.py v3-afternoon
main.py sim-buy
main.py sim-sell
main.py v3-dashboard
```

PushPlus Token 只保存在被 Git 忽略的 `v3/.env`，不得提交到仓库。

## 研究准入状态

系统当前必须保持 `research_locked`。截至 2026-08-02：

- 严格 14:50/次日 09:30 配对样本为 0，最低要求为 500；
- 历史 15:00 代理数据不能代替真实 14:50 决策数据；
- 代理 Walk-Forward 只有 56 笔且窗口稳定性不足；
- 因此不得声明或保证盈利，也不得发布生产模型或开放模拟买入。

研究锁定只限制执行，不再把候选生成退回 V3。看板中的 V4 研究分是横截面排序分，不是胜率、盈利概率或模型预测。

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

`http://localhost:8898/?mode=chase` 保留原地址，但 `chase` 只表示 V4 自动总览视图，不代表强制追高策略；`mode=pullback` 只是查看 V4 回撤修复候选的展示过滤器，不控制执行。

看板严格隔离三类证据：V4 严格前向样本、旧模拟账户旁证、15:00 代理 Walk-Forward。只有第一类证据可以决定生产准入。
