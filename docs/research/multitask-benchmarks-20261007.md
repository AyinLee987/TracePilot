# 多类型 Agent benchmark：2026 论文与近期预印本

核验日期：2026-10-07。目标是为逐轮分析、低成本经验迁移和后续共同 deadline 实验选择环境。本轮只调研，没有部署或执行这些新基准。**优先读 EvoAgentBench 的迁移协议；初次落地优先 MCPMark 的本地任务或 Agent-Diff；要扩展任务跨度再考虑 Toolathlon。**

先纠正范围：昨天实际执行的是 Timely 的四个文字游戏，不能将这部分的任务种类局限直接写成 Timely 全文只有文字游戏。以下比较针对我们当前实验覆盖，而非替原论文做未经核对的全面否定。

## 检索与判定方式

研究问题固定为：哪些基准确实覆盖不同任务类型；是否有可重置环境、客观反馈和可用 trace；能否支持学习/开发/测试隔离而不泄漏答案。按 2026 正式论文、近期 arXiv、经验迁移方法三条线核验，并交叉检查负面条件。

收录要求是作者原文及代码/数据或官方 proceedings 支持。不同工具、不同企业应用、不同任务领域分开描述，不把单域的大样本数当广泛覆盖。会议身份以官方出版页为准：2025 首发预印本可以是 ICLR 2026；Findings 不能写成 ACL 主会；未核实接收的条目仅标 arXiv。代码可见不等于已经在本机成功运行，作者报告费用不作为本项目预算承诺。

## 2026 正式论文

| 基准 / 会议 | 覆盖与规模 | 评分、轨迹与部署 | 对本项目的价值与限制 |
| --- | --- | --- | --- |
| **MCPMark / ICLR 2026** | 127 任务，文件系统、PostgreSQL、Playwright、GitHub、Notion；论文均值 16.2 轮、17.4 调用 | 任务状态与程序化验证；当前 repo 默认 Verified 版本 | 从本地文件/数据库任务起步较合适；跨服务不等于所有 Agent 领域；旧版分数不可与 Verified 混用；easy 子集不是 train/test 划分 |
| **Toolathlon / ICLR 2026** | 108 任务、32 应用、604 工具；办公、数据、软件服务等，约 20 工具轮次 | 容器化状态重置、程序评分、公开轨迹；2026-06 发布 Verified | 范围广且接近实际跨应用工作；Linux/Docker、多服务准备较重。论文 108 与当前 Verified 的任务数量需锁版本后重核 |
| **HAL / ICLR 2026** | 汇集 9 benchmark，包含检索、科学、编程、业务交互等 | 21,730 公开 rollouts；统一运行/记录基础设施 | 最适合先离线分析别人的真实轨迹；它是基础设施及 trace 集，不是新统一任务数据集；repo 已归档、榜单暂停维护，各底层 benchmark 的 reset/评分不同 |
| **WindowsWorld / Findings ACL 2026** | 181 专业 GUI 任务、17 Windows 应用，多数跨应用，平均 4.97 检查点 | VMware 初始快照；基于轨迹的视觉模型检查点评分 | 适合研究过程完成度，但中间分不是确定性环境真值；GUI、虚拟机和评分成本较高，不宜第一批 |

