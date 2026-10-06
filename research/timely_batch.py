"""Frozen, serial R2 pilot around timely_reproduce.py; no network by default.

Create a fresh .local pilot with ``create-plan`` (``--plan-paid --import-r1 DIR``
for a future paid pilot). ``run`` is a dry inspection unless explicitly passed
``--execute-offline`` or ``--execute-paid --env-file PATH``. Run in the same
Python environment as the child runner. Offline and paid pilots never mix.
Execution requires Linux/WSL; plan creation and dry inspection are portable.
The fixed study registry permits one paid pilot and freezes the complete R1
inventory. A second plan cannot obtain another CNY 200 allowance.

The append-only, fsynced ledger reserves a complete balanced block before any
child starts. Child transport caps are CNY 5 for Flash and CNY 10/20 for
32/64-step Pro runs; these are liability guards, not expected spend. The pilot,
including explicitly imported R1 expenses, has a <= CNY 200 cap. Estimates are
not invoices. An unresolved started child keeps its full reservation and stops
the pilot: there is no automatic retry, result adoption, or stale-lock removal.
Clean stops between children can resume in the frozen order. The exclusive
lock covers the coordinator lifetime (including its child), not an application
data lock. No other coordinator may spend this pilot's budget concurrently.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, nullcontext
import ctypes
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Iterator
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("timely_reproduce.py")
COMMIT = "e13af2b8c98d799857ace789ebcfdfd4ea6c2985"
PROMPTS_SHA256 = "dd664c1d31548b30d54b51d96401382b1203bdecfe21e12e5fc5e7c60b2a2b84"
MODELS = ("deepseek-flash", "deepseek-v4-pro")
CHILD_CAPS = {"deepseek-flash": {32: "5", 64: "5"},
              "deepseek-v4-pro": {32: "10", 64: "20"}}
TOOLS = ("step", "get_available_actions", "get_score", "get_max_score", "end_game")
VERSION_NAMES = ("openai", "httpx", "jericho", "spacy")
RUNNER_NAMES = ("timely_reproduce.py", "timely_transport.py", "timely_evidence.py")
PAID_STUDY_ROOT = ROOT / ".local" / "timely-pilot-budget-20261006"
R1_ROOT = ROOT / ".local" / "timely-reproduction-runs"


class PilotError(RuntimeError):
    """Body-free operational failure; never contains child output or credentials."""


class ProcessCleanupError(PilotError):
    """Owned descendants may remain; preserve both coordinator locks."""


def require(value: Any, reason: str) -> None:
    if not value:
        raise PilotError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def invalid(_: str) -> None:
        raise PilotError("nonfinite_json")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=invalid)


def money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise PilotError("invalid_money") from None
    require(result.is_finite() and result >= 0, "invalid_money")
    return result


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def local_path(path: Path) -> Path:
    resolved = path.resolve()
    require(resolved.is_relative_to((ROOT / ".local").resolve())
            and resolved != (ROOT / ".local").resolve(), "pilot_path_outside_local")
    return resolved


@contextmanager
def exclusive(root: Path) -> Iterator[None]:
    lock = root / "pilot.lock"
    token = str(uuid.uuid4())
    try:
        write_new(lock, {"token": token, "pid": os.getpid(), "created_at":
                         datetime.now(timezone.utc).isoformat()})
    except FileExistsError:
        raise PilotError("existing_lock_requires_operator_inspection") from None
    preserve = False
    try:
        yield
    except ProcessCleanupError:
        preserve = True
        raise
    finally:
        # Only remove the exact lock owned by this invocation. SIGKILL leaves it.
        if not preserve and lock.exists() and read_json(lock).get("token") == token:
            lock.unlink()


def constant(path: Path, name: str) -> Any:
    """Read frozen literal configuration without importing the network adapter."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise PilotError("missing_runner_configuration_constant")


def group_members(group: int) -> dict[int, str]:
    members = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group and int(fields[3]) == group:
                members[int(path.name)] = fields[0]
        except FileNotFoundError:
            continue
    return members


