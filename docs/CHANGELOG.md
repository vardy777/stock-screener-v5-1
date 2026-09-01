# 项目变更日志

- 2026-09-01：冻结`V5.1-RC1`。精确源码提交`14cbcf2615a68a50789997e26527f82074a2ca6e`、tree `985930b9bc0786393004d8e3ab76d83286537b54`；提交后构建的自包含artifact SHA-256为`092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4`。全新clean-room目录中确认`shared_core`/`v5_1`仅从artifact导入，release-only acceptance、142项专项及649项全仓测试全部通过。release scope clean；仓库整体因无关G1/历史V5工作仍dirty。Natural SHADOW尚未启动，严格日仍为0，V5继续持有生产所有权。

- 2026-09-01：V5.1最后一轮strict canonical contract收口。修复`AcquisitionSessionV1.build`与`CandidateFunnelV1.build`对`accepted`执行`bool(...)`导致字符串`"false"`被接受为True的问题；canonical写入与直接构造现在统一要求精确boolean、integer、string及enum类型。同步收紧Security Master、Master evidence、execution observation身份字段和verification record_count/string-sequence边界、calendar配置boolean。新增31项对抗测试；V5.1专项142项、全仓649项通过。生产所有权、Scheduler、8899、严格日及券商状态未改变；RC冻结仍需独立干净提交边界。

- 2026-09-01：完成V5.1第一批Production Readiness离线修复。D日15:20验收降为PreliminaryDayAcceptance，只有D+1严格退出、持仓关闭、账本对账及完整交易血缘重建后的RoundTripAcceptance才可形成严格日证据；合法ACTIVE_FLAT也要求D+1无持仓观察闭环。稳定基础设施提升到`shared_core`，V5与V5.1使用同一实现且V5.1直接`v5.*`运行时依赖为0。持久化读取器拒绝隐式布尔/数字转换和字段漂移。新增确定性、自包含、无密钥的UNFROZEN发布包及单命令验收。专项111项、全量618项通过；Scheduler、8899、V5生产所有权、真实事实和券商订单均未修改，仍NOT CUTOVER READY。

- 2026-08-31：完成V5.1 Security Master证据链和单点故障离线修复。SSE/SZSE官方目录改为各自交易所的权威基础Master，Eastmoney降为可选第三方交叉核验；第三方停机产生可观察降级，不再阻断完整官方基础，官方停机、身份冲突、重复代码、缺失实体或内容哈希错误继续失败关闭。新增可复算SHA-256的不可变原始响应blob、逐证券MasterMatch及Verification引用解析，新增08:10/08:30/08:50/09:05/09:20禁用且仅报告的SHADOW恢复定义。V5.1专项90项、全量597项通过；Windows Scheduler、8899、V5账本和通知均未修改。V5.1仍直接依赖V5日历/行情/漏斗/账本/供应商模块，尚未满足V5可退役独立性门禁，因此不可切换；真实SHADOW窗口与策略有效性亦待验证。

- 2026-08-30：完成V5.1独立Security Master生产适配器。Eastmoney仅负责发现，上海证券逐只由SSE官方源核验，深圳证券逐只由SZSE官方XLSX核验；provider family固定为`eastmoney`/`sse`/`szse`，名称仅做NFKC、空白及ST前缀规范化，代码、交易所、名称与上市日期冲突或来源停机均失败关闭，BSE按契约排除。真实非严格诊断取得SSE 2,505条、SZSE 2,897条有效记录；Eastmoney在75秒预算内于第5页失败，未发布交叉源事实。V5.1专项86项、全仓593项通过；Scheduler、8899和V5生产所有权未改变，真实SHADOW窗口与切换授权仍待完成。

- 2026-08-27：完成V5.1最终三项契约收口。Tradability对仓库中同一交易日/证券的全部as-of状态强制唯一，调用方不能用单条参数隐藏第二条冲突事实；Master freshness日期只由已验证TradingCalendar生成当日与上一开放日，业务代码不再接收可扩大的日期列表；新增ImmutableReadModelBuilder及内容寻址run/failure/execution-result事实，8901实现只从保存的run、failure、confirmation、selection、execution事实推导WAITING/ACTIVE_FLAT/TRADED/FAIL_CLOSED。

- 2026-08-27：完成V5.1独立验收P0/P1契约修复。Security Master verification新增as-of、真实版本、有效期与来源血缘；DailySecurityStatus正式内容寻址存储并与Tradability逐ID解析；正式布尔拒绝字符串/0/1。冻结09:35快照最大年龄30秒、14:49:00–14:49:59不可变freeze、执行报价最大年龄5秒。删除看板事故日期硬编码，状态改由完成/失败/确认/成交事实推导。CloseScan新增独立candidate/run事实，comparison强制策略版本并拒绝重复STRICT交易日。未修改Windows Scheduler或8899，真实窗口和第二轮独立验收待完成。

- 2026-08-27：启动V5.1隔离架构升级。新增Persistent Security Master、验证周期、Daily Tradability、09:35母池、决策后执行快照、CloseScan独立选择/账本、STRICT配对统计和V5.1-only五页面看板；保留V5/G1事实，未修改Windows Scheduler或8899生产所有权。

- 2026-08-27：G1-1 P0独立复审补洞。正式股票池必须由独立权威当日证券清单驱动，彻底避免从已有状态事实反推清单而漏检“整只证券无状态事实”；清单自身为空、字符串化或重复也失败关闭。四类Fact直接构造边界补充严格布尔/枚举校验；DailyBar冻结契约移除可由真实涨跌停价格派生的`hit_*`字段。G1专项61项、全量504项通过。G1-1继续in_progress，历史来源批准数仍为0，未进入G1-2。

- 2026-08-26：修复V5全市场目录刷新可靠性：12秒串行分页改为75秒默认预算、8路受控并发、单页重试、隔离同日续传、重复/缺页/总数门禁及不可变成功/失败诊断事实；东方财富多域名明确保持同一供应商身份。新增08:10、08:30、08:50、09:05、09:15恢复触发与09:20绝对硬截止；2026-08-27已只对既有 `AStock-V5-Readiness-Daily` 部署5个触发器，执行程序和参数未变，其他10个V5任务未改动。生产日状态区分等待、主动空仓、已交易和失败关闭。离线504项测试通过；真实窗口与独立备用目录源仍待验收，`research_locked`、95%门槛、券商禁用及冻结基线不变。

