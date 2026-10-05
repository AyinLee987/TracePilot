# Langfuse 接入先导审查

日期：2026-10-05。范围：本地 Langfuse 部署脚本/配置、可安装 Python 包、harness 适配器、E2E 示例与接入文档。外部医疗 Agent 仓库只读，未纳入本次提交。

## Claude CLI

使用只读 CLI 调用，完整代码和相关 harness 上下文通过 stdin 提供，关闭工具与持久会话，未设置费用或轮次上限：

```text
claude --print --permission-mode plan --permission-prompts none --tools= --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json
```

首轮和实质性修复后的复审均退出码 0，`is_error=false`，实际 `modelUsage` 为 `claude-opus-5-5`。首轮指出的隐私、容错和计量问题已处理；复审明确“未发现阻断问题”，其余发现不阻断推送。Claude 仅静态审查，未自行复现 E2E；本文件实测结果由主执行者和协作代理运行。原始输出留在 Git 忽略的 `.local/reviews/`。

随后发现外部 harness 的导入需要 PyYAML，补入 `pilot` extra 后完成第三次针对依赖和导入边界的增量审查，实际模型仍为 `claude-opus-5-5`、退出码 0、无阻断发现。在全新虚拟环境中安装并运行完整 SDK 内存导出 E2E，19 traces / 115 observations 通过；TracePilot 核心不导入 harness 或 yaml。依赖说明与约束文件注释已同步。

## 修复及处置

| 发现 | 处置 |
| --- | --- |
| telemetry 派生字段处理异常可能影响业务结果 | 用量、账本、响应属性、检索摘要分别做有界容错，不吞业务异常；增加创建/update/end 故障验证 |
| 未注册工具名、模型调用 ID 和动态 stop reason 可能包含正文 | 名称限制为已注册工具，未知名称脱敏；正文关闭时用本地 call 序号和稳定终止分类；恶意名称/ID 哨兵检查通过 |
| 已送出最终事件后 close 被标为取消 | 标记结果已交付，保留终态；同步/异步最终事件后关闭验证通过 |
| 取消发生在清理阶段可能被 GeneratorExit 掩盖 | 取消/中断信号完成收尾后继续传播；普通清理错误不覆盖既有业务错误 |
| 恢复运行的累计 token 可能重复求和 | 标记 resumed、原有累计量、本段增量与账本口径；同一 run ID 关联恢复段，验证分段增量之和 |
| 估算 token 可引出服务端推算费用 | 保留 token 可视化，明确 cost 来源、用量来源和 billed_cost_known=false；文档禁止当成实际账单或直接用于论文费用汇总 |
| 取消、超时、线程、暂停与故障验证不足 | 扩展为 18 项检查，真实服务端核对 19 traces / 115 observations |
| steer_handoff 被视作失败 | 映射为 handoff；尚未覆盖完整业务 steering E2E，不宣称已验证该功能 |
| python -O 会跳过断言 | E2E 在优化模式下明确拒绝运行 |
| SDK 显式 trace context 给子节点加根标记 | 子节点通过父 handle 创建；实际 SDK 与服务端都核对逻辑根及父子关系 |
| v4 events_only 下旧 trace API 返回 404 | 改用 observations v2，区分逻辑根与物理父 ID |

下列建议不扩大到本次先导：并行工具字典（当前 harness 串行派发）、通用私有接口兼容框架、路由后实际模型标识。当前依赖/接口范围和升级后复验要求已写入接入说明。不会声称适配器使原业务模型/provider 自动获得线程安全。

复审剩余发现的处置：

- `answer_requires_handoff` 未启用，交接段可能保留 harness 的成功结果：明确列为未支持的计量场景，并说明任务成功率按最终段与独立验收统计，不能数成功 trace；启用该回调前补显式交接映射和 E2E。
- 检索摘要 32 条限制：已核对当前 harness 的 `_MAX_EVENTS=16`，外加 1 条截断通知，实际最多 17 条，当前不触发适配器 32 条截断；升级时重新验证。
- provider deepcopy/pickle 的潜在递归：当前无此执行路径；文档明确不复制已构造 loop/provider，跨进程重新构造。通用序列化不在本次支持范围。
- 正文采集、异步恢复、真实压缩/refresh/restore 与 steering 未做完整 E2E，已列入明确限制。
- 缺少父上下文时的根回退：当前 `_bound` 成对设置上下文，所有受支持 E2E 都检查唯一逻辑根；创建父节点失败时丢弃子遥测符合观测降级，避免生成孤立记录。
- 外部线程 ContextVar：已核对 harness `run_in_thread` 使用 `asyncio.to_thread` 或 `copy_context`，并通过线程/异步 E2E 验证。

部署脚本保留已有 `.env.local`，使用明确的 `.local/langfuse/sdk.env` 做本次鉴权；说明中要求保留原始配置和数据卷。Compose 最低版本已写明并经 `config --quiet` 验证；六个固定 digest 的镜像在本机全部拉取成功。其他 OTel instrumentation 的正文采集不受本适配器开关控制，文档已说明。

## 实测证据

- Python 3.12.14 / Langfuse SDK 4.17.0 / 服务端 4.50.0。
- Docker 6 个容器运行，依赖健康，health / projects API 返回 HTTP 200。
- `examples/harness_smoke.py --live --env-file .local/langfuse/sdk.env`（同时传实际 `--harness-path`）退出码 0；合成 LLM/fetch、真实 harness/词法 RAG/SDK/服务端。报告 `.local/harness-smoke-live.json`。
- 检查父子关系、run 隔离、起止时间、用量来源、首 chunk 时间、正文关闭和续跑 token 增量；18 项流程检查通过，付费模型请求 0。
- `pip check`、本地文档链接、忽略规则和 diff 空白检查通过。

这不是模型质量或真实费用实验。隐藏 Provider 重试、辅助模型/embedding 逐次计量、跨进程/子 Agent 观测与路由仍未实现；完整医疗服务器入口未改动。
