"""Exercise the real harness and SDK with synthetic LLM/tool data (no paid API).

Pass --live to additionally export to Langfuse and read the observations back.
Without --live, spans stay in the SDK's in-memory OpenTelemetry exporter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main() -> None:
    if not __debug__:
        raise SystemExit("Run this validation without -O: assertions must remain enabled.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-path", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path, default=Path(".local/harness-smoke.json"))
    args = parser.parse_args()
    harness_path = args.harness_path.resolve()
    if not (harness_path / "agent/trigger/react_loop.py").is_file():
        parser.error("--harness-path must point to agent-harness-from-scratch")
    sys.path.insert(0, str(harness_path))
    # All harness-generated logs stay in this project's ignored directory.
    os.environ["AGENT_LOG_DIR"] = str(Path(".local/harness-logs").resolve())

    from dotenv import dotenv_values
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agent.errors import FatalToolError, RecoverableToolError
    from agent.execution_control import ExecutionControl
    from agent.jobs.models import SuspendRun
    from agent.llm import LLMResponse, MockLLM, ToolCall, Usage
    from agent.rag import (
        BM25Retriever, InMemoryRAGRepository, MedicalParentChildChunker,
        RAGContextProvider, RAGIngestionService, RAGPipeline,
    )
    from agent.tools import FunctionTool, ToolRegistry
    from agent.trigger.events import RAG_COMPLETED, REFLECTION, RUN_COMPLETED, TEXT
    from agent.trigger.react_loop import ReActLoop
    from tracepilot.harness import TracedReActLoop

    class PilotLLM(MockLLM):
        """Stateless scripted provider: behavior depends only on this run's messages."""

        model = "tracepilot-synthetic"

        def chat(self, messages, tools=None):
            time.sleep(0.015)
            task = next(m["content"] for m in messages if m["role"] == "user")
            label = task.split("case=", 1)[1].split()[0]
            results = [m for m in messages if m["role"] == "tool"]
            usage = Usage(prompt_tokens=40, completion_tokens=10, estimated=True)
            if results and not tools and "ERROR" in results[-1]["content"]:
                return LLMResponse(content="Retry with the valid fixture URL.", usage=usage)
            if results and "ERROR" not in results[-1]["content"]:
                return LLMResponse(content=f"done:{label} [E1]", usage=usage, finish_reason="stop")
            target = "bad" if "recover" in label and not results else "good"
            return LLMResponse(tool_calls=[ToolCall(
                id=f"fetch-{len(results)}", name="fetch", arguments={"url": target},
            )], usage=usage, finish_reason="tool_calls")

    class StreamingLLM(PilotLLM):
        def __init__(self):
            super().__init__()
            self.closed = False

        async def astream(self, messages, tools=None):
            try:
                for chunk in ("stream ", "done"):
                    await asyncio.sleep(0.02)
                    yield {"type": "text", "data": chunk}
                yield {"type": "usage", "data": {
                    "prompt_tokens": 40, "completion_tokens": 10, "estimated": True,
                }}
                yield {"type": "finish", "data": {"reason": "stop"}}
            finally:
                self.closed = True

    def fetch(url: str) -> str:
        """Read a synthetic source; deliberately fail on the bad fixture URL."""
        time.sleep(0.01)
        if url == "bad":
            raise RecoverableToolError("synthetic fetch failure")
        return "synthetic reference [E1]; no clinical advice"

    repository = InMemoryRAGRepository()
    lexical = BM25Retriever(repository)
    ingestion = RAGIngestionService(repository, MedicalParentChildChunker(
        target_tokens=80, min_tokens=20, max_tokens=120,
    ), [lexical])
    ingestion.ingest_text(
        logical_id="synthetic/pilot", title="TracePilot synthetic evidence",
        content="# Synthetic evidence\nTracePilot fixture retrieval verifies source citations. "
                "This synthetic document contains no clinical recommendation.",
    )
    rag = RAGContextProvider(RAGPipeline(repository, lexical, None))
    registry = ToolRegistry()
    registry.register(FunctionTool(fetch))

    # Explicit provider ownership prevents installing a global OTel provider.
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    config = dotenv_values(args.env_file) if args.live else {}
    if args.live and not all(config.get(k) for k in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
    )):
        parser.error("--live requires all three LANGFUSE_* values in --env-file")
    sdk = Langfuse(
        public_key=config.get("LANGFUSE_PUBLIC_KEY", "pk-lf-offline-pilot"),
        secret_key=config.get("LANGFUSE_SECRET_KEY", "sk-lf-offline-pilot"),
        base_url=config.get("LANGFUSE_BASE_URL", "http://localhost:3100"),
        environment="tracepilot-pilot", tracer_provider=provider,
        **({} if args.live else {"span_exporter": InMemorySpanExporter()}),
    )

    def loop(name, llm=None, client=sdk, tool_registry=registry):
        return TracedReActLoop(
            llm or PilotLLM(), tool_registry, context_providers=[rag],
            langfuse_client=client, agent_name=name, max_steps=8,
        )

    def task(label):
        return f"TracePilot fixture retrieval case={label} PRIVATE_INPUT_SENTINEL"

    async def collect(instance, label):
        events = [event async for event in instance.aiter_run(task(label))]
        result = next(e.data["result"] for e in events if e.kind == RUN_COMPLETED)
        assert result.success and result.answer == f"done:{label} [E1]"
        return events

    async def async_scenarios():
        # One shared loop proves our added state is run-local, not instance-local.
        shared = loop("pilot.concurrent")
        await asyncio.gather(collect(shared, "parallel-a"), collect(shared, "parallel-b"))
        stream_model = StreamingLLM()
        events = [e async for e in loop("pilot.stream", stream_model).aiter_run(task("stream"))]
        assert stream_model.closed
        assert "".join(e.data["token"] for e in events if e.kind == TEXT) == "stream done"
        assert next(e.data["result"] for e in events if e.kind == RUN_COMPLETED).success
        cancelled_model = StreamingLLM()
        iterator = loop("pilot.cancel", cancelled_model).aiter_run(task("cancel"))
        try:
            async for event in iterator:
                if event.kind == TEXT:
                    break
        finally:
            await iterator.aclose()
        assert cancelled_model.closed, "early close left the underlying LLM stream open"
        completed = loop("pilot.final-close-async").aiter_run(task("final-close-async"))
        try:
            async for event in completed:
                if event.kind == RUN_COMPLETED:
                    assert event.data["result"].success
                    break
        finally:
            await completed.aclose()

        class BlockingStream(StreamingLLM):
            def __init__(self):
                super().__init__()
                self.entered = asyncio.Event()

            async def astream(self, messages, tools=None):
                try:
                    self.entered.set()
                    await asyncio.Event().wait()
                    yield {"type": "text", "data": "unreachable"}
                finally:
                    self.closed = True

        blocked = BlockingStream()
        iterator = loop("pilot.task-cancel", blocked).aiter_run(task("task-cancel"))

        async def consume():
            async for _ in iterator:
                pass

        consumer = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(blocked.entered.wait(), timeout=5)
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("task cancellation was swallowed")
        finally:
            if not consumer.done():
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)
            await iterator.aclose()
        assert blocked.closed

    try:
        if args.live:
            assert sdk.auth_check(), "Langfuse authentication failed"
        baseline = ReActLoop(PilotLLM(), registry, context_providers=[rag], max_steps=8).run(task("normal"))
        normal = loop("pilot.normal").run(task("normal"))
        assert normal.success and normal.answer == baseline.answer and normal.tokens == baseline.tokens
        recovery_events = list(loop("pilot.recover").iter_run(task("recover")))
        assert any(e.kind == REFLECTION for e in recovery_events)
        assert any(e.kind == RAG_COMPLETED for e in recovery_events)
        recovery = next(e.data for e in recovery_events if e.kind == RUN_COMPLETED)
        assert recovery["success"] and recovery["answer"] == "done:recover [E1]"
        # Interleave sync generators on the same thread: context must reset at yield.
        interleaved = loop("pilot.interleaved")
        generators = [interleaved.iter_run(task(label)) for label in ("interleaved-a", "interleaved-b")]
        active = list(generators)
        try:
            while active:
                for generator in active[:]:
                    try:
                        next(generator)
                    except StopIteration as done:
                        assert done.value.success
                        active.remove(generator)
        finally:
            for generator in generators:
                generator.close()
        completed = loop("pilot.final-close-sync").iter_run(task("final-close-sync"))
        try:
            for event in completed:
                if event.kind == RUN_COMPLETED:
                    assert event.data["success"]
                    break
        finally:
            completed.close()
        asyncio.run(async_scenarios())

        threaded = loop("pilot.threads")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(threaded.run, [task("thread-a"), task("thread-b")]))
        assert {r.answer for r in results} == {"done:thread-a [E1]", "done:thread-b [E1]"}

        def fatal_fetch(url: str) -> str:
            raise FatalToolError("PRIVATE_INPUT_SENTINEL synthetic fatal failure")

        fatal_registry = ToolRegistry()
        fatal_registry.register(FunctionTool(fatal_fetch, name="fetch"))
        fatal = loop("pilot.fatal", tool_registry=fatal_registry).run(task("fatal"))
        assert not fatal.success and fatal.stop_reason == "fatal_tool_error"

        ready = threading.Event()

        def suspended_fetch(url: str) -> str:
            if not ready.is_set():
                raise SuspendRun(["fixture-job"])
            return "synthetic reference [E1]"

        suspend_registry = ToolRegistry()
        suspend_registry.register(FunctionTool(suspended_fetch, name="fetch"))
        resumable = loop("pilot.resume", tool_registry=suspend_registry)
        suspended = resumable.run(task("resume"))
        assert suspended.stop_reason == "suspended_on_jobs" and suspended.checkpoint
        ready.set()
        resumed = resumable.run(task("resume"), resume_from=suspended.checkpoint)
        assert resumed.success and resumed.answer == "done:resume [E1]"

        timeout = loop("pilot.timeout").run(task("timeout"), execution_control=ExecutionControl(
            deadline=time.monotonic() - 1, cancel_event=threading.Event(),
        ))
        assert not timeout.success and timeout.stop_reason == "timed_out"
        cancelled = threading.Event()
        cancelled.set()
        result = loop("pilot.cancel-signal").run(task("cancel-signal"), execution_control=ExecutionControl(
            deadline=None, cancel_event=cancelled,
        ))
        assert not result.success and result.stop_reason == "cancelled"

        class InvalidToolLLM(PilotLLM):
            def chat(self, messages, tools=None):
                if not any(m["role"] == "tool" for m in messages):
                    return LLMResponse(tool_calls=[ToolCall(
                        id="PRIVATE_INPUT_SENTINEL-id", name="PRIVATE_INPUT_SENTINEL-tool",
                        arguments={},
                    )], usage=Usage(40, 10, estimated=True))
                return super().chat(messages, tools)

        private = loop("pilot.invalid-tool", llm=InvalidToolLLM()).run(task("invalid-tool"))
        assert private.success

        class UnavailableTelemetry:
            def start_observation(self, **kwargs):
                raise ConnectionError("synthetic telemetry outage")

        fallback = loop("pilot.outage", client=UnavailableTelemetry()).run(task("outage"))
        assert fallback.success and fallback.answer == "done:outage [E1]"

        class BrokenObservation:
            def start_observation(self, **kwargs):
                return self

            def update(self, **kwargs):
                raise ValueError("synthetic update failure")

            def end(self, **kwargs):
                raise ValueError("synthetic end failure")

        fallback = loop("pilot.update-outage", client=BrokenObservation()).run(task("update-outage"))
        assert fallback.success and fallback.answer == "done:update-outage [E1]"
        sdk.flush()
        spans = memory.get_finished_spans()
        groups = defaultdict(list)
        for span in spans:
            groups[f"{span.context.trace_id:032x}"].append(span)
        assert len(groups) == 19, f"expected 19 traces, got {len(groups)}"
        evidence = []
        for trace_id, group in groups.items():
            # Langfuse attaches a synthetic OTel parent for an explicit trace ID,
            # and marks the real root so ingestion can remove that placeholder.
            roots = [s for s in group if s.attributes.get("langfuse.internal.is_app_root")]
            assert len(roots) == 1, "trace has orphan or duplicate root"
            root = roots[0]
            ids = {s.context.span_id for s in group}
            for span in group:
                assert span.end_time is not None and span.end_time >= span.start_time
                assert span is root or span.parent.span_id in ids, "cross-run parent"
                assert span is root or not span.attributes.get("langfuse.internal.as_root")
                assert "PRIVATE_INPUT_SENTINEL" not in json.dumps(dict(span.attributes))
                assert "PRIVATE_INPUT_SENTINEL" not in span.name
                assert not any(k.endswith(".input") or k.endswith(".output") for k in span.attributes)
            metadata = {k.removeprefix("langfuse.observation.metadata."): v for k, v in root.attributes.items()
                        if k.startswith("langfuse.observation.metadata.")}
            if root.name not in {"pilot.timeout", "pilot.cancel-signal"} and not metadata.get("resumed"):
                assert any("RAGContextProvider.prepare" in s.name for s in group)
            generations = [s for s in group if s.name == "model.call"]
            if root.name in {"pilot.timeout", "pilot.cancel-signal"}:
                assert not generations
                assert metadata["status"] == ("timed_out" if root.name == "pilot.timeout" else "cancelled")
            elif root.name in {"pilot.cancel", "pilot.task-cancel"}:
                assert root.attributes["langfuse.observation.metadata.status"] == "cancelled"
                assert generations[0].attributes["langfuse.observation.metadata.usage_source"] == "unknown"
            else:
                expected_status = "completed"
                if root.name == "pilot.fatal":
                    expected_status = "failed"
                elif root.name == "pilot.resume" and not metadata.get("resumed"):
                    expected_status = "suspended"
                assert metadata["status"] == expected_status
                assert generations
                for generation in generations:
                    assert generation.attributes["langfuse.observation.metadata.usage_source"] == "estimated"
                    usage = json.loads(generation.attributes["langfuse.observation.usage_details"])
                    assert usage == {"input": 40, "output": 10}
            if root.name == "pilot.recover":
                tools = [s for s in group if s.name == "tool.fetch"]
                assert len(tools) == 2 and len(generations) == 4
                assert any(s.attributes.get("langfuse.observation.level") == "ERROR" for s in tools)
            evidence.append({"trace_id": trace_id, "name": root.name, "observations": len(group)})
        run_ids = [s.attributes["langfuse.observation.metadata.run_id"] for s in spans
                   if s.attributes.get("langfuse.internal.is_app_root")]
        assert len(set(run_ids)) == len(groups) - 1, "only the resume pair should share a run ID"
        resume_roots = [s for s in spans if s.name == "pilot.resume"]
        resumed_root = next(s for s in resume_roots if s.attributes.get("langfuse.observation.metadata.resumed"))
        assert resumed_root.attributes["langfuse.observation.metadata.carried_spent_tokens"] == suspended.tokens
        assert sum(s.attributes["langfuse.observation.metadata.segment_spent_tokens"] for s in resume_roots) == resumed.tokens

        if args.live:
            # Ingestion is asynchronous. Retry incomplete reads, not task execution.
            pending = {row["trace_id"]: row for row in evidence}
            deadline = time.monotonic() + 90
            while pending and time.monotonic() < deadline:
                for trace_id, row in list(pending.items()):
                    # v4 events_only deployments expose observations v2; the
                    # legacy trace endpoint returns 404 even after ingestion.
                    response = sdk.api.observations.get_many(
                        trace_id=trace_id, limit=1000,
                        fields="core,basic,time,io,usage,metadata",
                    )
                    observations = response.data
                    if len(observations) < row["observations"] or any(o.end_time is None for o in observations):
                        continue
                    assert len(observations) == row["observations"]
                    ids = {o.id for o in observations}
                    assert sum(bool(o.is_root_observation) for o in observations) == 1
                    for observation in observations:
                        assert observation.trace_id == trace_id
                        assert observation.is_root_observation or observation.parent_observation_id in ids
                        assert observation.input is None and observation.output is None
                        assert observation.end_time >= observation.start_time
                        assert "PRIVATE_INPUT_SENTINEL" not in observation.name
                        assert "PRIVATE_INPUT_SENTINEL" not in json.dumps(observation.metadata)
                    generations = [o for o in observations if o.type == "GENERATION"]
                    if row["name"] not in {"pilot.cancel", "pilot.task-cancel"}:
                        assert all(o.usage_details.get("input") == 40 and o.usage_details.get("output") == 10 for o in generations)
                        assert all(o.metadata["usage_source"] == "estimated" and not o.metadata["billed_cost_known"] for o in generations)
                    if row["name"] == "pilot.stream":
                        assert generations[0].completion_start_time is not None
                    del pending[trace_id]
                if pending:
                    time.sleep(2)
            assert not pending, f"Langfuse ingestion incomplete for {len(pending)} traces"
        report = {"mode": "live-langfuse" if args.live else "in-memory-sdk",
                  "llm_and_fetch": "synthetic", "paid_model_requests": 0,
                  "checks": ["baseline parity", "real lexical RAG", "tool failure and reflection",
                             "shared-loop concurrency", "interleaved generators", "stream completion",
                             "stream early close", "close after completion", "content off",
                             "telemetry failure isolation", "threaded shared loop", "fatal tool",
                             "suspend and resume accounting", "deadline", "cancellation signal",
                             "task cancellation", "untrusted tool names", "telemetry update/end failure"],
                  "traces": evidence, "observations": len(spans)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        sdk.shutdown()
        provider.shutdown()


if __name__ == "__main__":
    main()
