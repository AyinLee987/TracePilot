"""Fixed development trajectories with online delivery cutoffs and owned drain.

No hidden evaluation is performed by this executor. A paid run requires the
study's live admission; offline overrides are rejected on the paid branch.
"""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
import math
from pathlib import Path
import random
import signal
import sys
import time
import uuid

import httpx
import coding_pilot as pilot

coding, budget = pilot.coding, pilot.budget
ROOT = Path(__file__).resolve().parents[1]
TASKS = (55, 32, 7, 56, 16, 99, 18, 31)
POLICIES = ("resample", "repair")
MAX_ROUNDS = 64
REQUEST_CAP = Decimal("0.20")
BATCH_CAP = "120"
FEEDBACK_CAP = 12_288
MESSAGE_CAP = 32_768
# An outer owner must allow this grace before escalating cancellation. The
# helper gets 75s to close, then at most two bounded 30s Docker recovery calls.
OUTER_SIGINT_GRACE_S = 180
PUBLIC_SUPERVISOR_TIMEOUT_S = 240
PUBLIC_CLEANUP_TIMEOUT_S = 75
WORKER = Path(__file__).with_name("coding_deadline_worker.py")
RUNTIME_FILES = ("coding_deadline.py", "coding_deadline_worker.py", "coding_pilot.py",
                 "coding_tasks.py", "coding_environment_smoke.py", "timely_transport.py", "coding_deadline_calibration.py")
SEED_ROOT = ROOT / ".local/coding-extension16-paid-20261006"
SEED_RUN = "draft-11-he99-deepseek-flash-rep2"
SEED_CODE_SHA = "04e08559ca23e02df18bf9b365c7d485268c20a73fd21aa7d8d0f62b55b787c4"
SEED_PUBLIC_SHA = "e78caa3a76f6b89cd1ed07726be3f5ade42533beddd373d8b8c875d1e131023e"
SYSTEM = """Solve the supplied Python programming task according to its public specification.
Return a complete Python file defining the named function, or its complete
function definition. Function-only answers receive only the imports/helpers
preceding that definition in the published prompt. Return raw Python or one
python/untagged fenced block, with no surrounding prose. Preserve the named
function and signature. If a previous candidate and public diagnostic are
provided, use only that public information to produce your next complete
candidate. No tool calls are available in your response."""


def identities() -> dict:
    return {name: coding.sandbox.sha((ROOT / "research" / name).read_bytes()) for name in RUNTIME_FILES}


def rows() -> list[dict]:
    rng = random.Random(20261006)
    result = []
    for cohort, numbers in (("native", TASKS), ("common", (99,))):
        blocks = {}
        for number in numbers:
            block = [(model, policy, delay) for model in pilot.MODELS for policy in POLICIES for delay in (0, 1)]
            rng.shuffle(block)
            blocks[number] = block
        for repeat in (1, 2):
            for number in numbers:
                block = blocks[number] if repeat == 1 else list(reversed(blocks[number]))
                for model, policy, delay in block:
                    result.append({"run_id": f"{cohort}-{len(result)+1:03d}-he{number}-{model}-{policy}-delay{delay}-rep{repeat}",
                        "cohort": cohort, "task_id": f"HumanEval/{number}", "number": number,
                        "model": model, "policy": policy, "delay_s": delay, "repeat": repeat})
    return result


