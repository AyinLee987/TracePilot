"""Run the released Timely four-game sweep with unchanged prompts and scoring.

Each episode uses the existing isolated runner. Only the parent writes the study
journal; at most six independent processes execute concurrently. Format errors
are benchmark outcomes, not a reason to discard a trajectory or tune a prompt.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import nullcontext
from decimal import Decimal
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import sys
import time

import timely_batch as batch
import timely_study as study

GAMES = ("zork1.z5", "advent.z5", "enchanter.z3", "detective.z5")
STEPS = (10, 20, 30, 50, 100)
WORKERS = 6
CHILD_CAP = Decimal("20")


def protocol(source: Path, roms: Path) -> dict:
    from timely_reproduce import verify_source
    verify_source(source)
    identities = {name: batch.environment_identity(source, roms / name) for name in GAMES}
    rows = []
    for mode, budgets in (("speed", (32,)), ("timed", STEPS)):
        group = []
        for steps in budgets:
            for repeat in range(1, 9):
                for game in GAMES:
                    for model in batch.MODELS:
                        group.append({"game": game, "model": model, "mode": mode,
                                      "steps": steps, "repeat": repeat})
        random.Random(20261006 + len(rows)).shuffle(group)
        rows.extend(group)
    for i, row in enumerate(rows):
        row.update(run_id=f"episode-{i + 1:03d}", seed=20261006 + i, cap_cny=str(CHILD_CAP))
    return {"schema": 1, "source": str(source), "roms": str(roms), "games": list(GAMES),
            "models": list(batch.MODELS), "rows": rows, "identities": identities,
            "tool_format": "official", "tool_delay": "upstream_defaults",
            "workers": WORKERS, "repeats": 8, "calibration_steps": 32,
            "timed_steps": list(STEPS), "child_cap_cny": str(CHILD_CAP),
            "runner_sha256": {name: batch.file_hash(Path(__file__).parent / name) for name in
                              ("timely_official.py", "timely_batch.py", "timely_reproduce.py",
                               "timely_transport.py", "timely_evidence.py")},
            "calibration_policy": "official: positive-step returned trajectories; sum_time/sum_steps",
            "comparison_scope": "API substitutions; per-model logical deadlines; no paper-checkpoint reproduction"}


def append(root: Path, event: str, **data) -> None:
    with (root / "execution.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"event": event, "monotonic_s": time.monotonic(), **data}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def execute_one(root_s: str, plan: dict, row: dict, tau: float | None,
                env_file: str | None, fake_case: str = "valid") -> int:
    root = Path(root_s)
    command = [sys.executable, "-B", str(batch.RUNNER), "--source", plan["source"],
               "--game", str(Path(plan["roms"]) / row["game"]),
               "--output", str(root / row["run_id"]), "--model", row["model"],
               "--mode", row["mode"], "--steps", str(row["steps"]),
               "--max-calls", str(row["steps"]), "--budget-cny", row["cap_cny"],
               "--seed", str(row["seed"]), "--tool-format", "official"]
    if tau is not None:
        command += ["--average-duration-per-step", str(tau)]
    if plan["paid"]:
        command += ["--execute-paid", "--env-file", env_file]
    else:
        command += ["--fake-case", fake_case]
    return batch.run_owned_child(command, timeout=row["steps"] * 65 + 120,
                                 ownership_path=root / f"{row['run_id']}.process.json")


def inspect(root: Path, plan: dict, row: dict, tau: float | None) -> dict:
    directory = root / row["run_id"]
    manifest = batch.read_json(directory / "manifest.json")
    result = batch.read_json(directory / "result.json")
    for key, value in plan["identities"][row["game"]].items():
        batch.require(manifest.get(key) == value, f"changed_episode_identity:{key}")
    for key, value in {"model": row["model"], "steps": row["steps"], "max_calls": row["steps"],
                       "mode": row["mode"], "paid": plan["paid"], "python_random_seed": row["seed"],
                       "budget_cny": row["cap_cny"], "average_duration_per_step": tau}.items():
        batch.require(manifest.get(key) == value, f"changed_episode_condition:{key}")
    events = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    dispatched = [e for e in events if e["event"] == "request_dispatch"]
    completed = [e for e in events if e["event"] == "request_complete"]
    batch.require(events[0]["event"] == "batch_open" and events[-1]["event"] == "batch_close"
                  and not any(e["event"] in {"request_unknown", "request_rejected"} for e in events)
                  and [e["request_id"] for e in dispatched] == [e["request_id"] for e in completed]
                  and len({e["request_id"] for e in dispatched}) == len(dispatched), "unclosed_requests")
    cost = sum((batch.money(e["provider_usage_peak_estimate_cny"]) for e in completed), Decimal(0))
    for account in (result["accounting"], events[-1]):
        batch.require(account["unknown_calls"] == account["active_calls"] == 0
                      and batch.money(account["reserved_cny"]) == 0 and not account["stop_reason"]
                      and account["calls_dispatched"] == len(dispatched)
                      and batch.money(account["spent_estimate_cny"]) == cost, "unsettled_usage")
    batch.require(cost <= batch.money(row["cap_cny"]), "child_cap_exceeded")
    closed = batch.read_json(root / f"{row['run_id']}.process.closed.json")
    batch.require(closed["cleanup_verified"] is True, "unclosed_process")
    evidence = result["evidence"]
    # Technical failures need investigation; malformed calls alone are allowed.
    batch.require(evidence["technical_ok"] is True and result["failure_type"] is None,
                  "technical_failure:" + ",".join(evidence.get("errors", [])))
    path = directory / f"official/trajectories_max_steps_{row['steps']}.jsonl"
    trajectories = [json.loads(line) for line in path.read_text().splitlines()]
    batch.require(len(trajectories) == 1, "unexpected_trajectory_count")
    trajectory = trajectories[0]
    count, elapsed = trajectory["total_steps"], trajectory["total_actural_time_duration"]
    batch.require(type(count) is int and 0 <= count <= row["steps"] and count == len(trajectory["steps"])
                  and math.isfinite(elapsed) and elapsed >= 0, "invalid_step_or_time")
    virtual = trajectory["total_tool_duration"]
    wall = result["measured_evaluator_wall_s"]
    http = evidence["timing"]["http_completed_total_s"]
    clock_ok = (math.isfinite(virtual) and virtual >= 0 and math.isfinite(wall) and wall > 0
                and 0.99 * http - 0.1 <= elapsed - virtual <= 1.01 * wall + 0.1)
    # Keep measured clock diagnostics without silently changing official scoring.
    return {**row, "cost_cny": str(cost), "steps_recorded": count, "logical_s": elapsed,
            "wall_s": wall, "clock_consistent": clock_ok,
            "calibration_eligible": count > 0 and elapsed > 0,
            "strict_old_calibration_usable": evidence["calibration_usable"],
            "score": trajectory["final_score"], "game_state": evidence["game"],
            "counts": evidence["counts"], "official_trajectory": trajectory,
            "artifacts": batch.artifact_refs(directory, row["steps"], row["mode"])}


def calibrate(records: list[dict]) -> dict[str, float]:
    values = {}
    for game in GAMES:
        for model in batch.MODELS:
            items = [r for r in records if r["game"] == game and r["model"] == model and r["mode"] == "speed"]
            batch.require(len(items) == 8, "missing_speed_repeat")
            valid = [r for r in items if r["calibration_eligible"]]
            count = sum(r["steps_recorded"] for r in items)
            tau = sum(r["logical_s"] for r in valid) / count if count else 0
            batch.require(math.isfinite(tau) and 0 < tau <= 600, "no_official_calibration")
            values[f"{game}/{model}"] = tau
    return values


def aggregate(plan: dict, records: list[dict]) -> list[dict]:
    sys.path.insert(0, str(Path(plan["source"]) / "src"))
    from timely_eval.interactive import InteractiveEvaluator
    groups = {}
    for row in records:
        groups.setdefault((row["game"], row["model"], row["mode"], row["steps"]), []).append(row)
    return [{"game": game, "model": model, "mode": mode, "steps": steps,
             **InteractiveEvaluator._summarize_trajectories(
                 [r["official_trajectory"] for r in rows],
                 [r["official_trajectory"] for r in rows if r["steps_recorded"] > 0]),
             "mean_wall_s": sum(r["wall_s"] for r in rows) / len(rows),
             "clock_flags": sum(not r["clock_consistent"] for r in rows),
             "no_tool_steps": sum(r["counts"]["no_tool_steps"] for r in rows),
             "victories": sum(r["game_state"]["victory"] is True for r in rows)}
            for (game, model, mode, steps), rows in groups.items()]


def run(root: Path, *, env_file: str | None = None) -> dict:
    plan = batch.read_json(root / "plan.json")
    records, costs, held, calibration = [], Decimal(0), {}, {}
    opening = batch.money(plan["study_opening"]["known_cny"])
    carried = sum((batch.money(x["held_cny"]) for x in plan["study_opening"]["liabilities"]), Decimal(0))
    with (batch.exclusive(batch.PAID_STUDY_ROOT) if plan["paid"] else nullcontext()), batch.exclusive(root):
        if plan["paid"]:
            study.assert_active(root, plan)
        for name, sha in plan["runner_sha256"].items():
            batch.require(batch.file_hash(Path(__file__).parent / name) == sha, "runner_changed")
        batch.require(not (root / "execution.jsonl").exists(), "run_already_started_no_automatic_retry")
        append(root, "open", planned=len(plan["rows"]), opening_cny=str(opening), carried_cny=str(carried))
        stop = None
        ctx = multiprocessing.get_context("spawn")
        started = time.monotonic()
        try:
            with ProcessPoolExecutor(max_workers=plan["workers"], mp_context=ctx) as pool:
                for mode in ("speed", "timed"):
                    rows = [r for r in plan["rows"] if r["mode"] == mode]
                    if not rows:
                        continue
                    if mode == "timed":
                        calibration = calibrate(records)
                        batch.write_new(root / "calibration.json", calibration)
                    offset = 0
                    while offset < len(rows):
                        affordable = int((Decimal(200) - opening - carried - costs) / CHILD_CAP)
                        size = min(plan["workers"], len(rows) - offset, affordable)
                        batch.require(size > 0, "study_budget_censored")
                        chunk = rows[offset:offset + size]
                        futures = {}
                        for row in chunk:
                            tau = calibration.get(f"{row['game']}/{row['model']}") if mode == "timed" else None
                            held[row["run_id"]] = CHILD_CAP
                            append(root, "reserve", run_id=row["run_id"], cap_cny=str(CHILD_CAP), tau=tau)
                            future = pool.submit(execute_one, str(root), plan, row, tau, env_file,
                                                 row.get("fake_case", "valid"))
                            futures[future] = (row, tau)
                        failures = []
                        for future in as_completed(futures):
                            row, tau = futures[future]
                            try:
                                code = future.result()
                                batch.require(code == 0, f"child_exit:{code}")
                                result = inspect(root, plan, row, tau)
                                costs += batch.money(result["cost_cny"])
                                held.pop(row["run_id"])
                                records.append(result)
                                append(root, "settle", run_id=row["run_id"], cost_cny=result["cost_cny"],
                                       score=result["score"], steps=result["steps_recorded"], artifacts=result["artifacts"])
                            except Exception as exc:
                                failures.append(f"{row['run_id']}:{exc}")
                                append(root, "unresolved", run_id=row["run_id"], reason=str(exc))
                        print(json.dumps({"completed": len(records), "planned": len(plan["rows"]),
                                          "study_cny": str(opening + costs), "failures": failures}), flush=True)
                        batch.require(not failures, ";".join(failures))
                        offset += size
        except BaseException as exc:
            stop = f"{type(exc).__name__}:{exc}"
        report = {"paid": plan["paid"], "cost_interpretation": "peak-price estimate, not invoice" if plan["paid"] else "synthetic accounting; zero API spend",
                  "complete": stop is None and len(records) == len(plan["rows"]),
                  "planned": len(plan["rows"]), "completed": len(records), "stop_reason": stop,
                  "batch_cost_cny": str(costs), "study_known_cny": str(opening + costs),
                  "held_cny": str(carried + sum(held.values(), Decimal(0))), "elapsed_s": time.monotonic() - started,
                  "calibration": calibration,
                  "records": [{k: v for k, v in row.items() if k != "official_trajectory"} for row in records]}
        # Preserve settled evidence even if optional aggregation cannot finish.
        batch.write_new(root / "result.json", report)
        append(root, "close", complete=report["complete"], cost_cny=str(costs), held_cny=report["held_cny"], stop=stop)
        try:
            batch.write_new(root / "groups.json", aggregate(plan, records))
        except Exception as exc:
            batch.write_new(root / "aggregation-error.json", {"error_type": type(exc).__name__})
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "check"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--roms", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--historical-sources", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    root = batch.local_path(args.root)
    if args.action == "prepare":
        frozen = protocol(args.source.resolve(), args.roms.resolve())
        frozen["historical_sources"] = str(args.historical_sources.resolve())
        result = study.prepare_official(args.parent, root, frozen)
    elif args.action == "check":
        plan = protocol(args.source.resolve(), args.roms.resolve())
        # Concurrent real Jericho environments, synthetic HTTP; no API requests.
        rows = []
        for i, case in enumerate(("valid", "missing-close", "no-tool", "conclusion-after-tool")):
            rows.append({"run_id": f"check-{i}", "game": GAMES[0], "model": batch.MODELS[0], "mode": "speed",
                         "steps": 3, "repeat": i + 1, "seed": 20261006 + i, "cap_cny": str(CHILD_CAP), "fake_case": case})
        plan.update(paid=False, rows=rows, study_opening={"known_cny": "0", "liabilities": []})
        root.mkdir(parents=True, exist_ok=False)
        batch.write_new(root / "plan.json", plan)
        result = run(root)
        batch.require(result["complete"] and result["completed"] == 4, "offline_check_failed")
        batch.require(sum(r["counts"]["no_tool_steps"] for r in result["records"]) == 6,
                      "format_errors_did_not_continue")
        failure_root = root.with_name(root.name + "-failure")
        failure_root.mkdir(parents=True, exist_ok=False)
        plan["rows"] = [{**rows[0], "fake_case": "missing-usage"}]
        batch.write_new(failure_root / "plan.json", plan)
        failure = run(failure_root)
        batch.require(not failure["complete"] and batch.money(failure["held_cny"]) == CHILD_CAP,
                      "unknown_usage_did_not_hold_reservation")
        result["unknown_usage_stop_verified"] = True
    else:
        batch.require(args.execute_paid and args.env_file and args.env_file.is_file(), "paid_run_requires_explicit_flag_and_env")
        batch.require(batch.read_json(root / "plan.json")["paid"] is True, "not_a_paid_plan")
        result = run(root, env_file=str(args.env_file.resolve()))
    print(json.dumps({key: value for key, value in result.items() if key not in {"records", "groups"}}, indent=2))
    return int(result.get("complete") is False)


if __name__ == "__main__":
    raise SystemExit(main())
