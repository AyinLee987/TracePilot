"""Exercise the pinned Timely runner with real Jericho in offline children.

Run with the Jericho-enabled interpreter and explicit --source/--game paths.
No real credentials are read or passed, and each child blocks Python socket
network operations. Fake HTTP checks are supplemented by a real HTTP transport
setup check with a generated dummy .env, blocked before reaching a provider.
Actual provider requests and API spend are zero. The subprocess timeout is only an
offline test watchdog, never an alternative implementation of Timely's clock.
All evidence, including failed cases, is retained under .local.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("timely_reproduce.py")
PINNED_COMMIT = "e13af2b8c98d799857ace789ebcfdfd4ea6c2985"

# The runner still executes as __main__ in a fresh interpreter. Installing the
# guard before importing it catches accidental replacement of MockTransport.
# This is a Python network guard, not an OS-level network sandbox.
CHILD_BOOTSTRAP = """
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import sys

guard_path, runner, *runner_args = sys.argv[1:]
source = Path(runner_args[runner_args.index('--source') + 1])
prompt_path = source / 'src/timely_eval/prompts.py'
prompt_source_before = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
blocked_events = []
network_events = {
    'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
    'socket.gethostbyname', 'socket.gethostbyaddr',
    'socket.sendto', 'socket.sendmsg',
}
def deny_network(event, arguments):
    if event in network_events:
        blocked_events.append(event)
        raise RuntimeError('network disabled in offline Timely E2E')
sys.addaudithook(deny_network)
sys.path.insert(0, str(Path(runner).parent))
sys.argv = [runner, *runner_args]
paid_setup = '--execute-paid' in runner_args
http_transports = []
http_requests = []
if paid_setup:
    import httpx
    original_init = httpx.AsyncHTTPTransport.__init__
    original_handle = httpx.AsyncHTTPTransport.handle_async_request
    bounded_transport_ids = set()
    def observe_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        bounded = kwargs.get('trust_env') is False and kwargs.get('retries') == 0
        if bounded:
            bounded_transport_ids.add(id(self))
        http_transports.append({'type': 'httpx.AsyncHTTPTransport',
                                'budgeted_pool': bounded})
    async def observe_handle(self, request):
        http_requests.append({'budgeted_pool': id(self) in bounded_transport_ids,
                              'method': request.method, 'host': request.url.host})
        return await original_handle(self, request)
    httpx.AsyncHTTPTransport.__init__ = observe_init
    httpx.AsyncHTTPTransport.handle_async_request = observe_handle
try:
    runpy.run_path(runner, run_name='__main__')
finally:
    official = sys.modules.get('timely_eval.interactive')
    prompts = sys.modules.get('timely_eval.prompts')
    prompt_evidence = {}
    if official is not None and prompts is not None:
        base_system = prompts.INTERACTIVE_SYSTEM + '\\n\\n' + prompts.INTERACTIVE_TOOL_PROMPT
        prompt_evidence = {
            'tool_prompt_restored': official.INTERACTIVE_TOOL_PROMPT == prompts.INTERACTIVE_TOOL_PROMPT,
            'base_tool_prompt_sha256': hashlib.sha256(prompts.INTERACTIVE_TOOL_PROMPT.encode()).hexdigest(),
            'base_system_message_sha256': hashlib.sha256(base_system.encode()).hexdigest(),
            'source_unchanged': prompt_source_before == hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        }
    active_child_pids = [child.pid for child in multiprocessing.active_children()]
    proc_children = Path(f'/proc/self/task/{os.getpid()}/children')
    direct_child_pids = ([int(pid) for pid in proc_children.read_text().split()]
                         if proc_children.exists() else None)
    with Path(guard_path).open('x', encoding='utf-8') as stream:
        json.dump({'guard': 'python_socket_audit_hook', 'installed': True,
                   'blocked_events': blocked_events,
                   'credentials_source': 'generated_dummy_env_fixture' if paid_setup else 'none',
                   'real_credentials_passed': False,
                   'http_transports': http_transports, 'http_requests': http_requests,
                   'prompt_scope': prompt_evidence,
                   'active_child_pids': active_child_pids,
                   'procfs_direct_child_pids': direct_child_pids}, stream, indent=2)
        stream.write('\\n')
