# 本地运行手册

## 每次进入项目

```powershell
cd C:\Users\lisha\stock-screener
.\.venv\Scripts\python.exe scripts\project_status.py
```

先确认 `active_phase`、门禁、下一任务和测试状态，再开始改动。

## 看板

地址：`http://localhost:8898/`

独立启动：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m v4.dashboard
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8898/api/state?mode=chase
```

## 每日关键链路

| 时间 | 预期产物 |
|---|---|
| 09:25 | `candidate_journal/YYYY-MM-DD.json` 的 `morning` 与PushPlus回执 |
| 09:30:20 | 前一交易日持仓卖出或明确空仓回执 |
| 14:49 | 严格信号特征；失败不得伪造 |
| 14:50:20 | 同日日志的 `confirmation` 与PushPlus回执 |
| 14:50:40 | paper buy回执，可能成交、空仓或阻断 |
| 15:10 | 下一交易日上下文、标签和维护报告 |

运行数据位于 `v4/data/` 和 `phase1/data/`，均被Git忽略。

### P1快照目录

```text
phase1/data/execution_snapshots/
├── strict/       # 唯一允许进入执行标签、严格数据集和模型研究的快照
├── paper_only/   # 模拟账户执行观测，不得进入训练
├── diagnostic/   # 窗口外人工诊断
└── quality/      # 逐次质量原因和按日汇总
```

`strict`、`paper_only` 和 `diagnostic` 不得通过移动文件互相转换。旧版根目录下的
`buy/sell/signal` 仅作为只读历史资产保留，新标签构建默认不会读取。

## 故障定位顺序

1. Windows任务是否执行、返回码是什么；
2. `phase1/data/logs/` 对应任务日志；
3. 当日candidate journal是否有早盘和确认；
4. `v4/data/paper_receipts/` 是否有买卖回执；
5. `v4/data/paper_account.json` 是否存在且可对账；
6. 看板进程是否为 `python -m v4.dashboard`；
7. 不得通过降低严格门槛掩盖数据失败。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\project_status.py
.\.venv\Scripts\python.exe -m pytest -q
```

## 安全边界

- 不连接券商，不发送真实订单；
- `research_locked`不得人工绕过；
- `v4/.env`不得输出或提交；
- 重置账户、删除数据、重新注册系统任务前必须明确确认目标和影响。
