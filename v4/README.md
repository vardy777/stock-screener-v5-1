# V4隔夜系统

V4采用本地兼容迁移：命令名、推送入口和8898看板地址保持不变，所有任务由
Windows Task Scheduler调用项目`.venv`；现有V3入口在内部调用V4准入、候选
解释和执行时间控制。运行时不需要Codex、Hermes或其他AI Agent常驻。

当前状态为 `research_locked`。在全市场真实14:50/09:30数据、样本外准入、
加倍滑点压力测试和生产模型发布全部通过之前，V4只输出观察候选，不产生
可执行买入决定。

主要模块：

- `readiness.py`：数据、样本、压力测试和模型发布准入；
- `runtime.py`：候选解释、市场环境和V3兼容适配；
- `model_registry.py`：只加载通过准入的生产模型并验证实时特征完整性；
- `feature_store.py`：实时特征发布与新鲜度契约；
- `snapshots.py`：自动积累带买一/卖一和一档挂单量的真实执行时点快照；
- `calendar.py`：读取带官方来源和核验时间的本地交易日历；
- `execution.py`：14:49信号、14:50买入、09:30卖出窗口和行情新鲜度；
- `audit.py`：供看板读取的原子运行状态快照。

严格研究样本必须同时包含14:49冻结的完整特征、14:50新鲜非模拟卖一价、
下一开放交易日09:30后的新鲜非模拟买一价、一档挂单量覆盖、成交量单位为股、
全市场至少95%覆盖、成本与涨跌停可成交性验证。行情时间必须早于采集时间且
最多相差30秒；每个快照及其manifest均原子发布，09:36与14:53独立巡检，
15:10自动准备下一开放交易日上下文并重建标签。
任一环节缺失都会继续保持`research_locked`。现有V3命令和PushPlus传输链路
不改名；09:25推送早盘观察池，14:50:20重新计算并推送尾盘确认，严格快照
使用独立任务积累。两条推送都不执行自动买入。

截至2026-08-02，严格14:50/09:30配对样本仍为0。历史15:00代理的Top1
Walk-Forward只有56笔、7个窗口仅2个盈利，未满足样本量、胜率置信下限、
窗口一致性和严格执行合同；因此系统不得声明盈利，也不得开放模拟交易。

## 独立运行与两个必要推送

系统引擎、特征计算、机器学习训练、看板和PushPlus均在本项目及`.venv`中
独立运行。Codex/Hermes只用于开发，不属于任何生产调用链。两个必要入口仍为：

- `v3/scripts/morning_push.py`：仅在开放交易日09:20–09:29运行，09:25输出
  观察池和09:30待卖提醒；
- `v3/scripts/afternoon_push.py`：仅在14:50–14:51:59运行，重新抓取全市场
  行情并输出尾盘Top1确认；研究门禁未通过时明确空仓。

PushPlus请求最多重试3次，按“推送类型+交易日”记录成功回执，任务重复启动
不会重复发送。严格快照巡检失败会发送独立告警，但不会补造或回填严格样本。
推送卡片显示全市场覆盖率、行情时间、模型预期净收益、盈利概率、大亏概率和
阻断原因。Token只保存在`v3/.env`，不得提交到版本库。

## 严格数据、回测与发布顺序

历史15:00代理数据与真实严格数据分别保存；任何生产训练只能读取
`strict_dataset.csv.gz`。禁止调用旧的无标签重建路径。准入顺序固定为：

```powershell
.\.venv\Scripts\python.exe phase1\scripts\build_overnight_dataset.py
.\.venv\Scripts\python.exe phase1\scripts\walk_forward.py --dataset-mode strict
.\.venv\Scripts\python.exe phase1\scripts\walk_forward.py --dataset-mode strict --stress
.\.venv\Scripts\python.exe phase1\scripts\train_model.py --dataset-mode strict
```

压力测试必须逐窗口冻结普通Walk-Forward的原策略，且报告、窗口策略、严格
数据集和最终模型的SHA256血缘必须完全一致。最终模型保留尾部独立验证期和
最新日期embargo；`--force`只能在`model/diagnostic`生成`research_only`
诊断产物，永远不能写生产发布清单。只有`published_model.json`最后原子发布后，
运行时才会用已发布模型对完整合格A股股票池向量化排序Top1。

## 本机安装与定时任务

锁定依赖位于`phase1/requirements-lock.txt`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r phase1\requirements-lock.txt
```

任务注册脚本保留所有既有任务名，并使用S4U、`StartWhenAvailable`和严格时间
窗保护。覆盖现有任务需要管理员PowerShell（普通终端会得到Access denied）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File phase1\scripts\register_v4_snapshot_tasks.ps1
```

迟到启动的09:25/14:50任务会拒绝推送，迟到的严格采集也会拒绝写样本。
看板GET请求只读本地缓存，不会触发行情抓取、重新选股或污染确认快照。