def make_plan(deadlines_s: list[float], calibration_ref: dict, *, paid: bool = False,
              max_rounds: int = MAX_ROUNDS) -> dict:
    if (not isinstance(deadlines_s, list) or len(deadlines_s) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in deadlines_s)
            or not 0 < deadlines_s[0] < deadlines_s[1] <= 3600):
        raise ValueError("two_ordered_finite_positive_deadlines_required")
    if not isinstance(calibration_ref, dict):
        raise ValueError("calibration_reference_required")
    if type(max_rounds) is not int or not 64 <= max_rounds <= 100000:
        raise ValueError("invalid_safety_round_guard")
    if paid and calibration_ref.get("fixture_only"):
        raise pilot.PaidNotAdmitted("paid_calibration_cannot_be_fixture")
    return {"schema": 1, "scope": "R3-development-common-delivery-deadlines", "paid": paid,
        "deadlines_s": deadlines_s, "calibration_ref": calibration_ref, "trajectories": rows(),
        "denominator": 144, "native_denominator": 128, "common_denominator": 16,
        "snapshot_denominator": 288, "max_rounds": max_rounds, "per_request_cap_cny": str(REQUEST_CAP),
        "batch_cap_cny": BATCH_CAP, "scheduling_seed": 20261006, "heldout_used": False,
        "known_settlement_stop_reasons": [None, "budget_censored", "public_infrastructure_failure", "request_or_context_failure"],
        "request_contract": {"endpoint": pilot.ENDPOINT, "temperature": 0.7, "max_tokens": 2048,
            "thinking": {"type": "disabled"}, "stream": False, "n": 1, "retries": 0,
            "http_operation_timeout_s": 60, "whole_request_timeout_s": 65},
        "system_prompt": SYSTEM, "parse_policy": pilot.PARSER_POLICY,
        "feedback_cap_bytes": FEEDBACK_CAP, "message_cap_bytes": MESSAGE_CAP,
        "selector": "highest public passed; ties earliest eligible; equality at cutoff is late",
        "delay_policy": "actual wait after parsed public result and cleanup; no tool/delay for parse failure",
        "deadline_policy": "online immutable prefix snapshots; final cutoff stops dispatch; bounded in-flight drain",
        "public_worker_timeout_s": 30, "public_supervisor_timeout_s": 240,
        "seed_ref": {"parent_root": str(SEED_ROOT), "run_id": SEED_RUN,
                     "candidate_sha256": SEED_CODE_SHA, "public_summary_sha256": SEED_PUBLIC_SHA},
        "code_sha256": identities(), "runtime_identity": pilot.runtime_identity(require_wsl=paid)}


def validate_plan(plan: dict) -> None:
    expected = make_plan(plan["deadlines_s"], plan["calibration_ref"], paid=plan["paid"], max_rounds=plan["max_rounds"])
    for name, value in expected.items():
        if plan.get(name) != value:
            raise ValueError("frozen_deadline_plan_changed:" + name)


def load_seed() -> tuple[str, dict]:
    directory = SEED_ROOT / "drafts" / SEED_RUN
    raw = (directory / "candidate.py").read_bytes()
    public = (directory / "public/public-result.json").read_bytes()
    summary = (directory / "public-summary.json").read_bytes()
    if (coding.sandbox.sha(raw) != SEED_CODE_SHA or coding.sandbox.sha(public) != SEED_PUBLIC_SHA
            or coding.sandbox.sha(summary) != SEED_PUBLIC_SHA):
        raise ValueError("frozen_common_seed_changed")
    result = json.loads(public)
    if (result["visibility"] != "public" or result["task_id"] != "HumanEval/99" or result["passed"] != 3
            or result["total"] != 4 or result["status"] != "fail"):
        raise ValueError("common_seed_public_contract_changed")
    return raw.decode("utf-8"), result


class _StaticInputs:
    """In-process preflight result; credentials are never serialized or repr'd."""
    def __init__(self, plan, tasks, seed, image_id, credential):
        self.plan_sha256 = pilot.digest(plan)
        self.tasks, self.seed, self.image_id = tasks, seed, image_id
        self.credential = credential


def static_preflight(output: Path, plan: dict, *, env_file: Path | None = None,
                     real_public: bool = True) -> _StaticInputs:
    """Validate static inputs before opening the study's one-shot reservation."""
    started = time.monotonic()
    validate_plan(plan)
    output.mkdir(parents=True, exist_ok=True)
    directory = output / ("static-preflight-" + uuid.uuid4().hex)
    directory.mkdir()
    evidence = {"status": "failed", "paid": plan["paid"], "provider_calls": 0,
                "plan_sha256": pilot.digest(plan), "real_public": real_public}
    try:
        credential = None
        if plan["paid"]:
            if not real_public:
                raise pilot.PaidNotAdmitted("paid_preflight_requires_real_public_environment")
            if env_file is None or not env_file.is_file():
                raise pilot.PaidNotAdmitted("explicit_env_file_required")
            from dotenv import dotenv_values
            credential = dotenv_values(env_file, interpolate=False).get("DEEPSEEK_API_KEY")
            if (not isinstance(credential, str) or not credential or len(credential) > 4096
                    or any(c in credential for c in "\r\n")):
                raise pilot.PaidNotAdmitted("invalid_explicit_credential")
        tasks, provenance = coding.load_tasks()
        if "provenance_sha256" in plan and plan["provenance_sha256"] != pilot.digest(provenance):
            raise ValueError("deadline_provenance_changed")
        seed = load_seed()
        image_id = "offline-fixture-no-container"
        if real_public:
            environment = {}
            coding.sandbox.verify_daemon(directory, environment)
            pilot.dump(directory / "environment.json", environment)
            image_id = coding.existing_image(directory)
        evidence.update(status="passed", provenance_sha256=pilot.digest(provenance), image_id=image_id)
        return _StaticInputs(plan, tasks, seed, image_id, credential)
    except BaseException as exc:
        evidence["error_type"] = type(exc).__name__
        raise
    finally:
        evidence["wall_s"] = time.monotonic() - started
        pilot.dump(directory / "preflight.json", evidence)


