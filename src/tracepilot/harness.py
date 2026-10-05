"""Observe the existing harness without replacing its execution or budget logic.

This optional adapter imports ``agent-harness-from-scratch``. The caller owns
the Langfuse client and must flush/shut it down at application exit. Only the
logical calls visible to the harness are measured; hidden provider retries,
embeddings and auxiliary model calls need provider-level instrumentation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator

from agent.execution_control import DeadlineExceeded, ExecutionCancelled
from agent.jobs.models import SuspendRun
from agent.jobs.runner import JobCancelled
from agent.tool_outputs import READ_OUTPUT_TOOL
from agent.trigger.dispatch import is_failure_observation
from agent.trigger.events import (
    RUN_COMPLETED, RUN_STARTED, TOOL_COMPLETED, TOOL_STARTED,
    CallModel, CallTool, ManageContext, RunEvent,
)
from agent.trigger.react_loop import ReActLoop, _streams

logger = logging.getLogger(__name__)
_current_run: ContextVar[_Run | None] = ContextVar("tracepilot_harness_run", default=None)
_current_observation: ContextVar[_Observation | None] = ContextVar(
    "tracepilot_harness_observation", default=None,
)


def _telemetry_failure(exc: Exception) -> None:
    # Error messages and tracebacks may contain a patient's prompt or a key.
    try:
        logger.warning("TracePilot telemetry failed (%s)", type(exc).__name__)
    except Exception:
        pass


class _Observation:
    def __init__(self, run: _Run, name: str, kind: str = "span", **fields: Any) -> None:
        self.run = run
        self.handle: Any = None
        self.metadata = dict(fields.pop("metadata", {}))
        self.ended = False
        self.end_time: int | None = None
        self.first_chunk = False
        parent = _current_observation.get()
        try:
            if parent is not None and parent.run is run:
                if parent.handle is not None:
                    # SDK trace_context marks an observation as an application
                    # root. Its child factory preserves the intended hierarchy.
                    self.handle = parent.handle.start_observation(
                        name=name, as_type=kind, metadata=self.metadata, **fields,
                    )
            else:
                self.handle = run.client.start_observation(
                    trace_context={"trace_id": run.trace_id}, name=name,
                    as_type=kind, metadata=self.metadata, **fields,
                )
        except Exception as exc:
            _telemetry_failure(exc)

    def update(self, *, metadata: dict[str, Any] | None = None, **fields: Any) -> None:
        if self.ended:
            return
        if metadata:
            self.metadata.update(metadata)
        if self.handle is not None:
            try:
                self.handle.update(metadata=self.metadata, **fields)
            except Exception as exc:
                _telemetry_failure(exc)

    def error(self, exc: BaseException) -> None:
        if isinstance(exc, (GeneratorExit, asyncio.CancelledError, ExecutionCancelled, JobCancelled)):
            status, level = "cancelled", "WARNING"
        elif isinstance(exc, SuspendRun):
            status, level = "suspended", "DEFAULT"
        elif isinstance(exc, DeadlineExceeded):
            status, level = "timed_out", "WARNING"
        else:
            status, level = "failed", "ERROR"
        self.update(level=level, status_message=type(exc).__name__,
                    metadata={"status": status, "exception_type": type(exc).__name__})

    def end(self) -> None:
        if self.ended:
            return
        self.ended = True
        if self.handle is not None:
            try:
                self.handle.end(end_time=self.end_time)
            except Exception as exc:
                _telemetry_failure(exc)


@dataclass
class _Run:
    client: Any
    capture_content: bool
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    root: _Observation | None = None
    ctx: Any = None
    tool_event: dict[str, Any] = field(default_factory=dict)
    pending_tool: _Observation | None = None
    streams: dict[Any, _Observation] = field(default_factory=dict)
    result_delivered: bool = False
    tool_sequence: int = 0
    resumed: bool = False
    carried_spent_tokens: int | None = 0


@contextmanager
def _bound(run: _Run, observation: _Observation | None) -> Iterator[None]:
    run_token = _current_run.set(run)
    observation_token = _current_observation.set(observation)
    try:
        yield
    finally:
        _current_observation.reset(observation_token)
        _current_run.reset(run_token)


def _content(run: _Run, value: Any) -> dict[str, Any]:
    return {"input": value} if run.capture_content else {}


def _stop_reason(value: Any, capture_content: bool) -> str | None:
    if type(value) is not str:
        return None
    if capture_content:
        return value[:2048]
    reason = value.partition(":")[0]
    return reason if reason in {
        "finished", "no_answer", "cancelled", "timed_out", "suspended_on_jobs",
        "budget", "loop_detected", "context_integrity", "llm_unavailable",
        "llm_output_truncated", "llm_content_filtered", "llm_incomplete_response",
        "tool_timeout", "fatal_tool_error", "steer_handoff",
    } else "other"


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(value, name, default)
    except Exception as exc:
        _telemetry_failure(exc)
        return default


def _cleanup_overrides(original: BaseException | None, cleanup: BaseException) -> bool:
    return original is None or not isinstance(cleanup, Exception)


def _usage(observation: _Observation, usage: Any) -> None:
    try:
        values = usage if isinstance(usage, dict) else getattr(usage, "__dict__", None)
        if isinstance(values, dict):
            prompt, completion = values.get("prompt_tokens"), values.get("completion_tokens")
            if all(type(value) is int and 0 <= value <= 2**63 - 1 for value in (prompt, completion)) and prompt + completion > 0:
                source = "estimated" if values.get("estimated") is True else "reported"
                observation.update(
                    usage_details={"input": prompt, "output": completion},
                    metadata={"usage_source": source, "cost_source": "estimated_if_priced",
                              "cost_usage_source": source, "billed_cost_known": False},
                )
                return
    except Exception as exc:
        _telemetry_failure(exc)
    observation.update(metadata={"usage_source": "unknown", "cost_source": "unknown",
                                 "cost_usage_source": "unknown", "billed_cost_known": False})


def _response(observation: _Observation, response: Any) -> None:
    _usage(observation, _attribute(response, "usage"))
    fields = {"output": _attribute(response, "content")} if observation.run.capture_content else {}
    reason = _attribute(response, "finish_reason")
    if reason is not None and (type(reason) is not str or reason not in {"stop", "tool_calls", "length", "content_filter"}):
        reason = "other"
    observation.update(metadata={"finish_reason": reason}, **fields)


def _ledger(ctx: Any) -> dict[str, Any]:
    try:
        budget = getattr(ctx, "token_budget", None)
        if budget is not None:
            snapshot = budget.snapshot()
            result = {}
            for key in ("spent_tokens", "estimated_tokens", "unknown_requests", "usage_complete"):
                value = snapshot.get(key)
                if (type(value) is bool and key == "usage_complete") or (
                    type(value) is int and key != "usage_complete" and 0 <= value <= 2**63 - 1
                ):
                    result[key] = value
            return result
    except Exception as exc:
        _telemetry_failure(exc)
    return {}


def _retrieval_records(ctx: Any) -> list[dict[str, Any]]:
    try:
        if ctx is not None:
            records = ctx.state.get("__retrieval_trace__", {}).get("records", [])
            if type(records) is list:
                return records[:32]
    except Exception as exc:
        _telemetry_failure(exc)
    return []


def _retrieval_summary(ctx: Any, start: int) -> list[dict[str, Any]]:
    try:
        result = []
        for record in _retrieval_records(ctx)[start:]:
            if type(record) is not dict:
                continue
            summary = {}
            status = record.get("status")
            if type(status) is str:
                summary["status"] = status if status in {
                    "sufficient", "insufficient", "conflicting", "retrieval_failed",
                } else "other"
            for key in ("candidate_count", "evidence_count"):
                value = record.get(key)
                if type(value) is int and 0 <= value <= 2**63 - 1:
                    summary[key] = value
            if type(record.get("payload_truncated")) is bool:
                summary["payload_truncated"] = record["payload_truncated"]
            result.append(summary)
        return result
    except Exception as exc:
        _telemetry_failure(exc)
        return []


class _ContextProvider:
    """Delegate provider capabilities while timing fully consumed preparation."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._provider, name)
        if name not in {"prepare", "prepare_run", "refresh_context", "restore_run"}:
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            run = _current_run.get()
            if run is None:
                return target(*args, **kwargs)
            provider_type = type(self._provider)
            kind = "retriever" if provider_type.__module__.startswith("agent.rag.") else "span"
            observation = _Observation(run, f"context.{provider_type.__name__}.{name}", kind)
            retrieval_start = len(_retrieval_records(run.ctx))
            try:
                with _bound(run, observation):
                    result = target(*args, **kwargs)
                    if name in {"prepare", "prepare_run"}:
                        result = list(result)
                observation.update(metadata={"status": "completed",
                                             "retrievals": _retrieval_summary(run.ctx, retrieval_start)})
                return result
            except BaseException as exc:
                observation.error(exc)
                raise
            finally:
                observation.end()

        return call