def run_owned_child(command: list[str], *, timeout: float, ownership_path: Path,
                    grace_s: float = 2.0) -> int:
    """Own one Linux session until its direct child and adopted descendants exit.

    waitid(WNOWAIT) keeps the leader's PID reserved until group cleanup is done,
    avoiding PID reuse when signalling. Subreaper adoption lets this process
    reap orphaned multiprocessing descendants rather than relying on PID 1.
    Only children in the new session/group are signalled or reaped.
    """
    require(sys.platform == "linux" and Path("/proc/self/stat").exists(),
            "owned_process_tree_requires_linux_wsl")
    require(threading.current_thread() is threading.main_thread() and threading.active_count() == 1,
            "owned_process_launcher_requires_single_main_thread")
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    require(libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0, "cannot_read_subreaper_state")
    require(libc.prctl(36, 1, 0, 0, 0) == 0, "cannot_enable_subreaper")
    handlers = {sig: signal.getsignal(sig) for sig in
                (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    child = None
    def cancel(signum, frame):
        raise KeyboardInterrupt("owned_child_cancelled")
    try:
        for sig in handlers:
            signal.signal(sig, cancel)
        # Do not deliver cancellation between fork and recording ownership.
        # This launcher explicitly rejects threaded callers, so the minimal
        # preexec mask reset cannot inherit another Python thread's locks.
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(handlers))
        try:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True,
                                     preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask))
            write_new(ownership_path, {"schema": 1, "pid": child.pid, "pgid": child.pid,
                                      "session_id": child.pid, "coordinator_pid": os.getpid(),
                                      "ownership": "new_linux_session", "timeout_s": timeout})
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        until = time.monotonic() + timeout
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            if time.monotonic() >= until:
                raise PilotError("owned_child_timeout")
            time.sleep(0.05)
    finally:
        # A second cancellation must not interrupt bounded cleanup halfway.
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if child is not None:
                try:
                    # Python's SIGINT path gives the runner's finally blocks a
                    # chance to close the environment and write billing state.
                    os.killpg(child.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                until = time.monotonic() + grace_s
                while any(state != "Z" for state in group_members(child.pid).values()) and time.monotonic() < until:
                    time.sleep(0.05)
                if any(state != "Z" for state in group_members(child.pid).values()):
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    time.sleep(0.2)
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                until = time.monotonic() + 5.0
                while True:
                    members = group_members(child.pid)
                    for pid, state in members.items():
                        if pid != child.pid and state == "Z":
                            try:
                                os.waitpid(pid, os.WNOHANG)
                            except ChildProcessError:
                                pass  # Its still-running parent must exit first.
                    members = group_members(child.pid)
                    if all(pid == child.pid and state == "Z" for pid, state in members.items()):
                        child.wait(timeout=1)
                        break
                    if time.monotonic() >= until:
                        raise ProcessCleanupError("owned_process_group_not_drained_lock_retained")
                    time.sleep(0.05)
                require(not group_members(child.pid), "owned_process_group_still_present")
                write_new(ownership_path.with_suffix(".closed.json"),
                          {"cleanup_verified": True, "pid": child.pid, "returncode": child.returncode})
        except BaseException as exc:
            if isinstance(exc, ProcessCleanupError):
                raise
            raise ProcessCleanupError("owned_process_cleanup_uncertain_lock_retained") from exc
        finally:
            restored = libc.prctl(36, previous.value, 0, 0, 0) == 0
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            if not restored:
                raise ProcessCleanupError("cannot_restore_subreaper_state_lock_retained")
    return child.returncode


def prompt_literals(path: Path) -> tuple[str, str]:
    """Read prompt data without executing any code supplied through --source."""
    source = path.read_text(encoding="utf-8")
    nodes = ast.parse(source).body
    assignments = {node.targets[0].id: node.value for node in nodes
                   if isinstance(node, ast.Assign) and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Name)}
    if hashlib.sha256(source.encode("utf-8")).hexdigest() == PROMPTS_SHA256:
        # The builder format below is frozen to this exact official prompt file.
        system = ast.literal_eval(assignments["INTERACTIVE_SYSTEM"])
        tools = ast.literal_eval(assignments["INTERACTIVE_TOOLS"])
        tool_lines = "\n".join(json.dumps(tool, ensure_ascii=False) for tool in tools)
        prompt = f"""# Tools

You may call one or more functions to assist with the user query.

Function signatures are provided inside <tools></tools>:
<tools>
{tool_lines}
</tools>

For each function call, return a JSON object with function name and arguments inside <tool_call></tool_call>:
<tool_call>
{{"name": "<function-name>", "arguments": {{}}}}
</tool_call>"""
    else:
        # Synthetic fixtures may contain only these two literal assignments.
        # Calls, imports, raises, builders, and all other statements are refused.
        require(len(nodes) == len(assignments) == 2 and set(assignments) == {
            "INTERACTIVE_SYSTEM", "INTERACTIVE_TOOL_PROMPT"}, "unrecognized_prompt_source")
        system = ast.literal_eval(assignments["INTERACTIVE_SYSTEM"])
        prompt = ast.literal_eval(assignments["INTERACTIVE_TOOL_PROMPT"])
    require(isinstance(system, str) and isinstance(prompt, str), "invalid_prompt_literals")
    return system, prompt


