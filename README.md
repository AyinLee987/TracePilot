# TracePilot

Trace-guided model and agent routing for efficient task execution.

## Goals

- Capture agent traces, latency, token usage, and cost through lightweight integrations with Langfuse and local JSONL.
- Classify tasks to select a model and agent configuration, then use execution traces to guide later model calls.
- Evaluate quality, latency, and cost across RAG, coding, and shopping tasks.

## Status

An initial adapter observes runs, model calls, tools, and retrieval in the existing Python harness. Local Langfuse deployment scripts and a synthetic end-to-end example are available. Runtime JSONL and routing remain planned.

This research branch adds a timing audit, a real-API pilot, and local Pi/mini-SWE-agent smoke runners. See the [current research direction](docs/research/decision.md) and [earlier pilot results](docs/research/pilot-results.md); these scripts are separate from the runtime library.

See the [Langfuse pilot guide](docs/langfuse-pilot.md) for setup, validation, and current limitations.

## Development

Use end-to-end validation, review changes with Claude CLI, update relevant docs, then commit and push. Reviews focus on concurrency, extensibility, and abstractions.

- [Project plan and conventions](agent.md)
- [Progress](docs/progress.md)
- [Research direction and related work](docs/research/decision.md)
- [Review checklist](docs/review-checklist.md)
