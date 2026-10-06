# 项目任务记录

阶段状态以 [`agent.md`](../agent.md) 为准。本文件记录每次任务的实际工作、验证和审查结果。

## 2026-10-06：共同截止执行器与完整循环校准

- **范围**：实现八个开发题的 128 条原生轨迹和单个 Flash 公开错误状态的 16 条续跑，比较独立重采样/反馈修复、Flash/Pro、0/1 秒工具延迟；每条在两个共同截止产生相关快照，保留完整分母。尚未开始真实模型对照。
- **实现**：在线记录首稿、每轮候选、公开反馈、可用时间、实际快照交付、token/费用和截止后的清理；隐藏评分仅允许终态后独立执行。静态准备在整组预留之前；请求保护只截尾当前轨迹，未知费用/资源失败停止批次。
- **校准**：最终源码 `29b3bd27` 上的 16 路径、32 完整轮全部完成，48 个模拟 HTTP、32 个真实公开判定容器及 helper 全部闭合，无计时截尾。依预定公式冻结 5/15 秒和 64 请求保护。校准为零模型调用，旧版及中断记录保留；详见[协议](research/coding-deadline.md)。
- **审查/验证**：实际 Claude Opus 5.5 完成协议、初始代码和两轮聚焦审查，最终未发现在线代码阻断；修复未使用反馈投影、重复取消、同步回收和校准计数别名。最终源码额外验证单 SIGINT、helper 提前退出及五项准入/保护场景通过。各版本证据单列于[验证记录](../research/results/coding-deadline-validation.json)，不将旧版检查泛称最终全套通过。
- **离线评分**：缺失候选分类、真实 admission/runner 的 settle 与 cancel-stop 产物衔接、镜像绑定及中断回收通过 11 项聚焦模拟检查；正常返回但清理失败的精确回收另通过 `--missing-cleanup` 单项检查。实际 Claude Opus 5.5 增量复审与该三行修复的短审均通过；不声称重跑完整 suite。旧版五身份/十真实容器 smoke 保留，最终版本真实路径在首批离线评分核验。
- **待完成**：提交/推送后在原累计 200 元额度内启用 120 元批次保护并运行真实矩阵。当前研究已知估算仍为 0.344484448 元，所有实验合计 0.506995744 元，非账单且不含 Claude 审查。以上均为工程验证，尚无共同 deadline 下的模型比较结果。

## 2026-10-06：相关工作的路由近邻增量核查

- **范围**：再次从正式顶会、近期轨迹研究与反例三条线核验当前选题；新增 Harness-Native Data Flywheel、ORACLE v4 与 BEST-Route，文献表增至 35 篇。前两篇本轮仅核验预印本身份，BEST-Route 由 PMLR 确认为 ICML 2025 正式论文。
- **核验**：区分逐步状态路由和任务入口固定模型；ORACLE 版本记录显示 7 月 v1 题为 TRACE-Router，10 月 v4 已改题和作者列表，不能混用结果。EFC v2 的前缀控制及留出泛化意味着不能以这两个宽泛标签单独主张创新。
- **影响**：候选仍为反馈信号在共同 deadline、新任务与变化速度下对模型相对优势的额外预测价值。检索未确认全目标已有完整验证，也不宣称首次。README 已有相关工作入口，内容仍准确，未作无意义修改。
- **验证/审查**：35 条参考文献编号、相关文档本地链接及 diff 检查通过；实际 Claude CLI 为 Opus 5.5、exit 0，无阻断。已处理措辞、基线和版本意见，另据原文保留 DISC 入口后端选择及 PMLR 官方链接；见[审查记录](reviews/2026-10-06-routing-literature.md)。本轮无模型实验或运行时变更。

## 2026-10-06：编程隔离环境准备

- **实现**：固定 HumanEval/0 的预设候选容器执行；候选非 root、无网络及宿主挂载、只读根、资源和输出上限。只使用并验证本机原生 WSL Docker daemon。固定 EvalPlus/HumanEval+ 资产哈希、展开源码清单和不可变许可证来源。
- **验证**：5 个真实容器场景全部通过；canonical 1006/1006，known-wrong 199/1006 被正确拒绝，无限循环和两种输出洪泛被终止并清理。9 个增量 probe 全部通过，涵盖身份/哈希拒绝、二次中断、未启动容器清理和自动删除。零模型调用、零 API 支出；[脱敏证据](../research/results/coding-environment-validation.json)与当前源码 hash 一致。
- **审查**：两轮实际 Claude CLI 均为 Opus 5.5、exit 0，无该窄范围阻断；已修正 daemon/资产来源问题，其余具体边界记录在[处置说明](reviews/2026-10-06-coding-environment.md)。清理中的 SIGINT 是忽略而非延后，不能泛称所有终止方式均安全清理。
- **未完成**：完整 EvalPlus evaluator、通用候选判定、可见检查/隐藏验收隔离及统一 agent deadline。当前是 R3 准备，不能当作 R3/R4 实验结果。用法见[环境说明](research/coding-environment.md)。README 研究状态仍准确。

## 2026-10-06：R2 容量与批次中断修正

- **容量**：保留 32/64 步。R1 数值外推确认原 48 KB/5 元限制不足；消息 JSON 放宽至 256 KB、整请求 1 MiB，Flash/Pro32/Pro64 的保护上限为 5/10/20 元，累计仍为 200 元。敏感性假设及理论边界见 [容量核查](../research/results/timely-capacity-analysis.json)。
- **修正**：验证拒绝持久停止；SIGHUP/SIGQUIT 清理所属子进程树；显式 R1 导入清单先验证后登记；fsync 后中断先重载账本，损坏链不再追加记录。提示保留原终止语法，停止计划不自动重试或重新领取额度。
- **验证**：transport 30/30、完整 runner 19/19、batch fixture 43/43 通过，全部零 API。首轮 runner 检查仍用旧容量断言而失败，已同步断言后完整重跑，旧记录保留。协调器真实 evaluator 的新一轮零 API 集成在第八条因官方负耗时停止，全部请求用量闭合；该失败保留；独立重跑后真实官方 evaluator/ROM 的全部 24 条矩阵通过，144 个原始产物 hash 核对一致，未修改官方时钟。
- **审查**：此前实际 Claude Opus 5.5 的 B1 集成缺口已有旧版 8 校准+1 timed 证据；B2 容量问题已量化并修正。实际增量审查已完成，Opus 5.5 无必须修改代码的阻断。复核截止路径 4/4 与别名规范化源码；Pro 无真实历史证据，首请求不兼容即停止。停止与完整修订规则已预写；见[审查处置](reviews/2026-10-06-timely-batch.md)。此时 R2 付费尚未开始。