def feedback_projection(result: dict) -> dict:
    projected = {key: result[key] for key in ("status", "reason", "passed", "total") if key in result}
    if "diagnostic" in result:
        projected["diagnostic"] = result["diagnostic"]
    projected["checks"] = []
    for check in result.get("checks", []):
        item = {}
        for key in ("arguments", "expected", "observed", "passed", "error", "error_type"):
            if key not in check:
                continue
            encoded = json.dumps(check[key], ensure_ascii=True, allow_nan=False)
            item[key] = check[key] if len(encoded) <= 1024 else {"truncated": True, "json_prefix": encoded[:1024]}
        projected["checks"].append(item)
    if len(json.dumps(projected, ensure_ascii=True).encode()) > FEEDBACK_CAP:
        raise ValueError("feedback_projection_limit")
    return projected


def request_body(row: dict, task: dict, feedback: dict | None) -> dict:
    visible = coding.visible_task(task)
    content = f"Task: {visible['task_id']}\nEntry point: {visible['entry_point']}\n\n{visible['prompt']}"
    if row["policy"] == "repair" and feedback is not None:
        content += "\nPrevious candidate and PUBLIC diagnostic:\n" + json.dumps(feedback, ensure_ascii=True, allow_nan=False)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > MESSAGE_CAP:
        raise ValueError("message_limit_no_code_truncation")
    return {"model": row["model"], "messages": messages, "stream": False, "thinking": {"type": "disabled"},
            "max_tokens": 2048, "temperature": 0.7, "n": 1}


async def _bounded_read(stream, cap: int) -> bytes:
    data = bytearray()
    while True:
        part = await stream.read(min(65536, cap - len(data) + 1))
        if not part:
            return bytes(data)
        if len(data) + len(part) > cap:
            raise RuntimeError("trusted_public_helper_output_limit")
        data.extend(part)


async def _recovery_command(args: list[str]) -> dict:
    """Bound, own, and reap each exact Docker recovery client."""
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=coding.sandbox.process_env(), start_new_session=True)
    readers = [asyncio.create_task(_bounded_read(process.stdout, 65536)),
               asyncio.create_task(_bounded_read(process.stderr, 65536))]
    try:
        await asyncio.wait_for(process.wait(), 30)
        stdout, stderr = await asyncio.gather(*readers)
        return {"returncode": process.returncode, "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace")}
    finally:
        if process.returncode is None:
            import os
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await process.wait()
        await asyncio.gather(*readers, return_exceptions=True)


