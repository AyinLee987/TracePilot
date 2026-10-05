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

## 后续记录格式

每次任务新增一条记录，至少包含：日期、范围、实际完成内容、验证命令与结果、Claude 审查及处置、已知限制、下一步。代码功能的记录应附对应端到端场景；只读评审不单独触发提交循环。
