# P2严格验收状态

更新：2026-08-08。P2保持 `in_progress`，P3保持 `pending`。

## 离线验收

| 项目 | 证据 | 状态 |
|---|---|---|
| 不可变母池/确认实体 | 深层冻结、确定性ID、覆盖拒绝测试 | 通过 |
| 母池子集 | 实体校验、日志校验、冻结链路 | 通过 |
| 最终发布顺序 | DecisionChainService实际路径 | 通过 |
| 推送/看板/执行一致性 | 同一decision_id冻结端到端测试 | 通过 |
| 固定80分删除 | paper-top1-integrity-v1及源码扫描 | 通过 |
| 评分尺度 | base_score + bounded confirm_delta | 通过 |
| 原因码 | paper政策全部阻断路径无unknown | 通过 |
| 原子写入 | 磁盘replace失败无半文件、可重试 | 通过 |
| 推送失败 | 最终实体不变、看板仍读同一ID | 通过 |
| 旧日志 | 8月6—7日只读对照，不晋升新证据 | 通过 |
| 自动测试 | 131项 | 通过 |

## 在线验收（未完成）

2026-08-10首个开放交易日必须通过：

1. 09:25生成 `morning-pool-v1` 和 `mp-*`；
2. 14:50生成 `confirmation-decision-v1` 和 `cd-*`；
3. 确认代码集合为母池子集；
4. 推送日志保存相同pool/decision ID；
5. 原因码不含 `unknown_block`；
6. 看板和执行指令读取同一decision ID与outcome；
7. 14:53健康任务运行 `p2-session-acceptance-v1` 并输出 `passed=true`。

手工只读复核命令：

```powershell
.\.venv\Scripts\python.exe scripts\validate_p2_live.py --trade-date 2026-08-10
```

在该报告通过前，不得将P2标记完成或进入P3。

## 调度事实

两次必要推送、14:49信号、14:50快照和14:53联合健康验收任务均为Ready，
下次运行是2026-08-10。独立paper买卖任务尚未注册；尝试重注册时Windows返回
`Access is denied`。该问题属于P3/P4执行调度，不影响P2决策链在线验收，但在进入
相关阶段时必须先解决，不能依赖看板常驻掩盖。