## 2026-10-06：顶会与同期工作的再次核验

- **范围**：独立核验 Timely、CUDAnalyst、EvoRoute、AgentTTS、Snell 和 HPCA 的正式身份，复核 EFC、SWE-Router、SSA、LEAP 与 Agents Are Systems 的重合及边界；新增 Apple/EPFL 的 MLE harness 论文，相关工作表共 32 篇。
- **结论**：共同时间曲线、轨迹解释、有效反馈和前缀路由均已有先行。候选问题继续限定为决策时可得信号对留出任务及改变延迟后的跨模型 deadline 质量差是否有额外预测价值，不声明已确认新颖性。
- **协议影响**：告知预算及回合末剩余时间提醒可能影响行为，对看到预算的策略不把长运行前缀直接视作短 deadline 运行；区分实际选出的提交和隐藏评分最优候选。README 研究问题仍准确，无需为本轮文献修改。
- **验证**：主会身份由官方 proceedings 核验；新增论文的日期、方法和作者由 arXiv 全文及 Apple 研究页核验，未确认正式录用。33 个本地链接与 staged diff 检查通过；没有模型实验调用或运行时修改。实际 Claude Opus 5.5 文档审查无阻断，已处理因果措辞和核验口径等意见，见[审查记录](reviews/2026-10-06-latest-literature.md)。

## 2026-10-06：首条真实 Timely 轨迹与格式兼容诊断

- **真实结果**：原提示、Zork1、`deepseek-flash`、8 步，8 次请求闭合，7 次工具执行，真实得分 5/350，未通关。墙钟 7.6183 秒，官方逻辑时间 13.8546 秒含 6.2 秒虚拟工具延迟。估算费用 0.008655072 元，无未知费用；计入当前累计 200 元先导。此前独立批次与本次合计估算 0.171166368 元，非账单。
- **发现**：官方提示允许多个调用而执行器只执行首个；首轮两个额外调用被忽略。第 6 轮输出 DSML、无法解析，第 7 轮在原错误反馈后恢复。技术证据完整，协议与校准门槛未过；原 τ 保留但不供 R2 使用。脱敏结果及原文件 hash 见 [R1](../research/results/timely-r1.json)，原始响应留忽略目录。
- **处理**：增加单独命名的 `single-json-v1` 提示条件，统一两模型的单工具 JSON 格式，保留 `official` 默认和原始结果；不改源码、解析器、评分或校准门槛。同步 README、agent.md、执行计划和命令说明。
- **批次边界**：固定研究登记、完整历史费用导入、整组预留、Linux 子孙进程回收以及完成后校准重验，已有 32 项离线 fixture 通过，0 Provider 调用。新增提示条件的完整 E2E 和 Claude 审查尚在执行；本条不声明 R2 已启动或成功。
- **后续**：通过新增条件的审查后冻结单游戏 24 条矩阵；再按计划扩到四游戏和编程机制实验。编程环境准备可独立进行，现有 Docker/旧 smoke 不等于严格 deadline 与隐藏验收已经就绪。

## 2026-10-05：P0 仓库与协作规范初始化

- **任务范围**：初始化用户指定的本地仓库与 GitHub remote，建立项目计划、进度和工程工作流程。
- **已完成**：确认本地目录与远端均为空；初始化 `main`；配置 `origin`；创建 `agent.md`、工具指令入口、README、忽略规则和审查文档。
- **验证**：Git、GitHub 账户认证和 Claude CLI 可用；10 个本地文档链接、`git diff --cached --check`、敏感/生成目录忽略规则检查通过。当前没有可执行功能，不声明运行时端到端验证通过。
- **Claude 审查**：已通过 Claude Code CLI 2.1.289 执行，退出码 0，无阻断发现；CLI 当前配置的后端为 `deepseek-v4-pro`。已处理文档一致性建议，详见[审查记录](reviews/2026-10-05-bootstrap.md)。
- **Git 同步**：初始化提交 `2887f2a` 已通过 `git push -u origin main` 推送；`git rev-parse HEAD` 与 `git ls-remote origin refs/heads/main` 核对一致，工作区干净。随后将本次同步结果补记到状态文档，作为独立文档提交同步。
- **下一步**：开始 P1 的事件与本地记录闭环。

## 2026-10-05：补齐任务分类路由与任务拓展计划

- **任务范围**：根据用户原始三条主线，补齐完整记录、任务分类与模型/Agent 分配、跨任务领域评估的计划；本次仅修改文档。
- **已完成**：在 `agent.md` 定义任务画像、冷启动和 trace 的使用边界、任务级配置选择与执行中模型调整；定义质量约束下的时间/费用比较；明确问答、编程、购物的场景、评分与阶段安排。同步阶段交付物和审查清单；按用户补充要求将 README 改为简短英文，并约定后续 Claude CLI 审查不主动设置费用/轮次上限。
- **验证**：新增审查记录后再次检查，8 个文档相对链接、README 英文与 LF 行尾、`git diff --check` 全部通过；README 为 21 行。未实现运行时功能，不声明端到端测试通过。
- **Claude 审查**：首次调用触及当时设置的额度上限，无有效结论；改为提供完整文档/diff 且关闭工具调用后，CLI 退出码 0，无阻断问题。已处理探测隔离、切换边界等设计建议，详见[审查记录](reviews/2026-10-05-task-routing-plan.md)。用户随后取消后续审查的默认额度/轮次限制，已写入规范。
- **Git 同步**：变更提交 `758da70` 已推送到 `origin/main`，本地 HEAD 与远端引用核对一致，工作区干净；本条同步结果随后作为独立文档记录提交。
- **下一步**：开始 P1 事件和本地记录；先完成问答与编程的实验准备，购物沙箱按后续阶段推进。