async def public_worker(task: dict, source: str, image_id: str, output: Path) -> dict:
    """Keep ownership until the helper and its exact Docker resources close."""
    output.mkdir()
    visible = {key: task[key] for key in ("task_id", "entry_point", "prompt")}
    pilot.dump(output / "input.json", {"task": visible, "source": source,
        "source_sha256": coding.sandbox.sha(source.encode()), "image_id": image_id})
    process = None
    readers = []
    cancellation = None
    error = None
    outcome = {"finished": False}
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", str(WORKER),
            "--input", str(output / "input.json"), "--output", str(output),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=coding.sandbox.process_env(), start_new_session=True)
        readers = [asyncio.create_task(_bounded_read(process.stdout, 65536)),
                   asyncio.create_task(_bounded_read(process.stderr, 65536))]
        await asyncio.wait_for(process.wait(), timeout=PUBLIC_SUPERVISOR_TIMEOUT_S)
    except BaseException as exc:
        error = type(exc).__name__
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            cancellation = exc
    finally:
        if process is not None and process.returncode is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), PUBLIC_CLEANUP_TIMEOUT_S)
            except BaseException:
                # Only the dedicated helper group belongs to this invocation.
                import os
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        for label, reader in zip(("stdout", "stderr"), readers):
            try:
                data = await reader
                (output / ("helper-" + label + ".txt")).write_bytes(data)
            except Exception as exc:
                error = type(exc).__name__
        receipt = {"closed": False, "worker_reaped": process is None or process.returncode is not None,
            "started": process is not None, "worker_pid": process.pid if process else None,
            "worker_exit_code": process.returncode if process else None,
            "containers_removed": True, "containers": [], "error_type": error}
        # Even a killed helper leaves the pre-create receipt. Recover only its
        # precise UUID name, never an unrelated container or a broad prefix.
        for path in output.glob("check/*/create-command.json"):
            args = json.loads(path.read_text())
            name = args[args.index("--name") + 1]
            if not name.startswith("tracepilot-coding-") or len(name) != len("tracepilot-coding-") + 32:
                receipt["containers_removed"] = False
                continue
            execution_path = path.parent / "execution.json"
            execution = json.loads(execution_path.read_text()) if execution_path.exists() else None
            removed = bool(execution and execution.get("cleanup", {}).get("removed")
                           and execution["cleanup"].get("remove_exit_code") == 0)
            if not removed:
                # These bounded operations happen only after helper draining;
                # no deadline result may be selected from this recovery path.
                try:
                    rm = await _recovery_command(["docker", "rm", "--force", name])
                    remaining = await _recovery_command(
                        ["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"])
                    removed = remaining["returncode"] == 0 and not remaining["stdout"].strip()
                    receipt["recovery"] = {"remove_exit_code": rm["returncode"]}
                except BaseException as exc:
                    receipt["recovery_error_type"] = type(exc).__name__
                    removed = False
                    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                        cancellation = exc
            receipt["containers"].append({"name": name, "removed": removed,
                "worker_cli_reaped": bool(execution and execution.get("worker_cli_reaped"))})
            receipt["containers_removed"] &= removed
        receipt["closed"] = receipt["worker_reaped"] and receipt["containers_removed"]
        pilot.dump(output / "public-resource-closed.json", receipt)
        if (output / "checker-exit.json").exists():
            outcome = json.loads((output / "checker-exit.json").read_text())
    if cancellation is not None:
        raise cancellation
    if not receipt["closed"] or not outcome["finished"] or error:
        return {"status": "infra", "reason": "public_helper_failed", "passed": 0, "total": 0}
    return outcome["result"]


def _candidate_ref(attempt: dict) -> dict:
    return {key: attempt[key] for key in ("candidate_id", "code_sha256", "candidate_path", "public_path",
                                         "public_passed", "public_total", "available_at_s")}