- 2026-08-25：G1-1 P0时点契约加固。正式股票池遇到应存在证券状态缺失/歧义时整日失败关闭，新增仅诊断用的跳过原因、缺失/歧义计数与覆盖率；同一证券状态有效区间重叠在存储构造时拒绝；数据源清单只接受真实JSON boolean。Fact模型补齐退市日、成交额、真实涨跌停价格、配股价和财务修订标记，并同步导入与边界验证。G1专项55项、全量474项通过。G1-1继续in_progress，历史来源批准数仍为0，未进入G1-2。

- 2026-08-24：G1-1接入无需账户的公开腾讯未复权日线采集器，仅产生明确 `approved_for_g1_research=false` 的诊断观测，用于与本地归档交叉核验；不把当前抓取时间伪装成历史可用时点。

- 2026-08-24：公开腾讯原始日线与Phase1归档对000001在2023-12-28至2024-01-05的6个重叠交易日收盘价逐日一致。该结果仅支持行情口径交叉核验，不能弥补历史证券状态、公司行为和披露时点缺失，数据源继续未批准。

- 2026-08-23：G1-1补齐已批准公司行为导入边界。除权、分红、送转与配股事件必须来自已批准的公司行为来源，并保留独立公告/可用/除权时点和供应商ID；公司行为不能通过复权价格序列隐式注入。

- 2026-08-23：G1-1新增已批准历史日线导入边界。导入器只接受时点验证且获批准的日线来源，并强制逐行 `available_at`、供应商记录ID、原始OHLCV和严格布尔交易状态；未批准的Phase1归档在导入前失败关闭。

- 2026-08-23：G1-1新增 Phase1 分时归档隔离扫描器。扫描器只能生成带 `quarantined=true` 的解析质量报告和日线候选，类型上不能产生正式 `DailyBarFact`；候选不允许进入因子、策略、组合或回测。完成对4,997份本地文件的只读质量盘点：3,081,511个诊断会话候选、0无效行；报告明确 `approved_for_g1_research=false`。全量438项测试通过。

- 2026-08-23：G1-1完成历史数据接入决策说明。明确优先检查已有Wind/CSMAR合法权限；Tushare Pro仅作为待字段验收的低成本候选；Phase1归档永久仅限诊断。冻结证券状态、原始行情、公司行为和财务披露的最小字段以及30证券抽样、公告前不可见、公司行为重建和不可成交案例等批准门禁；未注册账号、购买服务或下载外部数据。

- 2026-08-23：G1治理测试增加运行时导入审计，禁止G1导入V5候选漏斗、决策、通知、模拟执行和调度模块，防止两条研究线发生业务耦合。

- 2026-08-23：G1-1新增原始 `DailyBarFact`、`CorporateActionFact` 与时点日线读取器。日线强制可用时点、OHLC边界、成交/停牌和涨跌停一致性；公司行为强制公开/可用顺序并与复权价格解耦。未导入或批准任何本地行情归档，历史研究门禁保持关闭。G1专项30项、全量432项测试通过。

- 2026-08-23：G1-1建立时点证券与披露事实契约。新增 `SecurityStatusFact`、`FinancialDisclosureFact`、`PointInTimeStore` 和可交易股票池 fail-closed 规则；强制时区、可用时点、有效区间、ST/退市/停牌/北交所排除及上市天数门禁，财务数据按公开可用时点读取。盘点确认本地V5实时事实和旧缓存均不能充当长期历史回测的权威输入，因此未产生任何历史策略结果；历史证券状态和披露时点数据仍是G1-1开放门禁。

- 2026-08-23：G1-1新增版本化数据源清单和历史研究就绪门禁。历史研究必须同时具备时点验证且批准的证券状态、日线、公司行为和财务披露四类单一来源；覆盖不足、未验证、未批准或多来源冲突均失败关闭。当前清单只登记V5短窗口实时事实和遗留缓存，均明确禁止作为G1长期历史研究权威输入。

- 2026-08-23：G1-1盘点并登记Phase1本地分时行情归档：4,997个证券文件、可见覆盖约2023-12-28至2026-08-07。该来源未通过时点验证且缺少同期证券状态、公司行为和披露事实，保持 `approved_for_g1_research=false`；新增清单加载校验，未产生任何策略回测。

- 2026-08-23：正式启动独立 G1 多策略组合研究项目。冻结 G1 V1 产品章程、架构、路线图和机器状态，建立 `g1` 独立命名空间、四类证据隔离及不可变组合研究政策：5—15只、单票不超过10%、单行业不超过25%、持有2—10个交易日。G1-0治理验收完成，全量408项测试通过，项目进入G1-1时点数据阶段。G1保持 `research_locked`，禁止券商、PushPlus和生产调度；V5继续拥有全部生产入口、候选、账本、通知和8899看板。

- 2026-08-21：新增独立“量价挑战者”研究线 `volume_price_v1`。挑战者消费与V5冻结基线完全相同的09:25、14:49和次日09:30快照，14:50确认强制为自身早盘母池子集；叠加因果5/10日均线、收益、成交量结构和不过热过滤，使用独立10万元影子账本，不发送PushPlus、不连接券商、故障不阻断基线。完成2026-08-24上下文5215只股票构建，5116只有效，覆盖98.10%、独立参考匹配98.83%。8899新增两线对照；全量402项、独立性审计和生产静态审计通过，真实窗口仍待2026-08-24。

- 2026-08-13：启动独立 V5 产品闭环重构（影子开发、只读复用V4）。新增多源严格采集会话、全市场可解释候选漏斗和内容寻址V5事实存储；95%/时间因果等全局硬门槛保持，停牌/涨跌停/盘口缺失改为逐标的漏斗淘汰，避免单只证券关闭整个市场。新增V5产品章程和机器状态；未切换生产调度、8898、PushPlus或P3账本，`research_locked`不变。

- 2026-08-13：真实窗口日终审计未通过并保持失败证据。修复 Windows 中文系统命令输出被验收器强制按 UTF-8 解码而崩溃的问题；确认决策生产路径现在强制加载同日 `FeatureContextV1`，空母池也写入 `feature_context_id`，缺失或日期不一致则失败关闭。当天两次 PushPlus 均取得真实 HTTP 200/ACCEPTED，14:49、14:50、14:53任务成功，但15:10维护被系统终止且确认输出缺少特征输入血缘，因此当日闭环不通过。全量245项测试和任务静态审计通过；历史实体未改写，`research_locked`不变。

