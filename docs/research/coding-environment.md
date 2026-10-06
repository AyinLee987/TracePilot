# Coding environment preparation

`research/coding_environment_smoke.py` verifies fixed HumanEval/0 preset candidates in dedicated native-WSL Docker containers. It does not implement the full EvalPlus judge, arbitrary model-code evaluation, an agent deadline, or R3/R4.

Run from Windows against the existing Ubuntu 24.04 native daemon:

```powershell
wsl.exe -d Ubuntu-24.04 -u root -- /usr/bin/python3 -B '/mnt/c/Users/Li Zhuoyang/Desktop/TracePilot-research-20261005/research/coding_environment_smoke.py'
```

The host launcher uses root for this daemon; candidate code runs as UID/GID 65534 with no network or host mounts, a read-only root, resource limits and bounded output. The script verifies daemon identity before image/container operations and refuses Desktop or a mismatched environment. It creates only UUID-named owned containers and checks their cleanup. Existing Cube services are not selected or modified.

Sources are fixed to EvalPlus v0.3.1 and HumanEval+ v0.1.10, with immutable license references, acquisition hashes and an expanded source manifest. These are locally verified acquisition bytes, not publisher-signed checksums. GitHub API/codeload bytes can change on a fresh machine despite an unchanged source commit; acquisition then fails closed rather than silently changing the assets. First-time asset preparation is serial, not concurrently supported.

[Validation](../../research/results/coding-environment-validation.json): five real Docker cases passed: canonical 1006/1006; known-wrong 199/1006 correctly rejected; infinite loop stopped; stdout/stderr floods bounded. Nine extra probes cover synthetic Desktop refusal (no actual Desktop connection), five fixed-hash refusals without a previous lock, actual double SIGINT cleanup, unstarted-container cleanup and AutoRemove lifecycle. All used zero model calls.

The two actual Claude Opus 5.5 reviews found no blocking issue for this narrow preset scope. The second review confirmed the daemon and provenance fixes. [Review dispositions](../reviews/2026-10-06-coding-environment.md) record the remaining boundaries.

The checklist below is partially addressed by the multi-task increment; full evaluator fidelity and the common deadline remain pending. Before claiming full R3 evaluation, integrate the full pinned evaluator and its timing semantics, distinguish candidate failure from infrastructure failure, add visible tests and a common absolute agent deadline, then validate generated code. Hidden test results belong to offline scoring; they must not be sent back as an optimization tool. Raw worker output and inputs remain local and never become model feedback. The current one-task parent oracle and whole-batch timeout cannot be presented as full EvalPlus results.

## 多题判定准备（2026-10-06 增量）

新增 `coding_tasks.py`，限定 8 个预定开发题；4 个留出题保持未执行。公开示例和隐藏验收是两个独立入口，每次要求独立空目录，隐藏期望不发送给候选，模型侧只接收公开题面和公开诊断。状态区分 pass/fail/timeout/infra；ready 握手区分未启动基础设施错误，公开异常只暴露白名单类别或语法行号，孤立 Unicode surrogate 安全处理。复用提取后的有界容器生命周期，不使用模块全局 monkeypatch。

第一版 27/27 检查符合预期，涉及 5,023 个隐藏输入、35 个容器；旧 /0 五项 smoke 与真实 SIGINT 清理通过。Claude 初审后补 11 项真实 Docker 增量检查及异常/静态边界，均通过；这些检查各自绑定代码 hash，不称当前代码重新执行了旧整套。脱敏证据见 [多题验证](../../research/results/coding-tasks-validation.json)。

当前实现的 /32 残差判定下，数据集 canonical 为 881/888，已保留真实 fail；一次 guarded fixture 仍为 885/888，随后停止对隐藏输入调整。固定源码实际在候选执行后对同一 `inp` 求残差，而本桥接父进程使用原始参数，因此候选修改参数的行为不完全等价。`atol=1e-4` 与公开检查一致。不能把上述测量称完整官方 evaluator 的交叉复现。

依然不是共同 deadline、完整 EvalPlus 或防恶意伪造 judge。候选与 worker 同进程；模型 Agent 不应获得隐藏结果宿主目录的 shell 访问。标准库环境和整批 worker 超时属于显式差异。下一步首稿采样与后续实验见 [R3 开发协议](coding-pilot.md)。
