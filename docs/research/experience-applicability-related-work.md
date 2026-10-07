# 经验何时适用：条件化技能、拒绝复用与负迁移的相关工作

核验日期：2026-10-07。对象：TracePilot 方向一。仅调研，无新模型实验。

## 摘要

本轮针对“从执行成败中提炼经验，并判断在新任务上何时使用或拒绝”检索方法、反例与评测三类证据。结果要求修正前一轮建议：条件化经验、推理时筛选、失败后修订以及无模型权重更新的技能学习，均已有直接工作；相关机制不仅见于近期预印本，也见于 ICML 2026 正式论文。可继续研究的应是具体方法在受控条件变化下的失败机制及可测改进，不能将字段设计、LLM 适用性判断或增加验收单独宣称为创新。现有证据也不支持“有条件的记忆总比完整轨迹好”。

## 1. 本轮具体问题

方向一原表述是：将轨迹提炼成“触发条件、操作建议、验收方式、不适用条件”，让冻结模型在后续新任务减少重复错误。调查回答：RQ1，是否已有相同机制且无需模型微调；RQ2，是否已有选择不使用经验的方法；RQ3，现有实验如何证明迁移、如何区分帮助和伤害。

前轮已查的 ExpeL、MemRL、WikiSkill 等是背景，本轮优先找比它们更直接的重合。**这是补充查重后的判断修正，不是已确认的研究空白。**

## 2. 检索与证据边界

三条并行检索线分别覆盖适用性/效用方法、负迁移与评测反例、带前置条件的程序技能。关键词包含 applicability、precondition、boundary-aware、when not to reuse、abstention、negative transfer、procedural memory。主要覆盖 2025–2026，沿直接相关论文补查先行。

以下纳入 11 篇核心工作，另列两篇相邻但任务设定不同的论文。存在性、题名/作者、方法描述通过作者原文核对；会议身份优先核对 PMLR、ACL Anthology、IFAAMAS。论文数字不是本项目复现结果。XSkill 的方法细节来自 arXiv v1，会议身份单独由 PMLR 核实；Skill-Pro 的旧版题名 ProcMEM 与正式版不可当两篇。未核实官方会议记录的工作仅标预印本，即使作者自报接收。

## 3. 按经验生命周期划分

| 主要问题 | 对应工作 | 已经覆盖的想法 |
| --- | --- | --- |
| 表达、适配和执行时判断 | BASM、XSkill、MACLA、SkillAdaptor | 条件化技能、成功/失败对照、针对当前状态改写或拒绝 |
| 验收、维护和更新 | Skill-Pro、Grounding Agent Memory、ACL experience-following 研究 | 候选技能门控、环境核验、按后续表现维护记忆 |
| 拒绝复用与效果归因 | RSCB-MC、MemHarness、Compliance Trap、MATE | 不注入记忆、状态不匹配处理、伤害/恢复诊断、接口混杂控制 |

分类按本文主要比较目的，部分论文跨越多阶段。例如 BASM 同时包含检索和执行检查，SkillAdaptor 同时包含技能修订与接纳，不能把这些阶段当作互不关联的新方法。

## 4. 条件化技能已经有直接先行