- 2026-08-13：P5 看板按“结论—市场—候选—价格计划—风险—真实成绩”重建为单页股票研究界面，移除多视图和运维信息堆叠；空候选时明确展示数据门禁原因，所有模拟价格继续只接受冻结盘口。新增页面级策略有效性警示：严格样本为 0 时明确声明不能证明策略有效。专项 13 项、全量 244 项测试通过。14:49 特征冻结、14:50 决策/PushPlus 200 ACCEPTED/模拟买入及 14:53 健康检查均按时成功，但早盘覆盖仅 78.8%，因此当日母池、确认和成交均为空；这只证明工程链路与安全门禁工作，不构成策略有效性证据。8898 仍由旧高权限进程 PID 14476 占用，当前普通令牌无法完成原子替换，待管理员终止后启动 `AStock-V4-Dashboard-Logon`。

- 2026-08-12：全项目复审收口。修复 P5 展示模板真实的双重编码乱码，新增每日闭环、两次 PushPlus `200/ACCEPTED` 数量与严格标签样本投影；PushPlus 业务事实统一为内容寻址不可变回执。P4 增加九类任务统一业务时间窗门禁，防止 `StartWhenAvailable` 跨窗口补跑，并在维护后刷新只读每日验收。完成 `v4/data`、严格上下文和执行快照三套内容寻址备份，合计 219 文件隔离恢复逐哈希通过。九个 P4 任务静态审计通过，全量 241 项测试通过；`research_locked`、券商禁用和严格样本 0 不变，真实窗口仍待验。

- 2026-08-12：经用户管理员授权完成 Windows Time 生产修复：W32Time 改为 AUTO_START 并与阿里云 NTP 同步，初次条带测量发现仍慢 0.82 秒，校正后 3 次最大绝对偏差 0.0024 秒。当日生产验收升级为同时检查服务、同步源与 NTP 实测偏差（上限 0.5 秒）。下一交易日严格上下文预检通过：覆盖 99.50%、独立参考匹配 99.25%。

- 2026-08-12：后续收口修复 Windows Time 脚本的乱码解析缺陷并加入 PowerShell 语法验收；当前非管理员进程仍会正确 fail-closed。`candidate_journal`、运行诊断和 P3 执行批次改用跨进程锁与 PID 隔离原子写，防止丢失更新；生产架构审计增加旧 dashboard/simulation/sim_engine 导入禁止。

- 2026-08-12：严格全项复盘修复第一批。14:50 母池观察快照与 P3 实际 Top1 成交快照分离；单只停牌、涨跌停或缺少卖一只阻断该标的，不再拖垮整个决策与必需推送；最终 Top1 仍必须通过新鲜可成交盘口和严格归档，未降低证据门槛。P5 仅投影当日 P4 输出并优先显示失败/阻断；P4 新增子进程耗时、返回码和 stdout/stderr 不可变工件。新增与离线工程验收分离的当日生产验收，严格检查任务、实体、ID血缘、PushPlus 200/ACCEPTED 与 Windows 时间同步。加入预声明过热/流动性安全栏，不将规则分解释为胜率。`research_locked` 和禁止券商下单不变。

- 2026-08-11：供应商冷却后单实例恢复 2026-08-12 上下文，覆盖 4377/4399（99.50%），新浪独立参考 4375/4375（100%）。维护增加严格上下文幂等复用，避免成功后重复全市场请求；P4 维护恢复为成功终态。

- 2026-08-11：真实 14:49 因 Windows 系统时钟未同步而仅取得 87.07% 严格覆盖，失败证据保持原样。修复空母池确认血缘、同日必需通知有界恢复、空结批次恢复和 P2 不可变通知回执验收；下午 PushPlus 取得真实 200/ACCEPTED。15:10 次日维护因参考覆盖不足失败关闭，新增独立新浪收盘参考适配器，并禁止失败的上下文构建覆盖合格生产上下文。`research_locked` 不变。

- 2026-08-11：新增全市场前一交易日上下文网关，真实构建覆盖 4379/4399（99.55%），并以 09:25 不可变快照交叉验证 4359/4359；丢弃所有晚于目标日的供应商行，保持因果边界。P2/P3 网关快照直接进入严格执行归档，空早盘母池的买入健康检查改为明确不适用；修复 V3 退役后的残留模块导入。全量 234 项测试通过，14:49/14:50 真实窗口仍待当天验收，`research_locked` 不变。

- 2026-08-11：真实窗口发现并修复全市场快照投影O(n²)哈希问题；行情时效改为绑定快照完成时刻，14:49失败不再阻断14:50空仓确认/推送，健康失败不再阻断下一日维护。08-11 09:25真实行情覆盖99.52%，决策与PushPlus 200/ACCEPTED通过；冻结上下文仅2.59%仍阻断严格14:49，保持`research_locked`。

- 2026-08-09：经用户授权正式退役V3。81个V3代码/数据/本地配置文件生成内容寻址备份并通过隔离恢复校验；将仍有价值的快照质量能力迁入`v4.snapshot_compat`，移除V3命令、旧评分/看板/账户兼容测试和工作树`v3/`目录，启动器改为P5。`phase1/`作为V4研究链保留，生产门禁与任务不变。

- 2026-08-09：重构 P5 看板为新手首页、研究分析、系统运维三层视图；新增当日/历史候选隔离、行情和资金流日期校验、低覆盖/小样本情绪 fail-closed、面向新手的行动摘要和评分非概率说明，并完成单列移动端布局。看板继续只读，`research_locked`、调度、推送和模拟成交边界不变。

- 收口切换后六项离线缺口：14:49 特征冻结改为唯一 `MarketDataGateway`→`MarketSnapshotV1` 输入并将快照ID写入 `FeatureContextV1`；新增纯 `P2DecisionProducer`，生产决策不再加载 `SimulationEngine` 或账户；feature/health/maintenance 生产入口迁入 `v4/scripts`，健康与维护投影读取实际报告；统一离线验收新增生产叶子静态架构审计且未运行测试时不再误报通过；切换后文档状态统一；P5 增加非交易日和首窗口前心跳语义。全量256项通过，真实任务/推送/成交未触发，`research_locked`不变。

- 修复生产切换后的四个集成缺口：P4 失败/阻断结果改为不可变多次尝试并允许同日重试；早盘与尾盘通知只读 P3 账本持仓；P4 持久化生产心跳并在进程异常时降级；PushPlus 每次传输保存带父实体、负载哈希和返回结果的 `NotificationReceiptV1`。P5 改为逐请求读取最新实体。新增专项生产集成验收，未触发真实推送或成交。

## 2026-08-09

