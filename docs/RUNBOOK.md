# V5 本地运行手册

## 进入项目

```powershell
cd C:\Users\lisha\stock-screener
.\.venv\Scripts\python.exe scripts\project_status.py
```

看板：[http://localhost:8899/](http://localhost:8899/)。独立启动：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m v5.dashboard --port 8899 --data-dir v5/data
```

## 每日生产表

| 时间 | 任务 | 权威证据 |
|---|---|---|
| 08:30 | readiness | `v5/data/preflight/YYYY-MM-DD` |
| 09:25:05 | morning_pool | acquisition/snapshot/market_state/funnel/morning_pool |
| 09:25:50 | morning_push | `notifications/YYYY-MM-DD/morning.json` |
| 09:30:10 | paper_sell | paper订单、事件、sell acquisition与baseline |
| 14:49 | feature_freeze | signal acquisition/snapshot/frozen pointer |
| 14:50 | confirmation | 同日母池子集ConfirmationV5 |
| 14:50:30 | confirmation_push | `notifications/YYYY-MM-DD/confirmation.json` |
| 14:50:40 | paper_buy | Top1订单和事件 |
| 14:53 | health_check | 依赖、血缘、通知、账本与恢复 |
| 15:10 | maintenance | JSON校验和内容清单 |
| 15:20 | live_acceptance | 全日不可变验收报告 |

## 故障定位

1. `Get-ScheduledTaskInfo -TaskName AStock-V5-...-Daily` 查看时间和返回码。
2. 查看 `v5/data/runs/YYYY-MM-DD` 的不可变任务事实。
3. 查看当日 `acquisition` 和 `consensus` 中每个源的覆盖、年龄、批次耗时及拒绝原因。
4. 检查候选、确认、快照和市场状态ID血缘。
5. 推送必须同时存在最终实体和 `HTTP 200 / ACCEPTED` 回执。
6. 检查 `v5/data/paper` 事件链、待执行订单和对账。
7. 看板异常时先检查 `http://127.0.0.1:8899/api/read-model`；不得回退V4数据。

## 验收

```powershell
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\audit_production_tasks.ps1
.\.venv\Scripts\python.exe -m v5.independence_audit
.\.venv\Scripts\python.exe v5\scripts\live_acceptance.py --trade-date YYYY-MM-DD
```

## 安全与恢复

- 不连接券商；`research_locked`不得绕过。
- `v5/.env`不得显示、复制到日志或提交。
- 不补写错过窗口；恢复观察必须保持非严格、不可确认、不可模拟成交。
- 不同时启用V4和V5账本写者。
- 重置账本、删除事实或变更所有权前必须先核对持仓、事件数和备份。
- 公共行情失败时保持空仓，不通过放宽覆盖、时效或一致性门槛恢复表面可用性。