class TracedReActLoop(ReActLoop):
    """A drop-in loop for this harness's sync and async generator interfaces.

    Pass the existing loop constructor arguments plus ``langfuse_client``.
    Content export is disabled by default. Enabling it requires the caller to
    sanitize inputs/outputs first or configure a Langfuse client mask.
    This adapter never mutates or closes the caller's model/provider clients.
    """

    def __init__(self, *args: Any, langfuse_client: Any,
                 capture_content: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._langfuse_client = langfuse_client
        self._capture_content = capture_content
        self.context_providers = [_ContextProvider(provider) for provider in self.context_providers]

    def _new_run(self, task: str, resume_from: dict[str, Any] | None) -> _Run:
        run = _Run(self._langfuse_client, self._capture_content)
        run.resumed = resume_from is not None
        if run.resumed:
            run.carried_spent_tokens = None
            try:
                carried = resume_from.get("tokens_used", 0)
                if type(carried) is int and 0 <= carried <= 2**63 - 1:
                    run.carried_spent_tokens = carried
            except Exception as exc:
                _telemetry_failure(exc)
        with _bound(run, None):
            run.root = _Observation(
                run, self.agent_name, "agent", **_content(run, task),
                metadata={"adapter": "tracepilot.harness", "capture_content": run.capture_content,
                          "call_scope": "logical", "auxiliary_model_usage": "ledger_only",
                          "provider_retry_usage": "not_individually_observed",
                          "resumed": run.resumed, "carried_spent_tokens": run.carried_spent_tokens,
                          "harness_ledger_scope": "cumulative_logical_run",
                          "segment_token_scope": "settled_tokens_only"},
            )
        return run

    def _event(self, run: _Run, event: RunEvent) -> None:
        if event.kind == RUN_STARTED:
            run.root.update(metadata={"run_id": event.data.get("run_id")})
        elif event.kind == TOOL_STARTED:
            run.tool_sequence += 1
            raw_id = event.data.get("id")
            call_id = raw_id[:128] if run.capture_content and type(raw_id) is str else f"tool-{run.tool_sequence}"
            run.tool_event = {"id": call_id, "step": event.data.get("step"),
                              "name": self._tool_name(event.data.get("name"))}
        elif event.kind == TOOL_COMPLETED and run.pending_tool is not None:
            run.pending_tool.update(
                metadata={"ok": event.data.get("ok"), "status": "completed" if event.data.get("ok") else "failed"},
                level="DEFAULT" if event.data.get("ok") else "ERROR",
            )
            run.pending_tool.end()
            run.pending_tool = None
        elif event.kind == RUN_COMPLETED:
            run.result_delivered = True
            success = event.data.get("success")
            stop = _stop_reason(event.data.get("stop_reason"), run.capture_content)
            fields = {"output": event.data.get("answer")} if run.capture_content else {}
            status = {"cancelled": "cancelled", "timed_out": "timed_out",
                      "suspended_on_jobs": "suspended", "steer_handoff": "handoff"}.get(stop, "completed" if success else "failed")
            level = "ERROR" if status == "failed" else ("WARNING" if status in {"cancelled", "timed_out"} else "DEFAULT")
            run.root.update(metadata={"status": status, "success": success,
                                      "stop_reason": stop, "steps": event.data.get("steps")},
                            level=level, **fields)

    @staticmethod
    def _finish(run: _Run) -> None:
        if run.pending_tool is not None:
            run.pending_tool.end()
            run.pending_tool = None
        try:
            ledger = _ledger(run.ctx)
            spent = ledger.get("spent_tokens")
            segment_spent = (spent - run.carried_spent_tokens
                             if type(spent) is int and run.carried_spent_tokens is not None
                             and spent >= run.carried_spent_tokens else None)
            run.root.update(metadata={"harness_ledger": ledger, "segment_spent_tokens": segment_spent})
        except Exception as exc:
            _telemetry_failure(exc)
        finally:
            run.root.end()

    def iter_run(self, task: str, cancellation_event: Any = None,
                 resume_from: dict[str, Any] | None = None,
                 execution_control: Any = None) -> Iterator[RunEvent]:
        run = self._new_run(task, resume_from)
        iterator = super().iter_run(task, cancellation_event, resume_from, execution_control)
        failure: BaseException | None = None
        try:
            while True:
                with _bound(run, run.root):
                    try:
                        event = next(iterator)
                    except StopIteration as done:
                        return done.value
                    self._event(run, event)
                yield event
        except BaseException as exc:
            failure = exc
            if not (run.result_delivered and isinstance(exc, (GeneratorExit, asyncio.CancelledError))):
                run.root.error(exc)
            raise
        finally:
            with _bound(run, run.root):
                try:
                    iterator.close()
                except BaseException as exc:
                    if _cleanup_overrides(failure, exc):
                        run.root.error(exc)
                        raise
                    run.root.update(metadata={"cleanup_exception_type": type(exc).__name__})
                finally:
                    self._finish(run)

    async def aiter_run(self, task: str, cancellation_event: Any = None,
                        resume_from: dict[str, Any] | None = None,
                        execution_control: Any = None) -> AsyncIterator[RunEvent]:
        run = self._new_run(task, resume_from)
        iterator = super().aiter_run(task, cancellation_event, resume_from, execution_control)
        failure: BaseException | None = None
        try:
            while True:
                with _bound(run, run.root):
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration:
                        return
                    self._event(run, event)
                yield event
        except BaseException as exc:
            failure = exc
            if not (run.result_delivered and isinstance(exc, (GeneratorExit, asyncio.CancelledError))):
                run.root.error(exc)
            raise
        finally:
            with _bound(run, run.root):
                cleanup_error: BaseException | None = None
                try:
                    await iterator.aclose()
                except BaseException as exc:
                    cleanup_error = exc
                finally:
                    # The harness has nested async generators; closing its public
                    # generator alone does not close a suspended model stream.
                    for stream, observation in list(run.streams.items()):
                        try:
                            with _bound(run, observation):
                                await stream.aclose()
                        except BaseException as exc:
                            if _cleanup_overrides(cleanup_error, exc):
                                cleanup_error = exc
                        finally:
                            observation.update(metadata={"status": "cancelled"}, level="WARNING")
                            observation.end()
                            run.streams.pop(stream, None)
                    if cleanup_error is not None:
                        if _cleanup_overrides(failure, cleanup_error):
                            run.root.error(cleanup_error)
                        else:
                            run.root.update(metadata={"cleanup_exception_type": type(cleanup_error).__name__})
                    self._finish(run)
                if cleanup_error is not None and _cleanup_overrides(failure, cleanup_error):
                    raise cleanup_error

    def _prepare_providers(self, task: str, ctx: Any, execution_control: Any) -> None:
        run = _current_run.get()
        if run is not None:
            run.ctx = ctx
            run.root.update(metadata={"run_id": ctx.run_id})
        return super()._prepare_providers(task, ctx, execution_control)

    def _prepare_context(self, *args: Any, **kwargs: Any) -> Any:
        ctx = super()._prepare_context(*args, **kwargs)
        run = _current_run.get()
        if run is not None:
            run.ctx = ctx
        return ctx

    def _restore_providers(self, ctx: Any) -> None:
        run = _current_run.get()
        if run is not None:
            run.ctx = ctx
            run.root.update(metadata={"run_id": ctx.run_id})
        return super()._restore_providers(ctx)

    def _tool_name(self, name: Any) -> str:
        try:
            if type(name) is str and (name == READ_OUTPUT_TOOL or name in self.tools):
                return name[:128]
        except Exception as exc:
            _telemetry_failure(exc)
        return "unregistered"

    def _perform_effect(self, effect: Any, ctx: Any) -> Any:
        run = _current_run.get()
        if run is None or not isinstance(effect, (CallModel, CallTool, ManageContext)):
            return super()._perform_effect(effect, ctx)
        observation = self._effect_observation(run, effect, ctx)
        retrieval_start = len(_retrieval_records(ctx))
        try:
            with _bound(run, observation):
                result = super()._perform_effect(effect, ctx)
            if isinstance(effect, CallModel):
                _response(observation, result)
                observation.update(metadata={"status": "completed"})
            elif isinstance(effect, CallTool):
                ok = not is_failure_observation(result)
                observation.update(metadata={"ok": ok, "status": "completed" if ok else "failed",
                                             "retrievals": _retrieval_summary(ctx, retrieval_start)},
                                   level="DEFAULT" if ok else "ERROR",
                                   **({"output": result} if run.capture_content else {}))
            else:
                observation.update(metadata={"status": "completed"})
            return result
        except BaseException as exc:
            if isinstance(effect, CallModel):
                response = _attribute(exc, "response")
                if response is not None:
                    _response(observation, response)
                else:
                    _usage(observation, _attribute(exc, "usage"))
            observation.error(exc)
            raise
        finally:
            observation.end_time = time.time_ns()
            if isinstance(effect, CallTool):
                if run.pending_tool is not None:
                    run.pending_tool.end()
                run.pending_tool = observation
            else:
                if isinstance(effect, ManageContext):
                    observation.update(metadata={"ledger_after": _ledger(ctx)})
                observation.end()

    def _effect_observation(self, run: _Run, effect: Any, ctx: Any) -> _Observation:
        if isinstance(effect, CallModel):
            return _Observation(
                run, "model.call", "generation", model=_attribute(self.llm, "model", type(self.llm).__name__),
                metadata={"run_id": ctx.run_id, "step": effect.step_index, "usage_source": "unknown",
                          "cost_source": "unknown", "cost_usage_source": "unknown", "billed_cost_known": False},
                **_content(run, effect.messages),
            )
        if isinstance(effect, CallTool):
            return _Observation(run, f"tool.{self._tool_name(effect.name)}", "tool",
                                metadata={"run_id": ctx.run_id, **run.tool_event},
                                **_content(run, effect.arguments))
        return _Observation(run, "context.manage", metadata={"ledger_before": _ledger(ctx)})

    async def _aperform(self, effect: Any, ctx: Any, produced: list[Any]) -> AsyncIterator[RunEvent]:
        run = _current_run.get()
        if run is None or not isinstance(effect, CallModel) or not _streams(self.llm):
            async for event in super()._aperform(effect, ctx, produced):
                yield event
            return
        observation = self._effect_observation(run, effect, ctx)
        iterator = super()._aperform(effect, ctx, produced)
        run.streams[iterator] = observation
        failure: BaseException | None = None
        try:
            while True:
                with _bound(run, observation):
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration:
                        break
                yield event
            if produced:
                _response(observation, produced[-1])
            observation.update(metadata={"status": "completed"})
        except BaseException as exc:
            failure = exc
            response = _attribute(exc, "response")
            if response is not None:
                _response(observation, response)
            observation.error(exc)
            raise
        finally:
            with _bound(run, observation):
                try:
                    await iterator.aclose()
                except BaseException as exc:
                    if _cleanup_overrides(failure, exc):
                        observation.error(exc)
                        raise
                    observation.update(metadata={"cleanup_exception_type": type(exc).__name__})
                finally:
                    observation.end()
                    run.streams.pop(iterator, None)

    @staticmethod
    async def _next_stream_chunk(stream: Any, control: Any) -> Any:
        chunk = await ReActLoop._next_stream_chunk(stream, control)
        observation = _current_observation.get()
        if observation is not None:
            if chunk.get("type") == "usage":
                _usage(observation, chunk.get("data"))
            elif chunk.get("type") in {"text", "tool_call"} and not observation.first_chunk:
                observation.first_chunk = True
                observation.update(completion_start_time=datetime.now(timezone.utc))
        return chunk
