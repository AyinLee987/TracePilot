# 同时限下的模型速度、反馈迭代与能力：相关工作核查

检索截止：2026-10-06。本文是选题证据与实验定位，不是实验结果或投稿承诺。当前工作区：`research/acl-feasibility-20261005`；原 `main` 保留。

## 摘要与判断

用户希望研究：快模型是否能在相同实际时间内通过更多迭代追上较强模型，逐轮发生了什么，以及能否形成“速度—结果—任务特征”的选型图。这个问题有工程价值，但其中的宽泛结论已有直接先行：Timely Machine 已展示工具延迟改变小大模型优胜关系；测试时计算研究已按任务难度选择模型与采样策略；反馈研究已测量修复、退化和有效反馈；近期工作进一步用轨迹指标预测效果或控制执行。

**仍值得先导验证的候选贡献是：决策时可得（任务输入或截至决策点的前缀）的反馈利用与修复特征，能否预测指定真实截止时间下两个模型的相对优势，并在新任务和服务速度变化后保持预测价值。** 同状态续跑、延迟干预和留出评估是识别这一关系的手段，三项控制的组合本身不构成创新。当前没有我们自己的证据支持该主张，也不应预设快模型一定反超。

本轮主要变化：确认 EvoRoute 为 ACL 2026 主会、CUDAnalyst 为 ICML 2026 主会；发现 EFC v2 已加入仅使用前缀信息的在线控制；补入 AgentTTS、Strategy Auctions 和 Nature Machine Intelligence 的配置选择研究。以上使“分析轨迹后做 router”的宽泛定位进一步收窄。

同日补查又发现 AutoLab 和 AgentOpt 两项直接近邻：前者已有实际工程任务的时间曲线、失败轨迹及 pi 等 harness 对照，后者已有跨框架记录和模型组合搜索库。因此任务扩展与即插即用本身也不足以构成论文贡献。最近一周的增量检索补入 cua-speedrun、LEAP、SSA 最新版与评测可靠性研究；当前共记录 29 篇相关工作，版本及边界见第 5 节。

## 1. 研究问题与范围

本轮冻结三个问题，避免将研究漂移为剩余 token 预算路由或历史耗时紧迫感测试。

1. **现象与边界：** 在共同绝对墙钟时限下，哪些证据支持或反驳“较快模型通过更多尝试弥补单次能力”？
2. **机制识别：** 现有分析是否区分初稿质量、有效反馈、修复、退化、重复采样，以及模型和工具耗时？哪些差异通过干预得到支持？
3. **预测与决策：** 机制是否转化为可部署选型规则？测试的是新实例、新任务族、新模型还是新的延迟环境？是否允许测试时继续学习？

“小”“快”“弱”“便宜”分别记录。闭源模型参数量未知时，使用具体模型与服务配置、实测调用延迟和首轮质量，不能以产品名称猜参数规模。本文的“同时间”指同任务条件下共同的绝对截止时间，不把相同 token、FLOPs、调用数、美元或各模型耗时的相同倍数视为等价。

## 2. 检索与核验方法

检索围绕三个问题并行展开：测试时计算与模型规模；反馈机制及负面证据；轨迹路由与泛化。优先核验 ACL Anthology、ICLR/NeurIPS 官方论文集、PMLR、HPCA 官网和出版社正式页面，再阅读对应全文。时间重点为 2024–2026 年，另追踪直接先行的早期版本。同期稿重点补查 2026 年 5–9 月，并检查截至 10 月 6 日可访问的更新版本。

使用的查询组合包括 `agent wall-clock small large model iteration`、`test-time scaling feedback repair regression`、`agent trajectory model routing generalization`、`latency compute optimal agent`，以及候选题名加会议/官方站点限制。沿 Timely、EFC 等参考文献补查强近邻，并专门查找“小模型多试仍失败”“反馈不如重采样”“跨域预测失败”等反证。

纳入依据是与上述问题有实质重合，而不是标题含 agent。通用 tracing 平台、仅优化推理内核而不评估任务结果的系统、纯 token 预算控制不作为主证据。这里是有针对性的文献核查，没有声称穷尽数据库、完成 PRISMA 筛选或复现论文。

身份规则：官方论文集确认才标主会；作者自报录用与独立核验分开；未独立核实正式身份的稿件标“本次仅核验预印本”，不推断其未被录用。EvoRoute 的正式身份已确认，方法阅读依据仍是 arXiv 全文，未完成终稿逐页对照；EFC 使用 v2，避免将 v1 的实验数值和 v2 控制器混用。Nature Machine Intelligence 工作使用改题后的正式版，不沿用早期稿更强的泛化表述。

## 3. 文献地图

| 分支 | 解释对象 | 代表先行 | 对我们尚待验证的问题 |
| --- | --- | --- | --- |
| A：计算、时间与能力交换 | 为什么某种预算下小模型/大模型更优 | Timely；Snell；Inference Scaling Laws；HPCA | 这种边界能否由反馈机制预测，而不仅事后测出？ |
| B：反馈如何转化为进展 | 哪些尝试修复错误，哪些重复或造成退化 | EFC；CUDAnalyst；Self-Repair；PAIR；EdgeBench | 能否把局部反馈收益与实际速度结合，预测模型间相对优势？ |
| C：经验转化为选择 | 如何按任务、轨迹和经验分配模型或配置 | AgentTTS；SALE；EvoRoute；SWE-Router；NMI 配置研究 | 冻结规则在留出任务及变化的服务条件下是否仍有用？ |

这三类按主要研究问题分类，方法可跨类。尤其 EFC 同时涉及反馈分析、泛化和在线控制，不能被简化为纯事后指标。

## 4. 已确认的顶会与正式期刊先行