## 2026-10-05：切换 Claude CLI 默认审查模型

- **任务范围**：检查并切换本机 Claude CLI 默认模型，说明下一阶段 P1；未实现运行时代码。
- **已完成**：原用户设置为 `opus`，但继承环境将模型与端点覆盖为 DeepSeek。在本机用户设置中固定 `claude-opus-5-5`、使用官方端点与已有 Claude 登录，并覆盖旧模型映射；已备份原设置。项目约定同步记录默认审查模型，README 仍准确，无需修改。
- **验证**：不传 `--model` 的最小 CLI 请求退出码 0、返回 `OK`，`modelUsage` 为 `claude-opus-5-5`；认证方式为 `claude.ai`。此验证仅证明本机 CLI 默认调用可用，不代表 TracePilot 运行时已通过测试。
- **验证命令**：PowerShell 中将 `Validation only. Reply exactly OK. Do not use tools or inspect files.` 通过 stdin 传入 `claude --print --permission-mode plan --permission-prompts none --tools= --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json`，未传 `--model`。读取 JSON 的 `is_error`、`result` 和 `modelUsage` 核验。
- **Claude 审查**：Opus 5.5 已对本次 diff 完成只读审查，退出码 0、实际模型 `claude-opus-5-5`，无阻断问题；未设置费用或轮次上限。已采纳模型不符时重新审查、统一配置措辞、补全验证命令和最近更新等建议。
- **已知边界**：本机用户配置与备份不提交到仓库；模型约定与脱敏验证结论入库。P1 仍待开始。
- **下一步**：P1 依次完成事件格式、按运行隔离的本地状态、开销统计、JSONL 采集、Langfuse 导出和端到端验收。

## 2026-10-05：Langfuse 部署配置与自研 Agent 适配

- **任务范围**：先实施 Langfuse 独立部署/SDK 接入与现有 harness 执行边界埋点；保留内部 AgentState，不提前实现 router 或通用插件引擎。
- **已实现**：可安装 Python 包与可选依赖、固定版本/镜像 digest 的本地 Compose 配置、幂等部署脚本、`TracedReActLoop`、完整 E2E 示例与接入说明。旧 Agent 仓库的未提交改动保持原样。
- **记录范围**：完整运行、主模型 generation、工具业务状态、初始 RAG、context 管理；正文默认关闭，用量区分 reported/estimated/unknown，根 ledger 只作核对。后台导出由调用方拥有的官方 SDK 管理。
- **E2E 验证**：`.venv/Scripts/python.exe examples/harness_smoke.py --harness-path '../agent/agent-harness-from-scratch' --live --env-file .local/langfuse/sdk.env --report .local/harness-smoke-live.json` 退出码 0；真实 harness/词法检索/官方 SDK/本地 Langfuse 写入并读回 **19 条 trace、115 个 observations**。18 项流程检查覆盖答案/token 与原 loop 一致，失败→反思→恢复，共享 loop 线程/异步并发，同线程交错，流式完整/提前关闭，最终事件后关闭，超时/取消，致命错误，暂停续跑增量，恶意工具名/ID 脱敏，telemetry 创建/update/end 失败降级；核对 run/父子隔离、起止时间、正文关闭与用量来源。内存导出同样通过。LLM 与 fetch 是合成实现，付费模型调用为 0；不作为模型能力或真实费用证据。
- **基础检查**：Python 3.12.14、Langfuse SDK 4.17.0；`pip check`、`git diff --check` 通过。部署脚本语法/Compose 配置、重复执行保留凭证、进程环境恢复、并发 setup lock、6 个镜像 digest 与 2 个 loopback 映射检查通过。凭证、虚拟环境和运行结果均被 Git 忽略。
- **基础设施状态**：首次镜像拉取发生 Docker EOF/API 500，重启时发现两组 Windows 运行时 socket 残留；自动审批拒绝删除后，由用户手动清理，保留镜像、数据卷和配置。随后 6 个容器成功运行，依赖健康，`/api/public/health` 返回 OK / 4.50.0，项目 API 鉴权 HTTP 200。初次 live 读回发现 v4 events_only 模式不支持旧 trace API（404），改用 observations v2 后上述 E2E 通过。
- **修复与审查**：调试修复 SDK 子 observation 的根标记，以及结果已发出后关闭 generator 被误记为取消。按 Claude 发现补齐遥测派生计算容错、未知工具名/ID 和动态终止原因脱敏、恢复段 token 增量、清理时取消信号传播、估算费用标识及边界 E2E。初审、完整代码复审、依赖增量审查均由实际 `claude-opus-5-5` 完成，退出码 0；复审无阻断问题，未设置费用/轮次上限。Claude 做静态审查，E2E 由执行者运行；剩余建议及支持边界见[审查记录](reviews/2026-10-05-langfuse-pilot.md)。
- **干净安装复验**：发现外部 harness 在 `import agent` 时必须导入 PyYAML，已补进 `pilot` extra 并固定验证版本 6.0.3。在新建 `.local/clean-venv` 中按 `constraints-pilot.txt` 安装后，完整合成 E2E（SDK 内存导出）再次得到 19 traces / 115 observations。原环境真实服务端读回已通过；本次仅补齐依赖声明，没有修改运行时行为。
- **已知边界**：隐藏 Provider 重试、辅助模型/embedding 的逐次耗时和费用尚未拆分；原有共享模型/工具/provider 的线程安全仍由调用方负责。JSONL、本地路由前缀、分类路由及论文实验尚未实现。
- **下一步**：根据已采集的记录决定 TracePilot 事件语义和最小本地前缀，再补齐辅助调用/重试开销与 JSONL。