BASM 把适用边界写入技能并在行动时执行检查，XSkill 则针对当前任务/视觉状态改写经验并丢弃不适用项；两者已经覆盖“检索到相似经验后还要判断能否使用”的核心。MACLA 进一步以成败对照收紧前置条件，SkillAdaptor 用失败定位和重跑检验修订技能。因此，单纯从成功轨迹改为混合成功/失败、增加条件字段，不能形成区别。[BASM §4](https://arxiv.org/html/2608.22339v1)、[XSkill §2.3.2](https://arxiv.org/html/2603.12056v1)、[MACLA v1](https://arxiv.org/abs/2512.18950v1)、[SkillAdaptor §3](https://arxiv.org/html/2606.01311v1)。

| 工作与已核实身份 | 最接近的机制 | 实验证据与限制 |
| --- | --- | --- |
| **BASM / When Not to Imitate**，2026-08 arXiv | 技能含适用、风险、禁用、恢复字段；根据状态 apply/suppress/repair，含规则与模糊条件判断 | BFCL、AppWorld、AgentDojo；所读 §5.1 未清楚交代技能构建/调参/最终测试划分，不能断言已证明严格留出迁移，也不能反向断言泄漏。作者自报 EMNLP 2026 Findings，本轮未独立确认官方记录 |
| **XSkill，ICML 2026** | 冻结模型；condition–action 经验与任务级 skill 双路积累；推理时改写条件/动作并拒绝明显不适用项 | 附录 B.1 有独立积累/测试划分、跨 benchmark 和跨模型评估；适用性主要依赖模型判断，所读实验未建立逐条记忆收益的风险校准保证 |
| **MACLA，AAMAS 2026** | 前置条件、动作模式、后置条件；Beta 可靠性估计与预期效用选择；成败对照修订条件 | ALFWorld、WebShop、TravelPlanner、InterCodeSQL；需要可评价的后续结果。历史成功率不自动等于当前状态下使用记忆的因果收益 |
| **SkillAdaptor**，2026-05 首发预印本 | 冻结模型；成功轨迹初始化，失败步骤归因，修改关联技能，再重跑验收 | WebShop 有训练/测试划分；所读 PinchBench/Claw-Eval 部分未同样清楚交代各阶段隔离。技能更新的接纳门槛不同于新任务上的拒用概率校准 |

正式身份：[XSkill 的 PMLR 记录](https://proceedings.mlr.press/v306/jiang26aq.html)、[MACLA 的 AAMAS 2026 正式论文](https://ifaamas.org/Proceedings/aamas2026/pdfs/FKYO8341.pdf)。BASM 的字段和任务规模描述以固定 v1 为准，不将摘要中的最大提升直接解释成相对成功技能基线的提升。

## 5. 无权重更新也可以有验收与维护

Skill-Pro 在文字技能库中做候选生成和 PPO 风格评分门控，Grounding Agent Memory 用只读环境探查来验证或缩小记忆适用范围，ACL 的 experience-following 研究则根据后续使用表现删除有害记录。这三者分别提供离线候选筛选、外部证据核验和运行历史维护；“多加一个 verifier”同样已有直接先行。[Skill-Pro 官方论文](https://proceedings.mlr.press/v306/mi26d.html)、[Grounding §3.3](https://arxiv.org/html/2609.11060v1)、[ACL 2026 论文](https://aclanthology.org/2026.acl-long.27/)。

| 工作 | 无权重更新的含义 | 不应扩大解释的部分 |
| --- | --- | --- |
| **Skill-Pro，ICML 2026**，旧名 ProcMEM | 技能包含激活/执行/结束条件；以轨迹反馈提出文本候选并门控、维护技能池。Non-Parametric PPO 不等于微调 LLM | v1 门控涉及历史动作概率比和优势估计，需要核查具体 API 是否提供所需量；不能当成无需评价信号的通用即插即用方法 |
| **Grounding Agent Memory**，2026-09 arXiv | 任务后 curator 用只读工具核对前提、反例、陈旧信息，可收窄/删除记忆；不重训模型 | 后续任务在核验完成前不可见，但主要是共享环境内顺序任务复用，非留出环境泛化。CLBench 39→73 是相对无记忆；普通记忆 70±16→探查 73±5 才对应探查增量（百分比，均值±95% CI，5 次配对独立运行），不能混用或仅据点估计断言显著；curation 成本需单计 |
| **How Memory Management Impacts LLM Agents，ACL 2026 主会** | 选择性写入、按历史下游效用删除；揭示相似经验可能诱导相似但错误的行为 | 历史效用受 evaluator 质量影响，且是相关性；删除整条经验不同于只在特定状态拒用。任务重排序不等于未见域迁移 |

ProcMEM v1：[原方法细节](https://arxiv.org/html/2602.01869v1)；当前题名及正式身份以 [Skill-Pro PMLR](https://proceedings.mlr.press/v306/mi26d.html) 为准。

## 6. 拒绝使用经验及负迁移测量也已有研究

RSCB-MC 明确把不注入与 abstain 作为动作，MemHarness 会比较源状态和当前状态并输出空经验；两者表明“允许拒用”已经不是空白，但前者主要是代理指标验证，后者训练了策略。Compliance Trap 和 MATE 则提醒：表面上的门控收益可能来自额外尝试、保守提示或动作规范化，而非真正学会适用性。[RSCB-MC](https://arxiv.org/html/2604.27283v1)、[MemHarness §3.3/4.5](https://arxiv.org/html/2607.28272v1)、[Compliance Trap](https://arxiv.org/html/2607.10608v1)、[MATE](https://arxiv.org/html/2609.35808v1)。

| 工作 | 相关设计 | 关键限制/必要对照 |
| --- | --- | --- |
| **Learning When to Remember / RSCB-MC**，2026-04 arXiv | 用兼容性、不确定性、历史误注入风险、成本等特征选择注入、摘要、不使用、拒绝等 | 不微调 LLM，但更新 bandit/风险模型；主要是小规模离线代理测试，未充分证明端到端代码修复和跨仓库泛化 |
| **MemHarness**，2026-07 arXiv | 源观察与当前状态对照，保留/修改/拒绝经验；另有 1,000 个最小状态改动探针 | 使用 GRPO，非纯 training-free；状态探针评价重建行为，不等于完整任务成功。不能以“我们加入条件反例”作为唯一差异 |
| **The Compliance Trap**，2026-07 arXiv | 诊断冲突记忆的采纳、传播和恢复；比较先无记忆、失败后才使用记忆 | 机制样本按记忆敏感性挑选，部分记忆人工或根据任务规格构造；不是自动从旧任务学习后在新任务部署。重试依赖可靠失败信号，必须同预算比较无记忆重试 |
| **MATE**，2026-09 arXiv | 从轨迹取 condition–action–effect，规范动作并按任务呈现，额外 LLM 调用为零 | 受控实验的主要增益来自动作规范化；丰富条件卡未显著超过同源动作序列，在其他新记忆/任务设置中完整轨迹可更好。必须有同源、等预算、动作规范化的简单基线 |

两篇相邻工作也已核对但不作为完全同设定的方法：Decision-Aware Memory Cards 已有 trigger/evidence/action/scope 与负迁移风险评分，但主实验证据集中于上下文选择和文件检索；BCIT 的 Knowing When Not to Reuse 检查历史更新的适用性并选择验证/拒绝，但它管理的是模型后训练方案，涉及真实参数训练。前者不能冒充完整修复任务迁移，后者不能冒充 training-free agent 记忆。[Decision-Aware Memory Cards](https://arxiv.org/html/2606.08151v1)、[BCIT](https://arxiv.org/html/2608.26730v1)。

## 7. 对 TracePilot 的判断与阅读顺序

**当前方案存在高度重合，不建议以“给经验加适用条件并在新任务使用”直接主张方法创新。** training-free、来自 trace、保留失败经验、状态感知、跨任务评估、候选验收，已有工作分别或共同实现。上述方法的局限是可研究入口，不能自动当作我们的贡献。

先读 BASM §4–5，确认字段、checker 和基线；再读 XSkill §2.3.2/附录 B.1，确认适配与迁移协议；接着读 Grounding §3.3/§5，理解外部证据如何限定适用范围。Skill-Pro 和 MACLA 是候选方法基线，MATE 是必须纳入的反混杂对照。代码仓库公开不等于已经在本机成功复现，本轮没有部署它们。

一个共用的诊断维度是：**在表面相似、关键前提改变的新任务上，现有方法能否可靠区分有帮助和有害的经验？它们的收益是否超过同源动作规范化和等预算重试？** 它为下一节三个候选提供条件成立、前提改变和证据不足的评测切分，不表示已选定唯一主线或确认新颖性。MemHarness 的状态反例、BASM 的边界诊断、RSCB 的拒用选择均必须正面比较，不能只同无记忆基线比较。

如果继续，先冻结技能与阈值，再按任务族/环境分组留出。对同一任务环境从 reset 配对运行有/无记忆版本，多次采样估计成功差值，不把一次差值当稳定因果效应。按经验触发阶段记录“原本成功但被记忆破坏”“原本失败被挽救”、拒用覆盖率与全部门控开销；未执行分支不填伪反事实标签。只读核验没有权限验证的前提应保留未知。上述设计仍需单独冻结预算后执行，本轮只完成查重。

## 8. 中途发现、值得验证的研究问题

按用户要求保留以下候选。优先级表示与现有资源及原始速度问题的匹配程度，不表示新颖性已确认；它们都需要进一步比较具体先行，不能用更换题名代替差异。

| 优先级 / 问题 | 为什么值得检查、最近先行 | 最小可证伪实验 | 继续或停止的依据 |
| --- | --- | --- | --- |
| **A：核验经验的时间，什么时候值得花？** | Grounding 用环境探查核对或限定记忆，Skill-Pro 有候选验收，BASM 有执行检查。可研究的是共同 deadline 下的净收益及收益边界，而非首次加核验器 | 固定经验来源和任务，比较无核验、简单条件检查、LLM 检查、只读工具核验；另含无记忆、等预算无记忆重试、同源动作规范化对照。使用相同信息权限和预先锁定的少量共同 deadline，把生成、核验、失败重试成本列全；离线维护成本另报并按明确复用次数摊销 | 若改善成功率但代价超过时限，得到部署边界；只有优势随可观测任务条件稳定变化，才有继续研究选择策略的依据 |
| **A：同一份经验，是否更能帮助快模型？** | 与原始“快模型能否靠迭代补足能力”的问题衔接；XSkill、Skill-Pro 已研究跨模型/Agent 迁移，MATE 提醒完整轨迹和动作规范化可能更好 | 两个实测快慢配置使用同源固定经验；比较无记忆、规范化动作序列、原始轨迹、条件卡片。在共同 deadline 下比较各模型的配对成功率增量，并检查来源模型、上下文长度和额外调用的影响 | 不预设小模型获益更大。两个配置只能给配置级证据；若增益来自格式修复或缩短上下文，不归因于更好的经验适用性判断 |
| **B：拒绝有害经验，会不会也拒绝有用经验？** | BASM、RSCB-MC、MemHarness 已明确涉及拒用；Compliance Trap 观察到防御提示可能同时减少帮助。重点是帮助—伤害的取舍，不是“首次允许拒绝” | 使用条件成立、关键条件改变、证据不足三类分组留出任务；从 reset 对有/无记忆做重复配对，比较拒用策略的成功率、伤害减少与有效经验覆盖率，并加入等预算无记忆重试 | 只有优于简单保守阈值且不只是全面少用记忆，才支持更可靠的适用性判断；没有执行的分支保持未知，不伪造反事实标签 |

建议先用现有公开实现和小型可重置任务检查第一项，第二项作为与原始模型速度问题连接的扩展，第三项作为评测维度。初次先导只检查协议能否运行和信号能否识别，样本量及费用应据此确定；本轮不自动启动新实验，也不同时实现三个方法。

## 9. 回答研究问题

RQ1：已有直接的、无需 LLM 权重更新的条件化经验方法，其中 XSkill 和 Skill-Pro 已确认 ICML 2026，MACLA 已确认 AAMAS 2026。RQ2：已有明确拒用、状态适配和外部验证机制；“何时不使用”不是无人研究的问题。RQ3：现有评测在分组留出、人工构造记忆、历史效用与真实贡献、源环境复用及总成本上存在不同边界，不能合并成统一泛化结论。本次最有价值的结果是明确强基线并下调宽泛创新判断，而非马上换一个同义名称继续实现。

## 参考文献

以下为题名和版本索引；正文链接提供方法原文，会议身份另指官方记录。

1. Zihan Lin, Zhenyu Chen, et al. “When Not to Imitate: Boundary-Aware Skill Memory for Reliable Tool-Use LLM Agents.” arXiv:2608.22339v1, 2026.
2. Guanyu Jiang, Zhaochen Su, Xiaoye Qu, Yi R. Fung. “XSkill: Continual Learning from Experience and Skills in Multimodal Agents.” ICML, 2026. 方法核验版本 arXiv:2603.12056v1.
3. Saman Forouzandeh, Wei Peng, et al. “Learning Hierarchical Procedural Memory for LLM Agents through Bayesian Selection and Contrastive Refinement.” AAMAS, 2026. 方法核验 arXiv:2512.18950v1，正式版 DOI:10.65109/FKYO8341.
4. Zhuoyun Yu, Xin Xie, et al. “SkillAdaptor: Self-Adapting Skills for LLM Agents from Trajectories.” arXiv:2606.01311v1, 2026.
5. Qirui Mi, Zhijian Ma, et al. “Skill-Pro: Learning Reusable Skills from Experience via Non-Parametric PPO for LLM Agents.” ICML, 2026. 旧版 ProcMEM，arXiv:2602.01869v1.
6. Susheel Suresh, Hazel Mak, et al. “Grounding Agent Memory: Environment-Probing Curation for Enterprise Agents.” arXiv:2609.11060v1, 2026.
7. Zidi Xiong, Yuping Lin, et al. “How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior.” ACL, 2026.
8. Mehmet Iscan. “Learning When to Remember: Risk-Sensitive Contextual Bandits for Abstention-Aware Memory Retrieval in LLM-Based Coding Agents.” arXiv:2604.27283v1, 2026.
9. Rong Wu, Daocheng Fu, et al. “MemHarness: Memory Is Reconstructed, Not Replayed.” arXiv:2607.28272v1, 2026.
10. Yixiong Chen, Xinyi Bai, Alan Yuille. “The Compliance Trap: Diagnosing How AI Agents Consume Conflicting Memory.” arXiv:2607.10608v1, 2026.
11. Quanquan Li, Hongbo Zhang, et al. “When Successful Memories Mislead Embodied Agents: Memory Adaptation for Task-Conditioned Execution.” arXiv:2609.35808v1, 2026. HTML 题名为 Adaptation，摘要元数据拼为 Adaption。
12. Xinyu Guan, Qianyang Zhao, Yuming Deng. “Decision-Aware Memory Cards: Counterfactual-Inspired Context Selection and Compression for Tool-Using LLM Agents.” arXiv:2606.08151v1, 2026.
13. Tingyun Li, Wenfeng Feng, et al. “Knowing When Not to Reuse: Conditional Experience Transfer in Autonomous LLM Post-Training.” arXiv:2608.26730v1, 2026. 仅作设定边界说明。