- 经用户明确授权完成 P3/P4/P5 生产原子切换：备份并哈希旧任务和 V4 数据，初始化 P3 十万元单写者账本，注册九个 P4 任务并禁用旧任务，将 8898 切换到 P5 只读控制台。切换后所有权为 P2/P3/P4/P5，POST 返回 405，`research_locked` 保持不变；周一真实四窗口和任务回执仍待现场验收。
- 按顺序完成切换前十项离线工程工作：九类定时任务统一使用内容寻址输出契约，失败结果可跨重启审计，最终实体依赖 ID 必须连续。
- 新增默认禁用的 P3/P4 薄生产适配器、完整但禁用的九任务定义、P3 create-once 初始化和运行时单写者授权门禁；未注册任务、未迁移真实账户、未接通旧生产入口。
- P5 扩展为 P3/P4/四窗口/严格模型准入/切换准备的只读适配器，新增组件化的四窗口、严格样本和切换准备面板；8899 隔离视觉验收通过，8898 未切换。
- 新增冻结生命周期、六类崩溃故障与回滚矩阵，以及永不自行授权的原子切换准备包。全量 247 项测试通过；`research_locked`、PushPlus、现有生产任务和模拟成交生产链路均未改变。

- 完成生产切换准备包：新增真实四窗口证据派生、一次性不可变落盘与内容寻址验收、P3/P4/P5切换/回滚清单、Windows任务只读导出与可达的目标差异审计、单写者检查、完整隔夜生命周期及故障彩排、一键离线验收和日志保留审计；P5新增当前业务所有者与切换阻断面板。全量234项及实际一键验收通过；旧2026-08-07工件四窗口正确判定失败。全部工具默认只读，生产授权门禁固定失败，未修改任务、账户、PushPlus或8898。

- 完成全部当前可离线开发边界：P5新增真实V4文件零写入适配器、来源哈希、资金流、闭合往返、权益/回撤和多故障场景，并修复旧格式候选缺实体ID却显示DONE的问题；P6新增严格数据集与Walk-Forward/压力报告fail-closed审计；P7新增模型、策略、训练说明与普通/压力报告哈希绑定终审；P8新增内容寻址备份、损坏检测和隔离恢复。全量221项通过并产出全系统离线终审报告；现有8898、生产调度、真实推送、模拟成交和模型发布均未改接，`research_locked`保持不变。

- P5隔离重建第一检查点：决定保留未来8898/mode=chase入口但抛弃现有单文件内部架构，新增内容寻址`DashboardReadModelV1`和纯GET的8899隔离预览。完成当日链路、母池/确认关联、市场状态、描述性情绪、资金流口径、模拟账户闭环统计、三类证据隔离、P4任务与缺失降级；桌面和375px移动端浏览器验收通过。P5专项5项、全量211项通过；现有8898未改接。

- P4第三离线检查点完成用户要求的10项优化：完整禁用DAG、受控子进程超时、四边界崩溃矩阵与`OUTCOME_UNKNOWN`、实体→payload→请求→回执哈希、持久化心跳、告警去重升级恢复、60日压力、竞争NOOP、9节点禁用部署清单及独立守护进程重启。P4专项20项、全量206项通过；生产入口、Windows任务和真实PushPlus仍未改动。

- P4隔离离线第二检查点：新增Windows任务只读清单与脚本静态审计、多交易日安全漏跑扫描、显式历史审计补偿、任务中断恢复、心跳过期和分级告警、冻结P2实体到通知负载的完整ID血缘。过期09:25/14:50消息禁止补发；生产入口仍未改接，未注册任务、未调用真实PushPlus。

- P4隔离离线第一检查点：新增不可变任务规格/回执、有序事件日志、跨进程幂等、失败与超时重试、SLA前补偿、SLA漏跑告警、只读心跳及完全无网络的假推送适配器。默认只编排09:25与14:50两次必需通知；现有生产调度、推送和脚本入口未改接。P4专项9项、全量195项通过；未注册任务、未调用真实PushPlus、未连接P3生产链路、未标记P4完成。

- P3强化终审：完成1,000次往返/2,000持久化事件压力测试，消除追加路径重复加载并压缩原子JSON；强制终止进程覆盖订单前、订单后、成交后和结果后四个提交边界，重启可补单或修复缺失审计结果。对本机实际旧账户完成哈希锁定的只读验收，资金对平但因3个旧费用持仓和2笔T+1不兼容历史记录判定为不可切换。P3专项29项、全量186项通过；仍未迁移、未接生产、未启用调度、未标记阶段完成。

- P3离线韧性验收：金额统一量化到分并输出`cash_fen`；订单、成交与执行结果日志加入跨进程OS锁；新增不可变FILLED/REJECTED执行结果、恢复扫描与幂等补偿；实现只读旧账户校验器（不迁移、不切换）。完成200次往返/400事件、三标的交错、3进程并发、磁盘与权限故障、订单与成交之间崩溃、成交后审计写入失败等测试。P3专项28项、全量185项通过；P3仍为offline-only、未接生产、未标记完成。

- P3离线核心终审：账本升级为单文件原子有序事件链，校验事件计数、前序ID和头部摘要；新增不可变订单日志，补齐决策→订单→成交→往返血缘。删除、重排、截断、订单/成交篡改、跨决策平仓、重开仓和超过3只持仓均fail-closed；新增ADR-0008禁止旧账户与P3双写并静态阻止生产模块提前导入。P3专项19项、全量176项通过；P3阶段仍未完成且未接入生产。
- P3第二离线检查点：新增离线意图工厂和执行器，BUY只接受最终Top1决策及buy快照，SELL只接受T+1可卖持仓及sell快照；已验证交易日历负责节假日顺延。完成逐项失败隔离、原子写入故障保护、自动对账及周五买入/周一卖出端到端回放。P3专项14项、全量171项通过，仍未接入生产。
- P3第一离线检查点：新增不可变PaperOrderIntentV1、PaperFillV1和PaperRoundTripV1，以及无默认生产路径的OfflinePaperLedger；实现成交幂等、决策去重、一只上限1/3、冻结预算、费用现金流、T+1、状态重建和磁盘篡改拒绝。P3专项9项、全量166项通过，未改动或接入现有生产模拟账户与调度。
- 阶段门禁经用户明确修改：允许P3在P1/P2真实窗口待验期间进行隔离离线开发；禁止启用调度、接入每日模拟成交生产链路或标记P3完成。任何P1/P2真实窗口失败立即暂停P3并优先回退修复，research_locked保持不变。
- 文档事实统一：PROJECT、ROADMAP、MODULES、P2验收报告和机器状态统一声明P1/P2离线验收通过、P2仅等待真实09:25/14:49/14:50/次日09:30窗口；保留research_locked并禁止提前进入P3。治理/架构/回放专项20项及全量157项测试通过。
- P2离线验收完成：新增不可变 `FeatureContextV1`，将上一交易日上下文与14:49特征纳入内容哈希并由真实14:49任务自动归档；修复市场状态把当前墙上时钟写入历史实体导致的秒级非确定性。真实V4Runtime从两份冻结行情快照和冻结特征上下文重复回放一致，篡改、跨日及非因果输入均fail-closed。全量157项测试通过，P2仅保留真实窗口验收。
- P2事实源收口：推送、看板和模拟执行只投影 `candidate_journal` 最终实体；原Windows推送任务入口改为先运行独立V4决策生产作业，再运行纯推送消费者。
- P2确定性回放：新增从两份不可变 `MarketSnapshotV1` 读取、校验、生成母池与确认决策、投影执行指令的完整链路；历史回放使用快照时间且不污染实时缓存。静态架构与回放测试纳入全量153项测试。