async def run_trajectory(output: Path, row: dict, task: dict, plan: dict, client: httpx.AsyncClient,
                         transport, admission, seed, checker, image_id: str) -> tuple[dict, str | None]:
    ready = time.monotonic()
    directory = output / "trajectories" / row["run_id"]
    directory.mkdir(parents=True)
    record = {**row, "status": "running", "attempts": [], "snapshots": [],
              "baseline": {"attempt": 1, "outcome": "not_started", "candidate": None}, "first_eligible": None,
              "censored": False, "stop_reason": None}
    eligible = []
    feedback = None
    if row["cohort"] == "common":
        source, result = seed
        eligible.append({"candidate_id": "seed", "code_sha256": SEED_CODE_SHA,
            "candidate_path": "common-seed.py", "public_path": "common-seed-public.json",
            "public_passed": result["passed"], "public_total": result["total"], "available_at_s": 0.0})
        if row["policy"] == "repair":
            feedback = {"code": source, "public": feedback_projection(result)}
    record["task_ready_monotonic_s"] = ready
    max_deadline = ready + plan["deadlines_s"][-1]
    snapshot_map = {}

    def freeze(index, *, stopped=False):
        if index in snapshot_map:
            return
        cutoff = plan["deadlines_s"][index]
        candidates = [c for c in eligible if c["available_at_s"] < cutoff]
        selected = min(candidates, key=lambda c: (-c["public_passed"], c["available_at_s"])) if candidates else None
        now = time.monotonic() - ready
        snapshot = {"index": index, "deadline_s": cutoff, "selected": selected,
            "status": "stopped_before_cutoff" if stopped and now < cutoff else "frozen",
            "callback_at_s": now, "scheduling_lag_s": max(0, now - cutoff)}
        path = directory / f"snapshot-{index+1}.json"
        pilot.dump(path, snapshot)
        snapshot_map[index] = {**snapshot, "path": str(path.relative_to(output)),
                               "sha256": coding.sandbox.sha(path.read_bytes()),
                               "persisted_at_s": time.monotonic() - ready}

    async def clock():
        for index, cutoff in enumerate(plan["deadlines_s"]):
            await asyncio.sleep(max(0, ready + cutoff - time.monotonic()))
            freeze(index)

    timer = asyncio.create_task(clock())
    round_start = time.monotonic()
    record["setup_once_s"] = round_start - ready
    batch_stop = None
    cancellation = None
    try:
        for number in range(1, plan["max_rounds"] + 1):
            if time.monotonic() >= max_deadline:
                break
            attempt_dir = directory / f"attempt-{number:02d}"
            attempt_dir.mkdir()
            attempt = {"candidate_id": f"attempt-{number:02d}", "status": "started",
                "started_at_s": round_start - ready, "public_wall_s": 0.0, "checker_wall_s": 0.0,
                "http_wall_s": 0.0, "injected_delay_actual_s": 0.0}
            record["attempts"].append(attempt)
            try:
                if admission is not None:
                    admission.assert_live(output, plan)
                payload = request_body(row, task, feedback)
                request = client.build_request("POST", pilot.ENDPOINT, json=payload)
                preview = await transport.preview_reservation(request)
                attempt["reservation_cny"] = preview["reservation_cny"]
                available = Decimal(transport.snapshot()["batch_budget_cny"]) - Decimal(transport.snapshot()["committed_cny"])
                if Decimal(preview["reservation_cny"]) > REQUEST_CAP:
                    record.update(censored=True, stop_reason="request_guard_censored", guard_reason="per_request_cap")
                    attempt.update(status="request_guard_censored", guard_reason="per_request_cap")
                    break
                if Decimal(preview["reservation_cny"]) > available:
                    record.update(censored=True, stop_reason="budget_censored")
                    attempt["status"] = "budget_censored"
                    batch_stop = "budget_censored"
                    break
                pilot.dump(attempt_dir / "request.json", payload)
                if time.monotonic() >= max_deadline:
                    attempt["status"] = "deadline_before_dispatch"
                    break
                attempt["dispatch_at_s"] = time.monotonic() - ready
                http_start = time.monotonic()
                with budget.run_context(run_id=row["run_id"], case_id=attempt["candidate_id"],
                    task_id=row["task_id"], model=row["model"], repeat=row["repeat"], phase=row["cohort"],
                    condition=row["policy"] + "/delay-" + str(row["delay_s"]), deadline_s=plan["deadlines_s"][-1]):
                    response = await asyncio.wait_for(client.send(request), timeout=65)
                received = time.monotonic()
                attempt.update(http_wall_s=received - http_start, response_received_at_s=received - ready)
                (attempt_dir / "response.raw.json").write_bytes(response.content)
                body = response.json()
                attempt["usage"] = body["usage"]
                attempt["cache_usage"] = {k: body["usage"][k] for k in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}
                if received >= max_deadline:
                    attempt["status"] = "late_response_accounted_only"
                    break
                parsed = pilot.parse_candidate(body, task)
                attempt["parse_completed_at_s"] = time.monotonic() - ready
                attempt["parse"] = {k: v for k, v in parsed.items() if k != "code"}
                if parsed["status"] != "parsed":
                    attempt["status"] = parsed["status"]
                    feedback = {"format_diagnostic": "Return one complete synchronous Python function or file in the fixed format."}
                    continue
                source = parsed["code"]
                candidate_path = attempt_dir / "candidate.py"
                candidate_path.write_text(source, encoding="utf-8", newline="\n")
                attempt.update(code_sha256=parsed["code_sha256"], candidate_path=str(candidate_path.relative_to(output)))
                if time.monotonic() >= max_deadline:
                    attempt["status"] = "late_parse_no_tool"
                    break
                public_start = time.monotonic()
                attempt["public_started_at_s"] = public_start - ready
                resource_path = attempt_dir / "public/public-resource-closed.json"
                attempt["public_resource_path"] = str(resource_path.relative_to(output))
                result = await checker(task, source, image_id, attempt_dir / "public")
                public_end = time.monotonic()
                attempt.update(public_wall_s=public_end - public_start, public_returned_at_s=public_end - ready,
                               checker_wall_s=result.get("wall_s", 0.0), public_status=result["status"])
                resource = json.loads(resource_path.read_text())
                if not all(resource.get(k) is True for k in ("closed", "worker_reaped", "containers_removed")):
                    result = {"status": "infra", "reason": "public_resource_unclosed", "passed": 0, "total": 0}
                if result["status"] == "infra":
                    attempt["status"] = "public_infrastructure_failure"
                    batch_stop = "public_infrastructure_failure"
                    break
                if public_end >= max_deadline:
                    attempt["status"] = "late_public_result"
                    break
                delay_start = time.monotonic()
                await asyncio.sleep(row["delay_s"])
                attempt["injected_delay_actual_s"] = time.monotonic() - delay_start
                attempt["delay_released_at_s"] = time.monotonic() - ready
                public_path = attempt_dir / "public-feedback.json"
                pilot.dump(public_path, result)
                attempt.update(public_path=str(public_path.relative_to(output)), public_passed=result["passed"],
                               public_total=result["total"])
                attempt["available_at_s"] = time.monotonic() - ready
                if time.monotonic() >= max_deadline:
                    attempt["status"] = "late_delay_or_persistence"
                    break
                # Persist the complete immutable selection input before release.
                pilot.dump(attempt_dir / "candidate-ready.json", {k: v for k, v in _candidate_ref(attempt).items()
                                                                 if k != "available_at_s"})
                attempt["available_at_s"] = time.monotonic() - ready
                attempt["status"] = "eligible"
                if ready + attempt["available_at_s"] >= max_deadline:
                    attempt["status"] = "late_candidate_persistence"
                    break
                candidate = _candidate_ref(attempt)
                eligible.append(candidate)
                if record["first_eligible"] is None:
                    record["first_eligible"] = candidate
                feedback = {"code": source, "public": feedback_projection(result)} if row["policy"] == "repair" else None
            except (ValueError, budget.TransportBlocked, httpx.HTTPError, TimeoutError) as exc:
                if type(exc) is ValueError and str(exc) in {"message_limit_no_code_truncation", "feedback_projection_limit"}:
                    record.update(censored=True, stop_reason="request_guard_censored", guard_reason=str(exc))
                    attempt["guard_reason"] = str(exc)
                    if attempt["status"] != "eligible":
                        attempt["status"] = "request_guard_censored"
                    break
                attempt.update(status="request_or_context_failure", error_type=type(exc).__name__)
                batch_stop = transport.snapshot()["stop_reason"] or "request_or_context_failure"
                break
            finally:
                if "public_resource_path" in attempt:
                    path = output / attempt["public_resource_path"]
                    if path.exists():
                        attempt["public_resource"] = {"path": attempt["public_resource_path"],
                                                      "sha256": coding.sandbox.sha(path.read_bytes())}
                if number == 1:
                    first_outcome = ("public_pass" if attempt.get("public_status") == "pass" else "public_fail") if attempt["status"] == "eligible" else "parse_failed" if attempt["status"] == "parse_failed" else "no_candidate"
                    record["baseline"] = {"attempt": 1, "outcome": first_outcome, "attempt_status": attempt["status"],
                        "public_status": attempt.get("public_status"),
                        "candidate": _candidate_ref(attempt) if attempt["status"] == "eligible" else None}
                pilot.dump(attempt_dir / "attempt.json", attempt)
                # Include required round persistence. The next round starts
                # here, so observer bookkeeping/gaps are not made free.
                finished = time.monotonic()
                attempt["ended_at_s"] = finished - ready
                attempt["online_interval_s"] = finished - ready - attempt["started_at_s"]
                attempt["other_online_overhead_s"] = (attempt["online_interval_s"] - attempt["http_wall_s"]
                    - attempt["checker_wall_s"] - attempt["injected_delay_actual_s"])
                round_start = finished
        if len(record["attempts"]) == plan["max_rounds"] and time.monotonic() < max_deadline and batch_stop is None:
            record.update(censored=True, stop_reason="max_rounds_censored")
        if batch_stop is None:
            await timer
        else:
            record["stop_reason"] = batch_stop
    except asyncio.CancelledError as exc:
        cancellation = exc
        record["stop_reason"] = batch_stop = "cancelled"
    except BaseException as exc:
        record["error_type"] = type(exc).__name__
        record["stop_reason"] = batch_stop = "trajectory_failure"
        if isinstance(exc, KeyboardInterrupt):
            cancellation = exc
    finally:
        if not timer.done():
            timer.cancel()
        await asyncio.gather(timer, return_exceptions=True)
        for index in range(2):
            freeze(index, stopped=batch_stop is not None)
        record["snapshots"] = [snapshot_map[i] for i in range(2)]
        record["status"] = "interrupted" if cancellation else "stopped" if batch_stop else "complete"
        record["closed_at_s"] = time.monotonic() - ready
        record["drain_wall_s"] = max(0, record["closed_at_s"] - plan["deadlines_s"][-1])
        pilot.dump(directory / "trajectory.json", record)
    if cancellation is not None:
        raise cancellation
    return record, batch_stop


