# Timely 单回合 runner：审查与处置

范围为固定官方 evaluator、真实 Jericho、预算 transport 和其离线端到端脚本。批次调度器单独审查，本记录不授权其付费执行。

## 第一轮

Claude CLI 退出码 0、`is_error=false`，实际模型 `claude-opus-5-5`，未设置轮次或费用上限；未发现首个独立 R1 的阻断。原始记录为忽略目录 `.local/overnight/timely-runner-review.json`。审查依据提供的文件和核验摘要，没有自行运行代码或联网。

处置：

1. 有效 usage 超过预留时，unknown 账目保留 `max(原预留, 已报告用量估算)`；已补输入/输出越界和 model 不匹配检查，后续请求停止。
2. `outer_retries` 改为 `official_agent_attempts: 1`；保留兼容的 `paid_call_count` 别名但明确包含模拟/未知调用。
3. manifest 补逐操作超时、传输上界、Python/系统来源。60 秒超时暂保留，任何超时完整计为失败，不静默选择有效校准样本。
4. 增加真实 HTTP transport/dotenv 设置路径的离线网络拦截、虚拟凭证输出扫描；增加真实动作发现后异常退出的进程池终止检查。完整套件 15/15、transport 27/27 通过。
5. DeepSeek 官方 API 文档确认 cache hit/miss 字段、thinking 开关和请求模型名，示例回显 `deepseek-flash`；继续严格匹配 response model，避免凭推测接受未知计价映射。
6. `insufficient_system_resource`/`aborted` 目前保留原始响应并作为异常 finish reason 使技术/校准失败；更细原因标签后续再补，不影响失败排除。参数错误轨迹的环境计数诊断可进一步细化，但现有协议/校准门已拒绝它，不为此扩展首跑范围。
7. 记录 transport 提前关闭会取消拥有在途请求的整个 caller task；当前 runner 在 episode 结束后关闭。README 移除提前称“reviewed”的措辞，区分两个实验依赖环境。

## 增量复审

Claude CLI 增量复审退出码 0、`is_error=false`、实际模型 `claude-opus-5-5`，未发现首条 R1 阻断。原始记录与输入哈希保留在 `.local/overnight/timely-runner-delta-review.*`。复审后核对七个输入文件 hash 一致，完整 15 例已全部通过；`.local` 忽略规则与目标目录未存在也已核验。

补充处置：

- 主执行者直接核实固定 `interactive.py:159` 创建 `Timer(mode="static", speed_factor=1.0)`，默认噪声范围来自固定 `timer.py`；manifest 字面值有源码依据。上游使用 `time.time()`，R2 校准另加相对单调计时的粗一致性门。R1 的 8 步默认延迟记录仅作路径验证并导入费用，不用于 R2 的独立 32 步校准。
- 首跑省略 `--tool-delay`，明确保留官方默认字典；R2 的统一延迟 0/10 是不同、预先披露的条件，不能混用 τ。
- model 不匹配时保留未知预留并停止；真实价格不能由未识别模型名推断。共享账本须导入完整 commitment 与未知状态，不能只导入已确认消费。任何此类失败保留记录，不自动放宽映射重跑。
- reason 字符串、无效 completion body 的额外测试、保守防御分支均为非阻断诊断改进；本轮不为增加测试数量扩张范围。实际实验尚未启动，不把离线成功写成论文数值复现。
