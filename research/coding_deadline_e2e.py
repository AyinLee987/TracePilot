"""Focused zero-provider deadline checks and an explicitly separate calibration."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid

import coding_deadline as runner


def fake_http(tasks, *, wait_s=0.01, unknown=False, seen=None, first_bad=False):
    count = 0
    async def reply(request):
        nonlocal count
        count += 1
        payload = json.loads(request.content)
        if seen is not None:
            seen.append(payload)
        number = int(re.search(r"Task: HumanEval/(\d+)", payload["messages"][1]["content"]).group(1))
        await asyncio.sleep(wait_s)
        source = f"def {tasks[number]['entry_point']}(*args):\n    return None\n# fixture-{count}\n"
        if first_bad and count == 1:
            source = "This is deliberately not a Python function."
        body = {"id": f"fixture-{count}", "model": payload["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": source}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45,
                          "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 30}}
        if unknown:
            body.pop("usage")
        return runner.httpx.Response(200, json=body)
    return runner.httpx.MockTransport(reply)


def fake_checker(*, wait_s=0.001, ready=None, pending=False, first_wrong=False):
    count = 0
    async def check(task, source, image_id, output):
        nonlocal count
        count += 1
        output.mkdir()
        started = time.monotonic()
        try:
            if ready:
                ready.set()
            if pending:
                await asyncio.Event().wait()
            await asyncio.sleep(wait_s)
            passed = 1 if first_wrong and count == 1 else 2
            return {"task_id": task["task_id"], "visibility": "public", "status": "pass" if passed == 2 else "fail",
                    "reason": "explicit_fake_checker", "checked": 2, "passed": passed, "total": 2,
                    "checks": [], "wall_s": time.monotonic() - started}
        finally:
            runner.pilot.dump(output / "public-resource-closed.json", {"closed": True,
                "worker_reaped": True, "containers_removed": True, "started": False, "fixture_only": True})
    return check


def inspect(root: Path) -> tuple[dict, list]:
    result = json.loads((root / "result.json").read_text())
    rows = json.loads((root / "trajectories.json").read_text())
    closure = json.loads((root / "generation-closed.json").read_text())
    assert result["denominator"] == len(rows) == 144
    assert sum(len(row["snapshots"]) for row in rows) == 288
    assert result["http_closed"] and result["public_resources_closed"]
    assert result["accounting"]["active_calls"] == 0 and result["accounting"]["closing"]
    assert result["trajectories_sha256"] == runner.coding.sandbox.sha((root / "trajectories.json").read_bytes())
    assert result["requests_sha256"] == runner.coding.sandbox.sha((root / "requests.jsonl").read_bytes())
    inventory = {str(p.relative_to(root)): runner.coding.sandbox.sha(p.read_bytes()) for p in root.rglob("public-resource-closed.json")}
    assert inventory == {r["path"]: r["sha256"] for r in closure["public_resources"]}
    for row in rows:
        for snapshot in row["snapshots"]:
            if snapshot is None:
                continue
            assert runner.coding.sandbox.sha((root / snapshot["path"]).read_bytes()) == snapshot["sha256"]
            if snapshot["selected"]:
                chosen = snapshot["selected"]
                assert chosen["available_at_s"] < snapshot["deadline_s"]
                assert runner.coding.sandbox.sha((root / chosen["candidate_path"]).read_bytes()) == chosen["code_sha256"]
    return result, rows


async def checks(output: Path) -> dict:
    tasks, _ = runner.coding.load_tasks()
    matrix = runner.rows()
    assert len(matrix) == 144 and len({r["run_id"] for r in matrix}) == 144
    assert sum(r["cohort"] == "native" for r in matrix) == 128
    assert sum(r["cohort"] == "common" for r in matrix) == 16
    for cohort, numbers in (("native", runner.TASKS), ("common", (99,))):
        for number in numbers:
            first = [(r["model"], r["policy"], r["delay_s"]) for r in matrix
                     if r["cohort"] == cohort and r["number"] == number and r["repeat"] == 1]
            second = [(r["model"], r["policy"], r["delay_s"]) for r in matrix
                      if r["cohort"] == cohort and r["number"] == number and r["repeat"] == 2]
            assert first == list(reversed(second)) and len(set(first)) == 8
    chosen = next(r for r in matrix if r["cohort"] == "native" and r["delay_s"] == 0 and r["policy"] == "repair")
    report = {"passed": False, "output": str(output), "provider_calls": 0, "judge_containers": 0,
              "code_sha256": runner.identities(), "cases": [{"name": "fixed_complete_matrix_and_reversed_repeats", "passed": True}]}

    async def execute(label, deadlines, inner, checker, row=chosen):
        root = output / label
        plan = runner.make_plan(deadlines, {"fixture_only": True})
        await runner.execute_batch(root, plan, inner=inner, checker=checker, offline_trajectory_ids=[row["run_id"]])
        result, records = inspect(root)
        record = next(r for r in records if r["run_id"] == row["run_id"])
        return root, result, record

    _, result, record = await execute("late-http", [0.02, 0.04], fake_http(tasks, wait_s=0.08), fake_checker())
    assert result["accounting"]["calls_dispatched"] == 1 and result["accounting"]["unknown_calls"] == 0
    assert record["attempts"][0]["status"] == "late_response_accounted_only"
    assert all(s["selected"] is None for s in record["snapshots"])
    assert "parse" not in record["attempts"][0]
    report["cases"].append({"name": "late_http_settled_without_parse_tool_or_selection", "passed": True})
    _, _, record = await execute("late-public", [0.025, 0.05], fake_http(tasks, wait_s=0.005), fake_checker(wait_s=0.08))
    assert record["attempts"][0]["status"] == "late_public_result"
    assert all(s["selected"] is None for s in record["snapshots"])
    report["cases"].append({"name": "public_return_after_cutoff_ineligible_and_closed", "passed": True})
    delayed = next(r for r in matrix if r["cohort"] == "native" and r["delay_s"] == 1)
    _, _, record = await execute("delay-crosses-cutoff", [0.03, 0.06], fake_http(tasks, wait_s=0.005), fake_checker(), delayed)
    assert record["attempts"][0]["status"] == "late_delay_or_persistence"
    assert record["attempts"][0]["injected_delay_actual_s"] >= 1
    assert all(s["selected"] is None for s in record["snapshots"])
    report["cases"].append({"name": "real_one_second_tool_delay_crosses_cutoff", "passed": True})
    _, _, record = await execute("prefix", [0.075, 0.20], fake_http(tasks, wait_s=0.04), fake_checker(first_wrong=True))
    short, long = record["snapshots"]
    assert short["selected"]["candidate_id"] == "attempt-01"
    assert short["selected"]["public_passed"] == 1 and long["selected"]["public_passed"] == 2
    assert long["selected"]["candidate_id"] == "attempt-02"
    report["cases"].append({"name": "immutable_prefix_best_and_earliest_tie", "passed": True})
    seen = []
    _, _, record = await execute("parse-failure", [0.06, 0.13], fake_http(tasks, wait_s=0.02, first_bad=True, seen=seen), fake_checker())
    assert record["baseline"]["candidate"] is None and record["baseline"]["outcome"] == "parse_failed"
    assert record["first_eligible"] is not None and record["first_eligible"]["candidate_id"] != "attempt-01"
    assert record["attempts"][0]["public_wall_s"] == record["attempts"][0]["injected_delay_actual_s"] == 0
    assert "format_diagnostic" in seen[1]["messages"][1]["content"]
    report["cases"].append({"name": "attempt_one_baseline_not_replaced_and_parse_feedback_has_no_tool_delay", "passed": True})
    seed_code, seed_public = runner.load_seed()
    common = next(r for r in matrix if r["cohort"] == "common" and r["policy"] == "resample" and r["delay_s"] == 0)
    repair = {**common, "policy": "repair"}
    seed_feedback = {"code": seed_code, "public": runner.feedback_projection(seed_public)}
    blind = runner.request_body(common, tasks[99], seed_feedback)
    feedback = runner.request_body(repair, tasks[99], seed_feedback)
    assert "Previous candidate" not in blind["messages"][1]["content"]
    assert seed_code in json.loads(feedback["messages"][1]["content"].split("PUBLIC diagnostic:\n")[1])["code"]
    first_blind = runner.request_body({**chosen, "policy": "resample"}, tasks[chosen["number"]], None)
    assert first_blind == runner.request_body(chosen, tasks[chosen["number"]], None)
    _, _, record = await execute("common-fallback", [0.015, 0.03], fake_http(tasks, wait_s=0.06), fake_checker(), common)
    assert all(s["selected"]["candidate_id"] == "seed" for s in record["snapshots"])
    report["cases"].append({"name": "blind_never_receives_seed_and_both_selectors_have_fallback", "passed": True})
    _, result, _ = await execute("unknown", [0.04, 0.08], fake_http(tasks, unknown=True), fake_checker())
    assert result["accounting"]["calls_dispatched"] == result["accounting"]["unknown_calls"] == 1
    assert result["stop_reason"] and float(result["accounting"]["unknown_reserved_cny"]) > 0
    report["cases"].append({"name": "unknown_stops_entire_matrix_preserving_denominator", "passed": True})
    root = output / "cancel"
    ready = asyncio.Event()
    call = asyncio.create_task(runner.execute_batch(root, runner.make_plan([0.5, 1.0], {"fixture_only": True}),
        inner=fake_http(tasks), checker=fake_checker(ready=ready, pending=True), offline_trajectory_ids=[chosen["run_id"]]))
    await ready.wait()
    call.cancel()
    try:
        await call
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancellation swallowed")
    result, _ = inspect(root)
    assert result["interrupted"] and result["stop_reason"] == "cancelled"
    report["cases"].append({"name": "cancel_propagates_after_http_public_closure_and_full_matrix", "passed": True})
    report["passed"] = True
    return report


def scripted_http(tasks, *, rounds=1, late_after_s=2.0, source_override=None, intervals=None, interval_path=None):
    """Known responses only; the final response arrives beyond the delivery cutoff."""
    count, first = 0, None
    async def reply(request):
        nonlocal count, first
        payload = json.loads(request.content)
        number = int(re.search(r"Task: HumanEval/(\d+)", payload["messages"][1]["content"]).group(1))
        within = count % (rounds + 1)
        count += 1
        started = time.monotonic()
        if within == 0:
            first = started
        await asyncio.sleep(0.01 if within < rounds else max(0.01, first + late_after_s - started))
        ended = time.monotonic()
        interval = {"request_index": count, "started_monotonic_s": started,
                    "ended_monotonic_s": ended, "actual_wait_s": ended-started}
        if intervals is not None:
            intervals.append(interval)
        if interval_path is not None:
            with interval_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(interval, ensure_ascii=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        task = tasks[number]
        source = source_override if source_override is not None else task["prompt"] + task["canonical_solution"]
        return runner.httpx.Response(200, json={"id": f"scripted-{count}", "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": source}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45,
                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 30}})
    return runner.httpx.MockTransport(reply)


async def docker_checks(output: Path) -> dict:
    tasks, _ = runner.coding.load_tasks()
    chosen = next(r for r in runner.rows() if r["number"] == 55 and r["delay_s"] == 0
                  and r["policy"] == "repair" and r["repeat"] == 1)
    report = {"passed": False, "provider_calls": 0, "code_sha256": runner.identities(), "cases": []}
    sources = {"canonical": None,
        "fd-flood": "import os\ndef fib(n):\n    while True: os.write(1, b'x' * 65536)\n",
        "timeout": "def fib(n):\n    while True: pass\n"}
    for label, source in sources.items():
        root = output / label
        deadlines = [0.5, 2.0] if label != "timeout" else [0.1, 0.2]
        await runner.execute_batch(root, runner.make_plan(deadlines, {"fixture_only": True}),
            inner=scripted_http(tasks, late_after_s=2.1, source_override=source),
            offline_trajectory_ids=[chosen["run_id"]])
        result, records = inspect(root)
        row = next(r for r in records if r["run_id"] == chosen["run_id"])
        first = row["attempts"][0]
        assert result["stop_reason"] is None and result["accounting"]["unknown_calls"] == 0
        execution_paths = list(root.rglob("execution.json"))
        assert len(execution_paths) == 1
        execution = json.loads(execution_paths[0].read_text())
        assert execution["worker_cli_reaped"] and execution["cleanup"]["removed"]
        assert execution["cleanup"]["remove_exit_code"] == 0
        if label == "canonical":
            assert first["status"] == "eligible" and first["public_status"] == "pass"
        elif label == "fd-flood":
            assert first["public_status"] == "fail" and execution["output_limit_exceeded"]
        else:
            assert first["status"] == "late_public_result" and execution["timed_out"]
            assert all(s["selected"] is None for s in row["snapshots"])
        report["cases"].append({"name": label, "passed": True, "public_status": first["public_status"],
            "deadline_status": first["status"], "closed_at_s": row["closed_at_s"],
            "evidence": str(root), "containers": len(execution_paths)})
        print(json.dumps({"case_complete": label, "output": str(root)}), flush=True)
    report["judge_containers"] = sum(c["containers"] for c in report["cases"])
    report["passed"] = True
    return report


def calibration(output: Path, blocked_network_attempts: list[str]) -> dict:
    """Real admission and public Docker calls; synthetic history and HTTP only."""
    import coding_deadline_study_e2e as fixture
    import timely_study as study
    import timely_batch as batch
    timing_path = runner.ROOT / ".local/overnight/r3-timing-inputs.json"
    timing = json.loads(timing_path.read_text())
    intervals = []
    fixture_started = time.monotonic()
    with fixture.prepared_deadline(output / "study-fixture", (3.0, 6.0)) as prepared:
        root = prepared["root"]
        plan = json.loads((root / "plan.json").read_text())
        # Both policy paths on all eight tasks; one actual delayed repair path.
        selected = [r for r in plan["trajectories"] if r["cohort"] == "native" and r["repeat"] == 1
            and r["model"] == "deepseek-flash"
            and r["delay_s"] == (1 if r["number"] == 55 and r["policy"] == "repair" else 0)]
        assert len(selected) == 16
        study.activate(root, plan_sha256=prepared["prepared"]["plan_sha256"], review=prepared["review"],
                       review_sha256=batch.file_hash(prepared["review"]))
        ready_inputs = runner.static_preflight(root, plan)
        preparation = {"synthetic_history_prepare_activate_wall_s": time.monotonic()-fixture_started}
        admission_started = time.monotonic()
        with study.deadline_session(root) as admission:
            preparation["session_entry_full_audit_wall_s"] = time.monotonic()-admission_started
            execution_started = time.monotonic()
            result = asyncio.run(runner.execute_batch(root, plan, admission,
                inner=scripted_http(prepared["tasks"], rounds=2, late_after_s=6.1, intervals=intervals,
                                    interval_path=root / "synthetic-http.jsonl"),
                offline_trajectory_ids=[r["run_id"] for r in selected], _prepared=ready_inputs))
            settlement = admission.finish()
        assert settlement["status"] == "known_settled"
        result, records = inspect(root)
        assert result["stop_reason"] is None
        preparation["executor_before_first_task_ready_wall_s"] = min(r["task_ready_monotonic_s"] for r in records
            if r["status"] != "not_started") - execution_started
    samples, setups = [], []
    remaining = iter(intervals)
    for record in records:
        if record["status"] == "not_started":
            continue
        setups.append({"run_id": record["run_id"], "setup_once_s": record["setup_once_s"]})
        eligible = [a for a in record["attempts"] if a["status"] == "eligible"]
        assert len(eligible) == 2, "calibration requires two complete online rounds per path"
        for attempt in record["attempts"]:
            http = next(remaining)
            if attempt["status"] != "eligible":
                continue
            # The synthetic network wait is the only HTTP time subtracted.
            # Client/transport serialization, journal I/O, and helper startup
            # remain in round_other rather than being made free.
            other = (attempt["online_interval_s"] - http["actual_wait_s"]
                     - attempt["checker_wall_s"] - attempt["injected_delay_actual_s"])
            assert other >= 0, "negative timing residual is invalid, never clipped"
            samples.append({"run_id": record["run_id"], "task_id": record["task_id"],
                "policy": record["policy"], "cohort": record["cohort"],
                "candidate_id": attempt["candidate_id"], "outcome": attempt["status"],
                "started_at_s": attempt["started_at_s"], "ended_at_s": attempt["ended_at_s"],
                "online_interval_s": attempt["online_interval_s"], "synthetic_http": http,
                "public_checker_wall_s": attempt["checker_wall_s"], "public_wrapper_wall_s": attempt["public_wall_s"],
                "injected_delay_planned_s": record["delay_s"],
                "injected_delay_actual_s": attempt["injected_delay_actual_s"], "round_other_s": other})
    assert len(setups) == 16 and len(samples) == 32
    def p90(values):
        return sorted(values)[math.ceil(.9 * len(values))-1]
    setup_p90 = p90([x["setup_once_s"] for x in setups])
    other_p90 = p90([x["round_other_s"] for x in samples])
    http_p90 = timing["pooled"]["http_transport"]["p90"]["seconds"]
    public_p90 = timing["pooled"]["public_checker"]["p90"]["seconds"]
    min_http = timing["pooled"]["http_transport"]["min_s"]
    short = max(5, math.ceil(http_p90 + public_p90 + 1 + setup_p90 + other_p90))
    long = 3 * short
    report = {"status": "passed", "passed": True, "provider_calls": 0, "full_loop_calibration": True,
        "offline_guard_installed": True, "blocked_network_attempts": len(blocked_network_attempts),
        "fixture_history": True, "fixture_only": False, "synthetic_http": True, "real_public_checker": True,
        "real_light_admission": True, "heldout_used": False, "deadlines_s": [short, long],
        "calibration_execution_deadlines_s": [3.0, 6.0], "min_prior_http_s": min_http,
        "max_rounds": max(64, math.ceil(long/min_http)+2),
        "setup_once_p90_s": setup_p90, "round_other_p90_s": other_p90,
        "prior_http_p90_s": http_p90, "prior_public_p90_s": public_p90,
        "quantile_method": "nearest_rank_1_based_ceil_p_times_n",
        "formula": "Dshort=max(5,ceil(http_p90+public_p90+1+setup_once_p90+round_other_p90));Dlong=3*Dshort",
        "meaning": "Calibration rule, not a latency guarantee; 16 native trajectories with two canonical synthetic replies each. No hidden evaluation.",
        "conservative_overlap": "Prior transport HTTP includes local bookkeeping also retained in round_other; the sum may modestly double-count it.",
        "timing_inputs": {"path": str(timing_path), "sha256": batch.file_hash(timing_path)},
        "code_sha256": runner.identities(), "runtime_identity": runner.pilot.runtime_identity(),
        "study_sha256": batch.file_hash(Path(study.__file__)), "batch_sha256": batch.file_hash(Path(batch.__file__)),
        "evidence_root": str(root), "settlement": settlement, "setups": setups, "samples": samples,
        "pre_ready_preparation": preparation,
        "all_synthetic_http_intervals": intervals, "judge_containers": len(list(root.rglob("execution.json")))}
    evidence_paths = [root / name for name in ("plan.json", "trajectories.json", "requests.jsonl", "synthetic-http.jsonl")]
    evidence_paths += (list(root.rglob("trajectory.json")) + list(root.rglob("public-result.json"))
                       + list(root.rglob("public-feedback.json")))
    report["evidence_files"] = {str(path.relative_to(root)): batch.file_hash(path) for path in evidence_paths}
    assert not blocked_network_attempts, "offline network guard observed an attempted dispatch"
    runner.pilot.dump(output / "calibration.json", report)
    return report


def outer_cancel(output: Path, *, double_signal=False) -> dict:
    import timely_batch as batch
    child_root = output / "cancel-child"
    command = ["env", "-i", *[f"{k}={v}" for k, v in runner.coding.sandbox.process_env().items()],
        sys.executable, "-B", str(Path(__file__).resolve()),
        "--double-signal-child" if double_signal else "--cancel-child", str(child_root)]
    started = time.monotonic()
    try:
        returncode = batch.run_owned_child(command, timeout=45 if double_signal else 12,
            ownership_path=output / "outer-owner.json", grace_s=runner.OUTER_SIGINT_GRACE_S)
    except batch.PilotError as exc:
        assert not double_signal and str(exc) == "owned_child_timeout"
    else:
        assert double_signal and returncode != 0, "child unexpectedly finished before cancellation"
    result, records = inspect(child_root)
    assert result["interrupted"] and result["stop_reason"] == "cancelled"
    closure = json.loads((output / "outer-owner.closed.json").read_text())
    assert closure["cleanup_verified"] and not batch.group_members(closure["pid"])
    resources = list(child_root.rglob("public-resource-closed.json"))
    assert len(resources) == 1
    resource = json.loads(resources[0].read_text())
    assert resource["closed"] and resource["worker_reaped"] and resource["containers_removed"]
    assert not batch.group_members(resource["worker_pid"])
    executions = list(child_root.rglob("execution.json"))
    assert len(executions) == 1
    execution = json.loads(executions[0].read_text())
    assert execution["worker_cli_reaped"] and execution["cleanup"]["removed"]
    if double_signal:
        assert json.loads((child_root / "signals-sent.json").read_text())["signals"] == ["SIGTERM", "SIGINT"]
    return {"passed": True, "provider_calls": 0, "judge_containers": 1, "code_sha256": runner.identities(),
        "outer_sigint_grace_s": runner.OUTER_SIGINT_GRACE_S, "elapsed_s": time.monotonic()-started,
        "cases": [{"name": "double_signal_idempotent_cleanup" if double_signal else "outer_SIGINT_owned_helper_and_container_drained_before_parent_reaped", "passed": True}],
        "resource": resource, "outer_closure": closure, "result": result}


async def review_checks(output: Path) -> dict:
    from unittest.mock import patch
    import timely_study as study
    cases = []
    for label in ("missing-env", "daemon-failure"):
        root = output / label
        root.mkdir()
        plan = runner.make_plan([0.2, 0.4], {}, paid=True)
        runner.pilot.dump(root / "plan.json", plan)
        env = output / (label + ".env")
        if label == "daemon-failure":
            env.write_text("DEEPSEEK_API_KEY=offline-dummy-preflight-only\n")
        with patch.object(study, "deadline_session", side_effect=AssertionError("reservation reached")), \
                patch.object(runner.coding.sandbox, "verify_daemon", side_effect=ValueError("fixture_daemon_unavailable")):
            try:
                runner.execute_study(root, env)
            except (runner.pilot.PaidNotAdmitted, ValueError):
                pass
            else:
                raise AssertionError("preflight should fail before reservation")
        assert not (root / ".deadline-run-entry").exists() and not (root / "requests.jsonl").exists()
        assert not (root / "pilot.lock").exists()
        cases.append({"name": label + "_refused_before_study_reserve", "passed": True})
    tasks, _ = runner.coding.load_tasks()
    matrix = runner.rows()
    chosen = next(r for r in matrix if r["number"] == 55 and r["model"] == "deepseek-v4-pro"
                  and r["policy"] == "repair" and r["delay_s"] == 0 and r["repeat"] == 1)
    following = next(r for r in matrix[matrix.index(chosen)+1:] if r["delay_s"] == 0)
    for label, size in (("per_request_cap", 13000), ("message_limit_no_code_truncation", 40000), ("feedback_projection_limit", 0)):
        root = output / label
        count = 0
        async def reply(request):
            nonlocal count
            count += 1
            payload = json.loads(request.content)
            number = int(re.search(r"Task: HumanEval/(\d+)", payload["messages"][1]["content"]).group(1))
            await asyncio.sleep(.01)
            source = f"def {tasks[number]['entry_point']}(*args):\n    return 0\n" + ("#" + "x"*size if count == 1 else "")
            return runner.httpx.Response(200, json={"id": f"guard-{count}", "model": payload["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"content": source, "role": "assistant"}}], "usage": {"prompt_tokens": 30,
                "completion_tokens": 15, "total_tokens": 45, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 30}})
        plain_check = fake_checker()
        checker_count = 0
        async def checker(task, source, image_id, directory):
            nonlocal checker_count
            result = await plain_check(task, source, image_id, directory)
            checker_count += 1
            if label == "feedback_projection_limit" and checker_count == 1:
                result["diagnostic"] = {"message": "x" * (runner.FEEDBACK_CAP+1)}
            return result
        await runner.execute_batch(root, runner.make_plan([.1, .35], {"fixture_only": True}),
            inner=runner.httpx.MockTransport(reply), checker=checker,
            offline_trajectory_ids=[chosen["run_id"], following["run_id"]])
        result, records = inspect(root)
        first, later = [next(r for r in records if r["run_id"] == chosen_id)
                        for chosen_id in (chosen["run_id"], following["run_id"])]
        assert result["stop_reason"] is None and result["accounting"]["unknown_calls"] == 0
        assert first["censored"] and first["stop_reason"] == "request_guard_censored" and first["guard_reason"] == label
        assert first["baseline"]["candidate"] and first["snapshots"][-1]["selected"]
        assert later["attempts"] and later["status"] == "complete"
        cases.append({"name": label + "_only_current_trajectory_and_baseline_preserved", "passed": True})
    return {"passed": True, "provider_calls": 0, "judge_containers": 0,
            "code_sha256": runner.identities(), "cases": cases}


async def recovery_check(output: Path, *, stuck=False) -> dict:
    from unittest.mock import patch
    import timely_batch as batch
    # Trusted fault injection only: after the unchanged sandbox has created,
    # inspected and probed its container, exit before starting any exec client.
    helper = output / "abrupt-helper.py"
    fault = ("    import signal, time\n    signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
             "    while True: time.sleep(1)\n") if stuck else "    os._exit(97)\n"
    helper.write_text("import os, sys\nsys.path.insert(0, " + repr(str(runner.ROOT / "research")) + ")\n"
        "import coding_deadline_worker as worker\nimport coding_environment_smoke as sandbox\n"
        "def stop_before_exec(*args, **kwargs):\n" + fault +
        "sandbox.run_worker = stop_before_exec\nworker.main()\n", encoding="utf-8")
    tasks, _ = runner.coding.load_tasks()
    row = next(r for r in runner.rows() if r["number"] == 55 and r["delay_s"] == 0)
    root = output / "recovery"
    started = time.monotonic()
    with patch.object(runner, "WORKER", helper), \
            patch.object(runner, "PUBLIC_SUPERVISOR_TIMEOUT_S", 5 if stuck else 240), \
            patch.object(runner, "PUBLIC_CLEANUP_TIMEOUT_S", .2 if stuck else 75):
        await runner.execute_batch(root, runner.make_plan([.1, 1.0], {"fixture_only": True}),
            inner=scripted_http(tasks), offline_trajectory_ids=[row["run_id"]])
    result, records = inspect(root)
    assert result["stop_reason"] == "public_infrastructure_failure" and result["accounting"]["unknown_calls"] == 0
    resources = list(root.rglob("public-resource-closed.json"))
    assert len(resources) == 1
    receipt = json.loads(resources[0].read_text())
    assert receipt["closed"] and receipt["worker_exit_code"] == (-9 if stuck else 97) and receipt["recovery"]["remove_exit_code"] == 0
    assert len(receipt["containers"]) == 1 and receipt["containers"][0]["removed"]
    assert not batch.group_members(receipt["worker_pid"])
    return {"passed": True, "provider_calls": 0, "judge_containers": 1, "code_sha256": runner.identities(),
        "cases": [{"name": "stuck_helper_killpg_exact_recovery" if stuck else "abrupt_helper_death_exact_container_async_recovery", "passed": True}],
        "resource": receipt, "elapsed_s": time.monotonic()-started,
        "scope": "Real helper/container; supervision waits shortened to 5/.2 seconds for stuck test, not a real 240/75 second wait." if stuck else "Abrupt trusted helper exit before exec."}


async def blind_diagnostic_check(output: Path) -> dict:
    from unittest.mock import patch
    tasks, _ = runner.coding.load_tasks()
    row = next(r for r in runner.rows() if r["cohort"] == "native" and r["policy"] == "resample" and r["delay_s"] == 0)
    plain = fake_checker()
    async def checker(task, source, image_id, directory):
        result = await plain(task, source, image_id, directory)
        result["diagnostic"] = {"message": "x" * (runner.FEEDBACK_CAP+1)}
        return result
    seen = []
    root = output / "blind-diagnostic"
    await runner.execute_batch(root, runner.make_plan([.2, .5], {"fixture_only": True}),
        inner=fake_http(tasks, wait_s=.02, seen=seen), checker=checker, offline_trajectory_ids=[row["run_id"]])
    result, records = inspect(root)
    record = next(r for r in records if r["run_id"] == row["run_id"])
    assert result["stop_reason"] is None and not record["censored"] and len(record["attempts"]) > 1
    assert all("Previous candidate" not in payload["messages"][1]["content"] for payload in seen)
    interrupted_root = output / "keyboard-interrupt"
    with patch.object(runner.asyncio, "create_subprocess_exec", side_effect=KeyboardInterrupt):
        try:
            await runner.execute_batch(interrupted_root, runner.make_plan([.2, .5], {"fixture_only": True}),
                inner=fake_http(tasks), checker=runner.public_worker, offline_trajectory_ids=[row["run_id"]])
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("KeyboardInterrupt was swallowed")
    interrupted, _ = inspect(interrupted_root)
    assert interrupted["interrupted"] and interrupted["stop_reason"] == "KeyboardInterrupt"
    return {"passed": True, "provider_calls": 0, "judge_containers": 0, "code_sha256": runner.identities(),
        "cases": [{"name": "blind_long_diagnostic_never_projected_or_censored", "passed": True},
                  {"name": "KeyboardInterrupt_propagates_after_closure_with_interrupted_true", "passed": True}]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--outer-cancel", action="store_true")
    parser.add_argument("--review-delta", action="store_true")
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--stuck-helper", action="store_true")
    parser.add_argument("--double-signal", action="store_true")
    parser.add_argument("--blind-diagnostic", action="store_true")
    parser.add_argument("--cancel-child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--double-signal-child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sum((args.docker, args.calibrate, args.outer_cancel, args.review_delta, args.recovery, args.stuck_helper,
            args.double_signal, args.blind_diagnostic, args.cancel_child is not None, args.double_signal_child is not None)) > 1:
        parser.error("choose one focused mode")
    if args.cancel_child is not None or args.double_signal_child is not None:
        runner.pilot.install_offline_guard()
        tasks, _ = runner.coding.load_tasks()
        chosen = next(r for r in runner.rows() if r["number"] == 55 and r["delay_s"] == 0 and r["repeat"] == 1)
        child_root = args.cancel_child or args.double_signal_child
        async def invoke_child():
            async def send_signals():
                while not list(child_root.rglob("create-command.json")):
                    await asyncio.sleep(.02)
                await asyncio.sleep(1)
                os.kill(os.getpid(), signal.SIGTERM)
                await asyncio.sleep(.02)
                os.kill(os.getpid(), signal.SIGINT)
                runner.pilot.dump(child_root / "signals-sent.json", {"signals": ["SIGTERM", "SIGINT"]})
            sender = asyncio.create_task(send_signals()) if args.double_signal_child else None
            try:
                await runner._invoke_with_owned_signals(runner.execute_batch(child_root,
                    runner.make_plan([20, 60], {"fixture_only": True}),
                    inner=scripted_http(tasks, source_override="def fib(n):\n    while True: pass\n"),
                    offline_trajectory_ids=[chosen["run_id"]]))
            finally:
                if sender is not None:
                    await sender
        asyncio.run(invoke_child())
        return 1
    output = runner.coding.sandbox.LOCAL / "deadline-e2e" / uuid.uuid4().hex
    output.mkdir(parents=True)
    report = {"output": str(output), "passed": False}
    blocked = []
    try:
        blocked = runner.pilot.install_offline_guard()
        if args.outer_cancel or args.double_signal:
            report = outer_cancel(output, double_signal=args.double_signal)
        elif args.calibrate:
            report = calibration(output, blocked)
        else:
            with asyncio.Runner() as loop:
                report = loop.run(blind_diagnostic_check(output) if args.blind_diagnostic
                                  else recovery_check(output, stuck=args.stuck_helper) if args.recovery or args.stuck_helper
                                  else review_checks(output) if args.review_delta
                                  else docker_checks(output) if args.docker else checks(output))
        assert not blocked
    except BaseException as exc:
        report.update(error_type=type(exc).__name__, error=str(exc)[:400])
    finally:
        report["blocked_network_attempts"] = len(blocked)
        runner.pilot.dump(output / "summary.json", report)
        print(json.dumps({"output": str(output), **{k: v for k, v in report.items()
            if k not in ("samples", "setups", "all_synthetic_http_intervals")}}, ensure_ascii=True), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