## 2026-10-05：研究方向可行性讨论

- **任务范围**：按用户要求，与 Claude 讨论少数据/迁移路由和基于 trace 的升级决策，补查相似研究与备选方向，准备次日阅读笔记；仅修改文档。
- **已完成**：实际 Claude Opus 5.5 两轮讨论；补检更直接的 Calibration Is Not Control、TACIT-Switch、The Handoff Tax 等，调整新颖性判断。新增 [研究方向与阅读笔记](research-directions.md)，记录 A/B 的风险、时延分布与反思备选、必要对照、预算账本和继续/停止条件。同步 `agent.md` 与 README 的文档入口，P1–P5 实现状态保持真实。
- **讨论边界**：首次 CLI 请求 529 过载，重试成功；两轮 `modelUsage` 均为 `claude-opus-5-5`。Claude 使用 Codex 提供的证据摘要，没有自行浏览；已处理其初版的任务筛选、非显著性解释和成本公式问题。详见 [讨论与审查记录](reviews/2026-10-05-research-directions.md)。
- **验证与文档审查**：独立 Claude CLI 文档审查退出码 0、模型 `claude-opus-5-5`，未发现阻断问题；已处理月度排期/共享预算、重试与辅助计时、deadline 截断口径和单一 deadline 的局限。14 个 Markdown 文件的 22 个本地链接、英文 README（24 行）、尾随空格、`git diff --check` 与原始输出忽略规则检查通过。没有模型能力实验、付费批量调用或运行时代码改动，不声明 E2E 或论文复现通过。
- **下一步**：用户阅读核心论文后选择窄先导；工程继续补事件/JSONL 与用量边界。候选时延实验不以完整 router 或通用快照系统为前置条件。

## 2026-10-05：独立研究分支、论文审计与真实计时先导

- **保护范围**：原 `TracePilot` 工作区保持干净的 `main@dadab3f67a65f7a5e3a2d910b8d094255e6d60a8`。新 worktree `TracePilot-research-20261005` 使用 `research/acl-feasibility-20261005`；只向该研究分支提交推送。
- **研究工作**：核查 Timely Machine 的 ACL 最终版与固定官方源码，区分设计选择、公开实现行为和未知论文影响；补查顶会与直接预印本先行。适当使用 lateral/inversion 生成候选，再做文献否证。最新建议和次日阅读顺序见 [decision](research/decision.md)。
- **E0**：标准库脚本 `research/timely_audit.py` 验证固定提交和源文件 hash，并以明确的 fake/stub 运行不变 AST 定义。计时宽限、动作顺序、transcript 时钟奖励和噪声范围反例检查通过；不声称模型复现或论文结果失效。
- **E1**：独立串行 `research/timing_pilot.py` 的 fake E2E 和关键截止／计费／未知用量边界通过。Claude 初审发现延迟相位与链长首个 RNG 抽样耦合，已在任何付费调用前用 `latency-phase:{seed}` 独立种子修复，重新完成 32 runs / 136 fake requests；fake 费用不计入研究支出。
- **真实开发批次**：`dev --execute-paid --budget-cny 10 --max-calls 60`，本地批次 `.local/timing-pilot/dev-20261005-reviewed`，8 runs / 26 requests；工具 4/4 完整成功，无工具 0/4。预声明公式得出 10s deadline，随后冻结。
- **真实 probe**：`probe --execute-paid --deadline 10 --budget-cny 50 --max-calls 384`，本地批次 `.local/timing-pilot/probe-20261005-d10`，32 runs / 165 requests。Countdown 与 deadline-only 各 9/16 完整按时成功。三次晚返回计费但不算及时成功，全部请求在截止前派发；独立从原始 JSONL 重算通过。总峰值价格估算 0.13446048 元（非账单；Claude 订阅审查另计）。完整结果、口径与局限见 [pilot-results](research/pilot-results.md)。
- **审查**：两轮 Claude Opus 5.5 计划讨论、完整代码审查与相位修复复审，实际模型均为 `claude-opus-5-5`，复审无阻断。之后完成证据／开源 Agent 计划审查、双 runner 完整审查和增量复审。E0 证据标签进一步收紧；[处置记录](reviews/2026-10-05-overnight-research.md)。
- **开源 Agent 部署与执行**：Pi `@earendil-works/pi-coding-agent@1.0.3` 使用本地 npm 目录，mini-SWE-agent `2.4.6` 使用独立 venv；原项目及全局配置保持原状。两套 runner 初审后真实调用；Pi 按初审建议做最小修复并通过 fake 后试跑，后续 delta review 再确认修复无阻断；mini 提示词修复则在 delta review 后补跑。使用当前 DeepSeek key，工具在无网络／无 key 的 Docker 中执行。Pi 正常 stop，mini 修正提示词后正常 Submitted，均通过五项验收与最终代码人工检查。它们是独立工程烟测，不代表正式库已完成跨框架支持。
- **开源 Agent 首轮与补跑预算**：Pi 首轮 4 次请求正常完成，mini 首轮 8 次请求产物正确但因适配器提示词含糊未正常提交；已澄清单独 `validate` 动作并经 Claude 复审无阻断。补跑前累计已知峰值估算：E1 0.13446048 + Pi 0.005496672 + mini 0.019653024 = **0.159610176 元**，未知计费预留为 0。mini 一次补跑最坏预留 0.393216 元，仍在 mini 累计 2 元及今晚 200 元范围内；保留首轮记录，不能只报告调整提示词后的结果。
- **补跑与最终计费**：mini 修正提示词后的 fake/live 均为 4 次请求并正常提交；新增真实估算 0.00290112 元。今晚真实 API 总计 **207 requests / 0.162511296 元峰值价格估算**（非账单），没有未知计费或余额不足报错；fake 不计费，Claude 审查使用量另计。脱敏 [结果](../research/results/open-agent-smoke.json)保留三次运行，包括首轮未完成的 mini workflow；最终无 Pi/mini 实验容器残留。
- **研究边界**：E1 是工程验证，任务几乎只有固定行动链，不能验证候选 C，也不构成模型能力排序。正式 router、通用 checkpoint、运行时 JSONL、跨域研究尚未完成。
- **最终检查**：Claude 最终产物审查无阻断，已处理 Pi 审查时间线、局部 provenance 字段、累计预算和研究措辞。29 个修改／新增文件的 55 个本地链接、Python AST、JavaScript 语法、JSON、README 英文、实际 key 字节缺席检查与忽略规则通过；`git diff --check` 通过。原工作区与远端 main 仍为 `dadab3f`。交付只面向 `research/acl-feasibility-20261005`，不合并 main。