## 2026-08-08

- P1严格收尾：V4删除松散DataFrame捕获器和DataFetcher市场状态业务旁路，旧捕获器迁至V3兼容层；SnapshotPolicyV1进入快照内容哈希，读取时按持久化政策重算质量；MarketStateV1 metrics递归冻结。新增篡改、深度不可变和旁路不存在测试，全量145项通过。
- P1离线验收通过：清除V4业务路径naive datetime自动补时区、无时区now和隐式本地astimezone；新增AST时间门禁与特征存储fail-closed测试。142项测试通过，P1仅保留四个真实交易窗口验证，离线开发转入P2。
- P1行情边界收口：物理删除看板内未使用的直接行情/回调选股函数；新增内容寻址的MarketSnapshotV1不可变仓储、原子非覆盖写入、幂等读取、schema/内容哈希/文件名/质量计数校验；新增AST架构门禁，除提供方实现和唯一网关外禁止V4模块导入DataFetcher或调用batch_fetch_quotes。离线测试140项通过。
- P1重新实施第一批：新增唯一提供方边界 `MarketDataGateway`、稳定 `snapshot_id` 和带快照血缘的 `MarketStateV1`；交易动作与行情时效对naive datetime统一fail-closed；支持09:25 morning快照会话。当前仅完成基础契约，旧核心调用方尚未迁移，P1不得标记完成。
- P0事实校正：确认关键文档磁盘内容为有效UTF-8，修复Windows状态命令输出编码并新增严格解码测试；撤销不符合代码事实的P1/P2完成声明，P1重新打开、P2等待P1，二者离线和真实窗口验收全部通过前禁止进入P3。
- 架构基线改为唯一行情网关、MarketSnapshotV1唯一核心输入、MarketStateV1契约和candidate_journal唯一候选/决策事实源；登记松散行情绕行、多候选状态源、消费者现场重算和非快照起点回放为阻断债务。
- 建立 `PROJECT.md`、`AGENTS.md` 和完整项目文档体系；
- 建立分阶段路线图、模块契约、运行手册和ADR；
- 建立机器可读项目状态与项目一致性检查；
- 将候选日志/执行门禁口径不一致和母池重排固定阈值登记为P2结构性问题。
- P0退出检查通过：项目一致性PASS、V4导入V3为0、自动测试94/94；项目进入P1。
- 新增8—10周大修日程、逐日交付物、验收门槛、20交易日稳定观察和样本驱动的策略/模型时间预期。
- 用户要求压缩工程时间；日程改为12—16个自然日冲刺，8月24日Beta、8月28日工程验收，仅真实交易窗口和样本积累保留自然时间。
- P1新增版本化 `QuoteV1`、`MarketSnapshotV1`、`SnapshotQualityV1`；严格拒绝缺字段、错误类型、无时区、跨日和非因果时间，并以原因码隔离strict与paper-only质量口径。
- V4新浪适配器记录交易所/供应商同源时间、机器接收时间和批次边界，并可无损转换为 `QuoteV1`；新增ADR-0004说明不伪造供应商时钟的原则。
- P1完成：实际快照保存接入MarketSnapshotV1质量判定，strict/paper-only/diagnostic物理隔离；失败采集只写质量原因、不写证据CSV；严格标签构建只读strict目录；新增每日分层质量报告和入口回放。
- P2第一检查点：新增深层不可变MorningPoolV1和ConfirmationDecisionV1、BUY/EMPTY/BLOCKED及机器原因码；尾盘流程改为先关联母池、再最终评估、最后单次写入，修复日志保留旧阻断理由的问题。
- P2第二检查点：早盘/尾盘推送、模拟买入和看板统一读取最终决策实体；候选缓存不能绕过BLOCKED或缺失决策。冻结全市场base_score，尾盘只加固定且有界的confirm_delta，消除小母池百分位重排失真。
- P2核心实现：以paper-top1-integrity-v1替换固定80分，按母池关联、Top1、评分血缘、95%覆盖、市场风险和行情时效准入；补齐缺母池持久化BLOCKED以及8月3—7日五类合成契约场景。该阶段尚未完成端到端、故障注入和真实窗口验收，不再标记完成。
- P2严格验收补齐：实际DecisionChainService统一生产与回放路径；增加同ID推送/看板/执行测试、磁盘故障注入、推送失败不变性、paper原因码全覆盖、旧日志只读审计及在线验收器。离线131项通过，P2仍等待8月10日真实窗口，不进入P3。

## 2026-08-07

- 早盘母池5只、尾盘确认3只、两次PushPlus成功；
- 自动买入任务执行但因Top1规则分77.5低于固定80分而空仓；
- 修复研究模拟被全市场批次时效整体阻断的问题；
- 看板增加自动模拟闭环观测。

## 2026-08-06

- V4运行时迁出V3，实现独立行情、账户、推送、看板和调度；
- 看板直接使用 `python -m v4.dashboard`；
- 加入V4禁止导入V3的自动测试。
# V5 offline product closure - 2026-08-13

## 2026-08-21 final live-window acceptance

