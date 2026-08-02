# V4本地运行说明

V4的生产运行面完全位于`C:\Users\lisha\stock-screener`：Python使用项目
`.venv`，调度使用Windows Task Scheduler，看板只监听`127.0.0.1:8898`。
Codex及其他AI Agent只用于开发维护，不参与每日选股或推送。

## 两条必需推送

| 时间 | Windows任务 | 行为 |
|---|---|---|
| 工作日09:25 | `AStock-V4-Push-Morning-0925` | 获取全市场行情，生成早盘观察池并提醒09:30待卖持仓；明确禁止早盘买入 |
| 工作日14:50:20 | `AStock-V4-Push-Confirm-145020` | 重新获取行情和评分，读取14:49严格特征，经V4门禁后推送尾盘确认 |

当前系统为`research_locked`，所以尾盘推送只能显示观察候选和阻断原因；不能
通过修改推送文案或定时任务绕开准入门禁。

## 本地任务

- `AStock-V4-Dashboard-Logon`：登录后从项目`.venv`启动看板；
- `AStock-V4-Sell-0930`：严格卖出时点快照；
- `AStock-V4-Health-Sell-0936`：卖出快照审计；
- `AStock-V4-Signal-1449`：严格特征冻结；
- `AStock-V4-Buy-1450`：严格买入盘口快照；
- `AStock-V4-Health-Close-1453`：信号和买入快照审计；
- `AStock-V4-Maintenance-1510`：准备下一交易日上下文并重建标签。

使用以下命令重新注册或审计任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File phase1\scripts\register_v4_snapshot_tasks.ps1
.\.venv\Scripts\python.exe main.py v3-cron-list
```

## 外部服务边界

系统仍需要新浪/东财行情接口和PushPlus网络服务，但不需要外部Agent。PushPlus
令牌只放在`v3/.env`：

```text
PUSHPLUS_TOKEN=替换为有效令牌
```

禁止将令牌写进Python、PowerShell或任务描述。PushPlus只有返回JSON
`code=200`才记为发送成功；网络错误、无效JSON或服务拒绝都会使任务失败。
更新令牌后，运行以下命令发送一条明确标注“非选股”的测试消息：

```powershell
.\.venv\Scripts\python.exe phase1\scripts\test_pushplus.py
```
