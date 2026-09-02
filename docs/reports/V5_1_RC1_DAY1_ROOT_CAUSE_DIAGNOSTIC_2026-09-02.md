# V5.1-RC1 Natural SHADOW Day 1 根因定位报告

## 1. 结论

V5.1-RC1 Natural SHADOW Day 1 的五次 preflight 失败已定位到 **SSE Official Master 解析结果内存在重复证券代码**，不是“官方目录为空”，也不是后续行情、候选、模拟成交或通知链路故障。

2026-09-02 23:09（Asia/Shanghai）对冻结 RC1 相同源码进行只读、非事实写入诊断：

| 来源 | HTTP | 原始记录 | 解析有效记录 | 唯一代码 | 重复代码组 |
|---|---:|---:|---:|---:|---:|
| SSE Official | 200 | 2,516 | 2,506 | 2,462 | **44** |
| SZSE Official | 200 | 2,899 | 2,899 | 2,899 | 0 |

SSE 响应 SHA-256：`0b980fb8cabff9cbba6980a4c5a5a4539767d8c227f5affa1962729ff554cbbe`

SZSE 响应 SHA-256：`5e37e716956cebdaecc6760cced0168ac1e06d31558eeb296d1e4d5b19f0acde`

已确认的部分重复代码示例：

`600054, 600094, 600190, 600221, 600272, 600295, 600320, 600555, 600602, 600604, 600610, 600611, 600612, 600613, 600614, 600617, 600618, 600619, 600623, 600625, 600639, 600648, 600650, 600663, 600679, 600680, 600689, 600695, 600698, 600726`

本报告不宣称策略有效，也不改变 `research_locked=true`、`broker_orders=false`。

## 2. 冻结版本与审计边界

- RC artifact SHA-256：`092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4`
- 源码 commit：`14cbcf2615a68a50789997e26527f82074a2ca6e`
- 源码 tree：`985930b9bc0786393004d8e3ab76d83286537b54`
- Day 1：`2026-09-02`
- Day 1 最终摘要 SHA-256：`b6d47d6aca65db4cd0808c42ea3eb70d1990254fbb24a56a6c8b9e79213b9cac`
- Day 1 manifest SHA-256：`88a07ad51ad177d9f2e1338a279eea7492ceaf9ed293fff35d2c91c191030479`
- manifest 条目数：24

本次诊断只调用冻结源码的两个官方 Master source 并在内存中统计；没有写入 shadow/strict/production fact，没有追赶窗口，没有回放，没有发送通知或订单，没有修改 Scheduler、8899、V5 生产任务或账本。

## 3. Day 1 不可变失败时间线

五次自然 preflight 均以相同异常失败关闭：

`ContractViolation: official master empty or duplicate symbol`

| 时间 | failure fact | failure SHA-256 | run fact |
|---|---|---|---|
| 08:10 | `v51failure1-57cb...` | `58b3a57...` | `v51prodrun1-55ec...` |
| 08:30 | `v51failure1-6718...` | `a7ef7cf...` | `v51prodrun1-11de...` |
| 08:50 | `v51failure1-aebc...` | `3d8354c...` | `v51prodrun1-1a7b...` |
| 09:05 | `v51failure1-afb1...` | `c5cf5c...` | `v51prodrun1-92a5...` |
| 09:20 | `v51failure1-511f...` | `3a15b38...` | `v51prodrun1-1e93...` |

所有 run 均属于 `SHADOW / V51_SHADOW`，`strict_evidence=false`。09:20 最终失败后，14 个 `V51-RC1-Shadow-*` 任务均已停用。没有运行依赖 preflight 的后续阶段，`real_window_strict_days=0`。

## 4. 代码路径与失败条件

生产入口：

1. `python -m v5_1.task_runner preflight --mode SHADOW`
2. `V51Runtime._preflight(...)`
3. `CrossVerifiedMasterDirectory.discover()`
4. `SSEOfficialMasterSource.discover()` 与 `SZSEOfficialMasterSource.discover()`
5. 合并后执行全局代码唯一性断言

冻结实现的关键逻辑位于 `v5_1/master_sources.py`：

```python
sse_rows, sse_diag = self.sse.discover()
szse_rows, szse_diag = self.szse.discover()
official = tuple(sorted((*sse_rows, *szse_rows), key=lambda x: x["code"]))
codes = [x["code"] for x in official]
if not official or len(codes) != len(set(codes)):
    raise ContractViolation("official master empty or duplicate symbol")
```

两个单源实现都已经在零有效记录时提前抛出更具体异常：

- `sse official directory has no valid identity records`
- `szse official directory has no valid identity records`

因此，Day 1 到达合并层的统一异常时，“empty”分支实际上不可达；结合只读诊断可以确认命中的是 duplicate 分支。

## 5. 根因分层

### 5.1 已证明

- SSE 官方请求成功（HTTP 200），并非网络空响应。
- SSE 解析器产出 2,506 条有效记录，但只有 2,462 个唯一证券代码。
- SSE 内部存在 44 组重复代码。
- SZSE 解析结果无重复代码。
- SSE 只接受以 `6` 开头的代码，SZSE 只接受以 `00/30` 开头的代码，因此不是沪深市场之间代码碰撞。
- `CrossVerifiedMasterDirectory` 在重复检查处失败，尚未进入 Eastmoney 交叉核验、Daily Tradability、行情快照、候选或模拟成交阶段。