- Recorded the real 15:10 maintenance and 15:20 fail-closed daily acceptance. The report contains no immutable validation errors and correctly remains incomplete because the strict 09:25 mother pool is absent.
- Made the read-only project status renderer distinguish strict tail evidence, non-strict recovery observations and strict mother pools instead of crashing on strict-pool-only fields or reporting an older recovery as current. Full suite: 388 passed.
- Hardened the production scheduler's own dependency, alert-suppression and recovery readers: only content-address-valid run entities count, and the latest valid attempt is authoritative. Corrected the recurring task description to acknowledge V5 local paper execution while still forbidding broker and V4 writes. Full suite: 391 passed.
- Reconciled roadmap/module/known-issue status with immutable 2026-08-21 evidence: recurring tail scheduling and strict 14:49 dual-source capture are now accepted, while 09:25 continuity and a complete full day remain explicitly pending.
- Added a leakage-bounded, research-only 20-session hourly proxy that maps the frozen V5 funnel, mother-pool subset, Top1 and execution-cost rules without creating strict facts. The 2026-07-09 to 2026-08-05 result is a negative warning: 14 trades, 21.43% wins, -1.6907% average net return and CNY -7,146.27 account PnL. Production policy remains frozen and research-locked; full suite: 395 passed.

- Closed the V5-native paper/strategy measurement loop without enabling a second writer: implemented both paper task entrypoints, causal 14:50/next-09:30 execution, immutable orders and hash-chained events, crash recovery, process locking, depth/fees/slippage/T+1 constraints, ledger-derived round trips and a strict equal-weight confirmed-set baseline. Added a V5-owned exchange calendar and immutable whole-market state with fail-closed risk gating and full lineage into notifications and the dashboard. Strategy evidence remains `INSUFFICIENT_EVIDENCE`, V4 remains the sole paper writer, and cutover remains blocked on real source/live-window acceptance. Full suite: 328 passed.
- Replaced the stale 8899 dashboard listener through its supervised task after proving that stopping the Windows task did not terminate an older descendant Python process. The live V5 page now returns HTTP 200 from the current code and explicitly reports that risk cannot be judged when no market-state fact exists, instead of claiming that no risk gate was triggered.
- Hardened the V5 dashboard supervisor runner against orphaned listeners: it replaces only a listener whose command line proves it is this repository's V5 dashboard, refuses destructive takeover of any foreign port owner, and verifies the port is free before launch.
- Made the 14:53 task dependency gate ownership-aware: while V4 remains the sole paper writer the V5 shadow health task excludes paper tasks, but after a separately authorized V5 cutover it cannot start unless both the next-open sell and 14:50 buy task have immutable SUCCESS records.
- Tightened the read-only product projection so the dashboard cannot combine a latest acquisition, mother pool and confirmation from different immutable lineages after retries; snapshot acceptance and same-day mother-pool identity must match or the page fails closed.
- Corrected next-open exit accounting: a missing bid or insufficient bid depth now creates an immutable rejected sell event and returns `UNFILLED` instead of silently reporting `FILLED`; V5-owned health rejects any still-open position whose eligible sell date has arrived. Round-trip derivation was also reduced from repeated ledger scans to one validated pass for long histories.
- Made the comparable confirmed-set baseline execution-equivalent to the paper account: initial CNY 100,000, per-symbol one-third cap, board lots, top-of-book depth, slippage, minimum/proportional commission and sell stamp tax now determine shares and portfolio return. The former cost-free average could no longer make the strategy comparison artificially harsher or internally inconsistent.
- Fixed the readiness module CLI so `--trade-date` and `--data-dir` are actually parsed and passed to the report instead of being silently ignored; manual and scheduled acceptance can no longer claim it probed a requested date while recording the current date.
- Added the previously missing per-trade-date 08:30 V5 readiness task to the safe shadow cohort. It prepares and validates the native universe behind the strict clock gate, probes both transports, carries an explicit date, and performs no candidate notification, paper or broker write. Production static audit now requires exactly one readiness task alongside the seven downstream shadow tasks.
- Hardened real-source acquisition: consensus now refuses the same source identity or same instance masquerading as two independent providers. Eastmoney full-market capture derives its page count from the provider's actual returned page size, supports server-side downscaling beyond twenty pages, caps unreasonable pagination, and rejects incomplete traversal instead of quietly yielding sub-95% coverage.
- Made operational-alert attempts append-only instead of overwriting a fixed failure file on retry. Persisted error text is bounded and the configured PushPlus token is redacted before hashing, display or audit storage; only a real accepted receipt suppresses repeat delivery.
- Made dashboard fact corruption and lineage failures explicit product states: readers no longer collapse invalid JSON/contracts into "no data", and both HTML and API return a cache-disabled HTTP 503 validation response without stack details or stale-decision fallback.
- Changed V5 readiness evidence from a mutable wall-clock filename to atomic content-addressed reports under the requested trade date. Identical retries are idempotent and distinct attempts cannot overwrite one another.
- Removed the last mutable market-decision artifacts: source-consensus reports are content-addressed, and the single 14:49 freeze pointer is create-once with collision rejection. Dashboard source/coverage now come from the attempt whose snapshot ID was actually selected, while retaining both complete provider identities for transparency.
- Made next-open execution outcome authoritative at the scheduler boundary: `UNFILLED` and `PARTIALLY_FILLED` now persist their paper events but fail the task and trigger operational handling; only a complete fill or a genuine no-position/no-baseline no-op records SUCCESS.
- Applied the same scheduler truth rule to 14:50 paper buys: an immutable engine rejection can no longer be reported as a successful task run.
- Completed immutable storage hardening for two remaining paths: universe facts now use atomic create-once writes under concurrent preparation, and each maintenance scan is a content-addressed manifest instead of overwriting the day's previous audit evidence.
- Serialized each V5 business-notification stage across processes. Concurrent retries now recheck the immutable accepted receipt under a Windows file lock, send PushPlus at most once, and atomically create both attempt and final receipt artifacts.
- Corrected confirmation ranking leakage-by-rescaling: the 14:49 confirmation no longer recomputes factor percentiles inside the much smaller mother pool. It uses the frozen morning full-market score, percentile and rank, while current data may only remove ineligible names and record changes. This restores comparability and prevents small-pool rank distortion.
- Kept deterministic end-to-end replay on that exact production path by passing the immutable morning candidate baseline into confirmation; replay can no longer silently exercise a different ranking policy.
- Embedded the complete funnel policy parameters and factor weights into every content-addressed funnel fact. The current CNY 5 million cumulative-turnover threshold remains explicitly pending calibration against real 09:25 and 14:49 distributions; it was not changed without evidence.
- Corrected the investable-universe scope: STAR Market `688/689` securities are now retained, with a one-time expansion-only anomaly exception that requires every prior code to remain. The product explicitly states "SSE/SZSE A shares including STAR, excluding BSE" because the current independent Sina source cannot validate BSE; it no longer labels a partial universe as all A shares.
- Corrected Sina limit-band parsing for STAR Market `688/689` securities to the 20% band (like ChiNext) instead of the main-board 10% band, preventing false limit-lock classifications after expanding the universe.
- Fixed the daily universe anomaly baseline to select the latest causal entity by timezone-aware `created_at`, not by a content-hash filename; future rehearsal facts and random same-day older retries cannot become the comparison baseline.
- Added bounded Windows Task Scheduler recovery (three retries, two minutes apart) to each dated V5 shadow task, including 08:30 readiness. Strict-window entrypoints still reject late retries, so recovery cannot fabricate missed-window evidence; static production audit now requires the retry contract.
- Added a read-only daily V5 live-acceptance summary/CLI that joins readiness, immutable task outcomes, both HTTP 200 notification receipts, acquisition stages, full lineage, paper reconciliation/recovery and strict round-trip count. It exits nonzero until the actual window chain is complete and never creates evidence itself.
- Added a bounded, official-calendar-driven shadow-horizon registrar for up to ten future trading days. It delegates only to the accepted eight-task safe manifest and cannot register paper or broker actions; production horizon expansion remains an explicit deployment action.
- Added a dated 15:20 read-only acceptance task to every safe cohort. It persists a content-addressed summary of the day's actual readiness, runs, notification receipts, lineage and paper health; a failed/incomplete chain remains a nonzero task result and cannot be converted into success evidence.
- Reconciled machine-readable deployment state with the current cohort: nine dated safe tasks consist of seven shadow business tasks plus 08:30 readiness and 15:20 acceptance; the two deliberately missing business tasks remain paper sell/buy under the single-writer gate.
- Added content-addressed V5 point-in-time universe facts and strict two-source consensus without coverage merging.
- Added V5-native immutable market snapshots and an independent Eastmoney adapter.
- Added V5-native event-sourced paper ledger with fees, slippage, one-third cap, T+1, immutable rejections, idempotency and reconciliation.
- Upgraded the candidate funnel to frozen explainable factors, risk filters and contribution lineage; scores remain research ranks, not probabilities.
- Added a disabled-by-default nine-task shadow schedule with no notifications, broker orders or V4 writes.
- Added deterministic frozen end-to-end replay through next-session sell and insufficient-evidence performance projection.
- Extended the V5 dashboard projection with data time/source/snapshot lineage and per-candidate risks.
- Retired V4 notification execution at the scheduled adapter boundary and registered one-shot V5-only PushPlus tasks for 2026-08-14. V5 notifications project the same final V5 pool/confirmation facts as the dashboard, persist parent entity IDs and payload hashes, and fail closed when V5 facts are missing or invalid.
- Added a V5-native Sina adapter, one-time universe seed boundary, V5 fact-production jobs, a paper-production adapter and a read-only independence audit. Registered V5 fact jobs before the two V5 notification jobs for the 2026-08-14 shadow window; paper production remains unregistered to prevent dual writes.
- Corrected the V5 nine-task business inventory, separated 14:49 feature freeze from 14:50 confirmation, added immutable health/maintenance/recovery artifacts, production ownership and report-only atomic cutover contracts, and registered seven safe shadow tasks. Paper buy/sell remain gated to prevent dual writers. Added an expiring diagnostic-only weekend preflight task that cannot create strict evidence, notifications or paper writes.
- Closed the live-window causality gap: 14:50 confirmation now consumes only the content-addressed 14:49 frozen snapshot, signal acquisition lineage is persisted, and morning/confirmation notifications bind to their own acquisition stage. Unified the three remaining one-shot job actions behind the immutable V5 task runner. Shadow health explicitly excludes paper tasks while V4 retains exclusive ledger ownership and reports `production_complete=false` instead of claiming full cutover. Full suite: 278 passed.
- Added provider-wide 25-second acquisition budgets and concurrent independent-source capture, while preserving deterministic source audit order and the unchanged 95% gates. Replaced hash-filename "latest" selection with timezone-aware entity timestamps. Added fail-closed daily lineage acceptance from morning/signal acquisition through frozen snapshots, mother-pool confirmation and both HTTP 200 notification receipts, and embedded it in 14:53 health. Full suite: 283 passed.
- Rebuilt the V5 preview as the requested single-page research product: market conclusion, current action, recommendation/empty reason, execution rules, frozen quote lineage, paper account and strategy evidence now share one scroll flow. Candidate facts retain last/bid/ask, provider and quote time from their immutable input snapshot; morning candidates never show an entry price and confirmed candidates show only the frozen ask reference. Browser DOM and responsive visual checks passed; full suite: 284 passed.
- Hardened operational continuity: health no longer reports its currently-running health task as missed; rejected PushPlus attempts are immutable but no longer poison the final receipt path, so a later real HTTP 200 can safely succeed. Push content now mirrors the single-page conclusion, risks and execution rules. Added a V5-native daily market-directory universe refresh with prior-count/churn gates, corrected full-content universe IDs and latest-universe selection, and prepared an admin-gated seven-task Monday registration script with no paper/broker tasks. Registration was attempted but Windows denied the non-elevated process token; no false success is recorded. Full suite: 291 passed.
- Separated the daily V5 universe preparation to 08:55 so the 09:24:30 mother-pool task retains its full 50-second push window and does not immediately repeat the Eastmoney directory request. Added a 12-second universe-wide budget, complete-pagination proof, fail-closed timeout/incomplete-page tests, and atomic immutable shadow-run writes. The administrator registration manifest now verifies eight safe tasks (universe preparation plus seven shadow tasks), still excluding paper and broker actions. Reconciled the V5 charter and historical dashboard review with the current single-page product. Full suite: 293 passed.
- Upgraded the existing 08:30 V5 readiness task to prepare the workday universe without creating strict-window evidence, notifications or paper writes. Added bounded retry and multiple Eastmoney access hosts under the same provider identity, dynamic pagination based on the provider's actual 100-row pages, and a one-time fail-closed legacy-seed-to-native-directory expansion contract. Real rehearsal returned all 5,549 directory rows and published a 4,930-code V5 universe only after proving 100% retention of the 4,399-code seed plus 531 additions. All eight 2026-08-14 V5 actions were re-audited Ready. Full suite: 297 passed.
- Strengthened V5 source independence from adapter-name checking to quote-level lineage checking: every quote in a selected snapshot must carry the exact source identity. A mislabeled or same-source snapshot now fails closed in both fallback and consensus acquisition. Updated production/replay fixtures to prove genuine dual-source lineage; full suite: 351 passed and production task static audit passed.
- Made PushPlus a complete projection of the same final V5 entity used by the dashboard: it no longer truncates confirmation candidates and now carries ordered candidate codes/count plus snapshot and market-state lineage in the hashed payload. Corrected shadow recovery so deliberately excluded unowned paper tasks cannot remain phantom blockers of health or maintenance. Full suite: 352 passed.
- Corrected the strategy-admission baseline from all-confirmed equal weight to the exact production Top1 exposure: same frozen ask, one-third capital cap, fees/slippage and next-session bid. Performance v2 now reports all strict paper round trips separately from same-confirmation paired comparison trades; only paired Top1 returns can support a baseline conclusion, so 40 unpaired trades remain insufficient evidence. Full suite: 353 passed.
- Prevented failed next-open exits from creating comparison evidence. Insufficient bid depth and other unfilled attempts remain immutable rejected events and may be retried within the strict continuous-auction window, but a Top1 paired baseline is now persisted only after all due paper positions actually fill. Full suite: 354 passed.
- Closed a coverage-denominator loophole at the provider boundary. Consensus now requires each independent snapshot's `expected_codes` to equal the requested immutable universe size, so an adapter cannot manufacture 95% coverage by silently shrinking its denominator. Full suite: 355 passed.
- Added a send-time freshness gate to production V5 notifications. PushPlus must now load the exact immutable snapshot named by the final entity and prove every quote is causal and no more than 120 seconds old at delivery; missing, future or stale snapshot content fails closed instead of sending old candidates. Full suite: 356 passed.
- Unified dashboard and PushPlus market-state integrity. If a decision entity names a market state, the file must exist, validate its own content hash, carry the exact named market-state ID and match the decision snapshot; missing or substituted state now produces a fail-closed 503/no-send rather than an empty market panel. Full suite: 357 passed.
- Serialized operational failure alerts by immutable failure fingerprint. Concurrent scheduler retry/manual recovery can no longer send duplicate PushPlus alerts for the same incident; rejected attempts remain auditable, accepted receipts remain idempotent and alert delivery stays separate from candidate snapshot freshness. Full suite: 358 passed.
- Added bounded same-provider host failover to the Eastmoney real-time adapter. Four Eastmoney endpoints rotate inside the original 25-second acquisition budget without being miscounted as independent sources; quote lineage remains `eastmoney_realtime_full_market`, and stale overnight quotes still fail strict snapshot gates. Full suite: 359 passed.
- Added one bounded full-batch retry to the Sina real-time adapter under the existing 25-second source budget. A transient disconnect can recover without losing an entire 700-symbol batch; exhausted retries still fail the whole snapshot and cannot lower the 95% gate. Full suite: 360 passed.
- Refreshed the machine-readable Windows/NTP blocker from stale documentation to the latest raw stripchart evidence: approximately 0.85 seconds offset versus the unchanged 0.5-second causal threshold. The gate remains fail-closed and still requires an elevated Windows token to repair; no threshold was weakened.
- Closed remaining content-address read gaps. Snapshot consumers now require JSON-declared ID, rebuilt snapshot hash and filename to agree before confirmation, paper execution or baseline use. PushPlus reconstructs morning/confirmation entities and verifies their content IDs before projecting candidates, so edits to codes, ranks, reasons, risks or lineage fail closed. Replaced hand-written fake-ID test fixtures with real immutable entities. Full suite: 361 passed.
- Upgraded daily live-lineage acceptance from declaration comparison to independent reconstruction. It now rebuilds and verifies both acquisition-session IDs, morning-pool and confirmation IDs, both snapshot content addresses, both market-state IDs/snapshot links, the freeze pointer and both notification payload/receipt lineages. Forged or mutually self-consistent substituted files cannot produce a passing 15:20 summary. Full suite: 362 passed.
- Upgraded the 15:20 acceptance summary to v2 task truth. Every immutable run artifact must match its content-derived `run_id` and filename; the summary exposes attempt count, ever-success, latest outcome and latest run ID per task. Completion requires each required task's latest valid attempt to be SUCCESS, so an earlier success cannot hide a later failure and edited run JSON cannot manufacture completion. Full suite: 363 passed.
- Applied the same immutable validation to 08:30 readiness evidence consumed at 15:20. Filename, content-derived report ID, trade date, `diagnostic_only=true` and `strict_evidence=false` are mandatory; corrupted or edited passed reports are excluded, surfaced as validation errors and cannot satisfy completion. Full suite: 364 passed.
- Made top-level notification truth in the 15:20 summary depend on the full daily lineage audit, not merely receipt fields. A stage is true only when HTTP 200/ACCEPTED, parent entity, payload hash, rebuilt decision entity, snapshot and market-state lineage all agree; forged 200 receipts remain false. Full suite: 365 passed.
# 2026-08-28 — V5.1 offline Runtime repair

