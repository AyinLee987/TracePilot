"""Read-only reconstruction of the fixed R3 deadline calibration evidence.

This verifies recorded measurements and their source hashes. It does not run
models, candidate programs, Docker, or the calibration generator itself.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIOR_BATCHES = ("coding-first16-paid-20261006", "coding-extension16-paid-20261006")
TASKS = {55, 32, 7, 56, 16, 99, 18, 31}
TOLERANCE_S = 1e-8  # Floating subtraction only; never round before ceil.


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("deadline_calibration_" + reason)


def seconds(value, name: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid_seconds:" + name)
    return value


def same(actual, expected, name: str) -> None:
    seconds(actual, name)
    require(math.isclose(actual, expected, rel_tol=0, abs_tol=TOLERANCE_S), "mismatch:" + name)


def p90(values: list[float]) -> float:
    require(bool(values), "empty_quantile")
    return sorted(values)[math.ceil(.9 * len(values)) - 1]


def read_hashed(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "source_hash_changed:" + path.name)
    return raw


def jsonl(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def request_pairs(events: list[dict]) -> list[tuple[dict, dict]]:
    dispatched, completed = {}, {}
    for event in events:
        # This historical alias counts all dispatches, including MockTransport.
        # It is a consistency check, never evidence of live provider use.
        if "calls_dispatched" in event or "paid_call_count" in event:
            count = event.get("calls_dispatched")
            require(type(count) is int and count >= 0 and type(event.get("paid_call_count")) is int
                    and event["paid_call_count"] == count, "dispatch_alias_mismatch")
        if event["event"] == "request_dispatch":
            key = event["request_id"]
            require(key not in dispatched, "duplicate_dispatch")
            dispatched[key] = event
        elif event["event"] == "request_complete":
            key = event["request_id"]
            require(key in dispatched and key not in completed, "unpaired_completion")
            completed[key] = event
    require(set(dispatched) == set(completed), "incomplete_requests")
    require(events[-1]["event"] == "batch_close" and events[-1]["active_calls"] == 0
            and events[-1]["unknown_calls"] == 0, "request_journal_not_closed")
    require(events[-1]["calls_dispatched"] == len(dispatched), "dispatch_count_mismatch")
    return [(event, completed[key]) for key, event in dispatched.items()]


def prior_timings(reference: dict) -> dict:
    path = Path(reference["path"])
    if not path.is_absolute():
        path = ROOT / path
    timing = json.loads(read_hashed(path, reference["sha256"]))
    sources = timing["source_files"]
    require(len(sources) == 104, "prior_source_inventory_count")
    raw_files = {}
    for relative, ref in sources.items():
        relative_path = Path(relative)
        require(not relative_path.is_absolute() and ".." not in relative_path.parts, "prior_source_path")
        raw = read_hashed(ROOT / relative_path, ref["sha256"])
        require(len(raw) == ref["bytes"], "prior_source_size")
        raw_files[relative_path.as_posix()] = raw
    required, http, public = set(), [], []
    for batch in PRIOR_BATCHES:
        prefix = ".local/" + batch
        required.update(prefix + "/" + name for name in ("summary.json", "requests.jsonl", "phases.jsonl",
                        "generation-closed.json", "execution-process-closed.json"))
        pairs = request_pairs(jsonl(raw_files[prefix + "/requests.jsonl"]))
        require(len(pairs) == 16, "prior_request_denominator")
        run_ids = set()
        for dispatch, complete in pairs:
            run_id = dispatch["run_id"]
            require(run_id not in run_ids and "/" not in run_id and "\\" not in run_id, "prior_run_identity")
            run_ids.add(run_id)
            start = seconds(dispatch["start_monotonic_s"], "prior_http_start")
            end = seconds(complete["end_monotonic_s"], "prior_http_end")
            require(end > start, "prior_http_interval")
            http.append(end - start)
            generation_path = prefix + "/drafts/" + run_id + "/generation.json"
            required.add(generation_path)
            generation = json.loads(raw_files[generation_path])
            require(generation["run_id"] == run_id and generation["generation_status"] in
                    {"parsed", "parse_failed"}, "prior_generation_identity")
            if generation["generation_status"] == "parsed":
                summary_path = prefix + "/drafts/" + run_id + "/public-summary.json"
                result_path = prefix + "/drafts/" + run_id + "/public/public-result.json"
                required.update((summary_path, result_path))
                require(raw_files[summary_path] == raw_files[result_path], "prior_public_copies_differ")
                result = json.loads(raw_files[result_path])
                require(result["visibility"] == "public" and result["task_id"] == generation["task_id"],
                        "prior_public_identity")
                public.append(seconds(result["wall_s"], "prior_public_wall"))
    require(set(raw_files) == required and len(http) == 32 and len(public) == 31, "prior_inventory_incomplete")
    for name, values in (("http_transport", http), ("public_checker", public)):
        reported = timing["pooled"][name]
        require(reported["n"] == len(values), "prior_summary_count")
        same(reported["min_s"], min(values), "prior_" + name + "_min")
        for label, fraction in (("p50", .5), ("p75", .75), ("p90", .9)):
            rank = math.ceil(fraction * len(values))
            require(reported[label]["rank"] == rank, "prior_summary_rank")
            same(reported[label]["seconds"], sorted(values)[rank - 1], "prior_" + name + "_" + label)
    return {"prior_http_p90_s": p90(http), "prior_public_p90_s": p90(public),
            "min_prior_http_s": min(http), "prior_source_count": len(raw_files)}


def _verify_calibration(calibration: dict) -> dict:
    """Return independently reconstructed numbers, or raise ValueError.

    Call only for the real, zero-provider calibration. Small admission fixtures
    have a separate explicit fixture gate and are not accepted as calibration.
    """
    import coding_deadline as runner

    require(calibration.get("status") == "passed" and calibration.get("provider_calls") == 0
            and calibration.get("fixture_only") is False and calibration.get("full_loop_calibration") is True,
            "not_real_zero_provider_calibration")
    for flag in ("synthetic_http", "real_public_checker", "real_light_admission"):
        require(calibration.get(flag) is True, "missing_execution_mode:" + flag)
    require(calibration.get("offline_guard_installed") is True
            and type(calibration.get("blocked_network_attempts")) is int
            and calibration["blocked_network_attempts"] == 0, "offline_network_guard_not_verified")
    require(calibration.get("heldout_used") is False, "heldout_used")
    require(calibration["code_sha256"] == runner.identities(), "runtime_source_changed")
    require(calibration["runtime_identity"] == runner.pilot.runtime_identity(), "runtime_identity_changed")
    for name, key in (("timely_study.py", "study_sha256"), ("timely_batch.py", "batch_sha256")):
        read_hashed(ROOT / "research" / name, calibration[key])
    prior = prior_timings(calibration["timing_inputs"])
    root = Path(calibration["evidence_root"])
    if not root.is_absolute():
        root = ROOT / root
    refs, evidence = calibration["evidence_files"], {}
    for relative, sha in refs.items():
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, "evidence_path")
        evidence[path.as_posix()] = read_hashed(root / path, sha)

    def document(relative: str):
        require(relative in evidence, "unbound_evidence:" + relative)
        return json.loads(evidence[relative])

    plan = document("plan.json")
    require(plan["paid"] is False and plan["code_sha256"] == calibration["code_sha256"] and plan["runtime_identity"] ==
            calibration["runtime_identity"], "execution_identity_changed")
    records = document("trajectories.json")
    require(len(records) == 144 and len({r["run_id"] for r in records}) == 144, "trajectory_denominator")
    require("requests.jsonl" in evidence and "synthetic-http.jsonl" in evidence, "missing_interval_sources")
    events = jsonl(evidence["requests.jsonl"])
    pairs = request_pairs(events)
    waits = jsonl(evidence["synthetic-http.jsonl"])
    require(len(waits) == len(pairs), "synthetic_interval_denominator")
    require(calibration["all_synthetic_http_intervals"] == waits, "synthetic_intervals_summary_changed")
    by_attempt = {}
    for index, ((dispatch, complete), wait) in enumerate(zip(pairs, waits), 1):
        require(wait["request_index"] == index, "synthetic_request_order")
        begin = seconds(wait["started_monotonic_s"], "synthetic_start")
        end = seconds(wait["ended_monotonic_s"], "synthetic_end")
        same(wait["actual_wait_s"], end - begin, "synthetic_wait")
        require(dispatch["start_monotonic_s"] <= begin <= end <= complete["end_monotonic_s"],
                "synthetic_wait_outside_http")
        key = (dispatch["run_id"], dispatch["labels"]["case_id"])
        require(key not in by_attempt, "duplicate_attempt_request")
        by_attempt[key] = (wait, dispatch, complete)
    setups, samples, consumed, conditions = [], [], set(), set()
    for record in records:
        if record["status"] == "not_started":
            require(not record["attempts"], "unstarted_has_attempts")
            continue
        run_id = record["run_id"]
        require(document("trajectories/" + run_id + "/trajectory.json") == record, "trajectory_copies_differ")
        require(record["cohort"] == "native" and record["model"] == "deepseek-flash"
                and record["repeat"] == 1 and record["number"] in TASKS
                and record["policy"] in {"repair", "resample"}, "unexpected_calibration_condition")
        condition = (record["number"], record["policy"])
        require(condition not in conditions, "duplicate_calibration_condition")
        conditions.add(condition)
        planned_delay = 1 if condition == (55, "repair") else 0
        require(record["delay_s"] == planned_delay, "calibration_delay_changed")
        attempts = record["attempts"]
        require(len(attempts) == 3 and [a["status"] for a in attempts] ==
                ["eligible", "eligible", "late_response_accounted_only"], "incomplete_calibration_rounds")
        setup = seconds(attempts[0]["started_at_s"], "setup_once")
        same(record["setup_once_s"], setup, "setup_once")
        setups.append({"run_id": run_id, "setup_once_s": setup})
        previous_end = setup
        for attempt in attempts:
            candidate_id = attempt["candidate_id"]
            key = (run_id, candidate_id)
            require(key in by_attempt, "attempt_missing_dispatch")
            consumed.add(key)
            wait, dispatch, complete = by_attempt[key]
            start, end = attempt["started_at_s"], attempt["ended_at_s"]
            same(start, previous_end, "round_gap")
            interval = seconds(end - start, "round_interval")
            same(attempt["online_interval_s"], interval, "round_interval")
            previous_end = end
            task_ready = seconds(record["task_ready_monotonic_s"], "task_ready")
            require(task_ready + start <= dispatch["start_monotonic_s"] <=
                    complete["end_monotonic_s"] <= task_ready + end + TOLERANCE_S, "http_outside_round")
            if attempt["status"] != "eligible":
                continue
            prefix = "trajectories/" + run_id + "/" + candidate_id + "/"
            checker = document(prefix + "public/check/public-result.json")
            require(checker == document(attempt["public_path"]) and checker["visibility"] == "public"
                    and checker["task_id"] == record["task_id"], "public_checker_identity")
            checker_wall = seconds(checker["wall_s"], "checker_wall")
            same(attempt["checker_wall_s"], checker_wall, "checker_wall")
            wrapper = attempt["public_returned_at_s"] - attempt["public_started_at_s"]
            same(attempt["public_wall_s"], wrapper, "public_wrapper")
            require(wrapper + TOLERANCE_S >= checker_wall, "checker_exceeds_wrapper")
            actual_delay = seconds(attempt["injected_delay_actual_s"], "injected_delay")
            require(actual_delay + TOLERANCE_S >= planned_delay, "injected_delay_too_short")
            other = seconds(interval - wait["actual_wait_s"] - checker_wall - actual_delay, "round_other")
            samples.append({"run_id": run_id, "candidate_id": candidate_id, "task_id": record["task_id"],
                "policy": record["policy"], "cohort": record["cohort"], "outcome": attempt["status"],
                "started_at_s": start, "ended_at_s": end, "online_interval_s": interval,
                "synthetic_http": wait, "public_checker_wall_s": checker_wall,
                "public_wrapper_wall_s": wrapper, "injected_delay_planned_s": planned_delay,
                "injected_delay_actual_s": actual_delay, "round_other_s": other})
    require(conditions == {(n, p) for n in TASKS for p in ("repair", "resample")}
            and len(setups) == 16 and len(samples) == 32 and consumed == set(by_attempt), "calibration_coverage")
    require(len(calibration["setups"]) == 16 and len(calibration["samples"]) == 32, "summary_sample_count")
    for actual, reported in zip(setups, calibration["setups"]):
        require(reported["run_id"] == actual["run_id"], "setup_order")
        same(reported["setup_once_s"], actual["setup_once_s"], "setup_summary")
    for actual, reported in zip(samples, calibration["samples"]):
        for key, value in actual.items():
            if type(value) in (int, float):
                same(reported[key], value, "sample_" + key)
            else:
                require(reported[key] == value, "sample_identity:" + key)
    calculated = {**prior, "setup_once_p90_s": p90([s["setup_once_s"] for s in setups]),
                  "round_other_p90_s": p90([s["round_other_s"] for s in samples])}
    for key, value in calculated.items():
        if key != "prior_source_count":
            same(calibration[key], value, key)
    short = max(5, math.ceil(sum(calculated[k] for k in ("prior_http_p90_s", "prior_public_p90_s",
                    "setup_once_p90_s", "round_other_p90_s")) + 1))
    guard = max(64, math.ceil(3 * short / calculated["min_prior_http_s"]) + 2)
    require(calibration["deadlines_s"] == [short, 3 * short] and calibration["max_rounds"] == guard,
            "deadline_or_round_guard_mismatch")
    require(calibration["quantile_method"] == "nearest_rank_1_based_ceil_p_times_n", "quantile_method")
    return {**calculated, "deadlines_s": [short, 3 * short], "max_rounds": guard,
            "setup_count": len(setups), "round_count": len(samples), "verified": True}


def verify_calibration(calibration: dict) -> dict:
    """Verify without executing tools; all malformed/drifted evidence raises ValueError."""
    try:
        return _verify_calibration(calibration)
    except (OSError, KeyError, TypeError, IndexError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("deadline_calibration_"):
            raise
        raise ValueError("deadline_calibration_invalid_evidence:" + type(exc).__name__) from exc
