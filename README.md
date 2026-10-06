# TracePilot

Trace-based experiments on model speed, feedback iteration, and task quality, with lightweight agent observability. Model routing is planned.

## Research

When can a faster model use additional feedback iterations to compensate for weaker single-attempt performance? We record per-iteration signals and test whether they predict model choice under a shared wall-clock deadline.

1. Reproduce the available [Timely Machine](https://github.com/Entarochuan/Timely-Machine) evaluation pipeline and document differences from the paper.
2. Compare models under varying tool latency, separating feedback-driven repair and regression from independent retries.
3. Validate selection predictions on held-out tasks and changed latency conditions.

See the [experiment plan](docs/research/timely-reproduction.md) and [related work](docs/research/speed-feedback-related-work.md). Results may support or reject the hypothesis.

## Status

| Component | Status |
| --- | --- |
| Existing Python harness adapter and local Langfuse setup | Available; see [setup and limitations](docs/langfuse-pilot.md) |
| Timely code audit and Pi/mini-SWE-agent smoke runs | Available; [earlier results](docs/research/pilot-results.md) are engineering checks |
| Timely evaluation with real benchmark tasks | Two real Zork1 runs recorded; the first batch stopped on tool-format failures; no valid model comparison yet |
| Runtime JSONL, routing, and held-out selection experiments | Planned |

## Getting started

Python 3.12+. From this checkout on Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -c constraints-pilot.txt -e '.[pilot]'
```

Follow the [Langfuse guide](docs/langfuse-pilot.md) for integration or the [research instructions](research/README.md) for experiments. Jericho requires Linux/WSL and a separate environment. Credentials, downloaded datasets, and raw traces stay in ignored local directories.

## Development

Use end-to-end checks, review changes with Claude CLI, update the relevant docs, then commit and push. Reviews focus on concurrency, extensibility, abstractions, and research validity.

- [Project plan and conventions](agent.md)
- [Progress](docs/progress.md)
- [Research direction and related work](docs/research/decision.md)
- [Review checklist](docs/review-checklist.md)