def environment_identity(source: Path, game: Path, tool_format: str = "official") -> dict:
    package = source / "src" / "timely_eval"
    require(package.is_dir() and game.is_file(), "missing_source_or_game")
    upstream = {p.relative_to(source).as_posix(): hashlib.sha256(
        p.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()
        for p in sorted(package.rglob("*.py"))}
    require("src/timely_eval/interactive.py" in upstream, "missing_interactive_source")
    from timely_reproduce import tool_format_metadata
    system, tool_prompt = prompt_literals(package / "prompts.py")
    prompt_identity = tool_format_metadata(system, tool_prompt, tool_format)
    versions = {}
    for name in VERSION_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return {"upstream_commit": COMMIT, "upstream_sha256": upstream,
            **prompt_identity,
            "runner_sha256": {name: file_hash(RUNNER.parent / name) for name in RUNNER_NAMES},
            "game": game.name, "game_sha256": file_hash(game), "versions": versions,
            "timer": "upstream_static_0.99_1.01_noise", "batch_size": 1, "workers": 1,
            "official_agent_attempts": 1, "sdk_max_retries": 0, "max_tokens": 2048,
            "http_operation_timeout_s": constant(RUNNER, "HTTP_OPERATION_TIMEOUT_S"),
            "http_timeout_semantics": "per_operation_not_absolute_task_deadline",
            "transport_limits": {key: constant(RUNNER.parent / "timely_transport.py", name) for key, name in (
                ("max_message_bytes", "MAX_MESSAGE_BYTES"), ("max_request_bytes", "MAX_REQUEST_BYTES"),
                ("max_response_bytes_each_wire_decoded", "MAX_RESPONSE_BYTES"), ("max_output_tokens", "MAX_OUTPUT_TOKENS"),
                ("message_overhead_tokens_each", "MESSAGE_OVERHEAD_TOKENS"))},
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "temperature": 0.7, "thinking": "disabled",
            "jericho_seed": "3.2.1 implicit walkthrough default; not a new randomized game seed",
            "tool_delay_semantics": "upstream_virtual_accounting_no_sleep"}


def condition_identity(plan: dict, row: dict) -> dict:
    return {**plan["identity"], "paid": plan["paid"], "model": row["model"],
            "tool_durations": {name: row["tool_delay"] for name in TOOLS}}


def artifact_refs(directory: Path, steps: int, mode: str) -> dict[str, str]:
    summary = "speed_summary.json" if mode == "speed" else f"max_steps_{steps}_summary.json"
    names = ("manifest.json", "result.json", "requests.jsonl", "environment.json",
             f"official/trajectories_max_steps_{steps}.jsonl", f"official/{summary}")
    return {name: file_hash(directory / name) for name in names}


def check_refs(directory: Path, refs: dict[str, str]) -> None:
    for name, expected in refs.items():
        path = (directory / name).resolve()
        require(path.is_relative_to(directory.resolve()), "invalid_artifact_path")
        require(file_hash(path) == expected, "artifact_changed")


def episode(directory: Path, paid: bool, *, expected: dict | None = None,
            row: dict | None = None, tau: float | None = None) -> dict:
    """Verify billing closure and obtain tau's numerator from the raw trajectory."""
    manifest, result = read_json(directory / "manifest.json"), read_json(directory / "result.json")
    require(manifest.get("paid") is paid and result.get("paid") is paid, "paid_fake_mismatch")
    require(manifest.get("run_id") == directory.name == result.get("run_id"), "run_id_mismatch")
    if expected is not None:
        for key, value in expected.items():
            require(manifest.get(key) == value, f"manifest_incompatible_{key}")
    if row is not None:
        for key, value in (("mode", row["mode"]), ("steps", row["steps"]),
                           ("max_calls", row["steps"]), ("python_random_seed", row["seed"])):
            require(manifest.get(key) == value, f"manifest_incompatible_{key}")
        require(money(manifest.get("budget_cny")) == money(row["cap_cny"]), "child_cap_mismatch")
    require(manifest.get("average_duration_per_step") == tau, "tau_argument_mismatch")
    mode, steps = manifest.get("mode"), manifest.get("steps")
    require(mode in {"speed", "timed"} and type(steps) is int and steps > 0, "invalid_episode_mode")
    refs = artifact_refs(directory, steps, mode)
    events = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    require(events and events[0].get("event") == "batch_open"
            and events[-1].get("event") == "batch_close"
            and sum(e.get("event") == "batch_open" for e in events) == 1
            and sum(e.get("event") == "batch_close" for e in events) == 1, "unclosed_child_journal")
    dispatch = [e for e in events if e.get("event") == "request_dispatch"]
    complete = [e for e in events if e.get("event") == "request_complete"]
    require(not any(e.get("event") in {"request_unknown", "request_rejected"} for e in events),
            "unknown_or_rejected_request")
    ids = [e.get("request_id") for e in dispatch]
    require(ids and len(set(ids)) == len(ids) and ids == [e.get("request_id") for e in complete],
            "child_request_denominator_mismatch")
    cost = sum((money(e.get("provider_usage_peak_estimate_cny")) for e in complete), Decimal(0))
    accounting = result.get("accounting", {})
    for account in (accounting, events[-1]):
        require(account.get("calls_dispatched") == len(ids) and account.get("unknown_calls") == 0
                and account.get("active_calls") == 0 and not account.get("stop_reason"), "unresolved_child")
        require(money(account.get("reserved_cny")) == 0
                and money(account.get("spent_estimate_cny")) == cost, "child_cost_mismatch")
    cap = money(manifest["budget_cny"])
    require(cap > 0 and cap == money(CHILD_CAPS.get(manifest.get("model"), {}).get(steps, "0"))
            and cost <= cap, "child_cost_exceeds_cap")
    evidence = result.get("evidence", {})
    require(evidence.get("technical_ok") is True and result.get("failure_type") is None,
            "child_technical_failure")
    trajectories = [json.loads(line) for line in (directory / f"official/trajectories_max_steps_{steps}.jsonl")
                    .read_text(encoding="utf-8").splitlines()]
    require(len(trajectories) == 1, "trajectory_denominator_mismatch")
    trajectory = trajectories[0]
    require(len(trajectory.get("all_responses", [])) == len(ids), "response_request_denominator_mismatch")
    count, total = trajectory.get("total_steps"), trajectory.get("total_actural_time_duration")
    require(type(count) is int and 0 <= count <= steps and count == len(trajectory.get("steps", [])),
            "invalid_recorded_steps")
    require(type(total) in {int, float} and math.isfinite(total) and total >= 0, "invalid_official_time")
    virtual = trajectory.get("total_tool_duration")
    require(type(virtual) in {int, float} and math.isfinite(virtual) and virtual >= 0, "invalid_virtual_tool_time")
    tool_sum = 0.0
    for step in trajectory["steps"]:
        for tool in step.get("tool_results", []):
            duration = tool.get("duration")
            require(type(duration) in {int, float} and math.isfinite(duration) and duration >= 0
                    and duration == manifest["tool_durations"].get(tool.get("tool")), "tool_duration_mapping_mismatch")
            tool_sum += duration
    require(math.isclose(tool_sum, virtual, rel_tol=1e-9, abs_tol=1e-9), "virtual_tool_sum_mismatch")
    http_sum = 0.0
    for event in complete:
        start, end = event.get("start_monotonic_s"), event.get("end_monotonic_s")
        require(all(type(x) in {int, float} and math.isfinite(x) for x in (start, end)) and end > start,
                "invalid_http_monotonic_timing")
        http_sum += end - start
    wall = result.get("measured_evaluator_wall_s")
    require(type(wall) in {int, float} and math.isfinite(wall) and wall > 0, "invalid_evaluator_wall_time")
    official_real = total - virtual
    require(math.isfinite(official_real) and official_real > 0
            and 0.99 * http_sum - 0.1 <= official_real <= 1.01 * wall + 0.1,
            "official_clock_outside_monotonic_bounds")
    time_limit = steps * tau if mode == "timed" and tau is not None else None
    require(trajectory.get("time_limit") == time_limit == manifest.get("time_limit"), "time_limit_mismatch")
    summary = result.get("official_result")
    if mode == "timed":
        require(isinstance(summary, list) and len(summary) == 1, "invalid_timed_summary")
        summary = summary[0]
    require(isinstance(summary, dict) and summary.get("total_steps") == count
            and summary.get("total_games") == 1 and summary.get("failed_games") == 0,
            "official_summary_mismatch")
    summary_name = "speed_summary.json" if mode == "speed" else f"max_steps_{steps}_summary.json"
    require(read_json(directory / "official" / summary_name) == summary, "saved_summary_mismatch")
    expected_tau = total / count if count else 0.0
    require(math.isclose(summary.get("average_duration_per_step", -1), expected_tau, rel_tol=1e-9),
            "official_tau_mismatch")
    return {"directory": str(directory.resolve()), "run_id": directory.name,
            "paid": paid, "cost_cny": str(cost), "artifacts": refs,
            "mode": mode, "manifest": manifest, "numerator_s": total if count else 0.0,
            "denominator_steps": count, "calibration_usable": evidence.get("calibration_usable") is True}


def observed_commitment(directory: Path) -> Decimal:
    """Retain a larger observed liability, even when a child's evidence is invalid.

    The caller always applies its full child cap as a floor. Missing or torn
    artifacts never release that reservation. A provider's observed liability
    may exceed the planned cap; recording it honestly takes priority over a
    cosmetically bounded ledger, and the pilot then remains stopped.
    """
    largest = Decimal(0)
    candidates = []
    try:
        result = read_json(directory / "result.json")
        if isinstance(result, dict):
            candidates.append(result.get("accounting", {}))
    except (OSError, ValueError, PilotError):
        pass
    try:
        for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                candidates.append(json.loads(line))
            except ValueError:
                continue
    except (OSError, UnicodeError):
        pass
    for account in candidates:
        if not isinstance(account, dict):
            continue
        for value in (account.get("committed_cny"),):
            try:
                largest = max(largest, money(value))
            except PilotError:
                pass
        try:
            largest = max(largest, money(account["spent_estimate_cny"]) + money(account["reserved_cny"]))
        except (PilotError, KeyError):
            pass
    return largest


def r1_inventory() -> list[dict]:
    """Freeze all canonical historical attempts, including incomplete paid runs.

    An explicitly fake manifest is the only exclusion. A directory without a
    readable manifest may be a crashed paid attempt and therefore blocks paid
    work. Known failed attempts need closed billing, not successful gameplay.
    """
    require(R1_ROOT.is_dir(), "canonical_r1_inventory_missing")
    inventory = []
    for directory in sorted(path for path in R1_ROOT.iterdir() if path.is_dir()):
        directory = local_path(directory)
        require(directory.parent == R1_ROOT.resolve(), "r1_inventory_symlink_not_allowed")
        try:
            manifest = read_json(directory / "manifest.json")
        except (OSError, ValueError, PilotError):
            manifest = {}
        if isinstance(manifest, dict) and manifest.get("paid") is False:
            continue
        refs = {path.relative_to(directory).as_posix(): file_hash(path)
                for path in sorted(directory.rglob("*")) if path.is_file()}
        known, cost = False, max(Decimal(5), observed_commitment(directory))
        try:
            require(isinstance(manifest, dict) and manifest.get("paid") is True, "unclassified_r1_attempt")
            require(manifest.get("run_id") == directory.name, "r1_run_id_mismatch")
            require(0 < money(manifest["budget_cny"]) <= 5, "r1_cap_mismatch")
            events = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
            require(events and events[0].get("event") == "batch_open" and events[-1].get("event") == "batch_close",
                    "unclosed_r1_billing")
            dispatch = [e.get("request_id") for e in events if e.get("event") == "request_dispatch"]
            completed = [e for e in events if e.get("event") == "request_complete"]
            require(all(isinstance(value, str) and value for value in dispatch)
                    and len(dispatch) == len(set(dispatch)) and dispatch == [e.get("request_id") for e in completed]
                    and not any(e.get("event") == "request_unknown" for e in events), "unknown_r1_billing")
            billed = sum((money(e["provider_usage_peak_estimate_cny"]) for e in completed), Decimal(0))
            closing = events[-1]
            require(closing.get("calls_dispatched") == len(dispatch) and closing.get("unknown_calls") == 0
                    and closing.get("active_calls") == 0 and money(closing["reserved_cny"]) == 0
                    and money(closing["spent_estimate_cny"]) == billed, "r1_billing_mismatch")
            # A known transport rejection or unsuccessful game may still have
            # fully known costs. It is included, never selected away by quality.
            known, cost = True, billed
        except (OSError, ValueError, KeyError, TypeError, PilotError):
            pass
        inventory.append({"directory": str(directory), "run_id": directory.name, "paid": True,
                          "cost_cny": str(cost), "billing_known": known, "artifacts": refs})
    require(inventory, "no_historical_paid_r1_in_inventory")
    return inventory


def claim_paid_study(root: Path, imports: list[Path]) -> dict:
    """Called under the fixed study lock; there is one paid pilot, not one cap per plan."""
    inventory = r1_inventory()
    paths = [str(local_path(path)) for path in imports]
    require(len(paths) == len(set(paths)) and set(paths) == {item["directory"] for item in inventory},
            "explicit_imports_must_cover_complete_paid_r1_inventory")
    registry = PAID_STUDY_ROOT / "registry.json"
    record = {"schema": 1, "study": "timely-pilot-20261006", "cap_cny": "200",
              "pilot_root": str(root), "r1_inventory_root": str(R1_ROOT.resolve()),
              "imports": inventory, "historical_committed_cny": str(sum((money(x["cost_cny"]) for x in inventory), Decimal(0))),
              "blocked_unknown_history": any(not item["billing_known"] for item in inventory),
              "scope": "one R2-small plan; later extensions must reuse this study budget and require an explicit migration"}
    if registry.exists():
        existing = read_json(registry)
        require(existing.get("pilot_root") == str(root), "study_already_owns_another_paid_pilot")
        require(existing == record, "historical_inventory_changed_manual_reconciliation_required")
    else:
        write_new(registry, record)
    require(not record["blocked_unknown_history"], "unknown_prior_liability_recorded_study_blocked")
    require(money(record["historical_committed_cny"]) <= 200, "historical_liability_exceeds_study_cap")
    return record


def verify_paid_study(root: Path, plan: dict) -> None:
    registry = PAID_STUDY_ROOT / "registry.json"
    expected = plan.get("paid_study_registry")
    require(isinstance(expected, dict) and expected.get("path") == str(registry.resolve())
            and expected.get("sha256") == file_hash(registry), "paid_study_registry_changed_or_missing")
    record = read_json(registry)
    require(not record.get("blocked_unknown_history")
            and record.get("imports") == plan["imports"] == r1_inventory(),
            "study_inventory_mismatch_manual_reconciliation_required")
    verify_active_stage(root, plan)


def verify_active_stage(root: Path, plan: dict) -> None:
    """A reviewed successor must be the sole active head of the same study."""
    admission = plan.get("study_admission")
    if admission is not None:
        require(admission.get("module_sha256") == file_hash(Path(__file__).with_name("timely_study.py")),
                "study_module_changed")
    from timely_study import assert_active
    assert_active(root, plan)


def create_plan(root: Path, source: Path, game: Path, *, paid: bool = False,
                imports: list[Path] | None = None, cap_cny: str = "200", seed: int = 20261006,
                tool_format: str = "official") -> dict:
    context = exclusive(PAID_STUDY_ROOT) if paid else nullcontext()
    with context:
        return _create_plan(root, source, game, paid=paid, imports=imports, cap_cny=cap_cny, seed=seed, tool_format=tool_format)


def _create_plan(root: Path, source: Path, game: Path, *, paid: bool,
                 imports: list[Path] | None, cap_cny: str, seed: int, tool_format: str) -> dict:
    root, source, game = local_path(root), source.resolve(strict=True), game.resolve(strict=True)
    cap = money(cap_cny)
    require(0 < cap <= 200 and not root.exists(), "invalid_cap_or_existing_pilot")
    imports = imports or []
    require(bool(imports) if paid else not imports, "paid_requires_explicit_r1_import_offline_forbids_import")
    imported = claim_paid_study(root, imports)["imports"] if paid else []
    require(sum((money(item["cost_cny"]) for item in imported), Decimal(0)) <= cap, "imports_exceed_cap")
    rows, blocks = [], []
    rng = random.Random(seed)
    for phase, sizes in (("speed", (32,)), ("timed", (32, 64))):
        cells = [(model, delay, steps) for model in MODELS for delay in (0, 10) for steps in sizes]
        rng.shuffle(cells)
        for repeat in (1, 2):
            block = f"{phase}-repeat-{repeat}"
            block_rows = []
            for model, delay, steps in (cells if repeat == 1 else list(reversed(cells))):
                run_id = f"r{len(rows) + 1:03d}-{phase}-{model}-d{delay}-s{steps}-rep{repeat}"
                row = {"run_id": run_id, "block": block, "mode": phase, "model": model,
                       "tool_delay": delay, "steps": steps, "repeat": repeat,
                       "seed": seed + len(rows) + 1, "cap_cny": CHILD_CAPS[model][steps]}
                rows.append(row)
                block_rows.append(run_id)
            blocks.append({"block_id": block, "run_ids": block_rows})
    plan = {"schema": 1, "stage": "R2-small", "pilot_id": root.name, "paid": paid, "cap_cny": str(cap),
            "source": str(source), "game_path": str(game), "python": str(Path(sys.executable).resolve()),
            "python_version": sys.version,
            "runner": str(RUNNER.resolve()), "identity": environment_identity(source, game, tool_format),
            "request_contract": {"api_base": "https://api.deepseek.com", "stream": False,
                                 "thinking": {"type": "disabled"}, "max_tokens": 2048, "temperature": 0.7},
            "coordinator_sha256": file_hash(Path(__file__)), "seed": seed,
            "imports": imported, "rows": rows, "blocks": blocks,
            "calibration_repeats": 2, "calibration_steps": 32,
            "calibration_policy": "all_predeclared_speed_repeats_required; sum_time/sum_steps; matching_virtual_delay",
            "comparison_scope": "model-service-harness configurations; model-specific logical budgets; not shared wall-clock",
            "cost_interpretation": "peak-price estimate, not invoice" if paid else "synthetic accounting; zero API spend"}
    if paid:
        registry = PAID_STUDY_ROOT / "registry.json"
        plan["paid_study_registry"] = {"path": str(registry.resolve()), "sha256": file_hash(registry)}
    root.mkdir(parents=True, exist_ok=False)
    write_new(root / "plan.json", plan)
    with exclusive(root):
        ledger = Ledger(root, plan)
        ledger.append("open", {"plan_sha256": digest(plan)})
    return plan


class Ledger:
    def __init__(self, root: Path, plan: dict) -> None:
        self.path, self.plan = root / "ledger.jsonl", plan
        self.events: list[dict] = []
        self.state = {"opened": False, "reserved": {}, "started": None, "settled": {},
                      "blocks": [], "next": 0, "stopped": None, "calibrations": None, "complete": False,
                      "spent_cny": str(money(plan["study_opening"]["known_cny"]) if "study_opening" in plan else
                                       sum((money(x["cost_cny"]) for x in plan["imports"]), Decimal(0)))}
        if self.path.exists():
            raw = self.path.read_bytes()
            require(raw.endswith(b"\n"), "torn_ledger_requires_operator_inspection")
            for line in raw.splitlines():
                event = json.loads(line)
                self._validate_event(event)
                self._apply(event["event"], event["data"])
                self.events.append(event)

    def _validate_event(self, event: dict) -> None:
        payload = {key: value for key, value in event.items() if key != "sha256"}
        require(event.get("seq") == len(self.events) and event.get("previous_sha256") ==
                (self.events[-1]["sha256"] if self.events else None)
                and digest(payload) == event.get("sha256"), "invalid_ledger_chain")

    def committed(self) -> Decimal:
        carried = sum((money(item["held_cny"]) for item in self.plan.get("study_opening", {}).get("liabilities", [])), Decimal(0))
        return money(self.state["spent_cny"]) + carried + sum(map(money, self.state["reserved"].values()), Decimal(0))

    def _apply(self, event: str, data: dict) -> None:
        state, plan = self.state, self.plan
        require(not state["stopped"] and not state["complete"], "pilot_is_terminal")
        if event == "open":
            require(not state["opened"] and data == {"plan_sha256": digest(plan)}, "plan_hash_mismatch")
            state["opened"] = True
            return
        require(state["opened"], "missing_open_event")
        if event == "reserve_block":
            block = plan["blocks"][len(state["blocks"])]
            require(data == block and not state["reserved"] and state["started"] is None, "invalid_block_order")
            ids = block["run_ids"]
            require(plan["rows"][state["next"]]["run_id"] == ids[0], "invalid_block_start")
            reserved = {r["run_id"]: r["cap_cny"] for r in plan["rows"] if r["run_id"] in ids}
            require(self.committed() + sum(map(money, reserved.values()), Decimal(0)) <= money(plan["cap_cny"]),
                    "whole_balanced_block_does_not_fit")
            state["reserved"].update(reserved)
            state["blocks"].append(block["block_id"])
        elif event == "start":
            run_id = data["run_id"]
            require(state["started"] is None and run_id in state["reserved"]
                    and run_id == plan["rows"][state["next"]]["run_id"], "invalid_run_order")
            state["started"] = run_id
        elif event == "settle":
            run_id = data["run_id"]
            require(state["started"] == run_id and money(data["cost_cny"]) <= money(state["reserved"][run_id]),
                    "invalid_settlement")
            state["spent_cny"] = str(money(state["spent_cny"]) + money(data["cost_cny"]))
            del state["reserved"][run_id]
            state["settled"][run_id] = data
            state["started"] = None
            state["next"] += 1
        elif event == "calibrations":
            require(state["calibrations"] is None and state["next"] == 8, "invalid_calibration_boundary")
            state["calibrations"] = data
        elif event == "stop":
            if state["started"] is not None:
                run_id = state["started"]
                state["reserved"][run_id] = str(max(money(state["reserved"][run_id]),
                                                   money(data.get("observed_commitment_cny", "0"))))
            state["stopped"] = data["reason"]
        elif event == "complete":
            require(state["next"] == len(plan["rows"]) and not state["reserved"], "incomplete_plan")
            state["complete"] = True
        else:
            raise PilotError("unknown_ledger_event")

    def append(self, event: str, data: dict) -> None:
        old = json.loads(json.dumps(self.state))
        try:
            self._apply(event, data)
            payload = {"seq": len(self.events), "previous_sha256": self.events[-1]["sha256"] if self.events else None,
                       "event": event, "data": data, "utc": datetime.now(timezone.utc).isoformat()}
            record = {**payload, "sha256": digest(payload)}
            with self.path.open("ab") as stream:
                stream.write(canonical(record) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.events.append(record)
        except BaseException:
            self.state = old
            raise


def calibration_documents(root: Path, plan: dict, ledger: Ledger) -> dict[str, dict]:
    documents = {}
    for model in MODELS:
        for delay in (0, 10):
            rows = [r for r in plan["rows"] if r["mode"] == "speed" and r["model"] == model and r["tool_delay"] == delay]
            require(len(rows) == plan["calibration_repeats"], "missing_planned_calibration_repeat")
            sources = []
            for row in rows:
                saved = ledger.state["settled"].get(row["run_id"])
                require(saved is not None, "calibration_not_complete")
                directory = root / "runs" / row["run_id"]
                check_refs(directory, saved["artifacts"])
                item = episode(directory, plan["paid"], expected=condition_identity(plan, row), row=row)
                require(item["calibration_usable"] and item["denominator_steps"] > 0, "calibration_not_usable")
                sources.append({key: item[key] for key in ("directory", "run_id", "artifacts", "numerator_s", "denominator_steps")})
            numerator = sum(item["numerator_s"] for item in sources)
            denominator = sum(item["denominator_steps"] for item in sources)
            tau = numerator / denominator
            require(math.isfinite(tau) and 0 < tau <= 600, "calibration_tau_out_of_range")
            key = f"{model}-d{delay}"
            documents[key] = {"schema": 1, "plan_sha256": digest(plan), "identity": condition_identity(plan, rows[0]),
                              "source_mode": "speed", "sources": sources, "numerator_official_time_s": numerator,
                              "denominator_recorded_steps": denominator, "tau": tau,
                              "aggregation": "sum_official_time/sum_recorded_steps"}
    return documents


def ensure_calibrations(root: Path, plan: dict, ledger: Ledger) -> dict[str, dict]:
    documents = calibration_documents(root, plan, ledger)
    refs = {}
    for key, document in documents.items():
        path = root / "calibrations" / f"{key}.json"
        if path.exists():
            require(read_json(path) == document, "calibration_document_changed")
        else:
            require(ledger.state["calibrations"] is None, "calibration_document_missing")
            write_new(path, document)
        refs[key] = {"path": str(path), "sha256": file_hash(path)}
    if ledger.state["calibrations"] is None:
        ledger.append("calibrations", refs)
    else:
        require(ledger.state["calibrations"] == refs, "calibration_hash_mismatch")
    return documents


def run_pilot(root: Path, *, execute_offline: bool = False, execute_paid: bool = False,
              env_file: Path | None = None, max_runs: int | None = None,
              fixture_prefix: list[str] | None = None, fixture_timeout_s: float | None = None) -> dict:
    bound = "study_admission" in read_json(local_path(root) / "plan.json")
    context = exclusive(PAID_STUDY_ROOT) if execute_paid or (execute_offline and bound) else nullcontext()
    with context:
        return _run_pilot(root, execute_offline=execute_offline, execute_paid=execute_paid,
                          env_file=env_file, max_runs=max_runs, fixture_prefix=fixture_prefix,
                          fixture_timeout_s=fixture_timeout_s)


def _run_pilot(root: Path, *, execute_offline: bool, execute_paid: bool,
               env_file: Path | None, max_runs: int | None,
               fixture_prefix: list[str] | None, fixture_timeout_s: float | None) -> dict:
    root = local_path(root)
    plan = read_json(root / "plan.json")
    require(not (execute_offline and execute_paid), "conflicting_execution_modes")
    if not execute_offline and not execute_paid:
        ledger = Ledger(root, plan)
        return {"status": "dry", "paid": plan["paid"], "planned_runs": len(plan["rows"]),
                "settled_runs": ledger.state["next"], "committed_cny": str(ledger.committed()),
                "cap_cny": plan["cap_cny"], "stop_reason": ledger.state["stopped"]}
    require(plan["paid"] is execute_paid, "paid_fake_mismatch")
    require(sys.platform == "linux", "owned_process_tree_requires_linux_wsl")
    require(not execute_paid or (env_file is not None and fixture_prefix is None and fixture_timeout_s is None),
            "paid_requires_env_and_fixed_runner")
    require(fixture_timeout_s is None or (fixture_prefix is not None and fixture_timeout_s > 0), "invalid_fixture_timeout")
    if execute_paid:
        verify_paid_study(root, plan)
    elif "study_admission" in plan:
        verify_active_stage(root, plan)
    require(max_runs is None or (type(max_runs) is int and max_runs > 0), "invalid_max_runs")
    with exclusive(root):
        ledger = Ledger(root, plan)
        require(ledger.state["opened"], "missing_ledger")
        require(not ledger.state["stopped"], "pilot_stopped_requires_operator_inspection")
        require(ledger.state["started"] is None, "unsettled_child_reservation_retained")
        require(plan["python"] == str(Path(sys.executable).resolve()), "interpreter_changed")
        require(plan["python_version"] == sys.version, "python_version_changed")
        require(plan["coordinator_sha256"] == file_hash(Path(__file__)), "coordinator_changed")
        require(plan["runner"] == str(RUNNER.resolve()), "runner_path_changed")
        for item in plan["imports"]:
            check_refs(Path(item["directory"]), item["artifacts"])
        for run_id, item in ledger.state["settled"].items():
            check_refs(root / "runs" / run_id, item["artifacts"])
        for event in ledger.events:
            if event["event"] == "start":
                data = event["data"]
                require(file_hash(root / "bindings" / f"{data['run_id']}.json") == data["binding_sha256"],
                        "run_binding_changed")
        if ledger.state["calibrations"] is not None:
            # Includes completed resumes, whose execution loop has no next row.
            ensure_calibrations(root, plan, ledger)
        done = 0
        while ledger.state["next"] < len(plan["rows"]):
            require(environment_identity(Path(plan["source"]), Path(plan["game_path"]), plan["identity"]["tool_format"]) == plan["identity"],
                    "execution_environment_changed")
            row = plan["rows"][ledger.state["next"]]
            documents = ensure_calibrations(root, plan, ledger) if row["mode"] == "timed" else {}
            if row["block"] not in ledger.state["blocks"]:
                ledger.append("reserve_block", next(b for b in plan["blocks"] if b["block_id"] == row["block"]))
            key = f"{row['model']}-d{row['tool_delay']}"
            tau = documents[key]["tau"] if documents else None
            calibration_ref = ledger.state["calibrations"][key] if documents else None
            output = root / "runs" / row["run_id"]
            require(not output.exists(), "unstarted_child_output_already_exists")
            binding = {"schema": 1, "pilot_id": plan["pilot_id"], "plan_sha256": digest(plan),
                       "row": row, "calibration": calibration_ref, "average_duration_per_step": tau,
                       "time_limit": row["steps"] * tau if tau is not None else None}
            binding_path = root / "bindings" / f"{row['run_id']}.json"
            if binding_path.exists():
                require(read_json(binding_path) == binding, "binding_changed")
            else:
                write_new(binding_path, binding)
            command = list(fixture_prefix) if fixture_prefix else [sys.executable, "-B", str(RUNNER)]
            command += ["--source", plan["source"], "--game", plan["game_path"], "--output", str(output),
                        "--model", row["model"], "--mode", row["mode"], "--steps", str(row["steps"]),
                        "--tool-delay", str(row["tool_delay"]), "--seed", str(row["seed"]),
                        "--tool-format", plan["identity"]["tool_format"],
                        "--max-calls", str(row["steps"]), "--budget-cny", row["cap_cny"],
                        "--max-tokens", str(plan["identity"]["max_tokens"]), "--temperature", str(plan["identity"]["temperature"])]
            if tau is not None:
                command += ["--average-duration-per-step", repr(tau)]
            if execute_paid:
                command += ["--execute-paid", "--env-file", str(env_file.resolve(strict=True))]
            # The credential path/child output never enters this coordinator's log.
            ledger.append("start", {"run_id": row["run_id"], "binding_sha256": file_hash(binding_path)})
            try:
                returncode = run_owned_child(command, timeout=fixture_timeout_s or row["steps"] * 65 + 120,
                                             ownership_path=root / "processes" / f"{row['run_id']}.json")
                require(returncode == 0, "child_nonzero_exit")
                item = episode(output, plan["paid"], expected=condition_identity(plan, row), row=row, tau=tau)
                ledger.append("settle", {key: item[key] for key in ("run_id", "cost_cny", "artifacts", "calibration_usable")})
                if row["mode"] == "speed" and not item["calibration_usable"]:
                    ledger.append("stop", {"reason": "calibration_not_usable"})
                    raise PilotError("calibration_not_usable")
            except BaseException as exc:
                try:
                    # A signal can arrive after fsync but before append updates
                    # memory. Recover the durable sequence before adding stop;
                    # a torn journal fails closed here without another write.
                    ledger = Ledger(root, plan)
                    if not ledger.state["stopped"]:
                        ledger.append("stop", {"reason": "child_unresolved_full_reservation_retained",
                                               "error_type": type(exc).__name__,
                                               "observed_commitment_cny": str(observed_commitment(output))})
                except BaseException:
                    if isinstance(exc, ProcessCleanupError):
                        raise exc  # Never release locks after uncertain process cleanup.
                    raise
                raise
            done += 1
            if max_runs is not None and done >= max_runs:
                break
        if ledger.state["next"] == len(plan["rows"]) and not ledger.state["complete"]:
            ledger.append("complete", {})
        return {"status": "complete" if ledger.state["complete"] else "clean_stop",
                "stage": plan["stage"], "four_game_R2_complete": False,
                "paid": plan["paid"], "settled_runs": ledger.state["next"], "planned_runs": len(plan["rows"]),
                "spent_estimate_cny": ledger.state["spent_cny"], "committed_cny": str(ledger.committed()),
                "cost_interpretation": plan["cost_interpretation"], "paper_result_reproduced": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-plan")
    create.add_argument("--pilot-root", type=Path, required=True)
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--game", type=Path, required=True)
    create.add_argument("--plan-paid", action="store_true")
    create.add_argument("--import-r1", type=Path, action="append", default=[])
    create.add_argument("--cap-cny", default="200")
    create.add_argument("--seed", type=int, default=20261006)
    create.add_argument("--tool-format", choices=("official", "single-json-v1", "single-json-v2"), default="official")
    run = commands.add_parser("run")
    run.add_argument("--pilot-root", type=Path, required=True)
    modes = run.add_mutually_exclusive_group()
    modes.add_argument("--execute-offline", action="store_true")
    modes.add_argument("--execute-paid", action="store_true")
    run.add_argument("--env-file", type=Path)
    run.add_argument("--max-runs", type=int, help="Clean stop after this many children; does not change the plan")
    args = parser.parse_args()
    try:
        if args.command == "create-plan":
            plan = create_plan(args.pilot_root, args.source, args.game, paid=args.plan_paid,
                               imports=args.import_r1, cap_cny=args.cap_cny, seed=args.seed, tool_format=args.tool_format)
            result = {"status": "plan_created", "paid": plan["paid"], "planned_runs": len(plan["rows"]),
                      "plan_sha256": digest(plan), "cap_cny": plan["cap_cny"], "model_calls": 0}
        else:
            result = run_pilot(args.pilot_root, execute_offline=args.execute_offline,
                               execute_paid=args.execute_paid, env_file=args.env_file, max_runs=args.max_runs)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "stopped", "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, PilotError) else "inspect_local_evidence"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
