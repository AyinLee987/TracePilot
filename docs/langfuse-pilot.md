# Langfuse 接入先导

本阶段先观察真实执行边界，再决定 TracePilot 应补哪些字段。Langfuse 独立部署；TracePilot 使用官方 SDK，不修改或复制 Langfuse 服务端源码，不依赖 LangChain。

## 安装与本地部署

需要 Python 3.12+、PowerShell 7、已运行的 Docker Desktop Linux 引擎。依赖和镜像需要首次联网下载。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -c constraints-pilot.txt -e '.[pilot]'
./scripts/start-langfuse.ps1
./scripts/start-langfuse.ps1 -Action Status
```

Langfuse 服务端固定为 4.50.0，Python SDK 验证版本为 4.17.0。官方 Compose 的提交和校验值见 [upstream.json](../infra/langfuse/upstream.json)，全部服务镜像固定 digest。服务只在本机暴露网页 3100 和媒体 9190 端口；数据库不发布宿主机端口。[部署说明](../infra/langfuse/README.md)包含停止和重新启动方式。

`pilot` extra 包含外部 harness 导入所需依赖；其中 PyYAML 由 harness 的技能仓库模块使用，TracePilot 核心不导入它。`constraints-pilot.txt` 固定已验证的直接依赖及部分传递依赖，不是完整依赖锁文件。

网页为 <http://localhost:3100>。先确认 `/api/public/health` 就绪；容器启动不代表迁移和初始化已经完成。不需要注册云账号：脚本自动创建本地用户和项目。登录邮箱和密码在被 Git 忽略的 `.local/langfuse/.env` 中，对应 `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD`。SDK 凭证保存在 `.local/langfuse/sdk.env`；不存在 `.env.local` 时也会创建该文件。脚本重复运行保留原数据和凭证。

## 接入现有自研 Agent

当前适配器针对 `agent-harness-from-scratch` 的 `ReActLoop`，导入时需要该仓库在 Python 路径中。验证环境为该仓库 `334a4f76fe8cac13a6c0d834eb44851a7bf9c6ce` 的本地工作副本；工作副本有用户未提交改动，本任务没有修改它。适配器使用其内部 effect / stream 扩展点，升级 harness 后需重跑 E2E，不能视为任意框架的通用自动接入。

在已有程序中，用 `TracedReActLoop` 替换构造 `ReActLoop` 的位置，传入已有模型、工具与 context providers：

```python
from dotenv import dotenv_values
from langfuse import Langfuse
from tracepilot.harness import TracedReActLoop

config = dotenv_values(".env.local")
client = Langfuse(
    public_key=config["LANGFUSE_PUBLIC_KEY"],
    secret_key=config["LANGFUSE_SECRET_KEY"],
    base_url=config["LANGFUSE_BASE_URL"],
)
loop = TracedReActLoop(
    llm=llm, tools=tools, context_providers=context_providers,
    langfuse_client=client, capture_content=False,
)
try:
    result = loop.run(task)
finally:
    client.flush()
    client.shutdown()