async def execute_batch(output: Path, plan: dict, admission=None, *, env_file: Path | None = None,
                        inner=None, checker=None, offline_trajectory_ids: list[str] | None = None,
                        _prepared: _StaticInputs | None = None) -> dict:
    """One transport for the whole matrix. Caller owns the study session."""
    output = Path(output).resolve()
    validate_plan(plan)
    paid = plan["paid"]
    if paid:
        import timely_study as study
        if (type(admission) is not getattr(study, "DeadlineAdmission", None) or admission is None
                or inner is not None or checker is not None or offline_trajectory_ids is not None
                or type(_prepared) is not _StaticInputs):
            raise pilot.PaidNotAdmitted("deadline_requires_live_study_without_overrides")
        admission.assert_live(output, plan)
    elif type(inner) is not httpx.MockTransport:
        raise ValueError("offline_deadline_requires_mock_transport")
    if _prepared is None:
        _prepared = static_preflight(output, plan, real_public=checker is None)
    if _prepared.plan_sha256 != pilot.digest(plan):
        raise ValueError("static_preflight_plan_changed")
    if admission is not None:
        admission.assert_live(output, plan)
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".deadline-run-entry").open("x") as stream:
        stream.write("single execution\n")
    if not (output / "plan.json").exists():
        pilot.dump(output / "plan.json", plan)
    elif json.loads((output / "plan.json").read_text()) != plan:
        raise ValueError("output_plan_changed")
    tasks, seed, image_id = _prepared.tasks, _prepared.seed, _prepared.image_id
    (output / "common-seed.py").write_text(seed[0], encoding="utf-8", newline="\n")
    pilot.dump(output / "common-seed-public.json", seed[1])
    if checker is None:
        checker = public_worker
    cap = admission.batch_cap_cny if admission is not None else BATCH_CAP
    transport = budget.BudgetedTimelyTransport(log_path=output / "requests.jsonl", batch_budget_cny=cap,
        max_calls=144 * plan["max_rounds"], inner=inner)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False, timeout=60)
    records = [{**row, "status": "not_started", "snapshots": [None, None], "attempts": [],
                "stop_reason": "not_reached"} for row in plan["trajectories"]]
    http_closed = interrupted = False
    stop_reason = None
    cancellation = None
    try:
        if paid:
            client.headers["Authorization"] = "Bearer " + _prepared.credential
            _prepared.credential = None
        for index, row in enumerate(plan["trajectories"]):
            if stop_reason:
                records[index]["stop_reason"] = "batch_stopped:" + stop_reason
                continue
            if offline_trajectory_ids is not None and row["run_id"] not in offline_trajectory_ids:
                records[index]["stop_reason"] = "offline_fixture_not_selected"
                continue
            record, reason = await run_trajectory(output, row, tasks[row["number"]], plan, client,
                                                   transport, admission, seed, checker, image_id)
            records[index] = record
            if reason:
                stop_reason = reason
    except BaseException as exc:
        stop_reason = "cancelled" if isinstance(exc, asyncio.CancelledError) else type(exc).__name__
        interrupted = isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt))
        if interrupted:
            cancellation = exc
    finally:
        try:
            await client.aclose()
            http_closed = True
        finally:
            for index, row in enumerate(records):
                path = output / "trajectories" / row["run_id"] / "trajectory.json"
                if path.exists():
                    records[index] = json.loads(path.read_text())
                elif stop_reason:
                    row["stop_reason"] = "batch_stopped:" + stop_reason
            resources = []
            resources_closed = True
            for path in sorted(output.rglob("public-resource-closed.json")):
                document = json.loads(path.read_text())
                resources_closed &= document.get("closed") is True and document.get("worker_reaped") is True and document.get("containers_removed") is True
                resources.append({"path": str(path.relative_to(output)), "sha256": coding.sandbox.sha(path.read_bytes())})
            # Every issued public worker must have one closure receipt.
            issued = sum("public_started_at_s" in attempt for row in records for attempt in row["attempts"])
            resources_closed &= issued == len(resources)
            pilot.dump(output / "trajectories.json", records)
            trajectories_sha = coding.sandbox.sha((output / "trajectories.json").read_bytes())
            requests_sha = coding.sandbox.sha((output / "requests.jsonl").read_bytes())
            accounting = transport.snapshot()
            closure = {"schema": 1, "denominator": 144, "http_closed": http_closed,
                "public_resources_closed": resources_closed, "interrupted": interrupted, "transport": accounting,
                "requests_sha256": requests_sha, "trajectories_sha256": trajectories_sha, "public_resources": resources}
            pilot.dump(output / "generation-closed.json", closure)
            result = {"schema": 1, "paid": paid, "plan_sha256": pilot.digest(plan), "denominator": 144,
                "http_closed": http_closed, "public_resources_closed": resources_closed, "interrupted": interrupted,
                "stop_reason": stop_reason, "accounting": accounting, "requests_sha256": requests_sha,
                "trajectories_sha256": trajectories_sha}
            pilot.dump(output / "result.json", result)
    if cancellation is not None:
        raise cancellation
    return result


