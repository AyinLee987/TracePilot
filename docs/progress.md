# 项目任务记录

阶段状态以 [`agent.md`](../agent.md) 为准。本文件记录每次任务的实际工作、验证和审查结果。

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

## 后续记录格式

每次任务新增一条记录，至少包含：日期、范围、实际完成内容、验证命令与结果、Claude 审查及处置、已知限制、下一步。代码功能的记录应附对应端到端场景；只读评审不单独触发提交循环。
