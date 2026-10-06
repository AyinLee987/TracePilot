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

Before R3, integrate the full pinned evaluator and its timing semantics, distinguish candidate failure from infrastructure failure, add visible tests and a common absolute agent deadline, then validate generated code. Hidden test results belong to offline scoring; they must not be sent back as an optimization tool. Raw worker output and inputs remain local and never become model feedback. The current one-task parent oracle and whole-batch timeout cannot be presented as full EvalPlus results.