### 4.1 时间与计算交换：Timely 已覆盖核心现象

**[Timely Machine](https://aclanthology.org/2026.acl-long.211/)，ACL 2026 主会。** 最接近用户最初观察。正式版 §5.1、Fig.2 比较 Qwen3 不同尺寸与工具延迟：快速反馈时部分小模型可依靠更多交互领先，延迟提高后大模型更有利；更小的模型也可能因能力不足持续落后。论文还包含一般推理和机器学习编程任务，不能说“只做文字游戏”。其一般推理部分有模型原始耗时倍数预算，不应将所有实验统称共同绝对时限。它已有延迟干预；我们不能将“延迟导致排序改变”重新包装为首次发现。

上段是论文报告的现象，不能直接等同于当前公开实现的预算语义：发布版 [interactive.py](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/interactive.py) 按 `max_steps × average_duration_per_step` 设置预算，工具时延是逻辑累加，相同 step 数并非跨模型共同实际秒数。作者原始 Fig.2 的完整启动参数与时间网格未公开，我们尚未核实图中每个点与发布版配置的精确对应，不能声称现有代码直接复现了共同 wall-clock 协议。实际执行差异见 [复验计划](timely-reproduction.md)。

**[Snell 等的 compute-optimal scaling](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b623663fd9b874366f3ce019fdfdd44-Abstract-Conference.html) 与 [Inference Scaling Laws](https://proceedings.iclr.cc/paper_files/paper/2025/hash/8c3caae2f725c8e2a55ecd600563d172-Abstract-Conference.html)，均为 ICLR 2025。** 前者 §6–7 比较顺序修订和并行采样，分析任务难度及小大模型的计算交换；后者 §4.2–4.3 联合研究模型尺寸、搜索策略和计算预算。两篇已支持“最优模型随任务与预算改变”，也指出弱模型在难题上可能很快饱和。主要预算为 FLOPs/生成次数，不能直接推出真实工具等待下的截止前成功率。Snell 的难度估计还需要额外采样；移植其规则时不能把估计开销视为免费。

**[The Cost of Dynamic Reasoning](https://2026.hpca-conf.org/details/hpca-2026-main-conference/17/The-Cost-of-Dynamic-Reasoning-Demystifying-AI-Agents-and-Test-Time-Scaling-from-an-A)，HPCA 2026 主会。** [全文](https://arxiv.org/html/2506.04301v2) §V-B、Fig.14/16/17 与 Table III 同时报准确率、时间、token 和能耗。8B 增加尝试可能接近 70B，但耗时更多；70B 可以更早达到较高正确率。其 8B 使用 1 张 A100，70B 使用 8 张 A100，不能解释成同硬件下的纯模型尺寸效应。这是重要反证：小模型的优势可能是能耗，未必是秒数；拉高轮次上限也可能只延长尾部。

**[Are More LM Calls All You Need?](https://proceedings.neurips.cc/paper_files/paper/2024/hash/51173cf34c5faac9796a47dc2fdd3a71-Abstract-Conference.html)，NeurIPS 2024。** §3–5 用易题/难题混合解释投票系统随调用数非单调变化，并用少量样本预测合适调用数。它研究独立采样/投票，不能替代工具反馈闭环；但足以说明“画曲线、解释任务差异、形成资源选择规则”这一叙事本身已有成熟先例。

**对 RQ1 的回答：** 快模型反超是有条件的已知现象。我们的新知识不能仅是再次找到交叉曲线；必须说明新的预测依据比速度、首轮能力和历史结果曲线更有用，以及在哪些条件下失效。

### 4.2 反馈机制：控制初稿与研究修复都已有先例

**[Is Self-Repair a Silver Bullet for Code Generation?](https://proceedings.iclr.cc/paper_files/paper/2024/hash/9ddc141bdbf9d1db510cefff56c586ad-Abstract-Conference.html)，ICLR 2024。** [全文](https://arxiv.org/html/2306.09896) §4.1–4.3 对照自修复与额外采样，替换模型/人类反馈，并比较同一失败程序上的反馈作用。收益依赖任务和反馈质量；其串行/批量成本分析提醒我们，更多轮数不能直接解释为学会利用反馈。它没有给出共同真实 deadline 下的模型选型边界。

**[Towards Feedback-to-Plan Decisions for Self-Evolving LLM Agents in CUDA Kernel Generation](https://proceedings.mlr.press/v306/chong26b.html)，ICML 2026，方法名 CUDAnalyst。** [全文](https://arxiv.org/html/2605.26720v1) §3.2、附录 B.1 冻结程序状态、参考内容、提示和解码条件，替换反馈；让不同被测模型共享第三方固定轨迹，并在 §5.1 固定 evaluator、改变轨迹来源检验归因趋势。它提供比随意挑失败案例更强的局部机制证据。局部固定状态实验刻意阻断后续演化，因此既不能替代整条 Agent 轨迹收益，也没有回答实际速度改变时哪个模型能在截止前胜出。

两者分别说明反馈质量约束和固定状态干预已被研究。我们可以借鉴这些方法，不能把“统一初稿再比较纠错能力”本身当成新方法。下面的 EFC 更进一步，直接覆盖有效反馈指标与控制。

### 4.3 从分析到选型：不能把泛化描述成空白

**[AgentTTS](https://papers.nips.cc/paper_files/paper/2025/hash/8d9bbba8cac9cabb54e85ee7f21441c8-Abstract-Conference.html)，NeurIPS 2025。** 同时选择多阶段任务各阶段模型和采样预算，以历史试验反馈引导配置搜索。§4.2 已观察上游检索质量会改变下游模型与采样收益，更多采样也可能退化。实验主预算是 FLOPs；按数据集用训练样本搜索后评价测试实例，不等同于冻结选择规则后迁移到新的任务族。它是“机制/经验分析指导模型配置”的直接先行。

**[Scaling Small Agents Through Strategy Auctions](https://proceedings.mlr.press/v306/alazraki26a.html)，ICML 2026，简称 SALE。** [所读 v3](https://arxiv.org/html/2602.02751v3) 分析大小模型互补失败、规划与工具使用，再通过计划/拍卖和经验记忆分配模型。目标主要是美元成本；附录 D.5 有合成工具延迟惩罚，但测的是分配变化，并非共同 deadline 下的结果。测试流中记忆会增长，应与冻结规则区分。仅报告“弱模型也有强项”“大模型会过度规划”不足以超过其已有分析。

**[EvoRoute](https://aclanthology.org/2026.acl-long.1771/)，ACL 2026 主会。** [所读 arXiv 版本](https://arxiv.org/html/2601.02695v1) §3–4 已考虑墙钟目标，经验元组包含模型、角色、工具、成本、耗时、执行成功和任务回报，并做经验检索与模型选择。测试过程允许经验更新，不能将其后续 benchmark 全部描述成冻结的跨域迁移。它是 TracePilot 工程方向非常直接的近邻，也说明“trace＋时间＋router”这个组合本身已存在。

**[Router-R1](https://proceedings.nips.cc/paper_files/paper/2025/hash/ceaa137fce916aba5c65fceb1309088b-Abstract-Conference.html)，NeurIPS 2025。** 学习多轮选择/调用模型并聚合结果，确有冻结模型在训练集之外 QA 数据集及新候选模型上的评价。目标主要是质量与价格，不能直接回答相同时限内反馈修复的速度收益；但我们也不能声称既有路由器“都没有泛化”。

**[Capable language models can outgrow the benefits of collaboration](https://www.nature.com/articles/s42256-026-01268-y)，Nature Machine Intelligence，2026-07-24。** 原稿题为 *Towards a Science of Scaling Agent Systems*。正式版用能力与协作指标解释架构收益；87% 选型结果限定为域内留出配置，跨域整体预测较弱，另验证能力阈值对新增编程/终端配置的方向预测。它选择单/多 Agent 架构，而非同 deadline 下的快慢模型。这篇既是“分析→实用规则”的强先行，也是不能把域内拟合包装成泛化规律的提醒；早版的更强跨域数字不能沿用。

**对 RQ3 的回答：** 任务与模型适配、执行经验路由、冻结模型泛化和机制指导配置都已有研究。候选贡献应是具体的时间—反馈机制及其可迁移预测，而不是泛泛增加一个 router。

## 5. 同期工作与增量核查

以下均核验原始论文；SWE-Router 已由 [DL4C 官方 poster 名单](https://dl4c.github.io/poster-sessions/)和[日程](https://dl4c.github.io/schedule/)确认为 ICML 2026 Workshop（DL4C），不是 ICML 主会；其余六项本次未独立确认主会/期刊正式身份，按预印本处理。日期依据 arXiv 提交/修订记录，月份编号本身不作提交日证据。

| 论文与版本 | 与我们实质重合的内容 | 需要保留的差别/限制 |
| --- | --- | --- |
| [EFC：Scaling Laws for Agent Harnesses via Effective Feedback Compute](https://arxiv.org/html/2605.29682v2)，5月首稿，6月24日 v2 | 有效反馈坐标；匹配预算干预；留出及前瞻验证；前缀在线控制 | 必须分清完整轨迹预测和前缀控制；所检章节未见 deadline 条件下跨模型赢家预测 |
| [EdgeBench](https://arxiv.org/html/2607.05155v1)，7月6日首稿 | 真实环境长时迭代、时间—得分曲线、相近初始质量子集、修复/保留/回退与重启对照 | 模型与 harness 有耦合；子集匹配不是共享同一状态；未单独识别模型服务速度效应 |
| [When Agents Slow Down](https://arxiv.org/abs/2609.15309)，9月14日首稿 | 逐步结果、边际收益下降、长轨迹与并行重启资源分配 | 核心尺度是 Elo/token；不能把标题理解为 API 变慢；存在部分 wall-clock 分析，不能说完全没测时间 |
| [PAIR-Bench](https://arxiv.org/html/2607.01360v1)，7月1日首稿 | 定向修复、其他错误改善、已有正确行为保留、单调进展、提示效率 | 主要按交互轮数比较；反馈协议共享初稿，不代表所有模型共享同一初稿 |
| [Try Again, Don’t Look Back](https://arxiv.org/html/2607.26117v1)，7月28日首稿 | 同初稿/重试预算，对照盲重采样、失败通知、执行反馈和反思 | 部分小代码模型盲重采样优于自修复；不是普遍否定反馈，也非相同 wall-clock 对照 |
| [SWE-Router](https://arxiv.org/html/2607.00053v1)，6月30日首稿；ICML 2026 DL4C Workshop | 前 1–4 步 trace 决定继续弱模型或重启强模型，直接比较 prompt 与轨迹信息 | 质量—美元目标；主 mix-1 协议将 4/5 的 SWE-bench Verified 实例纳入训练，不能称整套 benchmark 未见迁移 |
| [RSI-Router](https://arxiv.org/abs/2609.34712)，9月28日首稿 | 从训练轨迹挖子任务，比较路由/强模型轨迹，联合优化模型分配和专用 skills | 本轮核验元数据与方法，未精读其数据划分，不据此作泛化结论 |

### EFC 对定位的影响最大

EFC v2 §4.2 已在同任务、模型以及 token、工具和墙钟预算条件下干预反馈质量。§6.3 冻结坐标/校准流程后采集新轨迹验证，预测指标按重复运行聚合后的配置组计算；§7 与附录 F 另有在线适配器，按预期边际反馈收益与成本选择动作、停止或回退。因此“有效反馈比调用数重要”“仅用当前 trace 控制下一步”“在留出数据预测效果”都不能独立作为我们的创新。[EFC v2](https://arxiv.org/html/2605.29682v2)

这里有两个不同的信息时点：完整轨迹指标可使用后来是否引用/保留反馈，前缀控制器明确移除未来信息。不能拿完整轨迹的预测分数证明运行前选型有效，也不能据此指控它的在线控制器泄漏。所检实验没有直接操纵模型服务速度来验证跨模型 deadline 排序；这只是可追问的边界，不是新颖性证明。[EFC §3.3、§6–7、附录 F](https://arxiv.org/html/2605.29682v2)

### 曲线与失败类型也不是空白

EdgeBench §4.1 尝试降低初始质量差异，§5 分析保留、修改、回退和重启；Slow Down §4–6 将边际收益分析用于资源分配。前者更接近真实时间曲线，后者更接近长轨迹何时继续无益。两者都要求我们超过“画每轮成绩、选几个失败案例”的证据强度。[EdgeBench](https://arxiv.org/html/2607.05155v1)；[Slow Down 全文](https://arxiv.org/pdf/2609.15309)

进一步核查预测范围：EdgeBench §3.2 已用同一任务集合前 6.5 小时的聚合曲线预测后续至 12 小时的表现，明确称为 population-level law；§5.2 还在同样 12 小时总预算下比较持续保留经验与六次独立两小时运行。因此不能说它只有事后曲线或没有经验积累对照，但这不等于新任务实例或人为改变服务速度后的赢家预测。Slow Down §7 则把从任务属性或早期统计预测单任务收益拐点列为未来工作，当前方法仍需测量该任务的 scaling curve。它的 §6 使用已测拐点安排重启预算，不能被描述为完全没有预测或配置决策。[EdgeBench §3.2、§5.2](https://arxiv.org/html/2607.05155v1)；[Slow Down §6–7](https://arxiv.org/pdf/2609.15309)

PAIR 与 Try Again 则给出互补要求：既记修复，也记原本正确部分的退化；既比较有反馈迭代，也比较相同资源下重新尝试。否则快模型的收益可能来自多次抽样，不能归因于有效利用工具反馈。[PAIR](https://arxiv.org/html/2607.01360v1)；[Try Again](https://arxiv.org/html/2607.26117v1)

另有直接反证 **[To Run or Not to Run](https://arxiv.org/html/2606.26978v1)**：对代码执行权限/配额做干预，发现部分强模型可以在明显减少执行开销时维持相近修复表现。§3–4 的执行政策同时影响信息与成本，不是单独的速度干预。作者自报 ISSTA 2026 接收，官方作者页列有该论文，但本轮未完成论文集级确认；不并入上面的已确认主会清单。

### 同日补查：实际工程轨迹、客户端选型和反例

**AutoLab 与 EdgeBench 共同压缩了“从文字游戏扩展到真实工程任务”的新颖性空间。** [AutoLab](https://arxiv.org/html/2606.05080v1) 于 2026-06-03 提交，包含 36 个任务、17 个模型和 2–12 小时预算；§3.3 展示随实际时间变化的优化轨迹，§4 分析失败与资源使用，并比较 terminus-2、mini-swe-agent 和 pi-mono。文中持续迭代与得分的关联不能直接等同于迭代的因果收益；所检分析也不构成在新任务、新推理延迟下冻结规则的赢家预测。它比文字游戏更接近我们的实际任务目标，但完整复跑超出当前低预算先导的合理范围。相比之下，[EdgeBench](https://arxiv.org/html/2607.05155v1) 更集中于长时间优化、保留与回退；二者均应成为轨迹分析的参考。

**AgentOpt 与 AgentTTS 使“记录后自动寻找高效模型配置”已有直接实现。** [AgentOpt v2](https://arxiv.org/html/2604.06296v2)（2026-04-15 修订）通过 HTTP transport 层记录模型调用、token、时延和归属，再搜索角色级模型组合并展示质量、费用和时延前沿。它与 TracePilot 原始的跨框架库目标直接相关；[AgentTTS](https://papers.nips.cc/paper_files/paper/2025/hash/8d9bbba8cac9cabb54e85ee7f21441c8-Abstract-Conference.html) 则联合搜索多阶段模型与采样预算。AgentOpt 的固定工作流配置搜索不同于前缀决策时预测共同 deadline 下的反馈收益，但这种区别仍需实验证明有用。库和可视化可以作为交付物，不独立主张研究创新。

**反复修复是否值得，现有证据随模型与协议而变。** [How Many Tries Does It Take?](https://arxiv.org/html/2604.10508) 在七个模型、HumanEval 和 MBPP 上分析逐轮增益及错误类型；其修复/重采样对照还混有解码温度差异，作者明确承认未完全分离反馈信息效应。[Try Again, Don't Look Back](https://arxiv.org/html/2607.26117v1) 则在另一组较小代码模型中观察到盲重采样的优势。这不是可以直接平均的矛盾：模型、任务和采样条件不同。我们必须固定候选选择规则、计算全部开销并加入无反馈重试，否则更多成功可能只是更多抽样机会。

两项相邻系统研究进一步限定实验解释。[GAIATrace / Vidur-Agent](https://arxiv.org/html/2606.01725v1) 使用 GAIA 上 MiroThinker、OWL 的细粒度轨迹做系统重放，提醒我们调用级 token 速度与任务完成时延并不等价；固定轨迹重放可以研究服务配置，但无法单独验证换模型后的语义行为。[ASAP](https://arxiv.org/html/2606.25207v1) 在 HPO 中对比每轮质量与墙钟收益，附录 B.1 显示评估极快时廉价优化器可凭吞吐量反超 LLM 方案。后者是任务耗时结构改变赢家的相邻证据，不是快慢 LLM 的直接对照。

这五项本次均按预印本/技术报告使用，未据检索不到正式会议记录推断它们没有录用；不计入已确认顶会数。对 AutoLab 只引用已检查的案例、统计和 harness 对照，未把摘要中的“predictor”表述当作已部署的跨条件预测模型。

### 最近一周增量：速度前沿、行为分解与预测已进一步接近

以下四项按本轮核验的预印本身份记录，没有据聚合站的会议标签推定录用。它们分别约束测量、机制与预测主张，不是要求本项目复跑其全部规模。

**[cua-speedrun](https://arxiv.org/html/2609.40284v1)，2026-09-30。** 在四种计算机操作 benchmark 上统一基础设施，并比较模型、reasoning effort、harness 与 I/O 条件的质量—时间—费用前沿。§3.2 已解释“更多推理有时更快”和“更快 I/O 有时反而更慢”：后者会过早取得界面截图，触发额外观察与动作。主结果是各 benchmark 上任务成绩与平均耗时的前沿，并非不同 deadline 下的未见任务赢家预测，也不是跨问答、编程和 GUI 的任务类型选型图。它为“速度—结果图”提供了直接同期参照；改变 I/O 还可能改变可见信息，不能自动视为只改速度的干预。

**[Dissecting model behavior through agent trajectories（SSA）](https://arxiv.org/html/2606.17454v3)，2026-06-16 首稿，10-01 v3。** §3–4.3 将代码状态映射到已验证解的距离，分析进展、回退、编辑/测试比例和阶段安排；最新版分析约 154k 条轨迹。与 EFC 的有效反馈度量相比，它更直接描述每个调用或代码状态变化，并在归一化轨迹位置上聚合行为。解距离依赖参考正确补丁，不能直接作为新任务在线路由的免费特征；回退也可能是有效的对照实验。相同最终成绩、不同解决路径的现象已经有大规模证据，不能把行为分类本身当作我们的核心贡献。

**[LEAP: Learning Efficient Action Proposals For LLM Agents](https://arxiv.org/html/2610.02670v1)，2026-10-02。** 用小 draft 提议动作、大 target 验证，建立包含动作接受、终止、生成与工具耗时的加速预测；§4.4、附录 D.3/H 已用留出顺序轨迹重放和额外工具等待验证模型。它预测的是投机执行相对顺序执行的加速比，而非两个独立模型在共同 deadline 下的质量差。与 EFC 一起，它使“轨迹机制＋留出预测＋延迟干预”的宽泛组合也不再足够新颖；我们的预测对象和增量价值必须具体。

**[Agent Evaluation Reliability: More Tasks Won’t (Always) Fix An Agent Leaderboard](https://arxiv.org/html/2610.00651v1)，2026-09-30。** 在 22 个 benchmark 的分析中用方差分解区分模型、任务、scaffold 及交互，指出可靠排名固定部署系统不等于可靠排名底层模型。它与 SSA 对 harness 影响的分析相互补充；附录 D.4 的留一 benchmark 重拟合用于可靠性敏感性分析，不能写成零样本预测任意新任务。对我们的直接要求是将结论限定到被评估的模型—harness—服务配置，保留配对任务和不确定性，不能靠增加同类任务就声称得到普适模型排名。

上述四项将目前的候选贡献进一步限定为**决策时可得的反馈信号，对未见任务和变化延迟下的截止前相对质量，是否有超出简单能力/速度画像及轨迹重计时的预测价值**。本轮未找到完整直接验证这一具体目标的工作；这不是“首次”的证明，也不能保证先导会得到正面结果。

## 6. 重合审计与剩余问题

| 可能写出的贡献 | 当前判断 | 最直接的先行 |
| --- | --- | --- |
| 小模型在相同时间靠更多交互反超 | 已有直接现象，不能单独主张新颖 | Timely |
| 最佳模型取决于任务难度和预算 | 已有计算最优分析 | Snell；Inference Scaling Laws |
| 分析每轮有效进展、修复与退化 | 已有指标和实验 | EFC；PAIR；Self-Repair；EdgeBench |
| 固定初稿/状态后替换反馈或模型 | 已有局部识别方法 | CUDAnalyst；Self-Repair |
| 用早期 trace 选择模型 | 已有非常直接方法 | SWE-Router；EvoRoute |
| 用机制分析指导模型/Agent 配置 | 已有正式先行 | AgentTTS；SALE；NMI |
| 实际工程任务中的时间曲线及多框架轨迹分析 | 已有直接同期工作 | AutoLab；EdgeBench |
| 跨框架记录后搜索模型组合并绘制开销前沿 | 已有公开库和技术报告 | AgentOpt |
| 计算机操作 benchmark 的速度—质量前沿，以及代码任务轨迹行为分解 | 两种方向各有直接近邻 | cua-speedrun；SSA v3 |
| 轨迹重放预测加速收益，并检验工具延迟变化 | 已有相邻系统方法 | LEAP；预测对象不同 |
| 预测共同 deadline 下的相对优势，并迁移到未见任务及速度条件 | 本轮未找到直接完整验证这一目标的工作；仍是候选 | 需要正面对比上述工作，不能靠控制项组合宣称首次 |

**最强拒稿论证：** 如果最终只是复现 Timely 的交叉曲线，再用 EFC 类指标解释“多轮不等于有效多轮”，最后训练普通 router，审稿人有充分理由认为是既有结论的拼接。换成代码任务、加 Langfuse 或把横轴改成秒数都不能自动解决这一问题。

**较有价值的主张应是一个可证伪的预测：** 在预先规定的决策时点，仅使用任务输入或截至该时点的轨迹前缀，并计入探测开销，使用开发集学得的反馈利用特征，能否预测快慢配置在时限 D 下的质量差，并在改变推理或工具延迟后，比首轮质量、纯速度、历史质量—时间曲线等基线更准确？若机制指标只在事后相关，不能外推或帮助选择，就只能写成有限范围的实证发现，不能声称通用选型规律。

所谓“选择图”应区分开发集测量点与留出集预测点。颜色表示某时限下的相对优势，附不确定性和无显著优势区域；任务特征尽量用可测量的反馈可得性、验证成本、可修复性等，而不是只用“代码/问答”标签。图是研究结论的呈现，预测成功才是证据。

## 7. 从文献直接导出的最小实验要求

以下为待设计/待运行项目，当前没有对应新实验结果。

1. **固定比较对象和总时间。** 先两个实际快慢配置、同一 harness、客观验收的小型编程任务。记录推理、工具、路由、重试及最终提交的实际时间；人工注入等待计入任务墙钟和截止判断，只在耗时分解中单列。依据独立开发集的时间校准预先定义一组绝对截止时间及选择规则，在所有测试速度条件下沿用同一组 D，不在观察胜负后挑交叉点。首版每任务内串行生成候选，任务之间也串行、随机交错次序；记录资源、限流、排队和缓存条件，并行采样另列协议。
2. **分别观察原生与共同状态。** 原生完整运行保留真实初稿能力差异；共同错误状态续跑测反馈利用/修复差异。先导交付物只需任务专用恢复：从不可变副本还原工作区、固定对话前缀及可见测试输出；先核验恢复一致再续跑，无需先建通用 checkpoint。状态按两候选模型均衡来源或独立来源预先采集并标记，按来源分层报告；状态、分支与原任务继承同一数据组，不能只选一方容易修复的错误。该局部估计不代替端到端比较。
3. **分开改变速度与信息。** 对同模型增加外部等待来识别受控减速效应；单独改变工具等待。固定任务环境、反馈生成规则和后续资源配置，相同动作/状态返回相同语义反馈，允许策略分叉产生不同后续反馈；固定反馈重放另作局部对照。减速只能识别该干预范围，不能冒充更快服务的真实效果。记录 deadline 可见性：时间不进入提示时接近固定行为的截断实验；进入提示时还包含策略适应，两者不能混为同一个效应。
4. **比较更多尝试与反馈利用。** 至少含首稿、盲重采样、执行反馈修复；逐轮记录有效修复、退化、无效重复、有效反馈与等待。盲重采样指下一候选不读取前一候选/诊断；若用可见测试选择样本，选择阶段仍使用反馈，须计入时间和费用并固定规则。隐藏验收只作离线评分，不提供给 Agent 或样本选择器。
5. **冻结预测再验证。** 运行前选型只用任务输入及开发集形成的模型/任务画像，画像获取成本单列；短前缀选型首版只探测一个显式候选，全部探测计入共同 deadline。两个模型都运行后提取的特征只作离线分析，不能冒充廉价在线选型。按任务来源/仓库/模板分组，并分别报告“同任务新延迟”“新任务原延迟”“新任务新延迟”；新条件下不重拟合规则/阈值，允许重校准的协议另列。任务实例、任务族和新模型泛化也分开。所有特征遵守决策时点，最终分数只作标签。
6. **以强简单基线决定是否继续。** 比较固定快/强模型、模型×任务画像查表、开发集估计的首轮能力与实测速度、历史质量—时间曲线外推、prompt-only/prefix 路由和可复现的 EFC 风格前缀指标。增加“开发集轨迹按新延迟重计时”的截断预测；目标测试任务的完整轨迹重放只作离线诊断，不能用来在线选型。增加独立尝试参照：若单次成功率为 p、可完成 k 次尝试，至少一次成功覆盖率为 `1-(1-p)^k`；p 按开发集任务属性/难度分层估计，目标任务隐藏标签不可用；K 使用实测尝试耗时分布推得。对分层后的 `1-(1-p_i)^K_i` 取期望，不把全局平均 p 与平均 K 直接代入；成功与耗时相关时，改用联合经验重采样而非该简式。该式依赖独立性，且是覆盖率，不等于实际选择出的最终答案成功率；部署基线必须用同一可见选择规则并计入成本。最终按选型后质量、相对离线 oracle 的损失和置信区间判断；oracle 仅为上界。改编既有方法要标明，不能把弱代理称为原方法。

特征来源进一步分开：运行前可用任务描述、已知工具/验证接口和开发集的模型修复/退化画像；需要实际执行才能估计的验证成本只能用开发集估计，或计入目标任务探测。短前缀可增加已发生的错误类型、可见测试变化、重复动作及耗时。隐藏验收、另一个模型在该目标任务上的结果均不可用。要验证的是任务属性与模型画像的交互或前缀的额外预测价值，而不只是把模型级常量换个名称。若排序变化完全由重计时截断解释，不主张发现新的反馈适应机制。

优先完成计时与恢复口径、两模型的原生/共同状态和盲重采样对照；仅在数据可靠且存在待解释差异时扩大到留出预测及第二任务族。正式实验协议还需冻结预测增益的评价指标、精度目标、样本量与停止条件，本次文献报告不任意指定数值门槛。

有额外迭代但没有有效修复、只有先验更强导致领先、改变任务/速度后预测失效，都是应保留的有效结果。先导用于判断是否存在值得扩展的规律，不以挑 deadline 或删掉负面任务制造反超。正式样本量和第二任务族在开发结果与预算核算后锁定；本轮不承诺一个月覆盖所有实验维度。

## 8. 阅读顺序与项目决定

建议优先读 **Timely §5.1 → EFC v2 §3.3、§6–7 → cua-speedrun §3.2 → SSA v3 §3、§4.3**：依次确认已知现象、指标与控制重合、实际速度前沿、逐轮行为先行。随后读 **LEAP §3.2、§4.4、附录 H**，检查“机制预测”应达到的证据强度，再读 CUDAnalyst 的局部干预与 AutoLab 的实际工程轨迹。工程上单独对照 AgentOpt，AgentTTS、SALE 和 SWE-Router 用于配置/路由基线，NMI 用于核对泛化口径。

当前决定：保留这个方向作为实证研究候选，按用户授权先完成官方 Jericho 评测路径的协议复验，再在客观验收的编程任务上冻结 R3/R4 机制与预测协议，验证机制能否增加预测价值。Jericho 的计时复验不自动承担编程修复/退化实验；详细衔接见 [执行计划](timely-reproduction.md)。TracePilot 负责可靠记录和实验复现；暂不以完整通用 router、后训练或购物扩展作为前置条件。与当前用户目标不同的“历史耗时预测价值 vs 紧迫感”仅保留为历史候选，不再作为默认主线。

## 参考文献与身份记录

下列题名、作者与正式身份取自原始记录；长作者列表用“等”缩写。正文所述未覆盖内容均限于已检查章节，而非全文不存在的穷尽证明。

1. Yichuan Ma 等. **Timely Machine: Awareness of Time Makes Test-Time Scaling Agentic.** ACL 2026, Long Papers, 4619–4636. [官方记录](https://aclanthology.org/2026.acl-long.211/)
2. Charlie Snell, Jaehoon Lee, Kelvin Xu, Aviral Kumar. **Scaling LLM Test-Time Compute Optimally Can be More Effective than Scaling Parameters for Reasoning.** ICLR 2025. [官方记录](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b623663fd9b874366f3ce019fdfdd44-Abstract-Conference.html)
3. Yangzhen Wu, Zhiqing Sun, Shanda Li, Sean Welleck, Yiming Yang. **Inference Scaling Laws: An Empirical Analysis of Compute-Optimal Inference for LLM Problem-Solving.** ICLR 2025. [官方记录](https://proceedings.iclr.cc/paper_files/paper/2025/hash/8c3caae2f725c8e2a55ecd600563d172-Abstract-Conference.html)
4. Jiin Kim, Byeongjun Shin, Jinha Chung, Minsoo Rhu. **The Cost of Dynamic Reasoning: Demystifying AI Agents and Test-Time Scaling from an AI Infrastructure Perspective.** HPCA 2026. [官方会议记录](https://2026.hpca-conf.org/details/hpca-2026-main-conference/17/The-Cost-of-Dynamic-Reasoning-Demystifying-AI-Agents-and-Test-Time-Scaling-from-an-A)
5. Lingjiao Chen, Jared Davis, Boris Hanin, Peter Bailis, Ion Stoica, Matei Zaharia, James Zou. **Are More LM Calls All You Need? Towards the Scaling Properties of Compound AI Systems.** NeurIPS 2024. [官方记录](https://proceedings.neurips.cc/paper_files/paper/2024/hash/51173cf34c5faac9796a47dc2fdd3a71-Abstract-Conference.html)
6. Theo X. Olausson, Jeevana Priya Inala, Chenglong Wang, Jianfeng Gao, Armando Solar-Lezama. **Is Self-Repair a Silver Bullet for Code Generation?** ICLR 2024. [官方记录](https://proceedings.iclr.cc/paper_files/paper/2024/hash/9ddc141bdbf9d1db510cefff56c586ad-Abstract-Conference.html)
7. Yee Hin Chong, Jiaming Wu, Youhui Zhang, Peng Qu. **Towards Feedback-to-Plan Decisions for Self-Evolving LLM Agents in CUDA Kernel Generation.** ICML 2026, PMLR 306:20365–20397. [官方记录](https://proceedings.mlr.press/v306/chong26b.html)
8. Fali Wang 等. **AgentTTS: Large Language Model Agent for Test-time Compute-optimal Scaling Strategy in Complex Tasks.** NeurIPS 2025. [官方记录](https://papers.nips.cc/paper_files/paper/2025/hash/8d9bbba8cac9cabb54e85ee7f21441c8-Abstract-Conference.html)
9. Lisa Alazraki, William F. Shen, Yoram Bachrach, Akhil Mathur. **Scaling Small Agents Through Strategy Auctions.** ICML 2026, PMLR 306:1706–1766. [官方记录](https://proceedings.mlr.press/v306/alazraki26a.html)；方法阅读依据 [arXiv:2602.02751v3](https://arxiv.org/html/2602.02751v3)。
10. Guibin Zhang, Haiyang Yu, Kaiming Yang, Bingli Wu, Fei Huang, Yongbin Li, Shuicheng Yan. **EvoRoute: Experience-Driven Self-Routing LLM Agent Systems.** ACL 2026, Long Papers, 38213–38225. [官方记录](https://aclanthology.org/2026.acl-long.1771/)；方法阅读依据 [arXiv:2601.02695v1](https://arxiv.org/html/2601.02695v1)。
11. Haozhen Zhang, Tao Feng, Jiaxuan You. **Router-R1: Teaching LLMs Multi-Round Routing and Aggregation via Reinforcement Learning.** NeurIPS 2025. [官方记录](https://proceedings.nips.cc/paper_files/paper/2025/hash/ceaa137fce916aba5c65fceb1309088b-Abstract-Conference.html)
12. Yubin Kim 等. **Capable language models can outgrow the benefits of collaboration.** Nature Machine Intelligence 8:1157–1172, 2026. [正式版](https://www.nature.com/articles/s42256-026-01268-y)；预印本原题 *Towards a Science of Scaling Agent Systems*, arXiv:2512.08296。
13. Xuanliang Zhang, Dingzirui Wang, Keyan Xu, Qingfu Zhu, Wanxiang Che. **Scaling Laws for Agent Harnesses via Effective Feedback Compute.** arXiv:2605.29682v2, 2026. [核验版本](https://arxiv.org/html/2605.29682v2)
14. Deyao Zhu 等. **EdgeBench: Unveiling Scaling Laws of Learning from Real-World Environments.** arXiv:2607.05155v1, 2026. [核验版本](https://arxiv.org/html/2607.05155v1)
15. Kaiyuan Liu 等. **When Agents Slow Down: Understanding LLM Agents' Test-Time Strategies via Elo-per-token Analysis.** arXiv:2609.15309, 2026. [原始记录](https://arxiv.org/abs/2609.15309)
16. Cuong Chi Le, Aashish Yadavally, Minh Le-Anh, Tien N. Nguyen. **Benchmarking Code Improvement with Progressive, Adaptive, and Interactive Feedback.** arXiv:2607.01360v1, 2026. [核验版本](https://arxiv.org/html/2607.01360v1)
17. Yuvraj Verma. **Try Again, Don’t Look Back: Blind Resampling Outperforms Self-Repair in Small Code Models.** arXiv:2607.26117v1, 2026. [核验版本](https://arxiv.org/html/2607.26117v1)
18. Seongho Son, Sangwoong Yoon, Jiahua Tang, Shuhan Wang, Lorenz Wolf, Ilija Bogunovic. **SWE-Router: Routing in Multi-turn Agentic Software Engineering Tasks.** ICML 2026 DL4C Workshop；arXiv:2607.00053v1. [原始记录](https://arxiv.org/abs/2607.00053)；[官方录用 poster 名单](https://dl4c.github.io/poster-sessions/)。Workshop CFP 明示 [non-archival](https://dl4c.github.io/callforpapers/)，不计入主会论文。
19. Hao Li, Hangfan Zhang, Zhiyao Cui, Chunjiang Mu, Yiqun Zhang, Bo Zhang, Danyang Jia, Shuyue Hu. **RSI-Router: Evolving Subtask-Level LLM Routing and Skills for Cost-Efficient Agents.** arXiv:2609.34712v1, 2026. [原始记录](https://arxiv.org/abs/2609.34712)
20. Zhihao Lin, Junhua Zhu, Mingyi Zhou, Xin Wang, Zhensu Sun, Renyu Yang, David Lo, Li Li. **To Run or Not to Run: Analyzing the Cost-Effectiveness of Code Execution in LLM-Based Program Repair.** arXiv:2606.26978v1；作者自报 ISSTA 2026 接收，[官方作者页](https://conf.researchr.org/profile/issta-2026/zhihaolin1)列文，本轮未完成论文集级核验。[全文](https://arxiv.org/html/2606.26978v1)
21. Zhangchen Xu 等. **AutoLab: Can Frontier Models Solve Long-Horizon Auto Research and Engineering Tasks?** arXiv:2606.05080v1, 2026-06-03. [原始记录](https://arxiv.org/abs/2606.05080)
22. Wenyue Hua 等. **AgentOpt v0.1 Technical Report: Client-Side Optimization for LLM-Based Agent.** arXiv:2604.06296v2, 2026-04-15. [核验版本](https://arxiv.org/html/2604.06296v2)
23. Johin Johny Arimbur. **How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation Across Model Scales and Benchmarks.** arXiv:2604.10508, 2026. [原始记录](https://arxiv.org/abs/2604.10508)
24. Donghwan Kim, Prakhar Singh, Younghoon Min, Jongryool Kim, Jongse Park, Kiwan Maeng. **Characterization of Multi-Model Agentic AI Systems on General Tasks via Trace-Driven Simulation.** arXiv:2606.01725v1, 2026-06-01. [全文](https://arxiv.org/html/2606.01725v1)
25. Taicheng Guo 等. **ASAP: Agent-System Co-Design for Wall-Clock-Centered Auto HPO Research for ML Experiments.** arXiv:2606.25207v1, 2026-06-23. [全文](https://arxiv.org/html/2606.25207v1)
26. Pranjal Aggarwal 等. **cua-speedrun: Standardized Benchmarking of the Speed of Computer-Use Agents.** arXiv:2609.40284v1, 2026-09-30. [全文](https://arxiv.org/html/2609.40284v1)
27. Gaurav Gupta, Vatshank Chaturvedi, Sudipta Sengupta, Jun Huan, Anoop Deoras. **Dissecting model behavior through agent trajectories.** arXiv:2606.17454v3, 2026-10-01. [版本记录](https://arxiv.org/abs/2606.17454)；[全文](https://arxiv.org/html/2606.17454v3)
28. Zhen Xu, Qizheng Zhang, Gerry Wan, Shang Zhu, Ce Zhang. **LEAP: Learning Efficient Action Proposals For LLM Agents.** arXiv:2610.02670v1, 2026-10-02. [全文](https://arxiv.org/html/2610.02670v1)
29. Michael Hardy, Ruhana Azam, Anka Reuel, Mykel Kochenderfer, Sanmi Koyejo. **Agent Evaluation Reliability: More Tasks Won’t (Always) Fix An Agent Leaderboard.** arXiv:2610.00651v1, 2026-09-30. [全文](https://arxiv.org/html/2610.00651v1)
