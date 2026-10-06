"""Pure offline R3 development analysis. Standard library only; no executor import.

Read a terminal raw batch and its independent hidden-score directory, then
write fresh redacted JSON/CSV tables. Never run candidates, Docker or a model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

MODELS = ("deepseek-flash", "deepseek-v4-pro")
TASKS = (55, 32, 7, 56, 16, 99, 18, 31)
STATUS = ("pass", "fail", "timeout", "infra", "no_candidate", "not_evaluated", "not_started")
IDENTITY = ("run_id", "cohort", "task_id", "number", "model", "policy", "delay_s", "repeat")
GROUP = ("cohort", "exclude_he32", "stratum", "model", "policy", "delay_s", "deadline_s")
LIMITS = {
    "scope": "eight development tasks and one conditional HE99 state; not full EvalPlus or broad model ranking",
    "units": "144 physical trajectories, 288 correlated prefix snapshots; task groups are the inference units",
    "status": "no_candidate is no eligible delivery from an executed trajectory; not_started/not_evaluated/infra is unknown quality, never an observed failure",
    "rates": "pass_rate uses the complete planned/stratum denominator; with unknown quality it is only observed success proportion",
    "baseline": "attempt 1, independently gated by each cutoff; a later eligible program never replaces the baseline",
    "stratum": "native attempt 1 format failure or parsed public fail/timeout only; common is not applicable because repair already receives seed feedback",
    "cost": "physical known usage costs counted once; cutoff/selected cost splits attribute full eventual request bills by dispatch time",
    "post_selection_cost": "continuing after public perfection is the frozen experimental protocol; post-selection fees are not automatically avoidable deployment waste",
    "unknown_cost": "per-request unresolved liability is separate from the terminal whole-batch hold; never add both",
    "transitions": "descriptive adjacent attempts; common seed-to-attempt-1 edges are separate; timeout counts as observed failure, infra/missing scores break known comparisons",
    "common": "conditional on one Flash-produced HE99 fallback; never pooled with native starts; absence of fallback improvement is unknown for incomplete trajectories",
    "he32": "full operational denominator and exclusion sensitivity; retain known numerical oracle/input-mutation limitation",
    "inference": "no p values, confidence intervals, fitted crossing times or causal claims from before/after traces",
    "task_threshold": "three distinct task groups meets only the prespecified minimum support threshold; it does not establish a cross-task effect",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def money(value):
    result = Decimal(str(value))
    require(result.is_finite() and result >= 0, "invalid_money")
    return result


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value), "invalid_time")
    return value


def contained(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "artifact_path_escape")
    result = (root / path).resolve()
    require(result.is_relative_to(root) and result != root, "artifact_path_escape")
    return result


def files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "artifact_symlink")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = file_hash(path)
    return result


def hidden_status(identity, scores, *, attempt=False):
    if identity is None:
        return "no_persisted_candidate" if attempt else "no_candidate"
    return scores.get(identity, {}).get("hidden", {}).get("status", "not_evaluated")


def success(status):
    return 1 if status == "pass" else 0 if status in {"fail", "timeout", "no_candidate"} else None


def load_closed(raw_root, score_root):
    raw_root, score_root = raw_root.resolve(), score_root.resolve()
    require(raw_root != score_root and not raw_root.is_relative_to(score_root)
            and not score_root.is_relative_to(raw_root), "raw_and_score_must_be_separate")
    require(not (raw_root / "pilot.lock").exists(), "raw_batch_still_locked")
    plan = read(raw_root / "plan.json")
    raw_ledger = (raw_root / "deadline-ledger.jsonl").read_bytes()
    require(raw_ledger.endswith(b"\n"), "torn_deadline_ledger")
    ledger, previous = [], None
    for line in raw_ledger.splitlines():
        event = json.loads(line)
        require(canonical(event) == line and event["seq"] == len(ledger) and event["previous_sha256"] == previous
                and event["sha256"] == digest({k: v for k, v in event.items() if k != "sha256"}), "invalid_deadline_ledger")
        ledger.append(event)
        previous = event["sha256"]
    require(len(ledger) == 3 and ledger[0]["event"] == "open"
            and ledger[0]["data"]["plan_sha256"] == digest(plan) and ledger[1]["event"] == "reserve"
            and ledger[-1]["event"] in {"settle", "stop"}, "deadline_not_terminal")
    expected_refs = {name: file_hash(raw_root / name) for name in
                     ("requests.jsonl", "result.json", "generation-closed.json", "trajectories.json")}
    require(ledger[-1]["data"]["artifacts"] == expected_refs, "terminal_artifacts_changed")
    result, closure = read(raw_root / "result.json"), read(raw_root / "generation-closed.json")
    require(result["plan_sha256"] == digest(plan), "result_plan_changed")
    for document in (result, closure):
        require(document["http_closed"] is True and document["public_resources_closed"] is True
                and document["denominator"] == 144 and document["requests_sha256"] == expected_refs["requests.jsonl"]
                and document["trajectories_sha256"] == expected_refs["trajectories.json"], "raw_resources_not_closed")
    journal_raw = (raw_root / "requests.jsonl").read_bytes()
    require(journal_raw.endswith(b"\n"), "torn_request_journal")
    journal = [json.loads(line) for line in journal_raw.splitlines()]
    require(journal[0]["event"] == "batch_open" and journal[-1]["event"] == "batch_close"
            and journal[-1]["active_calls"] == 0, "request_journal_not_closed")
    manifest, score_summary = read(score_root / "manifest.json"), read(score_root / "summary.json")
    require(Path(manifest["input_root"]).resolve() == raw_root and manifest["plan_sha256"] == digest(plan)
            and manifest["deadline_terminal_sha256"] == ledger[-1]["sha256"], "score_input_binding_changed")
    require(score_summary["manifest_sha256"] == file_hash(score_root / "manifest.json")
            and score_summary["status"] in {"complete", "stopped"} and score_summary["input_unchanged"] is True
            and score_summary["hidden_resources_closed"] is True, "score_not_closed_or_input_changed")
    raw_files = files(raw_root)
    require(raw_files == manifest["input_files"], "raw_files_differ_from_score_manifest")
    seed_public = read(raw_root / "common-seed-public.json")
    # The runner reserializes this copy; its exact bytes are bound above by the
    # scorer input inventory, rather than the ancestor's differently spaced JSON.
    require(type(seed_public["passed"]) is int and type(seed_public["total"]) is int
            and 0 <= seed_public["passed"] < seed_public["total"] and seed_public["status"] == "fail",
            "common_seed_public_changed")
    score_files = files(score_root)
    records = read(raw_root / "trajectories.json")
    baselines, snapshots, scored_attempts, scores = [read(score_root / name) for name in
        ("baselines.json", "snapshots.json", "attempts.json", "scores.json")]
    require(len(records) == len(plan["trajectories"]) == len(baselines) == 144 and len(snapshots) == 288,
            "analysis_requires_full_144_288_denominator")
    expected = Counter((cohort, number, model, policy, delay, repeat)
        for cohort, numbers in (("native", TASKS), ("common", (99,))) for number in numbers
        for model in MODELS for policy in ("resample", "repair") for delay in (0, 1) for repeat in (1, 2))
    require(Counter((r["cohort"], r["number"], r["model"], r["policy"], r["delay_s"], r["repeat"])
                    for r in plan["trajectories"]) == expected, "frozen_matrix_changed")
    by_id = {r["run_id"]: r for r in records}
    require(len(by_id) == 144 and len(plan["deadlines_s"]) == 2
            and 0 < finite(plan["deadlines_s"][0]) < finite(plan["deadlines_s"][1]), "invalid_frozen_plan")
    candidate_hashes = {"common-seed": plan["seed_ref"]["candidate_sha256"]}
    attempt_by_id = {}
    resource_refs = []
    for frozen, row, baseline in zip(plan["trajectories"], records, baselines):
        require(all(row[k] == baseline[k] == frozen[k] for k in IDENTITY)
                and row["task_id"] == f"HumanEval/{row['number']}"
                and row["status"] in {"complete", "stopped", "interrupted", "not_started"}, "trajectory_identity_changed")
        require(row["status"] == "not_started" or "baseline" in row, "started_baseline_missing")
        require(baseline["baseline"] == row.get("baseline", {"attempt": 1, "outcome": "not_started", "candidate": None}),
                "scored_baseline_changed")
        for index, attempt in enumerate(row["attempts"], 1):
            require(attempt["candidate_id"] == f"attempt-{index:02d}", "attempt_order_changed")
            key = row["run_id"] + "/" + attempt["candidate_id"]
            attempt_by_id[key] = attempt
            if "candidate_path" in attempt:
                require(attempt.get("parse", {}).get("status") == "parsed"
                        and file_hash(contained(raw_root, attempt["candidate_path"])) == attempt["code_sha256"], "candidate_hash_changed")
                candidate_hashes[key] = attempt["code_sha256"]
            if "public_started_at_s" in attempt:
                resource_refs.append(attempt["public_resource"])
    require(Counter(canonical(r) for r in resource_refs) == Counter(canonical(r) for r in closure["public_resources"]),
            "public_resource_inventory_changed")
    for ref in resource_refs:
        path = contained(raw_root, ref["path"])
        doc = read(path)
        require(file_hash(path) == ref["sha256"] and all(doc[k] is True for k in
                ("closed", "worker_reaped", "containers_removed")), "public_resource_not_closed")
    require(set(scores) <= set(candidate_hashes), "unexpected_scored_identity")
    for identity, item in scores.items():
        require(item["identity"] == identity and item["code_sha256"] == candidate_hashes[identity]
                and item["hidden"]["status"] in {"pass", "fail", "timeout", "infra"}, "score_identity_changed")
        for relative, sha in item["evidence"].items():
            require(file_hash(contained(score_root, relative)) == sha, "hidden_score_evidence_changed")
        results = [p for p in item["evidence"] if p.endswith("/hidden-result.json")]
        require(len(results) == 1, "hidden_result_reference_missing")
        actual = read(contained(score_root, results[0]))
        require(item["hidden"] == actual or (item["resources_closed"] is False and item["hidden"]["status"] == "infra"
                and item["hidden"].get("reason") == "hidden_resource_unclosed"), "hidden_result_changed")
    require(len(scored_attempts) == len(attempt_by_id), "scored_attempt_denominator_changed")
    seen = set()
    for item in scored_attempts:
        key = item["run_id"] + "/" + item["candidate_id"]
        require(key in attempt_by_id and key not in seen and item["attempt_status"] == attempt_by_id[key]["status"],
                "scored_attempt_identity_changed")
        seen.add(key)
        expected_identity = key if key in candidate_hashes else None
        require(item["score_identity"] == expected_identity
                and item["hidden_status"] == hidden_status(expected_identity, scores, attempt=True), "scored_attempt_status_changed")
    for index, item in enumerate(snapshots):
        row, cutoff = records[index // 2], plan["deadlines_s"][index % 2]
        require(all(item[k] == row[k] for k in IDENTITY) and item["snapshot_index"] == index % 2
                and item["deadline_s"] == cutoff and item["snapshot"] == row["snapshots"][index % 2], "scored_snapshot_changed")
        snapshot = item["snapshot"]
        ref = snapshot["selected"] if snapshot else None
        identity = None if ref is None else "common-seed" if ref["candidate_id"] == "seed" else row["run_id"] + "/" + ref["candidate_id"]
        require(item["score_identity"] == identity and item["hidden_status"] == hidden_status(identity, scores), "snapshot_score_changed")
        if snapshot:
            path = contained(raw_root, snapshot["path"])
            require(file_hash(path) == snapshot["sha256"] and all(snapshot.get(k) == v for k, v in read(path).items()),
                    "snapshot_file_changed")
        if ref:
            require(identity in candidate_hashes and ref["code_sha256"] == candidate_hashes[identity]
                    and finite(ref["available_at_s"]) < cutoff, "snapshot_candidate_binding_changed")
    for row, item in zip(records, baselines):
        ref = item["baseline"].get("candidate")
        identity = row["run_id"] + "/attempt-01" if ref else None
        require(item["score_identity"] == identity and item["hidden_status"] == hidden_status(identity, scores), "baseline_score_changed")
        if ref:
            require(ref["candidate_id"] == "attempt-01" and candidate_hashes.get(identity) == ref["code_sha256"], "baseline_not_attempt_one")
    require(score_summary["snapshot_denominator"] == 288 and score_summary["baseline_denominator"] == 144
            and score_summary["snapshot_status_counts"] == dict(Counter(s["hidden_status"] for s in snapshots)), "score_summary_counts_changed")
    return {"raw_root": raw_root, "score_root": score_root, "plan": plan, "records": records, "journal": journal,
            "scores": scores, "baselines": baselines, "snapshots": snapshots, "terminal": ledger[-1], "result": result,
            "raw_files": raw_files, "score_files": score_files, "score_summary": score_summary, "seed_public": seed_public}


def request_rows(data):
    records = {r["run_id"]: r for r in data["records"]}
    dispatched, ended = {}, {}
    for event in data["journal"]:
        if event["event"] == "request_dispatch":
            require(event["request_id"] not in dispatched, "duplicate_request_dispatch")
            dispatched[event["request_id"]] = event
        elif event["event"] in {"request_complete", "request_unknown"}:
            require(event["request_id"] not in ended, "duplicate_request_terminal")
            ended[event["request_id"]] = event
    require(set(ended) <= set(dispatched), "unpaired_request_terminal")
    output = {}
    for rid, event in dispatched.items():
        labels, done = event["labels"], ended.get(rid)
        row = records[labels["run_id"]]
        require(all(labels[k] == row[k] for k in ("run_id", "task_id", "model", "repeat")), "request_condition_changed")
        key = row["run_id"] + "/" + labels["case_id"]
        require(key not in output and any(a["candidate_id"] == labels["case_id"] for a in row["attempts"]), "request_attempt_changed")
        known = done is not None and done["event"] == "request_complete"
        cost = money(done["provider_usage_peak_estimate_cny"]) if known else Decimal(0)
        liability = Decimal(0) if known else max(money(event["reservation_cny"]), money(done.get("provider_usage_peak_estimate_cny") or 0) if done else Decimal(0))
        usage = (done.get("usage") or {}) if known else {}
        if known:
            require(all(type(usage.get(k)) is int and usage[k] >= 0 for k in
                        ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "completion_tokens")), "cache_usage_missing")
        ready = finite(row["task_ready_monotonic_s"])
        start = finite(event["dispatch_monotonic_s"]) - ready
        end = finite(done["end_monotonic_s"]) - ready if done and done.get("end_monotonic_s") is not None else None
        require(start >= 0 and (end is None or end >= start), "request_time_order_invalid")
        attempt = next(a for a in row["attempts"] if a["candidate_id"] == labels["case_id"])
        require(attempt.get("started_at_s") is None or finite(attempt["started_at_s"]) <= start + 1e-6,
                "request_before_attempt")
        require(attempt.get("available_at_s") is None or start <= finite(attempt["available_at_s"]) + 1e-6,
                "request_after_candidate_available")
        output[key] = {"request_id": rid, "dispatch_s": start, "http_end_s": end,
            "http_duration_s": None if end is None else end - start, "known_cost_cny": cost,
            "unknown_liability_cny": liability, "known_usage": known, "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
            "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
    known_total = sum((r["known_cost_cny"] for r in output.values()), Decimal(0))
    require(data["journal"][-1]["calls_dispatched"] == len(output)
            and money(data["journal"][-1]["spent_estimate_cny"]) == known_total, "request_cost_accounting_changed")
    if data["terminal"]["event"] == "settle":
        require(all(r["known_usage"] for r in output.values())
                and money(data["terminal"]["data"]["cost_cny"]) == known_total, "settled_cost_changed")
    return output


def baseline_at(baseline, deadline):
    ref = baseline["baseline"].get("candidate")
    return baseline["hidden_status"] if ref and finite(ref["available_at_s"]) < deadline else "no_candidate"


def observation_statuses(row, baseline, scored, cutoff):
    if row["status"] == "not_started":
        return "not_started", "not_started"
    start = baseline_at(baseline, cutoff)
    snapshot = scored["snapshot"]
    if snapshot is None or snapshot["status"] == "stopped_before_cutoff":
        # An already delivered attempt-1 baseline remains known. An unfinished
        # attempt with no delivery cannot establish a no-candidate result at D.
        if start == "no_candidate" and baseline["baseline"].get("outcome") != "parse_failed":
            start = "not_evaluated"
        return start, "not_evaluated"
    return start, scored["hidden_status"]


def failure_stratum(attempts, trajectory_status="complete"):
    if trajectory_status == "not_started":
        return None
    if not attempts:
        return False if trajectory_status == "complete" else None
    first = attempts[0]
    if first.get("parse", {}).get("status") == "parse_failed" or first["status"] == "parse_failed":
        return True
    if first.get("parse", {}).get("status") == "parsed" and first.get("public_status") in {"pass", "fail", "timeout"}:
        return first["public_status"] in {"fail", "timeout"}
    return False if trajectory_status == "complete" else None


def common_seed_edge(row, scores, seed_public):
    """Keep the supplied fallback separate from newly generated attempt baselines."""
    first = row["attempts"][0] if row["attempts"] else None
    identity = row["run_id"] + "/attempt-01" if first and "candidate_path" in first else None
    before, after = hidden_status("common-seed", scores), hidden_status(identity, scores, attempt=True)
    if row["status"] == "not_started":
        after = "not_started"
    known_after = after in {"pass", "fail", "timeout"}
    parse_failed = first is not None and (first["status"] == "parse_failed" or first.get("parse", {}).get("status") == "parse_failed")
    public = first.get("public_passed") if first else None
    return {**{k: row[k] for k in IDENTITY}, "transition": "common_seed_to_attempt1",
        "trajectory_status": row["status"], "attempt1_status": first["status"] if first else "not_started" if row["status"] == "not_started" else "no_attempt",
        "from_identity": "common-seed", "to_identity": identity, "seed_public_passed": seed_public["passed"],
        "seed_public_total": seed_public["total"], "seed_hidden_status": before, "attempt1_hidden_status": after,
        "attempt1_public_passed": public, "public_improved": public > seed_public["passed"] if public is not None else None,
        "correct_after_public_failure": False if parse_failed else after == "pass" if known_after else None,
        "hidden_fail_to_pass": after == "pass" if before in {"fail", "timeout"} and known_after else None}


def common_fallback_summary(physical):
    common = [r for r in physical if r["cohort"] == "common"]
    observed = sum(r["never_improved_common_fallback"] is not None for r in common)
    return {"count": sum(r["never_improved_common_fallback"] is True for r in common),
        "denominator": len(common), "observed_denominator": observed,
        "not_started_denominator": sum(r["status"] == "not_started" for r in common),
        "unknown_count": len(common) - observed}


def common_fallback_outcome(row, best, seed_passed):
    if row["cohort"] != "common":
        return None
    if best > seed_passed:
        return False
    return True if row["status"] == "complete" else None


def cost_segments(requests, cutoff, selected_at):
    """Attribute full eventual bills by dispatch, retaining unknown liabilities."""
    groups = {
        "prefix": [r for r in requests if r["dispatch_s"] < cutoff],
        "before_selection": None if selected_at is None else [r for r in requests if r["dispatch_s"] < selected_at],
        "after_selection": None if selected_at is None else [r for r in requests if selected_at <= r["dispatch_s"] < cutoff],
        "after_cutoff": [r for r in requests if r["dispatch_s"] >= cutoff],
    }
    result = {}
    for name, members in groups.items():
        cost_key = "prefix_known_cost_cny" if name == "prefix" else "known_cost_" + name + "_cny"
        result[cost_key] = None if members is None else str(sum((r["known_cost_cny"] for r in members), Decimal(0)))
        result[name + "_unknown_requests"] = None if members is None else sum(not r["known_usage"] for r in members)
        result[name + "_unknown_liability_cny"] = None if members is None else str(sum((r["unknown_liability_cny"] for r in members), Decimal(0)))
    result["requests_dispatched_before_cutoff"] = len(groups["prefix"])
    result["requests_after_selection"] = None if groups["after_selection"] is None else len(groups["after_selection"])
    return result


def score_reporting(summary):
    return {"score_status": summary["status"], "score_stop_reason": summary["stop_reason"],
            "unscored_identity_count": summary["unscored_identity_count"]}


def aggregate(rows, keys):
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row[k] for k in keys)].append(row)
    output = []
    for group, members in sorted(grouped.items()):
        counts = Counter(r["hidden_status"] for r in members)
        baseline_counts = Counter(r["baseline_status"] for r in members)
        gains = [r["gain"] for r in members if r["gain"] is not None]
        tasks = {r["task_id"] for r in members}
        output.append({**dict(zip(keys, group)), "n_trajectories": len(members), "n_tasks": len(tasks),
            **{"n_" + status: counts[status] for status in STATUS}, "pass_rate": counts["pass"] / len(members),
            **{"baseline_n_" + status: baseline_counts[status] for status in STATUS},
            "baseline_pass_rate": sum(r["baseline_status"] == "pass" for r in members) / len(members),
            "n_gain_observed": len(gains), "mean_gain": sum(gains) / len(gains) if gains else None,
            "quality_fully_observed": counts["infra"] + counts["not_evaluated"] + counts["not_started"] == 0,
            "baseline_fully_observed": baseline_counts["infra"] + baseline_counts["not_evaluated"] + baseline_counts["not_started"] == 0,
            "n_censored": sum(bool(r.get("censored")) for r in members),
            "n_guard_censored": sum(r.get("stop_reason") in {"request_guard_censored", "max_rounds_censored"} for r in members),
            "n_interrupted": sum(r.get("trajectory_status") == "interrupted" for r in members),
            "n_stopped_before_cutoff": sum(r.get("snapshot_status") == "stopped_before_cutoff" for r in members),
            "cross_task_inference_supported": len(tasks) >= 3 and members[0]["cohort"] == "native"})
    return output


def analyze(data):
    requests = request_rows(data)
    attempts, trajectories, observations = [], [], []
    for row, baseline in zip(data["records"], data["baselines"]):
        labels = {k: row[k] for k in IDENTITY}
        own_requests = [requests[row["run_id"] + "/" + a["candidate_id"]] for a in row["attempts"]
                        if row["run_id"] + "/" + a["candidate_id"] in requests]
        first = row.get("first_eligible")
        previous, best = None, (data["seed_public"]["passed"] if row["cohort"] == "common" else -1)
        stratum = failure_stratum(row["attempts"], row["status"]) if row["cohort"] == "native" else None
        for index, attempt in enumerate(row["attempts"], 1):
            identity = row["run_id"] + "/" + attempt["candidate_id"]
            request = requests.get(identity)
            status = hidden_status(identity if "candidate_path" in attempt else None, data["scores"], attempt=True)
            public = attempt.get("public_passed")
            eligible = attempt["status"] == "eligible"
            selection_change = eligible and public > best
            public_improved = (previous is not None and public is not None and previous.get("public_passed") is not None
                               and public > previous["public_passed"])
            prior_hidden = previous.get("hidden_status") if previous else None
            item = {**labels, "candidate_id": attempt["candidate_id"], "attempt_index": index,
                "status": attempt["status"], "hidden_status": status, "public_status": attempt.get("public_status"),
                "public_passed": public, "public_total": attempt.get("public_total"), "eligible": eligible,
                "available_at_s": attempt.get("available_at_s"), "started_at_s": attempt.get("started_at_s"),
                "ended_at_s": attempt.get("ended_at_s"), "response_received_at_s": attempt.get("response_received_at_s"),
                "public_started_at_s": attempt.get("public_started_at_s"), "public_returned_at_s": attempt.get("public_returned_at_s"),
                "late_http": attempt["status"] == "late_response_accounted_only", "selection_changed": selection_change,
                "additional_sample_no_selection_change": index > 1 and eligible and not selection_change,
                "public_improved": public_improved,
                "public_regression": bool(previous and public is not None and previous.get("public_passed") is not None and public < previous["public_passed"]),
                "correct_after_public_failure": bool(previous and previous.get("public_status") in {"fail", "timeout"} and status == "pass"),
                "hidden_fail_to_pass": prior_hidden in {"fail", "timeout"} and status == "pass",
                "hidden_regression": prior_hidden == "pass" and status in {"fail", "timeout"},
                "unchanged_failure": bool(previous and prior_hidden in {"fail", "timeout"} and status in {"fail", "timeout"}
                    and previous.get("code_sha256") == attempt.get("code_sha256")),
                "code_sha256": attempt.get("code_sha256"), "request_id": request["request_id"] if request else None,
                "known_cost_cny": str(request["known_cost_cny"]) if request else "0",
                "unknown_liability_cny": str(request["unknown_liability_cny"]) if request else "0",
                "dispatch_s": request["dispatch_s"] if request else None,
                "http_end_s": request["http_end_s"] if request else None,
                "http_duration_s": request["http_duration_s"] if request else None,
                "cache_hit_tokens": request["cache_hit_tokens"] if request else 0,
                "cache_miss_tokens": request["cache_miss_tokens"] if request else 0,
                "completion_tokens": request["completion_tokens"] if request else 0}
            attempts.append(item)
            previous = item
            if eligible:
                best = max(best, public)
        trajectories.append({**labels, "status": row["status"], "stop_reason": row.get("stop_reason"),
            "censored": row.get("censored", False), "guard_reason": row.get("guard_reason"),
            "attempts_total": len(row["attempts"]),
            "completed_rounds": sum(a["status"] in {"eligible", "parse_failed"} for a in row["attempts"]),
            "eligible_rounds": sum(a["status"] == "eligible" for a in row["attempts"]),
            "parsed_rounds": sum(a.get("parse", {}).get("status") == "parsed" for a in row["attempts"]),
            "tool_rounds": sum("public_started_at_s" in a for a in row["attempts"]),
            "requests_dispatched": len(own_requests), "http_completed_requests": sum(r["known_usage"] for r in own_requests),
            "unknown_requests": sum(not r["known_usage"] for r in own_requests),
            "known_cost_cny": str(sum((r["known_cost_cny"] for r in own_requests), Decimal(0))),
            "unknown_liability_cny": str(sum((r["unknown_liability_cny"] for r in own_requests), Decimal(0))),
            "first_eligible_s": first["available_at_s"] if first else None,
            "online_closed_s": row.get("closed_at_s"), "drain_wall_s": row.get("drain_wall_s"),
            "late_http_requests": sum(a["status"] == "late_response_accounted_only" for a in row["attempts"]),
            "late_http_known_cost_cny": str(sum((requests[row["run_id"] + "/" + a["candidate_id"]]["known_cost_cny"]
                for a in row["attempts"] if a["status"] == "late_response_accounted_only"
                and row["run_id"] + "/" + a["candidate_id"] in requests), Decimal(0))),
            "cache_hit_tokens": sum(r["cache_hit_tokens"] for r in own_requests),
            "cache_miss_tokens": sum(r["cache_miss_tokens"] for r in own_requests),
            "first_attempt_failure_stratum": stratum,
            "never_improved_common_fallback": common_fallback_outcome(row, best, data["seed_public"]["passed"])})
        for index, cutoff in enumerate(data["plan"]["deadlines_s"]):
            scored = data["snapshots"][len(observations)]
            snapshot = scored["snapshot"]
            ref = snapshot["selected"] if snapshot else None
            when = ref["available_at_s"] if ref else None
            start_status, end_status = observation_statuses(row, baseline, scored, cutoff)
            start_success, end_success = success(start_status), success(end_status)
            observations.append({**labels, "deadline_s": cutoff, "snapshot_index": index,
                "hidden_status": end_status, "baseline_status": start_status,
                "gain": end_success - start_success if start_success is not None and end_success is not None else None,
                "trajectory_status": row["status"], "stop_reason": row.get("stop_reason"),
                "censored": row.get("censored", False), "guard_reason": row.get("guard_reason"),
                "snapshot_status": snapshot["status"] if snapshot else "not_started",
                "selected_identity": scored["score_identity"], "selected_available_s": when,
                "selected_public_passed": ref["public_passed"] if ref else None,
                "snapshot_callback_s": snapshot.get("callback_at_s") if snapshot else None,
                "snapshot_persisted_s": snapshot.get("persisted_at_s") if snapshot else None,
                "snapshot_lag_s": snapshot.get("scheduling_lag_s") if snapshot else None,
                **cost_segments(own_requests, cutoff, when),
                "first_attempt_failure_stratum": stratum})
    expanded = [{**r, "exclude_he32": exclude, "stratum": stratum}
        for r in observations for exclude in (0, 1) if not exclude or r["number"] != 32
        for stratum in ("all", "first_attempt_public_or_format_failure")
        if stratum == "all" or r["first_attempt_failure_stratum"]]
    conditions, task_conditions = aggregate(expanded, GROUP), aggregate(expanded, (*GROUP, "task_id"))
    # Keep empty prespecified strata visible as zero-denominator rows.
    present = {tuple(r[k] for k in GROUP) for r in conditions}
    for row in list(conditions):
        if row["stratum"] != "all" or row["cohort"] != "native":
            continue
        empty = {**row, "stratum": "first_attempt_public_or_format_failure"}
        if tuple(empty[k] for k in GROUP) not in present:
            empty.update(n_trajectories=0, n_tasks=0, pass_rate=None, baseline_pass_rate=None,
                n_gain_observed=0, mean_gain=None, quality_fully_observed=True, baseline_fully_observed=True,
                cross_task_inference_supported=False, n_censored=0, n_guard_censored=0, n_interrupted=0, n_stopped_before_cutoff=0,
                **{"n_" + s: 0 for s in STATUS}, **{"baseline_n_" + s: 0 for s in STATUS})
            conditions.append(empty)
    contrasts = []
    for contrast, axis, left, right in (("repair_minus_resample", "policy", "repair", "resample"),
                                      ("flash_minus_pro", "model", MODELS[0], MODELS[1])):
        keys = tuple(k for k in (*GROUP, "task_id") if k != axis)
        pairs = defaultdict(dict)
        for row in task_conditions:
            pairs[tuple(row[k] for k in keys)][row[axis]] = row
        for group, pair in sorted(pairs.items()):
            l, r = pair.get(left), pair.get(right)
            observed = bool(l and r and l["quality_fully_observed"] and r["quality_fully_observed"])
            baseline_observed = bool(l and r and l["baseline_fully_observed"] and r["baseline_fully_observed"])
            contrasts.append({**dict(zip(keys, group)), "contrast": contrast,
                "left_n": l["n_trajectories"] if l else 0, "right_n": r["n_trajectories"] if r else 0,
                "paired_observed": observed, "pass_rate_difference": l["pass_rate"] - r["pass_rate"] if observed else None,
                "baseline_paired_observed": baseline_observed,
                "baseline_rate_difference": l["baseline_pass_rate"] - r["baseline_pass_rate"] if baseline_observed else None})
    return {"conditions.csv": conditions, "task_conditions.csv": task_conditions, "trajectories.csv": trajectories,
            "observations.csv": observations, "attempts.csv": attempts, "paired_task_contrasts.csv": contrasts,
            "common_seed_transitions.csv": [common_seed_edge(row, data["scores"], data["seed_public"]) for row in data["records"] if row["cohort"] == "common"]}


def write_analysis(raw_root, score_root, output):
    data = load_closed(raw_root, score_root)
    output = output.resolve()
    require(not output.exists() and all(not output.is_relative_to(r) and not r.is_relative_to(output)
            for r in (data["raw_root"], data["score_root"])), "analysis_requires_separate_fresh_output")
    tables = analyze(data)
    output.mkdir(parents=True)
    refs = {}
    for name, rows in tables.items():
        path = output / name
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)) if rows else ["run_id"])
            writer.writeheader()
            writer.writerows(rows)
        refs[name] = {"path": name, "sha256": file_hash(path)}
    physical = tables["trajectories.csv"]
    cache_groups = defaultdict(list)
    for row in physical:
        cache_groups[(row["cohort"], row["model"], row["policy"], row["delay_s"])].append(row)
    cache = []
    for group, rows in sorted(cache_groups.items()):
        hit, miss = sum(r["cache_hit_tokens"] for r in rows), sum(r["cache_miss_tokens"] for r in rows)
        cache.append({**dict(zip(("cohort", "model", "policy", "delay_s"), group)),
            "requests": sum(r["requests_dispatched"] for r in rows), "cache_hit_tokens": hit,
            "cache_miss_tokens": miss, "known_prompt_token_hit_fraction": hit / (hit + miss) if hit + miss else None})
    require(files(data["raw_root"]) == data["raw_files"] and files(data["score_root"]) == data["score_files"],
            "source_changed_during_analysis")
    summary = {"schema": 1, "status": "complete", "provider_calls": 0, "judge_containers": 0,
        "paid_input": data["plan"]["paid"], "fixture_scores": data["score_summary"]["fixture_only"],
        **score_reporting(data["score_summary"]),
        "deadlines_s": data["plan"]["deadlines_s"], "denominators": {"physical": 144, "native": 128, "common": 16, "snapshots": 288},
        "tables": refs, "limitations": LIMITS,
        "cache_by_condition": cache,
        "known_cost_cny": str(sum((money(r["known_cost_cny"]) for r in physical), Decimal(0))),
        "request_unknown_liability_cny": str(sum((money(r["unknown_liability_cny"]) for r in physical), Decimal(0))),
        "study_terminal_event": data["terminal"]["event"], "study_terminal_accounting": data["terminal"]["data"],
        "trajectory_status_counts": dict(Counter(r["status"] for r in physical)),
        "stratum_support": [{"cohort": cohort, "exclude_he32": exclude, "applicable": cohort == "native",
            "n_membership_unknown": sum(r["cohort"] == cohort and r["first_attempt_failure_stratum"] is None and (not exclude or r["number"] != 32) for r in physical) if cohort == "native" else None,
            "n_trajectories": sum(r["cohort"] == cohort and r["first_attempt_failure_stratum"] is True and (not exclude or r["number"] != 32) for r in physical) if cohort == "native" else None,
            "n_tasks": len({r["task_id"] for r in physical if r["cohort"] == cohort and r["first_attempt_failure_stratum"] and (not exclude or r["number"] != 32)}) if cohort == "native" else None,
            "cross_task_inference_supported": len({r["task_id"] for r in physical if r["cohort"] == cohort and r["first_attempt_failure_stratum"] and (not exclude or r["number"] != 32)}) >= 3 if cohort == "native" else None}
            for cohort in ("native", "common") for exclude in (0, 1)],
        "common_never_improved_fallback": common_fallback_summary(physical),
        "common_seed_provenance": data["plan"]["seed_ref"],
        "historical_seed_acquisition_cost": "reported separately in the sealed extension accounting; not the study opening",
        "provenance": {"raw_root": str(data["raw_root"]), "score_root": str(data["score_root"]),
            "raw_files": data["raw_files"], "score_files": data["score_files"],
            "analysis_sha256": file_hash(Path(__file__)), "source_unchanged": True}}
    (output / "summary.json").write_bytes(canonical(summary) + b"\n")
    return summary


def self_test():
    baseline = {"baseline": {"candidate": {"available_at_s": 6}}, "hidden_status": "pass"}
    require(baseline_at(baseline, 5) == "no_candidate" and baseline_at(baseline, 15) == "pass", "baseline_cutoff_test")
    require(baseline_at(baseline, 6) == "no_candidate", "strict_equality_test")
    require(success("no_candidate") == 0 and success("not_evaluated") is None and success("timeout") == 0, "unknown_not_failure_test")
    require(failure_stratum([{"status": "parse_failed"}]) and not failure_stratum([]), "format_stratum_test")
    require(not failure_stratum([{"status": "eligible", "parse": {"status": "parsed"}, "public_status": "pass"}]), "hidden_cannot_choose_stratum_test")
    rows = [{"cohort": "native", "exclude_he32": 0, "stratum": "first_attempt_public_or_format_failure",
             "model": MODELS[0], "policy": "repair", "delay_s": 0, "deadline_s": 5, "task_id": f"HumanEval/{n}",
             "hidden_status": status, "baseline_status": "no_candidate", "gain": gain}
            for n, status, gain in ((55, "pass", 1), (55, "not_evaluated", None), (99, "fail", 0))]
    grouped = aggregate(rows, GROUP)[0]
    require(grouped["n_tasks"] == 2 and grouped["cross_task_inference_supported"] is False
            and grouped["n_gain_observed"] == 2 and grouped["mean_gain"] == .5 and not grouped["quality_fully_observed"], "stratum_and_gain_test")
    common = {"run_id": "common-test", "cohort": "common", "task_id": "HumanEval/99", "number": 99,
        "model": MODELS[0], "policy": "repair", "delay_s": 0, "repeat": 1, "status": "not_started", "attempts": []}
    empty = common_fallback_summary([{**common, "never_improved_common_fallback": None}] * 16)
    require(empty == {"count": 0, "denominator": 16, "observed_denominator": 0,
        "not_started_denominator": 16, "unknown_count": 16}
        and common_seed_edge(common, {}, {"passed": 3, "total": 4})["correct_after_public_failure"] is None, "common_not_started_unknown_test")
    first = {"status": "eligible", "candidate_path": "fixture-only.py", "parse": {"status": "parsed"},
        "public_status": "pass", "public_passed": 4}
    edge = common_seed_edge({**common, "status": "complete", "attempts": [first]}, {
        "common-seed": {"hidden": {"status": "fail"}}, "common-test/attempt-01": {"hidden": {"status": "pass"}}}, {"passed": 3, "total": 4})
    require(edge["correct_after_public_failure"] is True and edge["public_improved"] is True
        and edge["hidden_fail_to_pass"] is True and not failure_stratum([first]), "common_seed_first_success_separate_test")
    requests = [{"dispatch_s": t, "known_cost_cny": money(cost), "known_usage": known,
                 "unknown_liability_cny": money(0 if known else ".20")}
                for t, cost, known in ((1, ".1", True), (3, 0, False), (4, ".2", True), (6, ".4", True))]
    split = cost_segments(requests, 5, 2)
    require(money(split["prefix_known_cost_cny"]) == Decimal(".3")
        and sum((money(split["known_cost_" + segment + "_cny"]) for segment in
                 ("before_selection", "after_selection", "after_cutoff")), Decimal(0)) == Decimal(".7")
        and split["prefix_unknown_requests"] == split["after_selection_unknown_requests"] == 1
        and money(split["after_selection_unknown_liability_cny"]) == Decimal(".20")
        and split["requests_after_selection"] == 2, "unknown_prefix_and_three_cost_segments_test")
    request_fixture = {"records": [{**common, "status": "interrupted", "task_ready_monotonic_s": 100,
        "attempts": [{"candidate_id": "attempt-01", "started_at_s": 0}]}], "terminal": {"event": "stop"},
        "journal": [{"event": "request_dispatch", "request_id": 1, "labels": {**common, "case_id": "attempt-01"},
                     "dispatch_monotonic_s": 101, "reservation_cny": ".2"},
                    {"event": "request_unknown", "request_id": 1, "provider_usage_peak_estimate_cny": ".3"},
                    {"event": "batch_close", "calls_dispatched": 1, "spent_estimate_cny": "0"}]}
    unknown = request_rows(request_fixture)["common-test/attempt-01"]
    require(unknown["http_end_s"] is None and unknown["unknown_liability_cny"] == Decimal(".3"), "unknown_without_end_test")
    unstarted = observation_statuses(common, {"baseline": {"candidate": None}, "hidden_status": "no_candidate"},
                                    {"snapshot": None, "hidden_status": "no_candidate"}, 5)
    missing = aggregate([{**rows[0], "hidden_status": unstarted[1], "baseline_status": unstarted[0], "gain": None}], GROUP)[0]
    require(missing["n_not_started"] == missing["baseline_n_not_started"] == 1
        and missing["n_gain_observed"] == 0 and not missing["quality_fully_observed"]
        and not missing["baseline_fully_observed"], "not_started_unknown_quality_and_gain_test")
    late = observation_statuses({"status": "interrupted"}, {"baseline": {"candidate": None}, "hidden_status": "no_candidate"},
        {"snapshot": {"status": "stopped_before_cutoff"}, "hidden_status": "no_candidate"}, 5)
    require(late == ("not_evaluated", "not_evaluated"), "interrupted_before_cutoff_unknown_test")
    guard = observation_statuses({"status": "complete", "censored": True},
        {"baseline": {"candidate": None}, "hidden_status": "no_candidate"},
        {"snapshot": {"status": "frozen"}, "hidden_status": "no_candidate"}, 5)
    require(guard == ("no_candidate", "no_candidate"), "guard_waited_to_cutoff_observed_test")
    # Tiny in-memory analysis fixture exercises baseline contrasts and cohort
    # handling through the actual table builder, without executor imports.
    records, baselines, snapshots = [], [], []
    for index, (cohort, model) in enumerate((("native", MODELS[0]), ("native", MODELS[1]), ("common", MODELS[0]))):
        row = {**common, "run_id": f"fixture-{index}", "cohort": cohort, "model": model, "status": "complete",
            "attempts": [{**first, "candidate_id": "attempt-01", "public_status": "fail", "public_passed": 2}]}
        ref = {"candidate_id": "attempt-01", "available_at_s": 1, "public_passed": 2}
        records.append(row)
        baselines.append({"baseline": {"candidate": ref}, "hidden_status": "not_evaluated" if index == 0 else "pass"})
        snapshots.extend({"snapshot": {"status": "frozen", "selected": ref}, "hidden_status": "pass",
                          "score_identity": row["run_id"] + "/attempt-01"} for _ in range(2))
    tables = analyze({"records": records, "baselines": baselines, "snapshots": snapshots, "scores": {},
        "seed_public": {"passed": 1, "total": 4}, "plan": {"deadlines_s": [5, 15]},
        "journal": [{"event": "batch_close", "calls_dispatched": 0, "spent_estimate_cny": "0"}],
        "terminal": {"event": "stop"}})
    paired = next(r for r in tables["paired_task_contrasts.csv"] if r["contrast"] == "flash_minus_pro"
                  and r["cohort"] == "native" and r["stratum"] == "all")
    require(paired["paired_observed"] and not paired["baseline_paired_observed"]
        and paired["baseline_rate_difference"] is None, "unknown_baseline_contrast_na_test")
    require(all(r["stratum"] == "all" for r in tables["conditions.csv"] if r["cohort"] == "common")
        and tables["trajectories.csv"][-1]["first_attempt_failure_stratum"] is None
        and tables["trajectories.csv"][-1]["never_improved_common_fallback"] is False,
        "common_no_prefeedback_stratum_and_seed_score_test")
    stopped_score = score_reporting({"status": "stopped", "stop_reason": "fixture_only", "unscored_identity_count": 7})
    require(stopped_score == {"score_status": "stopped", "score_stop_reason": "fixture_only", "unscored_identity_count": 7},
        "score_stop_reporting_test")
    flags = aggregate([{**rows[0], "censored": True, "stop_reason": "request_guard_censored", "trajectory_status": "complete"},
        {**rows[0], "trajectory_status": "interrupted", "snapshot_status": "stopped_before_cutoff",
         "hidden_status": "not_evaluated", "gain": None}], GROUP)[0]
    require(flags["n_guard_censored"] == flags["n_censored"] == flags["n_interrupted"] == flags["n_stopped_before_cutoff"] == 1,
        "guard_and_interrupted_counts_test")
    late_row = {**common, "cohort": "native", "status": "complete", "task_ready_monotonic_s": 100,
        "attempts": [{"candidate_id": "attempt-01", "started_at_s": 0, "status": "late_response_accounted_only"}]}
    late_data = {"records": [late_row], "baselines": [{"baseline": {"candidate": None}, "hidden_status": "no_candidate"}],
        "snapshots": [{"snapshot": {"status": "frozen", "selected": None}, "hidden_status": "no_candidate", "score_identity": None}] * 2,
        "scores": {}, "seed_public": {"passed": 3, "total": 4}, "plan": {"deadlines_s": [5, 15]},
        "terminal": {"event": "settle", "data": {"cost_cny": ".1"}},
        "journal": [{"event": "request_dispatch", "request_id": 1, "labels": {**late_row, "case_id": "attempt-01"},
                     "dispatch_monotonic_s": 104, "reservation_cny": ".2"},
                    {"event": "request_complete", "request_id": 1, "provider_usage_peak_estimate_cny": ".1", "end_monotonic_s": 120,
                     "usage": {"prompt_cache_hit_tokens": 1, "prompt_cache_miss_tokens": 2, "completion_tokens": 3}},
                    {"event": "batch_close", "calls_dispatched": 1, "spent_estimate_cny": ".1"}]}
    late_tables = analyze(late_data)
    require(money(late_tables["trajectories.csv"][0]["late_http_known_cost_cny"]) == Decimal(".1")
        and money(late_tables["observations.csv"][0]["prefix_known_cost_cny"]) == Decimal(".1")
        and late_tables["observations.csv"][0]["hidden_status"] == "no_candidate", "late_http_billed_without_candidate_test")
    require(failure_stratum([], "not_started") is None
        and failure_stratum([{"status": "interrupted"}], "interrupted") is None
        and failure_stratum([{"status": "late_response_accounted_only"}], "complete") is False
        and failure_stratum([{"status": "parse_failed"}], "interrupted") is True
        and failure_stratum([first], "interrupted") is False, "native_stratum_unknown_membership_test")
    require(common_fallback_outcome({**common, "status": "interrupted"}, 3, 3) is None
        and common_fallback_outcome({**common, "status": "interrupted"}, 4, 3) is False
        and common_fallback_outcome({**common, "status": "complete"}, 3, 3) is True, "common_interrupted_improvement_unknown_test")
    parse_edge = common_seed_edge({**common, "status": "complete", "attempts": [{"status": "parse_failed"}]}, {}, {"passed": 3, "total": 4})
    require(parse_edge["correct_after_public_failure"] is False
        and common_seed_edge(common, {}, {"passed": 3, "total": 4})["attempt1_hidden_status"] == "not_started",
        "common_parse_failure_and_not_started_edge_test")
    return {"status": "passed", "checks": 21, "provider_calls": 0, "judge_containers": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--score-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test()))
    else:
        require(all((args.raw_root, args.score_root, args.output)), "raw_root_score_root_output_required")
        summary = write_analysis(args.raw_root, args.score_root, args.output)
        print(json.dumps({"status": summary["status"], "summary": str(args.output / "summary.json"),
                          "denominators": summary["denominators"], "provider_calls": 0, "judge_containers": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
