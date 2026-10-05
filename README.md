# TracePilot

**Trace-guided model routing for efficient agents.**

TracePilot 计划通过 Agent 当前的执行轨迹，选择下一轮调用的模型，并记录决策对任务质量、端到端时间和费用的影响。项目将复用 Langfuse SDK 的观测能力，以独立 Python 扩展库的方式接入自定义 Agent，无需使用 LangChain。

## 当前状态

仓库与协作规范初始化已完成，并已同步至 GitHub。当前内容是项目计划、工程约定和审查流程；尚无运行时实现、安装包或已验证的路由效果。下一步开始 P1 的事件与本地记录闭环。

阶段计划与最新状态见 [`agent.md`](agent.md)，任务记录见 [`docs/progress.md`](docs/progress.md)。

## 首版计划

- 统一任务、模型和工具事件，维护按运行隔离的本地 trace 状态。
- 在完整模型/工具调用边界，根据 trace 在两个兼容模型之间选择。
- 记录路由依据、策略版本、实际 token、耗时和费用；支持本地 JSONL 与 Langfuse。
- 通过同状态的配对续跑，判断哪些情况下切换模型具有收益。
- 提供固定模型、规则策略与学习策略的对照实验和第二个最小接入示例。

首版研究模型路由；多 Agent 状态迁移、自建观测界面和大规模基础模型训练属于后续可选范围。

## 计划中的执行流程

```text
Agent 执行事件
    -> 本地 trace 状态
    -> 路由策略
    -> 兼容模型执行
    -> 新的模型与工具事件

执行事件与路由决策 -> JSONL / Langfuse
```

在线路由读取本地最新状态。观测平台用于保存、展示和离线分析；运行时库和实验工具保持独立。

## 开发约定

开始贡献前阅读 [`agent.md`](agent.md)。默认验证方式是可重复的端到端脚本/命令，不要求 pytest 或单元测试。

每完成一个功能：执行相关端到端验证，调用 Claude CLI 只读审查，修复并复验，更新受影响文档，再提交并推送当前任务分支。审查重点为并发隔离、扩展边界和抽象复杂度。

- [审查清单](docs/review-checklist.md)
- [审查提示模板](docs/review-prompt.md)
- [任务记录](docs/progress.md)

`AGENTS.md` 和 `CLAUDE.md` 为编码工具提供指令入口。这些是代理协作约定，目前没有后台自动更新程序或 Git hook。

## 研究与实现基础

- [Langfuse SDK](https://langfuse.com/docs/observability/sdk/overview)：观测与记录集成。
- [OpenTelemetry](https://opentelemetry.io/docs/)：trace 与 span 的通用接口。
- [MTRouter](https://aclanthology.org/2026.acl-long.2045/)：基于多轮历史进行模型路由的相关研究。
- [EvoRoute](https://aclanthology.org/2026.acl-long.1771/)：利用历史执行经验选择模型的相关研究。

以上为相关基础与参考。TracePilot 的有效性和新颖性需要通过后续实验检验。