```

示例中的 `llm`、`tools`、`context_providers`、`task` 来自原程序；可直接执行的完整示例见 [harness_smoke.py](../examples/harness_smoke.py)。长驻服务在应用退出时统一 flush/shutdown，不在每个请求后关闭共享客户端。同步 `iter_run` 和异步 `aiter_run` 保留原有事件接口；提前停止迭代需要调用 `close()` / `aclose()`。适配器不会自动修改旧项目的服务器入口。

`capture_content=False` 默认不导出任务、消息、工具参数、返回正文或答案；仍记录模型名、注册工具名、run ID、状态、数值用量和检索计数。未注册工具统一记为 `unregistered`，工具调用 ID 使用本次运行内序号，动态终止原因只保留分类。Agent/模型/注册工具名称应使用静态配置，避免把用户输入拼接到名称里。打开正文采集前，由调用方脱敏或为 Langfuse client 配置 `mask`；这项开关不控制原 Agent 自己的日志或其他自动 instrumentation。

## 已记录的内容与口径

| 执行边界 | Langfuse 类型 | 当前记录 |
| --- | --- | --- |
| 完整运行 | agent | run ID、开始/结束、成功与终止原因、步骤数、harness token ledger |
| 主模型调用 | generation | 模型、步骤、调用起止、输入/输出 token、用量来源、finish reason |
| 流式主模型 | generation | 首个文字或工具调用 chunk 的时间；提前结束时保留已收到用量，否则标记未知 |
| 工具执行 | tool | 调用 ID、步骤、耗时、业务成功/失败；失败后反思的模型调用单独计入 |
| 内置初始 RAG | retriever | context provider 的实际准备时间、检索状态与候选/证据数量 |
| 其他 context provider / 上下文管理 | span | 实际耗时；上下文管理前后 token ledger |

根 observation 从准备检索之前开始，完整任务时长包含消费者在 generator yield 之间的暂停；流式调用时长也可能包含消费者背压，不能直接解释为纯服务端推理速度。工具的结束时间在工具返回/抛错时采集，收到 `TOOL_COMPLETED.ok` 后补齐业务状态。并行任务时长按各自墙钟计算，不累加重叠 span。

用量来源为 `reported`、`estimated` 或 `unknown`。harness 默认全零 `Usage()` 无法证明真的消耗零 token，按未知处理。为了在 UI 检查 token，估算值也写入 `usage_details`，同时记录来源和费用推断口径。Langfuse 可能按模型价格表自动推算费用，这不是实付账单；尤其 estimated 用量对应的 UI cost 不得当作真实费用汇总。论文阶段必须结合用量来源、价格版本和独立实验口径计算，不直接将服务端 cost 求和。

根 ledger 是累计核对元数据，不再作为 generation usage 上传。恢复执行仍有独立 trace，通过相同 `run_id` 关联；根 metadata 标注 `resumed`、续跑前累计 token 和本段新增 token。按段统计使用本段增量，不能把各段累计 ledger 相加。未知模型价格、缺失用量和模拟模型均不能据此推导真实美元费用。

根 `success` 保留 harness 的本段执行结果，不是独立任务评分。后续任务成功率应按完整任务的最终段和外部验收统计，不能数成功 trace 的条数。当前没有启用或验证 `answer_requires_handoff`：该模式可能在交接段返回 `success=True` / `finished`，接入它前需增加显式交接标记与 E2E。

每次运行的追踪状态独立，创建子 observation 时显式使用父 handle；仅在推进 generator 时绑定本地 ContextVar，yield 后恢复调用方上下文。它不保证调用方传入的共享模型、工具和 citation counter 自身线程安全。SDK 导出失败允许业务继续；exporter 有界队列满或进程崩溃时仍可能丢记录，不是持久可靠队列。

## 端到端验证

在 TracePilot 根目录执行：

```powershell
# 真实 harness、词法 RAG、官方 SDK；LLM/fetch 使用合成数据，无付费请求。
.venv/Scripts/python.exe examples/harness_smoke.py --harness-path '../agent/agent-harness-from-scratch'

# 额外向本地 Langfuse 导出，并从服务端读取记录核对。
.venv/Scripts/python.exe examples/harness_smoke.py --harness-path '../agent/agent-harness-from-scratch' --live --env-file .local/langfuse/sdk.env
```

覆盖与未接入时答案/token 一致、检索、失败→反思→恢复、共享 loop 的线程/异步并发、同线程交错 generator、完整流式输出、提前关闭、收到最终事件后关闭、超时/取消、工具致命错误、暂停续跑、恶意工具名和 telemetry 创建/update/end 失败降级。检查 trace/run ID 隔离、父子关联、结束时间、token 来源及恢复增量；live 模式进一步核对服务端 observation 数量、层次、用量和首 chunk 时间。报告默认写入忽略目录 `.local/harness-smoke.json`；使用 `--report` 可保留多个结果。脚本拒绝 `python -O`，避免跳过验收断言。

已在 Langfuse 4.50.0 上完成真实写入和 observations v2 读回，19 条 trace / 115 个 observations 全部核对通过。v4 的 events_only 模式不提供旧 trace API；示例使用 observations v2 的 `is_root_observation` 判断逻辑根（根节点的物理父 ID 可能非空）。

这是接入验证，不是模型质量、性能或医疗能力评测。模拟 token 是固定的验证值，不能用于论文统计。最新实测结果和基础设施状态见[进度记录](progress.md)。

## 尚未覆盖与下一步

- 主调用边界以内的 Provider 隐藏重试尚未拆成 attempt；压缩、query decomposition、embedding 等辅助请求尚未逐次生成独立 generation。harness 已结算的辅助用量只能从 ledger 核对，不能声称获得全部真实费用。
- 后续检索工具作为 tool 记录，其检索计数附在该 span 上；没有把 RAG 内部每个检索器/重排器分别拆开。子 Agent、后台 job、跨进程父子关系仍未验证。
- 本地 JSONL、可供 router 读取的不可变 trace 前缀、任务分类和路由尚未实现。
- 尚未验证：开启正文采集、异步恢复、真实 compressor / provider refresh/restore 和完整 steering 流程；不能据此声称覆盖这些配置。当前不支持复制或 pickle 已构造的 traced loop/provider，跨进程应重新构造。正文开启前先运行脱敏合成场景验证。
- 当前只做必要字段映射。下一步根据实际 trace 选定 TracePilot 自己的事件含义与开销口径，再实现本地前缀；不把内部 AgentState 改成 Langfuse 格式，也不让在线 router 查询远端 Langfuse。

参考：[官方 SDK](https://langfuse.com/docs/observability/sdk/overview)、[官方 Docker Compose 部署](https://langfuse.com/self-hosting/deployment/docker-compose)。