## 2026-10-05：历史耗时决策方向二次查重

- **范围**：用户要求再次检索候选 C 的相关论文；并行检查时延预测／路由、时间感知行为、元推理和预测／控制分解，再核验原文。
- **新增依据**：JAUNT、NetMCP 已覆盖历史时延辅助路由；Can LLMs Perceive Time? 已测耗时自估和历史反馈校准，官方页面确认 ICLR 2026 ICBINB workshop poster；TicToc 已发表于 ACL 2026 Findings，包含同内容时间干预与 Think–Answer mismatch。重核 Lookahead-R 的 Cost-Shuffled 和 Calibration Is Not Control 的同前缀预测／控制比较。
- **结论更新**：宽泛方法组件已有先行；候选 C 只保留作小型实证探针，不把“尚未检索到完全相同控制组合”当作新颖性证明。详细差异、强基线与阅读优先级已同步到 [查重笔记](research/latency-history-check.md)、[方向说明](research/decision.md)和 `agent.md`。
- **边界**：本轮仅文献／文档工作，没有新增 Agent 能力实验或复现；原有试跑费用不变。README 仍准确，未作无意义修改。未核实的会议字段不冒称录用。
- **审查及验证**：Claude CLI 实际模型 `claude-opus-5-5`、`is_error=false`。已处理“推荐主线”旧标题与条件预算不一致、统一阅读顺序、将未见某实验的判断限定到已检查部分；详细处置追加到 [审查记录](reviews/2026-10-05-overnight-research.md)。文档相对链接、实际 key 缺席、忽略目录与 `git diff --check` 检查通过；无运行时代码改动，不声称新增 E2E。

## 2026-10-06：同时间下速度、反馈与能力的顶会/同期工作核查

- **范围**：围绕用户接受的快模型迭代机制与选型边界，按现象、反馈机制、路由泛化三条证据线检索原始论文，重点核验正式会议身份和最新版本。
- **已完成**：新增 [20 篇核心/直接相关工作核查](research/speed-feedback-related-work.md)，包括 11 篇已确认主会论文、1 篇正式期刊论文、7 篇本次仅核验为预印本的同期稿和 1 篇会议身份未完成独立论文集级核验的稿件。更正 EvoRoute 的 ACL 主会身份，核实 CUDAnalyst 的 ICML 主会身份；特别记录 EFC v2 的前缀在线控制及 NMI 正式版对泛化结论的收紧。
- **定位**：宽泛现象、轨迹指标和路由均有直接先行；当前候选问题是反馈利用机制能否增加共同 deadline 下的模型相对优势预测能力，并外推到留出任务与变化速度条件。不将“没有检到完全相同组合”视为新颖性证据。
- **文档一致性**：更新 `agent.md` 与 [当前决定](research/decision.md)，把历史耗时/紧迫感方案保留为历史候选。README 保持简短英文，研究入口改为当前决定，早期结果独立链接。P1–P5 状态不变。
- **边界**：本轮没有新增 Agent 能力实验或论文复现，没有新的实验 API 支出；原先 207 次请求的工程先导不能支持新方向。外部论文结果均未独立复现。
- **审查与验证**：两轮 Claude CLI 只读文档审查，退出码均为 0，`is_error=false`，实际模型均为 `claude-opus-5-5`，均未发现阻断问题。已落实信息时点、状态/任务分组、时间迁移、独立重采样及重计时基线等建议；详见 [审查与处置](reviews/2026-10-06-speed-feedback-literature.md)。文档链接、英文 README、凭证缺席、忽略规则和 `git diff --check` 已通过，原工作区 main 干净且未修改；无运行时改动，不声称新增 E2E。
- **下一步**：先冻结两个配置、客观编程任务、共同 deadline、反馈对照与留出预测的最小实验协议，再决定开发批次范围和费用上限。

## 2026-10-06：README 与 Timely 复现实验启动

- **授权范围**：用户要求完善项目 README，从 Timely Machine 复现开始再推进既定实验；完整目标保持 active。
- **文档**：README 保持英文，增加研究问题、顺序、状态与安装入口；新增 [执行计划](research/timely-reproduction.md)，分开官方代码协议复验、原论文数值复现和研究扩展。
- **来源核对**：官方 HEAD 仍为 `e13af2b`，本地源码干净；论文 Fig.2 使用未公开的 cold-start SFT checkpoints。公开版逻辑延迟并非真实 sleep，step 预算也非跨模型共同秒数。Jericho 新版本默认 seed 改变，优先隔离安装 3.2.1。
- **环境现状**：本机 GPU 为 RTX 4060 Laptop 8GB；Docker Desktop 启动因旧 secrets-engine socket 失败，没有删除 socket 或反复重启。Ubuntu WSL 独立环境现已通过官方 wrapper 动作/评分/同动作回放检查及 `pip check`；57 个 ROM 能 reset，其中 `lgop.z3` 不可靠支持评分，首批排除。依赖与证据在 `.local/timely-reproduction-env/`，零模型调用，尚无新真实模型评测结果。
- **预算**：第一条真实短轨迹上限 5 元/12 requests，先导累计上限 200 元，均计入原 2,000 元总预算；开始付费前完成代码审查和完整调用验证。
- **审查与验证**：README/计划已由 Claude CLI 实际模型 `claude-opus-5-5` 审查，`is_error=false`，未发现阻断问题；已落实能力状态、模型映射、测速请求、预算及格式失败口径建议。预算 transport 和 evaluator runner 仍需独立代码审查；未把准备状态写成已复现。