来源逐项可查：MCPMark [官方论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8138d211ce8790fdfbeeeb9781838a37-Abstract-Conference.html) / [代码与版本说明](https://github.com/eval-sys/mcpmark)；Toolathlon [官方论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/5783212d85c205ef823b8974d44872c5-Abstract-Conference.html) / [代码](https://github.com/hkust-nlp/Toolathlon) / [Verified 轨迹](https://huggingface.co/datasets/hkust-nlp/Toolathlon-Verified_Trajectories/tree/main)；HAL [官方论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a0928f924a344aaebbb7f6cd8d56e34c-Abstract-Conference.html) / [harness](https://github.com/princeton-pli/hal-harness) / [trace 数据](https://huggingface.co/datasets/agent-evals/hal_traces)；WindowsWorld [官方 Findings 页面](https://aclanthology.org/2026.findings-acl.750/) / [原文](https://arxiv.org/html/2604.27776v1) / [代码](https://github.com/HITsz-TMG/WindowsWorld)。

## 近期 arXiv

| 基准 / 首发日期 | 任务类型与规模 | 可用性及主要限制 | 建议 |
| --- | --- | --- | --- |
| **Agent-Diff / 2026-02-11** | Box、Slack、Linear、Calendar 共 224 任务；179 train / 45 test | 企业 API 副本、Docker/固定数据库、最终状态差异与约束判定；不是实时企业账号。逐轮 diff 需另外接入，不能把原终态评分说成已有密集奖励 | 优先考虑，适合客观检查经验的副作用；广度集中在企业 API |
| **Claw-Eval-Live / 2026-04-30** | 105 已发布任务，87 业务工作流 + 18 工作区修复，含文档、CRM、财务、人事、shell 等 | Python/Docker，默认 24 轮/300 秒；工作区确定性评分，其余有 LLM judge。Live 指基准持续更新，固定 fixtures 不等于 live web | 跨类型有吸引力；需审计 judge 与可留出划分。论文与 repo 的分类粒度不同，公开子集选择也可能影响模型排序 |
| **WildClawBench / 2026-05-11** | 60 任务，生产力、代码、社交、搜索、创作、安全六类 | CLI Agent + Docker，300–1,200 秒上限；一项基线平均约 8.5 分钟/26 调用。部分联网/API、媒体下载及混合评分，社交交互部分模拟 | 很符合用户希望的多分钟实际工作；但长耗时不自动等于有效迭代，先导与评分成本高于本地文件任务 |
| **EvoAgentBench / 2026-07-06** | 浏览检索、SWE、算法代码、专业工作四领域；528 train / 267 test | 专为自进化的能力迁移设计；训练产出冻结后测留出任务，不同底层环境成本不同 | 与“收集错题改善后续任务”最匹配的研究协议，优先阅读；测试能力由训练能力支持，不等于未见能力；Oracle AnchorSkill 不是可部署基线 |

来源：Agent-Diff [论文](https://arxiv.org/html/2602.11224v1) / [代码](https://github.com/agent-diff-bench/agent-diff) / [数据](https://huggingface.co/datasets/hubertmarek/agent-diff-bench)；Claw-Eval-Live [论文](https://arxiv.org/html/2604.28139v1) / [代码](https://github.com/Claw-Eval-Live/Claw-Eval-Live)；WildClawBench [论文](https://arxiv.org/html/2605.10912v1) / [代码](https://github.com/InternLM/WildClawBench)；EvoAgentBench [论文](https://arxiv.org/html/2607.05202v1)。Agent-Diff 仓库中的会议宣称本轮未独立核实，故不列为已确认顶会。

另有 [STAGE-Claw（2026-06）](https://arxiv.org/html/2606.10394v1)，40 个 macOS 原生应用/文件任务、可验收终态，但当前 Windows 机器不匹配，且应使用专用环境；不优先。单域代码、单域浏览器或全部为 LLM 模拟器的基准并非无价值，但不能直接解决本次“多类型真实执行”的全部需求。

## 实际选择

**零新增模型实验：**先用本次四游戏过程分析建好口径，随后可下载 HAL 或 Toolathlon 公开轨迹，对比协议错误、查询、状态推进和回退的定义是否能跨域使用。公开轨迹是观察数据，不提供未执行动作的因果标签，也不保证同时含同模型/同任务/同 deadline 对照。

**最小新增实验：**MCPMark 选本地文件/数据库/浏览器任务，或 Agent-Diff 的固定 API 状态任务。优先要求 reset、真实执行、终态 verifier，并保存每次动作后的可观测 diff。若使用子集，预先按类型和复杂度抽样并发布 ID，称为子集先导，不报告成整个 benchmark 结果。

**检验自进化：**参考 EvoAgentBench 的冻结与能力迁移划分；先做“新实例、已有能力”，再单列未见任务族。不从测试任务的技能标签、答案或未来 trace 检索经验。具体方法与对照见[方案](training-free-experience-plan.md)。

**真正跨应用、分钟级：**前述流程有效后再扩 Toolathlon 或 WildClawBench，保留每类任务的原生分数并报告宏平均，不把文本游戏积分、代码通过率、LLM judge 分数直接混合。每个 task × model 条件使用共同外部实际 deadline；工具等待、模型生成、检索、评估所需的在线步骤全部计时。

## 尚未确认、需要落地前核对

日志查看/轨迹重评不等于环境重置；初始 reset 也不等于任意中间状态 checkpoint。上述项目没有统一保证同状态分支续跑。版本、任务 ID、工具权限、可见反馈、隐藏评分、并行资源、模型与 judge 费用都需在实际先导前固定。当前没有新部署成功或预算承诺。

反方检查：基准跨度越大，评分和工具差异越容易混入“模型能力”；LLM judge 可能偏好表面完整答案；公开任务和轨迹可能被模型见过；有 verifier 不等于中间每步有可用奖励。因而第一批应优先提升可解释性，而非追求最多任务数或最长运行时间。