### 5.2 高置信原因

SSE 接口返回的是含历史/退市等多状态记录的公司/股票目录。当前解析器只用代码前缀、名称和上市日期判断“有效”，没有先按证券状态与记录身份建立版本关系；同一 A 股代码的多条历史/状态记录因此同时进入 Master，触发唯一性门禁。

### 5.3 尚需 RC2 诊断确认

44 组重复记录属于以下哪种情况，必须基于原始记录字段逐组确认：

- 完全相同身份记录的接口重复；
- 同代码、同公司但不同状态/有效期版本；
- 同代码被重新分配或存在冲突身份；
- 解析器错误地回退使用 `COMPANY_CODE`，把非 A 股记录映射成 A 股代码。

在确认前，不能简单用 `set`、首条、末条或字典覆盖来“修复”。这会把真实身份冲突静默吞掉。

## 6. 为什么连续五次都失败

五次 preflight 使用相同冻结解析契约访问同一官方目录口径。只要 SSE 返回的 44 组重复记录仍存在，重试只能重复得到同一个确定性契约失败。自动重试机制本身运行正常，但它不能修复确定性数据建模错误。

这也解释了为何系统没有积累交易样本：preflight 是依赖图的根节点，失败后按 fail-closed 设计停止所有下游任务。安全行为正确，但产品可用性为零。

## 7. RC1 评价

- fail-closed：**正确生效**。
- 失败证据保存与任务停止：**正确生效**。
- Master 输入契约：**不兼容真实 SSE 数据口径**。
- 可诊断性：**不足**。统一异常没有指出来源、重复数量和样例，且在构造完整 source diagnostics 之前抛出，导致 Day 1 不可变事实无法独立定位具体重复项。
- RC1 状态：**INVALID（CODE/DATA-CONTRACT BUG）**，不应重新启用做自然窗口重试。

## 8. 建议的 RC2 最小修复边界

不得直接修改冻结 RC1。应创建 RC2，且仅处理 Master 建模与诊断：

1. 在 SSE/SZSE 单源层分别检查代码唯一性，异常必须包含来源、重复组数和有限脱敏样例。
2. 在唯一性判断前保存或引用内容寻址的原始 source response/diagnostic，使失败可追溯。
3. 为 SSE 原始记录建立明确的记录分类与版本规则：A 股代码字段优先，禁止未证明安全的 `COMPANY_CODE` 回退。
4. 完全相同记录只有在协议预注册并保存 dedup evidence 后才可确定性去重。
5. 同代码身份、上市日期、状态或有效期冲突必须继续 fail-closed 并隔离，禁止 last-write-wins。
6. Security Master 与 Daily Tradability 保持分离；不得用当日可交易状态反向改写持久 Master 身份。
7. 不降低 freshness、coverage、独立来源或内容寻址门槛。

必须补充的反例测试：

- SSE 完全相同重复记录；
- SSE 同代码但名称/上市日期/状态冲突；
- `A_STOCK_CODE` 无效但 `COMPANY_CODE` 像 A 股代码；
- 历史退市记录与当前有效记录同代码；
- SZSE 重复记录；
- 沪深来源代码空间污染；
- 单源为空；
- 原始响应已取得但后续唯一性失败时仍可验证其内容哈希；
- Eastmoney 不可用时官方完整 Master 的既定降级语义不回退；
- 修复后对当前 SSE 响应的唯一 Master 数量与隔离数量可解释且总量守恒。

## 9. ChatGPT 可执行的复验重点

ChatGPT 不应只检查“去重后测试通过”，而应要求开发者提供：

1. 44 组重复记录的分类统计，不包含敏感信息或整份原始响应。
2. 每类重复的预注册处理规则及理由。
3. 处理前记录数 = 保留 Master 数 + 合法去重数 + 隔离数 + 非 A 股/无效数的守恒证明。
4. 冲突重复必然 fail-closed 的反例。
5. 失败情况下原始响应哈希和 duplicate diagnostics 可由事实链解析。
6. 新 RC artifact、commit、tree 和 SHA-256；不得覆盖 RC1。
7. 新一轮 Natural SHADOW 只能从 RC2 冻结后重新开始，RC1 的失败历史不得改写。

## 10. 当前不变状态

- `research_locked=true`
- `broker_orders=false`
- strategy effectiveness：`UNPROVEN`
- V5 仍持有生产所有权
- Windows Scheduler 生产任务：未修改
- 8899：未修改
- V5 生产账本/事实：未修改
- PushPlus：未发送
- 券商订单：未发送
- V5.1 real-window strict days：0
- V5.1 cutover ready：NO

## 11. 证据位置

本地不可变原始证据（不上传 GitHub）：

`C:\Users\lisha\V5_1_RC1_NATURAL_SHADOW\evidence`

Day 1 摘要报告：

`docs/reports/V5_1_RC1_NATURAL_SHADOW_DAY1_2026-09-02.md`

本根因报告只包含脱敏统计、哈希和必要代码路径；不包含 token、环境变量、整份官方响应或生产事实内容。