- Enforced physical mode/cohort isolation, Windows held-handle stage locking,
  strict idempotent entity validation, dual-source daily-status evidence and
  conservative sell execution persistence.
- Added immutable health, acceptance and legal flat-stage outcomes; dashboard
  now distinguishes current missed windows, historical/non-trading no-evidence,
  partial lineage, quarantine and recovered latest attempts.
- Added ownership-gated V5.1 notification stages. No real notification was
  sent and V5 remains notification/production owner.
- Offline result: 61 V5.1 tests and 568 repository tests passed. Real-window
  acceptance remains pending; cutover readiness is NO; effectiveness is
  unproven.

## Independent Runtime re-review

- Corrected BUY execution chronology so fill time is captured after the real
  provider acquisition; the five-second quote-age boundary remains unchanged.
- Added immutable execution-stage intent/result/rejection counts and explicit
  `ALL_FILLED`, `PARTIAL_FILL`, `NO_STRICT_FILL`, `EXECUTION_REJECTED`,
  `FAIL_CLOSED`, and true zero-intent `ACTIVE_FLAT` semantics.
- Health and Acceptance now consume the execution-stage fact and require one
  unique audit result or rejection per intent.
- REPLAY/TEST are rejected from production/shadow roots and descendants.
- New result: 73 V5.1 tests and 580 repository tests passed. Runtime is
  implemented, but final acceptance remains blocked by the missing live
  independent SSE/SZSE Security Master verification path.