async def _invoke_with_owned_signals(operation):
    """Cancel once; repeated terminal signals must not interrupt resource drain."""
    loop, task = asyncio.get_running_loop(), asyncio.current_task()
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    cancelled = False
    def cancel_once():
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            task.cancel()
    try:
        for sig in signals:
            loop.add_signal_handler(sig, cancel_once)
        return await operation
    finally:
        for sig in signals:
            loop.remove_signal_handler(sig)
            signal.signal(sig, previous[sig])


def execute_study(output: Path, env_file: Path) -> dict:
    """Minimal paid entry; the caller owns the outer process with >=180s grace."""
    import timely_study as study
    output = output.resolve()
    plan = json.loads((output / "plan.json").read_text())
    if plan.get("paid") is not True:
        raise pilot.PaidNotAdmitted("execute_study_requires_paid_frozen_plan")
    prepared = static_preflight(output, plan, env_file=env_file)
    with study.deadline_session(output, execute_paid=True) as admission:
        try:
            with asyncio.Runner() as loop:
                result = loop.run(_invoke_with_owned_signals(execute_batch(output, plan, admission, _prepared=prepared)))
        finally:
            # Cancellation propagates after the HTTP/resource/accounting
            # artifacts have closed and the same study retains its liability.
            if (output / "result.json").exists():
                settlement = admission.finish()
                print(json.dumps({"study_settlement": settlement}), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-plan", action="store_true")
    mode.add_argument("--execute-study", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--deadlines", type=float, nargs=2)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--paid", action="store_true")
    args = parser.parse_args()
    if args.execute_study is not None:
        if args.env_file is None or args.paid or args.deadlines is not None or args.calibration is not None:
            parser.error("--execute-study accepts only its root and --env-file")
        result = execute_study(args.execute_study, args.env_file)
        print(json.dumps(result), flush=True)
        return 0 if result["stop_reason"] in (None, "budget_censored") else 1
    if args.calibration is None or args.deadlines is None or args.env_file is not None:
        parser.error("--prepare-plan requires --calibration and --deadlines; no credentials")
    reference = {"path": str(args.calibration.resolve()), "sha256": coding.sandbox.sha(args.calibration.read_bytes())}
    calibration = json.loads(args.calibration.read_text())
    plan = make_plan(args.deadlines, reference, paid=args.paid, max_rounds=calibration["max_rounds"])
    output = coding.sandbox.LOCAL / "deadline-plans" / uuid.uuid4().hex
    output.mkdir(parents=True)
    pilot.dump(output / "coding-plan.json", plan)
    _, provenance = coding.load_tasks()
    pilot.dump(output / "provenance.json", provenance)
    print(json.dumps({"output": str(output), "model_calls_actual": 0, "status": "plan_only_not_admitted"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