## 2026-10-06：顶会及同期工作补充核验

- **范围与新增**：按用户最新要求重新访问一手论文与正式论文集。新增 AutoLab、AgentOpt v2、How Many Tries、GAIATrace / Vidur-Agent、ASAP，相关工作表扩充为 25 篇；重新核验 Timely、AgentTTS、CUDAnalyst、SALE、EvoRoute、Snell 的主会身份。
- **关键边界**：AutoLab 已做真实工程任务轨迹与 pi 等 harness 对照，AgentOpt 已有记录和模型组合搜索库；EdgeBench 已预测同任务集的后段聚合曲线；Slow Down 将从早期特征预测单任务拐点列为未来方向。候选贡献不能概括成“首次轨迹分析/预测/选型”。
- **状态**：更新 [相关工作](research/speed-feedback-related-work.md)与 `agent.md`；英文 README 已检查，其研究入口和候选措辞仍准确。没有因文献检索启动新的付费模型评测。
- **验证与审查**：Claude CLI 退出码 0、`is_error=false`、实际模型 `claude-opus-5-5`，无阻断；已处理论文/代码预算语义、任务域衔接、独立抽样统计及状态措辞。来源核验及全部处置见 [审查记录](reviews/2026-10-06-literature-supplement.md)。文档链接、README ASCII、可疑凭证模式与 diff 检查通过；运行时代码保持待审查，不纳入本次文档交付。
- **待澄清项**：完整 SFT/RL 训练优先级的可选问题尚未收到答复；继续评测路径与文献工作，不购买 GPU。

## 2026-10-06：最近一周同期工作与逐轮轨迹分析补查

- **范围**：按用户要求核查顶会与同期竞争工作；三条并行检索分别核实计算/时间交换、反馈机制、近期系统论文，并回到原始全文与正式论文集。
- **新增**：cua-speedrun（09-30）、SSA v3（10-01 更新）、LEAP（10-02）和 Agent Evaluation Reliability（09-30）；文献表共 29 篇。SALE 阅读版本固定为 v3，合成延迟扩展定位修正为附录 D.5。
- **影响**：速度前沿、逐轮行为分析、前缀反馈控制和轨迹加速预测均有先行。候选贡献仍需证明对新任务及变化延迟的 deadline 选型有额外预测价值，不将“没有完全相同论文”当成创新证明。
- **状态**：同步相关工作、当前决定及 `agent.md`；英文 README 的现有研究入口仍准确，无须增加篇幅。本轮没有新增付费实验；准备中的研究代码保留，不纳入文献提交。
- **验证与审查**：Claude CLI 退出码 0、`is_error=false`、实际模型 `claude-opus-5-5`，无阻断。已修正 benchmark 前沿与跨任务类型图的混称，补清 SSA 指标信息时点、CUDAnalyst 章节和阅读版本；其余来源问题回到原文定位后保留，详见 [处置记录](reviews/2026-10-06-recent-work.md)。文档相对链接、英文 README、29 条参考记录、忽略规则及 diff 检查通过；无新增运行时 E2E 声明。

## 2026-10-06：共同墙钟预算的直接同期工作补查

- **范围与新增**：按用户要求再次核查顶会及同期工作，新增 Agents Are Systems, Not Models（10-01 预印本）与 S*（EMNLP 2025 Findings），总计 31 篇。直接读取 EvoRoute 正式版 §3–4，核实既有时间目标与逐任务经验更新的描述；补清 CUDAnalyst 跨域分析和插件验证，避免将整篇误缩为局部诊断。
- **定位影响**：共同实际时限×模型配置、耗时分解和行为分类已有直接同期研究。候选贡献仍是决策时可得信号在新任务/新延迟下的额外选型预测价值；同时区分完成率、完成者质量与轨迹内退化，保留候选选择成本。
- **状态与边界**：同步相关工作、当前决定与 `agent.md`；英文 README 已检查，现有入口准确。此次文献任务无新增付费模型实验，不纳入准备中的 runner/batch 代码。
- **验证与审查**：Claude CLI 退出码 0、`is_error=false`、实际模型 `claude-opus-5-5`，未发现阻断问题。已修正预印本小节计数、Findings 标题范围和选择效应措辞，补齐模型族限制与原文章节；详见 [处置记录](reviews/2026-10-06-concurrent-followup.md)。文档链接、31 条参考编号、英文 README、敏感模式与 diff 检查通过；无新增运行时 E2E 声明。

## 2026-10-06：Timely 真实环境单回合 runner 就绪

- **完成**：新增固定源码验证、单回合官方 evaluator 适配、预算 HTTP 边界与真实环境观察；保留官方提示/虚拟时间/判停语义，额外区分技术、协议、校准和真实游戏终态。R0 完成，R1 真实调用尚未启动。
- **验证**：WSL 专用 Python 执行 `research/timely_transport_fake_e2e.py`，27/27 通过；执行 `research/timely_reproduction_fake_e2e.py --source .local/timely-machine-audit --game <本地zork1.z5>`，15/15 通过。覆盖未知计费、取消、流响应上界、SDK、真实动作进程池正常/异常清理，以及 dummy 凭证下真实 HTTP 客户端的联网前拦截。Provider 请求/费用均为 0，脱敏证据见 [validation](../research/results/timely-runner-validation.json)。
- **审查**：两轮 Claude CLI 退出码 0、`is_error=false`、实际模型均 `claude-opus-5-5`，无首跑阻断；修复已知 usage 超预留的负债低估、重试字段歧义，补运行参数和网络设置路径验证。七个复审输入 hash 与落盘文件一致。处置见 [runner review](reviews/2026-10-06-timely-runner.md)。
- **文档**：同步实验 README、执行计划与 `agent.md`；根 README 仍为简短英文，模型评测 pending 的状态准确。AST、相对链接、忽略规则、敏感模式和 diff 检查通过。
- **边界与下一步**：首条 R1 独立 8 步、默认官方延迟、5 元/12 requests；不把其 τ 用作 R2 校准。批次代码保留为未交付，须处理共享预算、子孙进程退出和完成后的校准复核后，再做独立 E2E/Claude 审查。原 checkpoint 不可用，不能声称论文数值复现。

