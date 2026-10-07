# Timely ML 离线分析审查

## 范围与实际调用

新增离线分析、绘图、阶段浏览器和验证脚本；不修改冻结运行协议、执行器、计费或原始评分。Claude CLI 使用 `--model claude-opus-5-5 --effort medium`，只读、无工具、无会话保留，没有设置费用或轮次上限。首轮退出码 0，`modelUsage` 与 canonicalModel 均为 `claude-opus-5-5`，结论为“未发现阻断问题”。原始审查输出留在忽略目录。

## 首轮发现与处置

1. **核验可复现性和缺失链接**：新增 `research/verify_timely_ml_analysis.py`，从冻结原始结果独立核验 48 个单元、有效性、费用、阶段覆盖、确定性构建与图表 hash，生成 validation.json；本文件补齐审查链接。
2. **时间归因**：检查实际 wrapper 和上游调用边界，请求时间从独立 episode 信号量之前起算；每 episode 串行，该信号量无跨任务争用。SDK、准入、网络都在请求区间；批次队列等待不在 episode 时间中。报告和图注披露其他调度/资源争用，不把残差当纯训练时间。
3. **规则计数与意图语义**：标签改为“建模器组合变化”，明确包括新增集成组件；计数是规则命中，质量改进可能漏入此类或 unknown。保留原规则结果，不谎称逐条人工真值。
4. **阶段边界**：明确单轮意图只使用当前/过去信息，合并边界可以用执行结果，是事后展示，不能整体作为在线特征。
5. **真实评分口径**：核对冻结 `ml_metrics.py`，Leaf 为 argmax accuracy，三个二分类任务按 >=0.5 阈值计算 accuracy；概率可接受，最终不按 AUC 择优。提示/AUC 冲突列为限制，原分数未改。
6. **旧提交复用**：执行日志没有逐轮提交 hash/mtime，明确 23 条恢复是评分状态恢复，不能宣称 23 次代码修复；不通过重跑补证据。
7. **公开字段**：逐行检查计划仅含 model、multiplier、phase、repeat、run_id、task；无本地路径、端点、密钥。原文、代码、stderr 不纳入公开导出。

可选建议处置：保留固定类别图例，并解释 same-code 主意图为零但实际重复 21 次；失败主类别优先级已披露；stderr 正则的泛化分类风险保留，11 条失败依据原始日志逐项核对，不将其用作通用错误分类器。Bootstrap 49/1949 索引采用 nearest-rank 百分位，属于有效定义，不采纳简单改成 50/1950 的建议；补充小样本区间限制。完成记录目前只含三个顶层文件，故暂不泛化 hash 路径映射。

Git 对生成数据、SVG 和 manifest 保留原始字节，避免 CRLF/LF 转换使提交后的引用失效。

## 实际端到端验证

```powershell
.local/analysis-venv/Scripts/python.exe -X utf8 -B research/analyze_timely_ml.py
.local/analysis-venv/Scripts/python.exe -X utf8 -B research/visualize_timely_ml.py
.local/analysis-venv/Scripts/python.exe -X utf8 -B research/verify_timely_ml_analysis.py
```

完成 1034 回复/616 执行对齐及 384 官方结果复算；48 个 n=8 单元独立核对，928 阶段对轮次覆盖无漏无重，费用一致；重建表字节一致，冻结输入未改，五图共 15 文件 hash 核对。当前规则抽查 22 个分层样本，只用于合理性检查，未测分类准确率。图表均视觉检查，修复耗时图底部图例重叠。

真实本地浏览器检查：11 条无效轨迹筛选、53 条含 unknown 的轨迹筛选、无匹配条件、上一条/下一条、`ml-174` 第 2–3 轮合并、逐轮相同代码显示均正常；控制台错误零。浏览器窄侧栏布局已目视检查。未声称进行全面浏览器兼容或移动设备测试。

第二轮实际 CLI 退出码 0，实际模型仍为 `claude-opus-5-5`，结论无阻断。补强 verifier：以冻结 plan 的唯一 run_id/分组为分母，核对全部 48 组、384 身份和 1034 完成请求；原始哈希与完成记录比较；在新建临时目录重建，清理前核对路径位于本仓库 `.local` 内，避免旧文件掩盖漏写。明确 analyzer 重建已有候选选择、verifier 独立核验聚合的不同职责，不声称重新执行评分器。

其他建议：确认费用为字符串；显式 UTF-8 子进程；跨平台字节一致性不作保证；模板哈希沿用双方一致的 UTF-8 规范化文本，模板源码为 LF；manifest 只含四个绘图输入，不含 validation，无自引用；本批输出没有子目录，暂不扩大属性匹配。全部受影响离线检查再次通过。

第三轮实际 CLI 退出码 0，`modelUsage` / canonicalModel 均为 `claude-opus-5-5`，结论“未发现阻断问题”。源码换行已由仓库 `* text=auto eol=lf` 固定，暂存 blob 与工作区脚本、派生数据和图表逐字节一致。额外人工脚本确认 manifest 的四输入/十五图集合完整、逐 episode 执行数总和 616；暂不为这个冻结批次追加更多重复硬编码断言。没有剩余阻断或未完成的审查；最终验证记录与 verifier 哈希一致后共同暂存。

对生成的 JSON/CSV/SVG 保留原生字节，其中 CRLF 或 Matplotlib 路径尾空格会触发通用 whitespace 检查，未为消除格式告警改写有 hash 引用的生成物。源代码、模板和文档的暂存 whitespace 检查通过。
