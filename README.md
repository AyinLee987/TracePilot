# TracePilot

Trace-guided model and agent routing for efficient task execution.

## Goals

- Capture agent traces, latency, token usage, and cost through lightweight integrations with Langfuse and local JSONL.
- Classify tasks to select a model and agent configuration, then use execution traces to guide later model calls.
- Evaluate quality, latency, and cost across RAG, coding, and shopping tasks.

## Status

Planning stage. Repository setup is complete; runtime features and experiments are not implemented yet. Start with RAG and coding, then add a shopping sandbox.

## Development

Use end-to-end validation, review changes with Claude CLI, update relevant docs, then commit and push. Reviews focus on concurrency, extensibility, and abstractions.

- [Project plan and conventions](agent.md)
- [Progress](docs/progress.md)
- [Review checklist](docs/review-checklist.md)