## 2026-10-06：R2 首批真实校准停止与协议修订验证

- **真实结果**：首个 24 条冻结矩阵执行 1 条后停止，Pro 共 32 次请求、26 次工具执行、得分 5/350；前六次缺闭合标签，技术有效但协议/校准无效。其余 23 条未执行，不删除失败或拼接成功片段。原始结果与计划/账本 hash 见 [脱敏结果](../research/results/timely-r2-small-v1.json)。
- **费用与清理**：本条 0.095050560 元，当前先导 0.103705632 元，与此前工程批次合计 0.266216928 元，均为 usage 峰值价格估算；未知费用为零。所属进程退出证据已核验。外层时钟偏移变化约 -0.455 秒，不作逐请求归因或稳定性保证。
- **修订范围**：一次允许的 v2 完整矩阵；追加单行完整工具调用示例，两模型共用，不改官方 parser、评分、计时或 conclusion。修订前将旧批次费用纳入同一累计 200 元登记。
- **验证与审查**：v2 提示 6/6 真实 Jericho/fake HTTP 检查通过，零 API；[验证记录](../research/results/timely-v2-validation.json)不证明真实模型遵守提示。预算迁移 26 项聚焦检查通过，包含完整 24 条 synthetic 子进程；实际 Claude Opus 5.5 审查无必须改代码的阻断，待真实 prepare/dry 门槛，尚未启动修订付费批次。原始响应诊断证实后 26 次有闭合标签且 25 次为多行，不能把换行认作根因；v2 仅为一次受控格式提示干预。
- **文档**：同步简短英文 README、agent.md、研究 README 与执行计划；完整 R2–R4 和论文数值复现均未完成。

## 2026-10-06：唯一 v2 修订真实停止，推进编程开发路径

- **真实执行**：迁移代码已审查并推送 `6601c11`，真实 prepare 的所有费用/封存门槛通过，活动 head 为 `2cff47511dce23d43bf975030b4b4fb47beb16462363ee111b6fa33495f78e52`。v2 首组在第一条 Pro32 后停止，32 条闭合标签齐全但第 24 条 JSON 损坏，31 次工具执行，40/350 未通关；剩余 23 条未执行，不能校准或排名。
- **预算**：新增 0.108484288 元，当前先导累计 0.212189920 元、所有实验估算 0.374701216 元，未知零、cleanup 已确认；均非账单。详见 [v2结果](../research/results/timely-r2-small-v2.json)。唯一修订机会用尽，不继续挑提示，R2 有效曲线/四游戏仍未完成。
- **编程准备**：多题 judge 初始 27 项及针对 Claude 发现的 11 项增量 Docker 检查通过；修正启动前 infra 分类、Unicode 编码、独立目录与安全公开诊断。固定 16 槽首稿 fake HTTP 六场景和真实 Docker 接缝通过，22/22 容器/worker 已清理，零实际模型调用。参考解 /32 的数值失败保留，不宣称完整 EvalPlus 等价。
- **当前门槛**：编程判定与首稿功能的实际 Claude Opus 5.5 增量审查已完成，当前零模型功能无提交阻断，付费入口仍拒绝；退出码/容器消失分类和整批预留预检列为付费前必要修订，终态代码版本迁移与 R3 同预算准入另行实现，不新建额度，不把 R2 失败改成成功。实验协议见 [R3开发计划](research/coding-pilot.md)。

## 2026-10-06：编程首稿同预算准入与真实执行准备

- **实现**：终态 Timely 源码归档核验与同一 200 元研究登记迁移；固定 16 槽先整批预留 3.20 元，transport 继续唯一逐请求记账。16 请求统一预检，未知/部分执行保留整批负债，HTTP 确闭后可离线评分已有候选。重复执行拒绝，历史 R2 两次停止结果保持原样。
- **定向验证**：judge 新增 2 个真实 Docker 用例及 4 组检查；paid-focus 10 场景含 3 容器，最终 CLI/policy 9 场景、WSL 控制流 3 场景、最终真实 study+MockHTTP 联合 21 场景均通过。版本分别保留，没有宣称旧 27/11/22 容器套件全量重跑。受审与最终证据中的 pilot SHA 同为 `fdd487d82c0464ae5b73aaf3fbf2b00d3926e6484c1d9020057b3a281de780f1`；后续计划必须冻结相同值。
- **审查与门槛**：两次实际 Claude CLI 均 exit 0 / is_error=false / claude-opus-5-5；修正取消传播、异常 finished 状态及已记账后本地交付超时停止余槽。同一 WSL 环境 dotenv/密钥格式可用，16 请求保守预留合计 1.03431936 元，无派发；native Docker 与固定镜像已核验。详见 [审查](reviews/2026-10-06-coding-paid-admission.md)和 [分版本验证](../research/results/coding-admission-validation.json)。
- **轨迹产物**：三条真实 Timely 轨迹的 72 步脱敏数据及 [单轨迹图](../research/figures/timely-v2-diagnostic.png)已生成并目视检查。第 24 条格式失败后第 25 条恢复合法调用，分数 15→15；不据此声称反馈因果效应或模型排名。
- **状态**：本条记录尚无真实 coding 付费调用，计划未 prepare/activate。累计实验费用不变。提交后执行首批 16 槽，再依据公开自然错误推进协议；共同 deadline、反馈闭环及留出预测仍待完成。

## 2026-10-06：首批 16 条真实编程首稿完成

