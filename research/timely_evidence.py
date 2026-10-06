"""Sidecar evidence for one pinned Timely episode in an isolated process.

The scoped environment replacement is deliberately NOT concurrency-safe. Use it
only around this runner's single episode, after preflight, and inspect evidence
after leaving the scope and closing the HTTP client. Actions, return values,
official scores, prompts, and stopping rules are unchanged. State reads add a
small measured overhead to the official clock; this module never subtracts it.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import json
import math
from numbers import Integral
from pathlib import Path
import re
import time
from typing import Any, Iterator


class _EnvironmentObserver:
    def __init__(self) -> None:
        self._instances: list[tuple[Any, dict[str, Any]]] = []
        self._state_read_s = 0.0

    def _state(self, wrapper: Any, record: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        state: dict[str, Any] = {}
        for field, method in (("score", "get_score"), ("max_score", "get_max_score"),
                              ("victory", "victory"), ("game_over", "game_over")):
            try:
                value = getattr(wrapper.env, method)()
                if field in {"score", "max_score"}:
                    if not isinstance(value, Integral) or isinstance(value, bool):
                        raise TypeError("non-integer game score")
                    value = int(value)
                elif not isinstance(value, (bool, Integral)):
                    raise TypeError("non-boolean game status")
                else:
                    value = bool(value)
                state[field] = value
            except Exception as exc:
                state[field] = None
                record["observation_errors"].append({"field": field, "type": type(exc).__name__})
        self._state_read_s += time.perf_counter() - started
        return state

    def _call(self, wrapper: Any, tool: str, callback: Any) -> Any:
        record = wrapper._timely_evidence_record
        before = self._state(wrapper, record)
        started = time.perf_counter()
        error = None
        try:
            return callback()
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            duration = time.perf_counter() - started
            after = self._state(wrapper, record)
            record["final"] = after
            record["operations"].append({
                "index": len(record["operations"]), "tool": tool,
                "before": before, "after": after, "duration_s": duration,
                "score_delta": after["score"] - before["score"]
                if after["score"] is not None and before["score"] is not None else None,
                "exception_type": error,
            })

    def _close_worker_pool(self, wrapper: Any, record: dict[str, Any], *, aborted: bool) -> bool:
        """Drain an existing Jericho action-discovery pool without creating one.

        Jericho 3.2.1's FrotzEnv.close only shuts down the parent interpreter.
        Successful synchronous discovery has no pending work, so close/join is
        sufficient. An interrupted or failed operation terminates workers first.
        """
        pool = getattr(wrapper.env, "pool", None)
        state = record["worker_pool"]
        state["present"] = pool is not None
        if pool is None:
            return True

        def attempt(operation: str) -> bool:
            state[f"{operation}_attempted"] = True
            try:
                getattr(pool, operation)()
                return True
            except Exception as exc:
                state["errors"].append({"operation": operation, "type": type(exc).__name__})
                record["close_error_type"] = record["close_error_type"] or type(exc).__name__
                return False

        state["cleanup_mode"] = "terminate_join" if aborted else "close_join"
        if not aborted and attempt("close") and attempt("join"):
            state["closed"] = True
            return True
        if not aborted:
            state["cleanup_mode"] = "close_join_then_terminate_join"
        terminated = attempt("terminate")
        joined = attempt("join")
        state["closed"] = terminated and joined
        return state["closed"]

    def close(self, *, aborted: bool = False) -> None:
        for wrapper, record in self._instances:
            if record["close_attempted"] or not hasattr(wrapper, "env"):
                continue
            record["final"] = self._state(wrapper, record)
            record["close_attempted"] = True
            pool_closed = self._close_worker_pool(
                wrapper, record,
                aborted=aborted or bool(record["constructor_error_type"])
                or any(operation["exception_type"] for operation in record["operations"]),
            )
            try:
                wrapper.env.close()
                record["closed"] = pool_closed
            except Exception as exc:
                record["close_error_type"] = record["close_error_type"] or type(exc).__name__

    def snapshot(self) -> dict[str, Any]:
        """Return only captured metadata, never game text, commands, or live objects."""
        return deepcopy({
            "schema": 1, "scope": "isolated_process_single_episode",
            "state_source": "underlying_frotz_env",
            "observed_operations": ["step", "get_available_actions", "end_game"],
            "unobserved_tool_durations": ["get_score", "get_max_score"],
            "duration_semantics": "actual_synchronous_method_wall_time_excludes_state_reads",
            "state_read_overhead_s": self._state_read_s,
            "worker_pool_cleanup": "existing_pool_only; close_join_on_success; terminate_join_on_abort_or_failure",
            "environments": [record for _, record in self._instances],
        })


@contextmanager
def observe_environment(official_module: Any) -> Iterator[_EnvironmentObserver]:
    """Observe and close official environments; restore the class even on failure.

    Only step, action discovery, and end_game are timed. Metadata getters are
    not intercepted because the official loop also calls them internally.
    All executed tool names remain available in the official trajectory.
    """
    original = official_module.JerichoToolEnvironment
    if getattr(original, "_timely_evidence_observed", False):
        raise RuntimeError("nested Timely environment observation is unsupported")
    observer = _EnvironmentObserver()

    class ObservedEnvironment(original):
        _timely_evidence_observed = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            record = {"index": len(observer._instances), "initialized": False,
                      "initial": None, "final": None, "operations": [],
                      "constructor_error_type": None, "observation_errors": [],
                      "close_attempted": False, "closed": False, "close_error_type": None,
                      "worker_pool": {"present": False, "cleanup_mode": None,
                                      "close_attempted": False, "terminate_attempted": False,
                                      "join_attempted": False, "closed": None, "errors": []}}
            self._timely_evidence_record = record
            # Register before construction so partial initialization is also cleaned up.
            observer._instances.append((self, record))
            try:
                super().__init__(*args, **kwargs)
                record["initialized"] = True
                record["initial"] = observer._state(self, record)
                record["final"] = dict(record["initial"])
            except BaseException as exc:
                record["constructor_error_type"] = type(exc).__name__
                raise

        def step(self, action: str) -> str:
            return observer._call(self, "step", lambda: original.step(self, action))

        def get_valid_actions(self) -> list[str]:
            return observer._call(self, "get_available_actions", lambda: original.get_valid_actions(self))

        def end_game(self) -> str:
            return observer._call(self, "end_game", lambda: original.end_game(self))

    official_module.JerichoToolEnvironment = ObservedEnvironment
    aborted = False
    try:
        yield observer
    except BaseException:
        aborted = True
        raise
    finally:
        official_module.JerichoToolEnvironment = original
        observer.close(aborted=aborted)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _read_jsonl(path: Path, label: str, errors: list[str]) -> list[dict[str, Any]]:
    rows = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("expected object")
                    rows.append(row)
                except (ValueError, TypeError):
                    errors.append(f"{label}_invalid_row_{line_number}")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label}_unreadable_{type(exc).__name__}")
    return rows


def _conclusion(text: str) -> bool:
    return bool(re.search(r"<conclusion>\s*(.*?)\s*</conclusion>", text, re.DOTALL))


def _tool_format_counts(text: str) -> tuple[int, int]:
    """Count malformed blocks and step arguments under the pinned parser's syntax.

    Unknown names are valid upstream action aliases. Only the first parsed call
    executes, so argument errors in discarded calls do not count as tool errors.
    """
    malformed = abs(text.count("<tool_call>") - text.count("</tool_call>"))
    parsed = []
    for content in re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL):
        try:
            value = json.loads(content)
        except ValueError:
            value = None
        if isinstance(value, dict) and "name" in value:
            parsed.append(value)
            continue
        name = re.search(r"<name>\s*(.*?)\s*</name>", content, re.DOTALL)
        if not name:
            malformed += 1
            continue
        arguments = {}
        match = re.search(r"<arguments>\s*(.*?)\s*</arguments>", content, re.DOTALL)
        if match:
            try:
                candidate = json.loads(match.group(1))
                if isinstance(candidate, dict):
                    arguments = candidate
            except ValueError:
                pass  # The official XML fallback also replaces malformed arguments with {}.
        parsed.append({"name": name.group(1).strip(), "arguments": arguments})
    if _conclusion(text) or not parsed:
        return malformed, 0
    first = parsed[0]
    name, arguments = str(first.get("name", "")), first.get("arguments", {})
    if name == "step":
        invalid = (not isinstance(arguments, dict)
                   or not isinstance(arguments.get("action"), str) or not arguments["action"])
    else:
        invalid = not name  # Unknown nonempty names become step(action=name).
    return malformed, int(invalid)


def inspect_evidence(output: Path, official_result: Any, *, mode: str,
                     expected_steps: int, accounting: dict, failure_type: str | None,
                     environment: dict) -> dict:
    """Validate one episode's denominators without altering official results.

    technical_ok covers execution/evidence integrity; protocol_ok additionally
    requires an executed tool and no format/argument errors. Zero reward is
    valid. Calibration additionally requires a speed run, a positive finite
    tau, ordinary completed responses, and no model-declared conclusion.
    No fields contain prompts, responses, game observations, or exception text.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if mode not in {"speed", "timed"} or type(expected_steps) is not int or expected_steps < 1:
        errors.append("invalid_inspection_configuration")
    events = _read_jsonl(output / "requests.jsonl", "requests", errors)
    trajectories = _read_jsonl(output / "official" / f"trajectories_max_steps_{expected_steps}.jsonl",
                               "trajectories", errors)
    summaries = [official_result] if mode == "speed" else official_result
    if not isinstance(summaries, list) or len(summaries) != 1 or not isinstance(summaries[0], dict):
        errors.append("expected_one_official_summary")
        summary = {}
    else:
        summary = summaries[0]
    if summary.get("total_games") != 1:
        errors.append("official_total_games_mismatch")
    if summary.get("failed_games") != 0:
        errors.append("official_episode_failure")
    if len(trajectories) != 1:
        errors.append("expected_one_returned_trajectory")
    trajectory = trajectories[0] if len(trajectories) == 1 else {}
    steps = trajectory.get("steps", [])
    responses = trajectory.get("all_responses", [])
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        errors.append("invalid_trajectory_steps")
        steps = []
    if not isinstance(responses, list) or any(not isinstance(item, str) for item in responses):
        errors.append("invalid_trajectory_responses")
        responses = []
    if trajectory.get("max_step") != expected_steps:
        errors.append("trajectory_step_budget_mismatch")
    if trajectory.get("total_steps") != len(steps) or len(steps) > expected_steps:
        errors.append("trajectory_step_count_mismatch")
    conclusion_count = sum(_conclusion(response) for response in responses)
    if len(responses) != len(steps) + conclusion_count or conclusion_count > 1:
        errors.append("response_step_count_mismatch")
    if conclusion_count and not _conclusion(responses[-1]):
        errors.append("nonterminal_conclusion")
    for index, step in enumerate(steps):
        if step.get("step") != index or index >= len(responses) or step.get("agent_response") != responses[index]:
            errors.append("step_response_sequence_mismatch")
            break
    total_time = trajectory.get("total_actural_time_duration")
    if not _finite(total_time) or total_time < 0:
        errors.append("invalid_official_total_time")
        total_time = None
    time_limit = trajectory.get("time_limit")
    if (mode == "speed" and time_limit is not None) or (mode == "timed" and (not _finite(time_limit) or time_limit <= 0)):
        errors.append("invalid_official_time_limit")
    if mode == "timed" and summary.get("eval_max_steps") != expected_steps:
        errors.append("timed_summary_step_budget_mismatch")
    tau_numerator = total_time if steps else 0.0
    tau = tau_numerator / len(steps) if steps and tau_numerator is not None else None
    expected_summary = {"total_steps": len(steps), "successful_games": int(bool(steps)),
                        "total_success": int(bool(trajectory.get("success")))}
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            errors.append(f"summary_{field}_mismatch")
    for field, expected in (("average_score", trajectory.get("final_score")),
                            ("average_duration_per_step", tau if steps else 0.0),
                            ("average_actural_time_duration", total_time if steps else 0.0)):
        value = summary.get(field)
        if not _finite(value) or not _finite(expected) or not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-9):
            errors.append(f"summary_{field}_mismatch")

    by_event = {name: [event for event in events if event.get("event") == name]
                for name in ("batch_open", "batch_close", "request_dispatch", "request_complete",
                             "request_unknown", "request_rejected")}
    if (len(by_event["batch_open"]) != 1 or len(by_event["batch_close"]) != 1
            or not events or events[0].get("event") != "batch_open" or events[-1].get("event") != "batch_close"):
        errors.append("incomplete_request_journal")
    ids = {}
    for name in ("request_dispatch", "request_complete", "request_unknown"):
        values = [event.get("request_id") for event in by_event[name]]
        if any(not isinstance(value, str) or not value for value in values) or len(set(map(str, values))) != len(values):
            errors.append(f"{name}_invalid_or_duplicate_id")
        ids[name] = Counter(map(str, values))
    if ids["request_dispatch"] != ids["request_complete"] + ids["request_unknown"]:
        errors.append("request_terminal_denominator_mismatch")
    if accounting.get("calls_dispatched") != len(by_event["request_dispatch"]):
        errors.append("accounting_request_count_mismatch")
    if accounting.get("unknown_calls") != len(by_event["request_unknown"]):
        errors.append("accounting_unknown_count_mismatch")
    if accounting.get("active_calls") != 0:
        errors.append("requests_still_active")
    if by_event["request_rejected"]:
        errors.append("request_rejected")
    if by_event["request_unknown"]:
        errors.append("request_usage_or_result_unknown")
    if accounting.get("stop_reason"):
        errors.append("transport_stopped")
    if failure_type:
        errors.append("runner_exception")
    sdk_errors = sum(response.startswith("Error: failed to generate response") for response in responses)
    if sdk_errors:
        errors.append("official_sdk_error_response")
    finish_reasons: Counter[str] = Counter()
    completed_contents = []
    http_duration_s = 0.0
    for event in by_event["request_complete"]:
        try:
            choice = event["response_body"]["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("non-text completion")
            completed_contents.append(content)
            reason = choice.get("finish_reason")
            if not isinstance(reason, str) or reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
                errors.append("invalid_finish_reason")
                reason = "unknown"
            finish_reasons[reason] += 1
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append("invalid_completed_response")
        start, end = event.get("start_monotonic_s"), event.get("end_monotonic_s")
        if _finite(start) and _finite(end) and end >= start:
            http_duration_s += end - start
        else:
            errors.append("invalid_request_timing")
    if completed_contents != responses:
        errors.append("http_trajectory_response_mismatch")

    no_tools = executed_tools = discarded_calls = parameter_errors = format_errors = 0
    for response in completed_contents:
        malformed, invalid_arguments = _tool_format_counts(response)
        format_errors += malformed
        parameter_errors += invalid_arguments
    tool_names: Counter[str] = Counter()
    for step in steps:
        calls, results = step.get("tool_calls"), step.get("tool_results")
        if not isinstance(calls, list) or not isinstance(results, list) or any(not isinstance(result, dict) for result in results):
            errors.append("invalid_tool_evidence")
            continue
        no_tools += int(not calls)
        discarded_calls += max(0, len(calls) - 1)
        executed_tools += len(results)
        for result in results:
            name = result.get("tool")
            tool_names[name if name in {"step", "get_available_actions", "get_score", "get_max_score", "end_game"} else "unknown"] += 1
        if len(results) != int(bool(calls)):
            errors.append("tool_execution_count_mismatch")

    envs = environment.get("environments", []) if isinstance(environment, dict) else []
    if not isinstance(envs, list) or len(envs) != 1 or not isinstance(envs[0], dict):
        errors.append("expected_one_observed_environment")
        env_record = {}
    else:
        env_record = envs[0]
    if (not env_record.get("initialized") or not env_record.get("closed")
            or env_record.get("constructor_error_type") or env_record.get("close_error_type")
            or env_record.get("observation_errors")):
        errors.append("environment_observation_or_cleanup_failure")
    final_state = env_record.get("final") or {}
    if not isinstance(final_state, dict):
        errors.append("invalid_final_environment_state")
        final_state = {}
    raw_score, raw_max = final_state.get("score"), final_state.get("max_score")
    if (type(raw_score) is not int or type(raw_max) is not int or raw_max <= 0
            or type(final_state.get("victory")) is not bool or type(final_state.get("game_over")) is not bool):
        errors.append("incomplete_final_environment_state")
    operations = env_record.get("operations", [])
    if not isinstance(operations, list) or any(not isinstance(operation, dict) for operation in operations):
        errors.append("invalid_environment_operations")
        operations = []
    if any(operation.get("exception_type") for operation in operations):
        errors.append("environment_operation_exception")
    if not parameter_errors:
        observed_tools = Counter(operation.get("tool") for operation in operations)
        expected_tools = Counter({name: tool_names[name] for name in ("step", "get_available_actions", "end_game")})
        if observed_tools != expected_tools:
            errors.append("environment_tool_denominator_mismatch")
    normalized_score = raw_score / raw_max if _finite(raw_score) and _finite(raw_max) and raw_max > 0 else None
    if _finite(raw_score) and _finite(trajectory.get("final_score")) and raw_score != trajectory["final_score"]:
        warnings.append("official_score_differs_from_signed_environment_score")
    if conclusion_count:
        warnings.append("official_conclusion_success_is_not_game_victory")
    if no_tools:
        warnings.append("responses_without_parseable_tool_calls")
    if discarded_calls:
        warnings.append("additional_tool_calls_ignored_by_official_loop")
    if finish_reasons["length"]:
        warnings.append("output_token_limit_reached")
    protocol_ok = executed_tools > 0 and not (sdk_errors or no_tools or format_errors or parameter_errors)
    technical_ok = not errors
    calibration_reasons = []
    if not technical_ok:
        calibration_reasons.append("technical_failure")
    if not protocol_ok:
        calibration_reasons.append("invalid_tool_protocol")
    if mode != "speed":
        calibration_reasons.append("not_speed_mode")
    if tau is None or tau <= 0:
        calibration_reasons.append("invalid_tau")
    if conclusion_count:
        # Upstream includes conclusion generation time but excludes it from steps.
        calibration_reasons.append("conclusion_outside_step_denominator")
    if finish_reasons["length"]:
        calibration_reasons.append("output_token_limit_reached")
    if any(count and reason not in {"stop", "length"} for reason, count in finish_reasons.items()):
        calibration_reasons.append("non_stop_completion")
    return {
        "schema": 1, "technical_ok": technical_ok, "protocol_ok": protocol_ok,
        "calibration_usable": not calibration_reasons,
        "calibration_exclusions": calibration_reasons,
        "errors": sorted(set(errors)), "warnings": sorted(set(warnings)),
        "episodes": {"planned": 1, "official_total": summary.get("total_games"),
                     "returned_trajectories": len(trajectories), "official_failed": summary.get("failed_games"),
                     "official_with_steps": summary.get("successful_games")},
        "counts": {"model_responses": len(responses), "recorded_steps": len(steps),
                   "request_dispatch": len(by_event["request_dispatch"]),
                   "request_complete": len(by_event["request_complete"]),
                   "request_rejected": len(by_event["request_rejected"]),
                   "request_unknown": len(by_event["request_unknown"]),
                   "sdk_error_responses": sdk_errors, "conclusion_responses": conclusion_count,
                   "no_tool_steps": no_tools, "malformed_tool_blocks": format_errors,
                   "invalid_tool_arguments": parameter_errors, "executed_tools": executed_tools,
                   "discarded_tool_calls": discarded_calls, "tools_by_name": dict(tool_names),
                   "finish_reasons": dict(finish_reasons)},
        "game": {"official_score": trajectory.get("final_score"),
                 "official_success_flag": trajectory.get("success"),
                 "signed_score": raw_score, "max_score": raw_max, "normalized_score": normalized_score,
                 "victory": final_state.get("victory"), "game_over": final_state.get("game_over")},
        "calibration": {"mode": mode, "official_tau": summary.get("average_duration_per_step"),
                        "numerator_official_time_s": tau_numerator,
                        "denominator_recorded_steps": len(steps), "recomputed_tau": tau},
        "timing": {"official_logical_total_s": total_time,
                   "official_virtual_tool_s": trajectory.get("total_tool_duration"),
                   "official_time_limit_s": time_limit, "http_completed_total_s": http_duration_s},
        "environment": environment,
    }
