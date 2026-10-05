# ACL direction: adversarial related-work audit

Checked: 2026-10-05. This is a focused novelty audit, not an exhaustive review or a claim that ACL acceptance is likely. No experiment was run for this document.

## Recommendation

优先验证候选 2 的窄版本：**在保持工具延迟边际分布不变时，延迟的顺序相关性是否改变 Agent 利用时间反馈的收益，以及简单的规则能否消除这种失配。** 候选 1 适合作为它的机制对照。候选 3 的通用版本已有直接先行工作，不建议目前作为主方向。

这不是预设“相关性一定伤害 Agent”。历史延迟在相关环境里可能更有预测价值，也可能诱导错误外推；没有显著行为差异或简单规则完全解释结果，同样会证伪我们想做的主张。

证据等级：**A** = 已从会议官方 proceedings 核实；**P** = 已核实 primary 预印本，未核实会议接收；**V** = 作者材料声称 venue，但未找到官方确认。P/V 同样可能构成新颖性冲突，不能因为未见正式发表而忽略。

## Anchor and confirmed venues

[Timely Machine](https://aclanthology.org/2026.acl-long.211/) 是 **ACL 2026 主会长文，A**。须读 [ACL 最终 PDF](https://aclanthology.org/2026.acl-long.211.pdf)：涵盖文本游戏、ML 任务和一般推理；已有工具延迟等级实验、推理长度行为分析及训练/奖励消融。因此，“扩展到非游戏”“首次考虑工具时间”“论文没有消融”都不是成立的贡献。Fig. 2 用绝对秒数作横轴，也不能笼统指控全部比较使用不公平的模型专属预算。

其他已经官方核实的相关论文：

| Paper | Official venue | What it establishes for this audit |
| --- | --- | --- |
| [s1: Simple test-time scaling](https://aclanthology.org/2025.emnlp-main.1025/) | EMNLP 2025 main, A | 通过预算强制、停止或延长推理改变质量，预算/终止本身就是重要干预。 |
| [ThunderAgent](https://proceedings.mlr.press/v306/kang26j.html) | ICML 2026, PMLR 306, A | 跨 LLM/tool 工作流的程序级资源管理与调度。其 [primary v1 Appendix C](https://arxiv.org/html/2602.13692v1) 实测工具时间长尾并讨论预测脆弱性。 |
| [An LLM Compiler for Parallel Function Calling](https://proceedings.mlr.press/v235/kim24y.html) | ICML 2024, A | 通过任务依赖、并行工具执行降低端到端延迟；不能把并行化或关键路径优化本身作为创新。 |
| [SwiftSage](https://proceedings.neurips.cc/paper_files/paper/2023/hash/4b0eea69deea512c9e2c469187643dc2-Abstract-Conference.html) | NeurIPS 2023, A | [§3.4](https://proceedings.neurips.cc/paper_files/paper/2023/file/4b0eea69deea512c9e2c469187643dc2-Paper-Conference.pdf) 用停滞、无效动作、关键决策、异常触发慢模型规划，再返回快模型。 |
| [ReflAct](https://aclanthology.org/2025.emnlp-main.1697/) | EMNLP 2025 main, A | 以当前世界状态和目标差距组织反思与动作；“利用 trace/state 反思”不是空白。 |
| [Stop Unnecessary Reflection](https://proceedings.iclr.cc/paper_files/paper/2026/hash/08fe50bf209c57eecf0804f9f9ed639f-Abstract-Conference.html) | ICLR 2026, A | 用 RL 的自适应反思与长度惩罚减少推理开销。它研究数学推理中的反思，不能直接等同于工具失败恢复。 |

## Candidate 1: behavior adaptation or budget/termination effects?

最强的三个相关先行如下。“Killer”指它否定的宽泛贡献，不代表它已经回答我们所有问题。

| Prior | Novelty threat | What remains unestablished |
| --- | --- | --- |
| Timely Machine, A | 已把预算、时间反馈、行为长度及奖励设计联系起来。只重做有/无时间提示很弱。 | 同一冻结模型、相同绝对 deadline 与停止执行器下，准确时间信息对工具决策的独立价值。 |
| [Real-Time Deadlines Reveal Fragile Temporal Adaptation in LLM Strategic Dialogues, v2](https://arxiv.org/html/2601.13206v2), P/V | **直接冲突**：比较数字倒计时、每轮 urgency、重复总 deadline、自行 CoT 计时；urgency 有时优于数字倒计时。不能声称首次区分 clock information 与 urgency。 | 谈判结果不直接回答随机工具延迟下的工具选择、并行/等待行为或时间历史利用。 |
| s1, A | 预算与停止规则可产生显著性能变化；“排除 token/停止混淆”是必要实验设计，不自动构成论文贡献。 | 从 token 控制到不可预测工具延迟的迁移不是其主要研究对象。 |

Sehgal 等论文的 [arXiv 页面](https://arxiv.org/abs/2601.13206) 写了 EMNLP 2026 journal reference；本次未从官方 proceedings 核实，所以不标为正式接收。v2 是 2026-08-30 修订，不能只读 1 月 v1。其 follow-up controls 使用同批 contemporaneous baselines，并明确把 turn-budget 对比视为诊断而非严格匹配的反事实。

**判断：**单独做“时间感知究竟是不是 urgency”已明显撞车。作为候选 2 的消融仍必要，但不能仅换一个 Agent benchmark 就认为贡献充分。

## Candidate 2: same marginal delays, different temporal structure

| Prior | Novelty threat | Candidate's narrower distinction |
| --- | --- | --- |
| Timely Machine, A | 已证明延迟等级可改变模型偏好，并明确讨论逐步时间比例变化与适应。 | 控制完整 delay distribution，隔离顺序相关性及反馈依赖，而非再次扫平均延迟。 |
| ThunderAgent, A | 工具长尾、随机性、静态预测失配及动态缓解已有研究。 | 它主要优化 serving/cache 吞吐；我们研究固定 serving 条件下 Agent 的决策收益与错误适应。 |
| LLMCompiler, A | 工具依赖、并行程度与关键路径显著影响时间，不能把这些当新发现。 | 固定工具依赖图/执行器；研究时间信息怎样影响语义决策，而非换一个并行调度器。 |

**有根据但仍待实验/进一步检索的缺口：**上述已读论文没有给出以下完整对照：相同工具语义、相同边际延迟、相同 deadline 和终止规则，改变延迟顺序结构，比较冻结模型的真实 clock、无 clock、urgency 和规则控制，并区分物理时间效应与在线决策适应。这是本次审计的范围性结论，不能写成“全领域首次”。

低成本证伪方案：

1. 用可复位、答案可自动判断的本地工具任务。先一个小型检索/执行任务集；工具输出固定，只改变时延。最终论文需至少一个成熟 benchmark 支撑外部有效性，不能只靠自造任务。
2. 分开两种处理：尾部实验固定均值改变分布；相关性实验固定同一 delay multiset，只改变随机顺序、成段慢调用等排列。不要一次同时改均值、尾部、相关性。
3. 预生成每种工具、每个调用索引的潜在 delay tape，并在策略间配对。固定的是生成器/潜在序列，不保证不同自适应策略实际消耗的前缀均值相同；后者可能本来就是策略效果。报告两者，不能把“相同均值”说过头。
4. 先跑冻结动作脚本，确定纯粹由 deadline 截断造成的损失；再让同一模型实时选择动作。**仅重放已有 trace 不能证明在线适应**：clock prompt 改变后，模型输出可能改变，需重新推理。
5. 最小策略组：无逐轮时间值、真实剩余时间、固定 urgency；统一绝对 deadline、最大步数、答案预留时间、取消规则。随后加入按过去工具延迟估计的简单均值/分位数规则。规则的估计参数只在开发集调节。
6. 报告 deadline 内正确率、超时率、质量—真实秒数曲线、工具选择/次数、推理 tokens。主要指标需包括超时，不能只报告及时完成子集的准确率。按 task 配对 bootstrap，种子/重复嵌套在 task 内。
7. 相关性来自可观察历史才有利用机会；检查策略是否真的读到各次 elapsed time。保持相同信息权限，不能给新方法未来 delay 或隐含 regime 标签。

成功门槛应是可重复的 **delay regime × information/policy interaction**，而不只是长尾条件下成功率更低。一个简单 deadline-reserve 规则若完全消除差异，论文方向应改成清晰的实证诊断，而不是继续包装复杂 router。

主要失败风险：任务只有唯一动作路径，根本无适应空间；deadline 太紧/太松导致地板/天花板；API 时间噪声掩盖注入处理；所谓 burst 的效果仅来自早期把时间耗光。用冻结脚本、配对随机化与多个中间难度 deadline 排除这些解释。

### What could make this an ACL contribution rather than a scheduling exercise?

**反方：**“有相关性就预测下一次工具耗时，再用分位数留安全余量”是经典预测与决策思想。即使实验有效，也不足以证明新的 NLP 贡献。长尾导致更多 deadline misses，更可能只是随机过程截断的必然结果。

值得检验的行为假设是：**LLM 能否区分历史时延的预测价值与一般紧迫感，并把前者用于工具决策？** 这不是已经成立的结论。最有辨识力的局部实验：

1. 构造可复位的同一任务决策点：语义证据、工具结果、历史动作和当前剩余秒数相同；历史时延总和相同，但最近几次快慢排列不同。
2. 在两个生成机制里继续执行：一个机制使近期时延对下次延迟有预测作用；另一个通过置换破坏这种关系，但保持边际分布。Agent 不能看到未来具体 delay。机制知识是否在 prompt 中提供必须单独标明和控制。
3. 比较只给当前 clock、给原始时间 trace、给可复现的分布摘要三种条件；加入无关或置换后的时间 trace 作为信息价值对照。新增摘要不能泄漏比其他方法更多的未来信息。
4. 动作需要存在真正取舍，例如“继续检索/执行可选验证/依据现有证据作答”。用开发集估计的简单决策规则作强基线；最好另有仅用于分析的已知环境策略上界。上界与未来分支结果不能成为部署特征。
5. 首先在强制相同语义 prefix 的局部诊断中估计决策差异，再在线完整执行确认实际收益。前者是干预诊断，不能冒充自然分布上的端到端结果；同 prefix branching 也必须承认 Calibration 等工作的先行。

潜在可发表的发现是：准确 trace 信息只在某些条件下被利用；无预测价值的慢反馈反而系统性触发错误的提前作答；或直接提供统计摘要能纠正可复现的错误映射。需要跨任务/模型证据和对替代解释的排除，不能由一次成功率差异推出这些机制。如果 raw trace、简单规则和 LLM 都按经典预测规律运作，没有剩余行为问题，应承认该方向更接近工程评测。

## Candidate 3: intervention value and actual wall-clock cost

| Prior | Novelty threat | Remaining qualification |
| --- | --- | --- |
| SwiftSage, A | 由执行状态/异常触发慢模型，再返回快模型，已经是明确先行。 | 它的启发式并不等于同 prefix 的干预收益估计。 |
| [Calibration Is Not Control](https://arxiv.org/html/2606.21399v1), P | **最直接冲突**：同 prefix branching、干预优势、基于 prefix 的 action-conditioned 控制、RF+LCB、成本效用，以及强模型接管/同模型验证。 | 其主要成本建模不是部署中的完整真实墙钟。仅换成本单位仍可能是很薄的增量。 |
| [TACIT-Switch](https://arxiv.org/html/2608.27911v2), P | trace 累积风险、成本敏感的单向升级、减少 checkpoint 标注负担已有方法。 | 用模型规模加权调用作为成本代理；并非全部真实时延。但它已否定“trace + cost-aware escalation”宽泛创新。 |

另有两篇不可略过：

- [The Handoff Tax](https://arxiv.org/abs/2608.24358)，2026-08-25，P：直接研究 coding agent 的升级/降级、交接时机和 full/compacted/removed trajectory，报告升级存在成本质量损失。不能默认强模型从坏 prefix 接手就恢复到强模型从头运行的能力，也不能把交接开销本身说成新发现。本文尚不能据摘要断言已完整覆盖真实 latency。
- [Signed Rescue Routing](https://arxiv.org/abs/2609.07786)，2026-09-07，P：增益应区分救回错误与破坏正确，是概念先行；**当前摘要的样本数与主要结果仍写 TBD**，不能引用为已经验证的实验效果。且其问题是请求级 cascade，不应等同于多步工具 Agent。

**判断：**撤回“预测升级收益本身有明显新颖性”的早期建议。若仍做候选 3，应先证明部署时延/交接造成了已有价值估计的系统性排序反转，并证明该反转超出少量固定成本校正；否则适合工程功能，未见足够强的 ACL 主贡献。

## First falsification gate and reading order

不要今晚写下想要的结论。今晚可冻结假设和协议：先 10–20 个任务、一个模型、两个 delay regimes、三个信息条件做 pilot。第一批先量每 episode 实际 token/API 成本，再确定可承担的重复数；不承诺人民币 2k 一定支持全规模实验，也不先租 GPU。

若无法复现中间难度下的 clock/行为差异，或差异被统一停止规则完全解释，停止扩大实验。若存在稳定交互，再增加第二模型、第二任务族与真实测量延迟验证。对现代 Agent 框架的接口化和 Langfuse instrumentation 是实验资产与工程价值，不能自动算算法贡献。

明天优先精读：

1. **Timely Machine 最终 ACL 版**：§3–5，辨别控制变量与训练收益。
2. **Real-Time Deadlines v2**：§4.3、§4.7、Limitations，避免重复已经完成的 clock/urgency 消融。
3. **ThunderAgent Appendix C + Calibration Is Not Control §3–5**：分别审查真实工具时延分布和干预价值评估的直接先行。

最终投稿定位只能在 pilot 后决定。候选 2 当前最值得做证伪实验；“有一个未完全回答的窄问题”与“已经够 ACL”是两回事。