- **执行**：已审查代码 `80e208e` 推送并核验远端。使用同一 WSL 解释器 prepare/activate；计划摘要 `2734c09b54d10b0313d0d2137df49a6753bfe37dd0e02a6d5ebd8750afea8a40`，pilot 字节与受审及最终 E2E 同为 `fdd487…`。首稿 16/16 请求闭合且全部可解析，CLI child4319 exit0/reaped；44/44 容器移除、worker 回收，先完成全部 HTTP 再 public、再 hidden。
- **结果**：Flash 与 Pro 各公开 8/8、隐藏整题 6/8。生成时间中位数分别 1.076/2.165 秒，包含本地处理且缓存命中不同；不是共同 deadline 或反馈迭代证据，不据此排名。四个隐藏整题失败均为 /32，保留数值判定局限，不作为反馈或选择依据。
- **费用**：新增 0.084681216 元，当前研究累计 0.296871136 元，所有实验估算 0.459382432 元，未知为零；非账单，不含 Claude 审查。完整分母、usage、状态和原文件 hash 见 [结果](../research/results/coding-first16.json)。独立分析的第一版因额外 usage 元数据误报 usage 不一致，五个计费字段逐条一致；原报告保留，修正版无完整性问题，未改 paid 根。
- **下一步**：依据公开检查全部通过，执行此前已规定的四题扩展（/16、/99、/18、/31），需要继承同一 study 的 coding ledger；不重建额度、不重复首16。共同 deadline、反馈修复、留出预测仍未完成。详见 [首批报告](research/coding-first16-results.md)。本条结果文件已由实际 Claude Opus 5.5 审查，无文档提交阻断；已澄清 /32 判定局限、12 次参考执行的构成与执行时源码身份，见 [处置](reviews/2026-10-06-coding-first16-results.md)。验证命令：python .local/overnight/publish_coding16_result.py 构建数值结果；cleanup 字段另由 document_coding16_result.py 从已哈希的 coding16-analysis-agent-v2.json 并入。随后独立核对所有原始产物 hash、16 条 public 状态、73 个文档链接及英文 README，均通过。

## 2026-10-06：预定编程扩展完成实现与审查

- **实现**：首稿执行器复用固定 `first16`/`extension16` 阶段；新增首批到唯一扩展的同预算准入，核验六份历史源码、结算、全部公开通过及 CLI/worker/container 清理。stop/unknown 父批拒绝并保留原负债，summary 绑定 paid、计划摘要及输出目录；隐藏成绩不参与分支。
- **验证**：当前 pilot 7 项 fake 流程和最终 study 21 项合成流程通过；四题参考解公开/隐藏 8 项实际 Docker 检查通过，12 个容器清理。WSL 整批请求预检 16/16 接受，保守预留 1.03196064 元；以上均零实际模型调用，不改变累计费用。
- **审查**：初审与增量复审均实际 Claude Opus 5.5 / exit0 / is_error=false，无当前提交或执行阻断。落实 stop 父批拒绝、fixture 目录隔离与 summary 绑定。记录拒绝原因未逐项断言的证据限制；真实父 summary 由 prepare 再核验，不为通过而修改历史文件。见 [扩展审查](reviews/2026-10-06-coding-extension.md)。
- **下一步**：提交后在相同 WSL 环境 prepare/activate，继承研究累计 0.296871136 元，再真实执行固定扩展；尚无扩展结果，共同 deadline、反馈与留出预测仍待完成。README 的首批状态仍准确；修正复现计划中旧的两条轨迹描述为三条。

## 2026-10-06：预定扩展真实完成并获得公开错误

- **执行**：代码 `bceaead` 审查、提交及远端核验完成后，在同一 WSL prepare/activate；真实父 summary 身份校验通过，开账 0.296871136 元。计划摘要 `7b01b16182ed6ecfe919525e26f81c9ed8e1a942aadbb2a7669247bf091f6804`，激活 head `b0133d528ddc381f487449f0ff61fb579fc3fc6ccba97b506a9bd4275947f654`。16 请求闭合，CLI child4207 exit0/reaped。
- **结果**：Flash 8parsed/公开7pass1fail；Pro 7parsed1parse_failed/公开7pass1未评估。代码错误为 Flash /99 rep2，公开题面已明确 -14.5→-15，候选负数 ROUND_HALF_DOWN 得到 -14；格式错误为 Pro /16 rep2 的 ambiguous_or_surrounded_fence。未用隐藏结果定位或选状态。保持全部16分母；15可执行候选的45个容器/worker清理记录完整，独立分析无完整性问题。
- **费用与分支**：新增 0.047613312 元，研究累计 0.344484448 元，连早期实验合计估算 0.506995744 元，无未知负债、无新额度；非账单，Claude另计。按预定规则继续 HumanEval 反馈研究，不迁移基准。八开发题完整对照与单个Flash错误状态续跑分开设计；没有共同deadline或repair结果。
- **计时发现**：生成阶段 89.401 秒，单条 timer 合计22.743秒，其余66.658秒为尚未细分的编排开销；timer 不含前置逐调用准入/请求写盘，不能拿它冻结共同deadline。后续先按完整循环校准；两种timer口径在JSON分列。
- **产物与审查**：[脱敏结果](../research/results/coding-extension16.json)、[实验报告](research/coding-extension16-results.md)。两批共32首稿中30份公开pass、1份代码fail、1份格式未评估。数值由 `.local/overnight/publish_coding_extension_result.py` 汇总，原始文件hash与独立分析来源保留；实际Claude Opus 5.5审查 exit0/is_error=false，无提交阻断。补齐公开错误/格式证据、45个worker exit0计数、脚本hash和完整循环计时限制；详见 [结果审查](reviews/2026-10-06-coding-extension-results.md)。后续源码修改前，六份执行源码已归档在 `.local/study-code-archives/bceaead150216a8047531123a36e75e8167bc60c/`，manifest SHA `d3ef3907d5bc064c417c810608bf558a8aea640da1f7f61c1ab3f7933bcd14c8`，与实际Git/计划/激活记录相符。

## 后续记录格式

每次任务新增一条记录，至少包含：日期、范围、实际完成内容、验证命令与结果、Claude 审查及处置、已知限制、下一步。代码功能的记录应附对应端到端场景；只读评审不单独触发提交循环。