"""


@dataclass(frozen=True)
class Case:
    name: str
    fake_case: str = "valid"
    tool_format: str = "official"
    network_setup: bool = False
    extra_args: tuple[str, ...] = ()
    technical_ok: bool = True
    protocol_ok: bool = True
    calibration_usable: bool = False
    recorded_steps: int = 3
    model_responses: int = 3
    executed_tools: int = 3
    tool_name: str = "step"
    request_dispatch: int = 3
    request_complete: int = 3
    request_unknown: int = 0
    request_rejected: int = 0
    sdk_error_responses: int = 0
    conclusion_responses: int = 0
    stop_reason: str | None = None
    required_errors: tuple[str, ...] = ()
    required_warnings: tuple[str, ...] = ()


CASES = (
    Case("valid-speed", calibration_usable=True),
    Case("single-json-v2-speed", tool_format="single-json-v2", calibration_usable=True),
    Case("single-json-v2-timed", tool_format="single-json-v2",
         extra_args=("--mode", "timed", "--average-duration-per-step", "0.000001"),
         recorded_steps=1, model_responses=1, executed_tools=1, request_dispatch=1, request_complete=1),
    Case("single-json-v2-missing-close", tool_format="single-json-v2", fake_case="missing-close",
         protocol_ok=False, executed_tools=0,
         required_warnings=("responses_without_parseable_tool_calls",)),
    Case("single-json-v2-conclusion", tool_format="single-json-v2", fake_case="conclusion", protocol_ok=False,
         recorded_steps=0, model_responses=1, executed_tools=0,
         request_dispatch=1, request_complete=1, conclusion_responses=1,
         required_warnings=("official_conclusion_success_is_not_game_victory",)),
    Case("single-json-v1-speed", tool_format="single-json-v1", calibration_usable=True),
    Case("single-json-v1-timed", tool_format="single-json-v1",
         extra_args=("--mode", "timed", "--average-duration-per-step", "0.000001"),
         recorded_steps=1, model_responses=1, executed_tools=1, request_dispatch=1, request_complete=1),
    Case("single-json-v1-conclusion", tool_format="single-json-v1", fake_case="conclusion", protocol_ok=False,
         recorded_steps=0, model_responses=1, executed_tools=0,
         request_dispatch=1, request_complete=1, conclusion_responses=1,
         required_warnings=("official_conclusion_success_is_not_game_victory",)),
    Case("single-json-v1-tool-error", tool_format="single-json-v1", fake_case="tool-error", technical_ok=False, protocol_ok=False,
         recorded_steps=0, model_responses=0, executed_tools=0,
         request_dispatch=1, request_complete=1,
         required_errors=("official_episode_failure", "expected_one_returned_trajectory")),
    Case("timed-after-action", extra_args=("--mode", "timed", "--average-duration-per-step", "0.000001"),
         recorded_steps=1, model_responses=1, executed_tools=1,
         request_dispatch=1, request_complete=1),
    Case("no-tool", fake_case="no-tool", protocol_ok=False, executed_tools=0,
         required_warnings=("responses_without_parseable_tool_calls",)),
    Case("conclusion", fake_case="conclusion", protocol_ok=False,
         recorded_steps=0, model_responses=1, executed_tools=0,
         request_dispatch=1, request_complete=1, conclusion_responses=1,
         required_warnings=("official_conclusion_success_is_not_game_victory",)),
    Case("tool-error", fake_case="tool-error", technical_ok=False, protocol_ok=False,
         recorded_steps=0, model_responses=0, executed_tools=0,
         request_dispatch=1, request_complete=1,
         required_errors=("official_episode_failure", "expected_one_returned_trajectory")),
    Case("http-error", fake_case="http-error", technical_ok=False, protocol_ok=False,
         executed_tools=0, request_dispatch=1, request_complete=0,
         request_unknown=1, request_rejected=2, sdk_error_responses=3,
         stop_reason="http_status_error",
         required_errors=("request_usage_or_result_unknown", "official_sdk_error_response", "transport_stopped")),
    Case("missing-usage", fake_case="missing-usage", technical_ok=False, protocol_ok=False,
         executed_tools=0, request_dispatch=1, request_complete=0,
         request_unknown=1, request_rejected=2, sdk_error_responses=3,
         stop_reason="unknown_usage",
         required_errors=("request_usage_or_result_unknown", "official_sdk_error_response", "transport_stopped")),
    Case("max-calls", extra_args=("--max-calls", "1"), technical_ok=False, protocol_ok=False,
         executed_tools=1, request_dispatch=1, request_complete=1,
         request_rejected=2, sdk_error_responses=2, stop_reason="max_calls_reached",
         required_errors=("request_rejected", "official_sdk_error_response", "transport_stopped")),
    Case("budget", extra_args=("--budget-cny", "0.0000001"), technical_ok=False, protocol_ok=False,
         executed_tools=0, request_dispatch=0, request_complete=0,
         request_rejected=3, sdk_error_responses=3, stop_reason="budget_exhausted",
         required_errors=("request_rejected", "official_sdk_error_response", "transport_stopped")),
    Case("length", fake_case="length", required_warnings=("output_token_limit_reached",)),
    Case("conclusion-after-tool", fake_case="conclusion-after-tool",
         recorded_steps=1, model_responses=2, executed_tools=1,
         request_dispatch=2, request_complete=2, conclusion_responses=1,
         required_warnings=("official_conclusion_success_is_not_game_victory",)),
    Case("invalid-finish-reason", fake_case="invalid-finish-reason", technical_ok=False,
         required_errors=("invalid_finish_reason",)),
    Case("action-discovery", fake_case="action-discovery", calibration_usable=True,
         tool_name="get_available_actions"),
    Case("paid-network-guard", network_setup=True, technical_ok=False, protocol_ok=False,
         executed_tools=0, request_dispatch=1, request_complete=0,
         request_unknown=1, request_rejected=2, sdk_error_responses=3,
         stop_reason="network_or_transport_error",
         required_errors=("request_usage_or_result_unknown", "official_sdk_error_response", "transport_stopped")),
    Case("pool-abort"),
)


def dump(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def read_jsonl(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"Expected JSON objects in {path.name}")
    return rows


def child_environment() -> dict[str, str]:
    """Read only named OS/runtime settings; never enumerate credential variables."""
    names = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {name: value for name in names if (value := os.environ.get(name)) is not None}
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def inspect_case(case: Case, output: Path, control: Path, game_path: Path,
                 exit_code: int | None, timed_out: bool) -> dict:
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    check(not timed_out, "offline subprocess watchdog expired")
    check(exit_code == (0 if case.technical_ok else 1), f"unexpected exit code: {exit_code}")
    summary: dict = {"name": case.name, "output": str(output), "exit_code": exit_code,
                     "timed_out": timed_out, "errors": errors}
    try:
        guard = read_json(control / "network-guard.json")
        check(guard.get("installed") is True, "network guard missing")
        if case.network_setup:
            check(bool(guard["blocked_events"]), "real HTTP setup never reached the Python network guard")
            check(guard["credentials_source"] == "generated_dummy_env_fixture", "dummy fixture boundary missing")
            check(sum(item["budgeted_pool"] for item in guard["http_transports"]) == 1,
                  "expected one real budgeted AsyncHTTPTransport construction")
            check(guard["http_requests"] == [{"budgeted_pool": True, "method": "POST", "host": "api.deepseek.com"}],
                  "real budgeted HTTP transport did not attempt exactly one request")
        else:
            check(guard.get("blocked_events") == [], "unexpected Python network operation attempted")
            check(guard["credentials_source"] == "none", "unexpected credential fixture")
        check(guard.get("real_credentials_passed") is False, "real credential boundary missing")
        check(guard.get("active_child_pids") == [], "multiprocessing children still active before runner exit")
        check(guard.get("procfs_direct_child_pids") in (None, []), "child PIDs remain before runner exit")
        check(guard["prompt_scope"].get("tool_prompt_restored") is True, "official prompt not restored after episode")
        check(guard["prompt_scope"].get("source_unchanged") is True, "official prompt source file changed")
        if case.name == "pool-abort":
            environment = read_json(output / "environment.json")
            result = read_json(output / "pool-abort.json")
            check(result["controlled_abort_seen"] is True, "controlled observer abort not observed")
            check(result["actions_count"] > 0 and bool(result["worker_pids_before"]),
                  "real action discovery did not create workers")
            check(result["worker_alive_after"] == [] and all(code is not None for code in result["worker_exitcodes"].values()),
                  "real worker processes remain alive or unjoined after observer abort")
            check(result["official_class_restored"] is True, "official environment class not restored")
            check(result["prompt_scope_restored"] is True and result["prompt_note_once"] is True,
                  "adapted prompt context did not restore after controlled abort")
            check(result["upstream_commit"] == PINNED_COMMIT and bool(result["upstream_sha256"]), "source pin missing")
            check(result["jericho_version"] == "3.2.1", "wrong Jericho version")
            check(len(environment["environments"]) == 1, "expected one real observed environment")
            env = environment["environments"][0]
            pool = env["worker_pool"]
            check(env["initialized"] and env["closed"] and not env["close_error_type"], "environment cleanup failed")
            check(pool["present"] and pool["closed"] and pool["terminate_attempted"] and pool["join_attempted"],
                  "real worker pool was not terminated and joined")
            check(pool["cleanup_mode"] == "terminate_join" and not pool["close_attempted"] and not pool["errors"],
                  "controlled error did not use clean terminate_join")
            check(len(env["operations"]) == 1 and env["operations"][0]["tool"] == "get_available_actions",
                  "real action discovery operation not captured")
            summary.update({"worker_pool": pool, "worker_pids_before": result["worker_pids_before"],
                            "worker_alive_after": result["worker_alive_after"], "zero_api": True,
                            "passed": not errors})
            return summary
        manifest = read_json(output / "manifest.json")
        result = read_json(output / "result.json")
        environment = read_json(output / "environment.json")
        events = read_jsonl(output / "requests.jsonl")
        evidence, accounting = result["evidence"], result["accounting"]
        counts, game = evidence["counts"], evidence["game"]
        mode = "timed" if "--mode" in case.extra_args else "speed"
        check(manifest["paid"] is case.network_setup and result["paid"] is case.network_setup, "wrong runner mode")
        check(manifest["evidence"] == ("api_model_protocol_replication" if case.network_setup else "fake_model_real_environment"),
              "wrong environment/model evidence label")
        check(manifest["fake_case"] == (None if case.network_setup else case.fake_case), "wrong fake response scenario")
        check(manifest["upstream_commit"] == PINNED_COMMIT and bool(manifest["upstream_sha256"]),
              "official source pin/hash evidence missing")
        check(manifest["game_sha256"] == hashlib.sha256(game_path.read_bytes()).hexdigest(),
              "ROM hash does not match the requested real game")
        check(manifest["run_id"] == output.name == result["run_id"], "run IDs are not isolated")
        check(manifest["mode"] == mode and manifest["steps"] == 3, "wrong episode configuration")
        check(manifest["jericho_seed"] and manifest["versions"]["jericho"] == "3.2.1", "wrong Jericho version")
        check(manifest["sdk_max_retries"] == 0 and manifest["official_agent_attempts"] == 1,
              "unexpected retry configuration")
        check("outer_retries" not in manifest, "legacy retry metadata is ambiguous")
        from timely_reproduce import SINGLE_JSON_TOOL_NOTE, SINGLE_JSON_V2_TOOL_NOTE
        note = {"official": "", "single-json-v1": SINGLE_JSON_TOOL_NOTE,
                "single-json-v2": SINGLE_JSON_V2_TOOL_NOTE}[case.tool_format]
        check(manifest["tool_format"] == case.tool_format
              and manifest["prompt_condition_id"] == f"timely-interactive:{case.tool_format}"
              and manifest["tool_format_note"] == note, "prompt condition metadata mismatch")
        prompt_hashes = manifest["prompt_sha256"]
        check(prompt_hashes["base_tool_prompt"] == guard["prompt_scope"]["base_tool_prompt_sha256"]
              and prompt_hashes["base_system_message"] == guard["prompt_scope"]["base_system_message_sha256"],
              "base prompt hashes differ from unchanged official module")
        adapted_difference = f"{case.tool_format} tool-format-only prompt clarification"
        check((adapted_difference in manifest["differences_from_paper"]) == bool(note), "prompt adaptation disclosure missing or invented")
        if not note:
            check(prompt_hashes["base_tool_prompt"] == prompt_hashes["actual_tool_prompt"]
                  and prompt_hashes["base_system_message"] == prompt_hashes["actual_system_message"],
                  "default official prompt was changed")
        for event in events:
            if event["event"] == "request_dispatch":
                system = event["request_body"]["messages"][0]["content"]
                check(hashlib.sha256(system.encode()).hexdigest() == prompt_hashes["actual_system_message"],
                      "actual request system prompt differs from manifest")
                if note:
                    check(system.count(note) == 1, "tool format note must appear exactly once only in adapted condition")
                else:
                    check(SINGLE_JSON_TOOL_NOTE not in system and SINGLE_JSON_V2_TOOL_NOTE not in system,
                          "official condition must not contain an adapted note")
                base = system.removesuffix("\n\n" + note) if note else system
                check(hashlib.sha256(base.encode()).hexdigest() == prompt_hashes["base_system_message"],
                      "adaptation changed the original system prompt beyond appending the note")
        check(manifest["http_operation_timeout_s"] == 60
              and manifest["http_timeout_semantics"] == "per_operation_not_absolute_task_deadline",
              "HTTP operation timeout confused with the evaluator deadline")
        check(manifest["transport_limits"] == {
            "max_message_bytes": 256_000, "max_request_bytes": 1_048_576,
            "max_response_bytes_each_wire_decoded": 1_048_576,
            "max_output_tokens": 2_048, "message_overhead_tokens_each": 1_024,
        }, "transport bounds differ from the pinned offline contract")
        check(manifest["runtime"]["python"] == ".".join(map(str, sys.version_info[:3]))
              and bool(manifest["runtime"]["platform"]), "runtime metadata missing or inconsistent")
        check(all(value == 2 for value in manifest["tool_durations"].values()), "wrong virtual tool durations")
        check(result["cost_interpretation"] == ("peak-price estimate" if case.network_setup else "synthetic accounting; zero API spend"),
              "runner cost interpretation changed")
        check(result["paper_result_reproduced"] is False, "fake run presented as paper reproduction")
        check(result["failure_type"] is None, "runner raised an exception instead of retaining evaluator evidence")
        for field in ("technical_ok", "protocol_ok", "calibration_usable"):
            check(evidence[field] is getattr(case, field), f"unexpected {field}: {evidence[field]}")
        for field in ("recorded_steps", "model_responses", "executed_tools", "request_dispatch", "request_complete",
                      "request_unknown", "request_rejected", "sdk_error_responses", "conclusion_responses"):
            check(counts[field] == getattr(case, field), f"unexpected {field}: {counts[field]}")
        check(set(case.required_errors) <= set(evidence["errors"]), "required evidence errors missing")
        check(set(case.required_warnings) <= set(evidence["warnings"]), "required evidence warnings missing")
        check(bool(evidence["errors"]) is not case.technical_ok, "technical status disagrees with diagnostic errors")
        check(bool(evidence["calibration_exclusions"]) is not case.calibration_usable,
              "calibration status disagrees with its explicit exclusions")
        check(evidence["environment"] == environment, "result/environment artifacts disagree")
        envs = environment["environments"]
        check(len(envs) == 1, "expected one observed environment")
        env = envs[0]
        check(env["initialized"] and env["close_attempted"] and env["closed"], "environment not initialized and closed")
        check(not env["constructor_error_type"] and not env["close_error_type"] and not env["observation_errors"],
              "environment observation or cleanup failed")
        check(len(env["operations"]) == case.executed_tools, "actual environment operation count differs")
        check(all(op["tool"] == case.tool_name and op["exception_type"] is None for op in env["operations"]),
              "unexpected environment operation or exception")
        pool = env["worker_pool"]
        if case.name == "action-discovery":
            check(pool["present"] and pool["closed"] and pool["close_attempted"] and pool["join_attempted"],
                  "action-discovery worker pool was not closed and joined")
            check(pool["cleanup_mode"] == "close_join" and not pool["errors"], "unexpected successful pool cleanup")
        else:
            check(pool["present"] is False and not pool["errors"], "an unused worker pool was created or failed cleanup")
        for operation in env["operations"]:
            check(operation["score_delta"] == operation["after"]["score"] - operation["before"]["score"],
                  "environment score delta inconsistent")
            check(math.isfinite(operation["duration_s"]) and operation["duration_s"] >= 0,
                  "actual operation duration is invalid")
        check(game["signed_score"] == env["final"]["score"] and game["max_score"] == env["final"]["max_score"],
              "game score differs from underlying environment")
        check(game["max_score"] > 0 and game["normalized_score"] == game["signed_score"] / game["max_score"],
              "normalized score denominator invalid")
        check(game["victory"] is env["final"]["victory"] and game["game_over"] is env["final"]["game_over"],
              "game termination evidence differs from underlying environment")
        event_counts = Counter(event["event"] for event in events)
        check(events[0]["event"] == "batch_open" and events[-1]["event"] == "batch_close",
              "request journal lacks complete lifecycle")
        check(event_counts["batch_open"] == event_counts["batch_close"] == 1, "duplicate request journal lifecycle")
        for name in ("request_dispatch", "request_complete", "request_unknown", "request_rejected"):
            check(event_counts[name] == getattr(case, name), f"raw journal count mismatch: {name}")
        request_events = [event for event in events if event["event"].startswith("request_")]
        check(all(event["run_id"] == output.name and event["labels"]["phase"] == mode for event in request_events),
              "request labels crossed run boundaries")
        dispatch_ids = Counter(event["request_id"] for event in events if event["event"] == "request_dispatch")
        terminal_ids = Counter(event["request_id"] for event in events
                               if event["event"] in {"request_complete", "request_unknown"})
        check(dispatch_ids == terminal_ids and all(value == 1 for value in dispatch_ids.values()),
              "dispatched requests do not have exactly one terminal event")
        check(accounting["calls_dispatched"] == case.request_dispatch, "accounting dispatch mismatch")
        check(accounting["unknown_calls"] == case.request_unknown, "accounting unknown count mismatch")
        check(accounting["active_calls"] == 0 and accounting["closing"] is True, "request resources left active")
        check(accounting["stop_reason"] == case.stop_reason, "wrong budget/transport stop reason")
        check(Decimal(accounting["in_flight_reserved_cny"]) == 0, "in-flight reservation remains after shutdown")
        reserved = Decimal(accounting["unknown_reserved_cny"])
        check((reserved > 0) if case.request_unknown else (reserved == 0), "unknown reservation was lost or invented")
        check(Decimal(accounting["reserved_cny"]) == reserved, "reservation accounting disagrees")
        estimated = Decimal(accounting["estimated_cny"])
        check((estimated > 0) if case.request_complete else (estimated == 0), "synthetic completed-call cost mismatch")
        check(Decimal(accounting["committed_cny"]) == estimated + reserved, "committed cost arithmetic mismatch")
        check(Decimal(accounting["committed_cny"]) <= Decimal(manifest["budget_cny"]), "synthetic budget exceeded")
        summary_name = "max_steps_3_summary.json" if mode == "timed" else "speed_summary.json"
        official_summary = read_json(output / "official" / summary_name)
        check(official_summary == (result["official_result"][0] if mode == "timed" else result["official_result"]),
              "official summary artifact differs from result")
        trajectory_path = output / "official" / "trajectories_max_steps_3.jsonl"
        if case.fake_case == "tool-error":
            check(official_summary["failed_games"] == 1 and not trajectory_path.exists(),
                  "tool exception should remain an official failed episode without a trajectory")
        else:
            trajectories = read_jsonl(trajectory_path)
            check(len(trajectories) == 1, "expected one official trajectory")
            trajectory = trajectories[0]
            check(trajectory["total_steps"] == len(trajectory["steps"]) == case.recorded_steps,
                  "raw trajectory steps disagree with expected count")
            check(len(trajectory["all_responses"]) == case.model_responses, "raw model response count mismatch")
            check(official_summary["failed_games"] == 0, "unexpected official episode failure")
            check(trajectory["total_tool_duration"] == 2 * case.executed_tools, "virtual tool time is not accumulated")
            tau = evidence["calibration"]["recomputed_tau"]
            if case.recorded_steps:
                expected_tau = trajectory["total_actural_time_duration"] / case.recorded_steps
                check(math.isclose(tau, expected_tau, rel_tol=1e-12), "tau denominator differs from recorded steps")
                check(math.isclose(official_summary["average_duration_per_step"], tau, rel_tol=1e-12),
                      "official and recomputed tau differ")
            else:
                check(tau is None and official_summary["average_duration_per_step"] == 0, "zero-step run invented tau")
            if case.conclusion_responses:
                check(trajectory["success"] is True and game["official_success_flag"] is True,
                      "official conclusion success flag not preserved")
                check(game["victory"] is False and game["game_over"] is False,
                      "fake conclusion must not be presented as an actual game victory")
            if mode == "timed":
                check(math.isclose(trajectory["time_limit"], 3e-6, rel_tol=1e-12), "wrong timed deadline")
                check(trajectory["steps"][0]["cumulative_actural_time_duration"] >= 2,
                      "timed episode did not execute the first action before checking its deadline")
                check(trajectory["total_actural_time_duration"] > trajectory["time_limit"],
                      "after-action deadline overshoot missing")
        if case.name == "no-tool":
            check(counts["no_tool_steps"] == 3, "no-tool scenario should record three unsuccessful protocol steps")
        if case.name == "length":
            check(counts["finish_reasons"].get("length") == 3, "length finish reasons missing")
        if case.fake_case == "tool-error":
            check(counts["invalid_tool_arguments"] == 1, "malformed tool argument diagnostic missing")
        summary.update({"technical_ok": evidence["technical_ok"], "protocol_ok": evidence["protocol_ok"],
                        "calibration_usable": evidence["calibration_usable"], "counts": counts,
                        "game": game, "calibration": evidence["calibration"],
                        "calibration_exclusions": evidence["calibration_exclusions"],
                        "worker_pool": pool,
                        "evidence_errors": evidence["errors"], "evidence_warnings": evidence["warnings"],
                        "synthetic_estimated_cny": str(estimated), "synthetic_reserved_cny": str(reserved),
                        "stop_reason": accounting["stop_reason"], "zero_api": True})
    except Exception as exc:
        # Continue the suite and preserve every child artifact when inspection fails.
        errors.append(f"artifact inspection failed: {type(exc).__name__}: {exc}")
    summary["passed"] = not errors
    return summary


def pool_abort_child(source: Path, game: Path, output: Path) -> int:
    """Use a real Jericho worker pool, then leave the observer with an error."""
    import importlib.metadata
    from timely_reproduce import verify_source, tool_prompt_condition, SINGLE_JSON_TOOL_NOTE
    from timely_evidence import observe_environment

    hashes = verify_source(source)
    sys.path.insert(0, str(source / "src"))
    import timely_eval.interactive as official

    output = output.resolve()
    if not output.is_relative_to(ROOT / ".local"):
        raise ValueError("Observer-check output must be below this checkout's .local")
    output.mkdir(parents=True, exist_ok=False)
    original = official.JerichoToolEnvironment
    original_prompt, prompt_note_once = official.INTERACTIVE_TOOL_PROMPT, False
    observer, workers, actions_count, aborted = None, [], 0, False

    class ControlledPoolAbort(Exception):
        pass

    try:
        with tool_prompt_condition(official, "single-json-v1"), observe_environment(official) as observer:
            prompt_note_once = official.INTERACTIVE_TOOL_PROMPT.count(SINGLE_JSON_TOOL_NOTE) == 1
            env = official.JerichoToolEnvironment(game)
            actions_count = len(env.get_valid_actions())
            workers = list(env.env.pool._pool)
            raise ControlledPoolAbort("offline cleanup-path check")
    except ControlledPoolAbort:
        aborted = True
    finally:
        dump(output / "environment.json", observer.snapshot() if observer is not None else {})
        dump(output / "pool-abort.json", {
            "controlled_abort_seen": aborted, "actions_count": actions_count,
            "worker_pids_before": [worker.pid for worker in workers],
            "worker_alive_after": [worker.pid for worker in workers if worker.is_alive()],
            "worker_exitcodes": {str(worker.pid): worker.exitcode for worker in workers},
            "official_class_restored": official.JerichoToolEnvironment is original,
            "prompt_scope_restored": official.INTERACTIVE_TOOL_PROMPT == original_prompt,
            "prompt_note_once": prompt_note_once,
            "upstream_commit": PINNED_COMMIT, "upstream_sha256": hashes,
            "jericho_version": importlib.metadata.version("jericho"), "zero_api": True,
        })
    return 0 if aborted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=90,
                        help="Offline subprocess watchdog only; does not change the official evaluator deadline")
    parser.add_argument("--case", action="append", choices=[case.name for case in CASES],
                        help="Run only named cases; omit to run the complete suite")
    parser.add_argument("--pool-abort-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
        parser.error("timeout-s must be finite and positive")
    source, game = args.source.resolve(strict=True), args.game.resolve(strict=True)
    if args.pool_abort_output is not None:
        return pool_abort_child(source, game, args.pool_abort_output)
    cases = [case for case in CASES if args.case is None or case.name in args.case]
    suite = ROOT / ".local" / "timely-reproduction-checks" / uuid.uuid4().hex
    suite.mkdir(parents=True, exist_ok=False)
    dump(suite / "suite-manifest.json", {
        "schema": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_real_jericho_guarded_subprocess", "zero_api": True,
        "actual_api_spend_cny": "0", "source": str(source), "game": str(game),
        "python": sys.executable, "watchdog_timeout_s": args.timeout_s,
        "timeout_semantics": "offline_test_watchdog_only", "child_environment": "OS/runtime allowlist; no real credentials",
        "paid_flag_semantics": "one real HTTP setup path with a generated dummy .env; socket guard prevents provider access",
        "network_guard": "Python socket audit hook; not an OS network sandbox",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": [case.name for case in cases],
    })
    summaries = []
    for case in cases:
        control = suite / case.name
        control.mkdir()
        output = control / uuid.uuid4().hex  # The child owns creation; never reuse a run directory.
        entry = Path(__file__).resolve() if case.name == "pool-abort" else RUNNER
        command = [sys.executable, "-c", CHILD_BOOTSTRAP, str(control / "network-guard.json"), str(entry),
                   "--source", str(source), "--game", str(game)]
        if case.name == "pool-abort":
            command.extend(["--pool-abort-output", str(output)])
        else:
            command.extend(["--output", str(output), "--steps", "3", "--tool-delay", "2",
                            "--max-calls", "8", "--budget-cny", "1", "--fake-case", case.fake_case, *case.extra_args])
            if case.tool_format != "official":
                command.extend(["--tool-format", case.tool_format])
        dummy_secret, fixture = None, control / ".dummy-input.env"
        started, timed_out, exit_code = time.perf_counter(), False, None
        try:
            if case.network_setup:
                dummy_secret = "offline-dummy-secret-" + uuid.uuid4().hex
                with fixture.open("x", encoding="utf-8") as stream:
                    stream.write(f"DEEPSEEK_API_KEY={dummy_secret}\n")
                command.extend(["--execute-paid", "--env-file", str(fixture)])
            dump(control / "invocation.json", {"command": command, "game": str(game), "cwd": str(ROOT),
                                               "output": str(output), "timeout_s": args.timeout_s, "zero_api": True,
                                               "generated_dummy_fixture": case.network_setup})
            with (control / "stdout.txt").open("xb") as stdout, (control / "stderr.txt").open("xb") as stderr:
                try:
                    with subprocess.Popen(command, cwd=ROOT, env=child_environment(), stdout=stdout, stderr=stderr,
                                          start_new_session=os.name == "posix") as process:
                        try:
                            exit_code = process.wait(timeout=args.timeout_s)
                        except subprocess.TimeoutExpired:
                            timed_out = True
                            # Kill only this isolated offline process group, including Jericho workers.
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                            exit_code = process.wait()
                except OSError as exc:
                    stderr.write(f"subprocess launch failed: {type(exc).__name__}\n".encode())
        finally:
            if dummy_secret is not None:
                fixture.unlink(missing_ok=True)  # Only the generated input; all output evidence is retained.
        summary = inspect_case(case, output, control, game, exit_code, timed_out)
        if dummy_secret is not None:
            files = [path for path in control.rglob("*") if path.is_file()]
            leaked = [str(path.relative_to(control)) for path in files if dummy_secret.encode() in path.read_bytes()]
            summary["dummy_secret_scan"] = {"files_scanned": len(files), "leaked_files": leaked,
                                             "fixture_removed": not fixture.exists()}
            if leaked:
                summary["errors"].append("generated dummy credential leaked to output artifacts")
                summary["passed"] = False
        summary["elapsed_wall_s"] = time.perf_counter() - started
        dump(control / "check.json", summary)
        summaries.append(summary)
        print(json.dumps({"case": case.name, "passed": summary["passed"], "exit_code": exit_code,
                          "errors": summary["errors"], "output": str(output)}, ensure_ascii=False), flush=True)
    report = {"schema": 1, "mode": "offline_real_jericho_guarded_subprocess",
              "zero_api": True, "actual_api_spend_cny": "0", "paper_result_reproduced": False,
              "passed_cases": sum(case["passed"] for case in summaries), "total_cases": len(summaries),
              "failed_cases": [case["name"] for case in summaries if not case["passed"]],
              "output_dir": str(suite), "cases": summaries}
    dump(suite / "summary.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False), flush=True)
    return 0 if report["passed_cases"] == report["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
