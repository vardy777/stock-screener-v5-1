# P2严格验收状态

更新：2026-08-08。P2离线工程与自动验收已经通过；P2仍为当前阶段，P3保持`pending`，生产状态保持`research_locked`。

## 离线验收（已完成）

| 项目 | 证据 | 状态 |
|---|---|---|
| 唯一事实源 | 候选与决策业务事实只存在于`candidate_journal` | 通过 |
| 不可变实体 | MorningPoolV1、ConfirmationDecisionV1深层冻结、内容寻址、幂等写入 | 通过 |
| 母池子集 | 14:50确认候选强制属于同日09:25母池 | 通过 |
| 完整血缘 | 输入快照、市场状态、排序、策略、政策和冻结上下文身份进入最终实体 | 通过 |
| 消费者纯投影 | 推送、看板和模拟执行不生成或重新解释候选 | 通过 |
| BUY/EMPTY/BLOCKED | 空候选与门禁阻断可区分，原因码机器可读 | 通过 |
| 评分一致性 | 全市场base_score加固定有界confirm_delta，不在小母池重算百分位 | 通过 |
| 无偏paper政策 | paper-top1-integrity-v1替代结果拟合的固定80分阈值 | 通过 |
| 冻结输入回放 | 两份MarketSnapshotV1与FeatureContextV1由真实V4Runtime完整回放 | 通过 |
| 确定性 | 快照时间替代墙上时钟；重复回放pool/decision ID及投影一致 | 通过 |
| 篡改与非因果 | 快照/特征内容哈希、跨日、未来特征、naive datetime均fail-closed | 通过 |
| 调度兼容 | 原Windows推送任务先运行V4决策生产，再运行纯推送消费者 | 通过 |
| 自动测试 | 全量157项 | 通过 |
| 项目一致性 | `scripts/project_status.py`，missing=0、v3_imports=0 | 通过 |

## 真实窗口验收（未完成）

必须在开放交易日验证并保存证据：

1. 09:25生成`morning-pool-v1`、`mp-*`及对应MarketSnapshotV1；
2. 14:49生成严格特征并自动归档不可变FeatureContextV1；
3. 14:50生成`confirmation-decision-v1`和`cd-*`，确认集合是母池子集；
4. 推送日志保存相同pool/decision ID；
5. 原因码不含`unknown_block`；
6. 看板和执行指令读取同一decision ID与outcome；
7. 次交易日09:30验证连续竞价卖出快照、时效和T+1链路；
8. 联合验收器输出`passed=true`。

只读复核命令：

```powershell
.\.venv\Scripts\python.exe scripts\validate_p2_live.py --trade-date YYYY-MM-DD
```

真实窗口报告全部通过前，不得将P2整体标记完成、不得进入P3，也不得解除`research_locked`。

## 阶段外事项

独立paper买卖Windows任务注册权限和看板进程解耦属于P3/P4，不属于P1/P2离线验收；这些问题仍必须在相应阶段解决，不能用看板常驻掩盖。
