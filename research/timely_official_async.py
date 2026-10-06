"""One user-directed scheduling switch: stopped chunk-six run to a six-slot queue.

Requires the original KeyboardInterrupt result and verified outer process exit 1.
Old plan/results/calibration stay immutable. A supplement makes this single-use;
any subsequent interruption or uncertain fee requires separate operator review.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import nullcontext
from decimal import Decimal
import json
import math
import multiprocessing
from pathlib import Path
import time

import timely_official as official

batch, study = official.batch, official.study
CLOSED = batch.ROOT / ".local/overnight/timely-official-live.process.closed.json"


def reconcile(root: Path, plan: dict) -> tuple[list[dict], dict, list[dict], dict]:
    """Read and verify every previously reserved episode before releasing any cap."""
    old = batch.read_json(root / "result.json")
    closed = batch.read_json(CLOSED)
    owner = batch.read_json(CLOSED.with_name("timely-official-live.process.json"))
    batch.require(old["complete"] is False and str(old["stop_reason"]).startswith("KeyboardInterrupt:")
                  and closed["cleanup_verified"] is True and closed["returncode"] == 1
                  and closed["pid"] == owner["pid"], "not_the_verified_manual_scheduling_stop")
    raw = (root / "execution.jsonl").read_bytes()
    batch.require(raw.endswith(b"\n"), "torn_execution_journal")
    events = [json.loads(line) for line in raw.splitlines()]
    batch.require(events[0]["event"] == "open" and events[-1]["event"] == "close"
                  and events[-1]["stop"] == old["stop_reason"]
                  and sum(e["event"] == "close" for e in events) == 1, "unexpected_old_journal")
    rows = {r["run_id"]: r for r in plan["rows"]}
    reserved, settled = {}, {}
    for event in events:
        kind, run_id = event["event"], event.get("run_id")
        batch.require(kind in {"open", "reserve", "settle", "unresolved", "close"}, "resume_already_attempted")
        if kind == "reserve":
            batch.require(run_id in rows and run_id not in reserved, "duplicate_or_foreign_reservation")
            reserved[run_id] = event
        elif kind == "settle":
            batch.require(run_id in reserved and run_id not in settled, "duplicate_or_unreserved_settlement")
            settled[run_id] = event
    batch.require(list(reserved) == list(rows)[:len(reserved)], "old_dispatch_order_changed")
    calibration = batch.read_json(root / "calibration.json")
    records = []
    for run_id, reservation in reserved.items():
        row = rows[run_id]
        tau = calibration[f"{row['game']}/{row['model']}"] if row["mode"] == "timed" else None
        batch.require(reservation["tau"] == tau and batch.money(reservation["cap_cny"]) == official.CHILD_CAP,
                      "old_reservation_changed")
        record = official.inspect(root, plan, row, tau)
        if run_id in settled:
            event = settled[run_id]
            batch.require(event["cost_cny"] == record["cost_cny"] and event["artifacts"] == record["artifacts"],
                          "old_settlement_changed")
        records.append(record)
    recomputed = official.calibrate(records)
    batch.require(sum(r["mode"] == "speed" for r in records) == 64 and recomputed.keys() == calibration.keys()
                  and all(math.isclose(value, calibration[key], rel_tol=1e-12, abs_tol=1e-12)
                          for key, value in recomputed.items()), "calibration_changed_or_incomplete")
    old_cost = sum((batch.money(r["cost_cny"]) for r in records if r["run_id"] in settled), Decimal(0))
    batch.require(old["planned"] == 384 and old["completed"] == len(settled)
                  and {r["run_id"] for r in old["records"]} == set(settled)
                  and batch.money(old["batch_cost_cny"]) == old_cost, "old_report_accounting_mismatch")
    remaining = [r for r in plan["rows"] if r["run_id"] not in reserved]
    batch.require(all(r["mode"] == "timed" and not (root / r["run_id"]).exists()
                      and not (root / f"{r['run_id']}.process.json").exists() for r in remaining),
                  "unreserved_episode_artifacts_exist")
    return records, calibration, remaining, settled


def run(root: Path, *, env_file: str | None = None, execute_paid: bool = False) -> dict:
    root = batch.local_path(root)
    plan = batch.read_json(root / "plan.json")
    batch.require(plan["paid"] is execute_paid, "explicit_paid_flag_required")
    batch.require(not execute_paid or env_file and Path(env_file).is_file(), "explicit_env_file_required")
    with (batch.exclusive(batch.PAID_STUDY_ROOT) if execute_paid else nullcontext()), batch.exclusive(root):
        if execute_paid:
            study.assert_active(root, plan)
            study._official_identity(plan)
        batch.require(plan["workers"] == 6 and len(plan["rows"]) == 384
                      and len({r["run_id"] for r in plan["rows"]}) == 384
                      and all(batch.money(r["cap_cny"]) == official.CHILD_CAP for r in plan["rows"]),
                      "not_the_frozen_384_six_worker_plan")
        for name, sha in plan["runner_sha256"].items():
            batch.require(batch.file_hash(Path(__file__).parent / name) == sha, "runner_changed")
        batch.require(not any((root / name).exists() for name in
                              ("supplement.json", "async-result.json", "async-groups.json")), "resume_already_attempted")
        records, calibration, remaining, settled = reconcile(root, plan)
        opening = batch.money(plan["study_opening"]["known_cny"])
        carried = sum((batch.money(x["held_cny"]) for x in plan["study_opening"]["liabilities"]), Decimal(0))
        costs = sum((batch.money(r["cost_cny"]) for r in records), Decimal(0))
        batch.require(opening + carried + costs <= 200, "study_budget_already_exceeded")
        supplement = {"schema": 1, "root": str(root), "plan_sha256": batch.digest(plan),
            "plan_file_sha256": batch.file_hash(root / "plan.json"),
            "reason": "user-directed scheduling change: chunk-six to refill each completed slot; no episode retry",
            "workers": 6, "old_runner_sha256": plan["runner_sha256"],
            "new_runner_sha256": batch.file_hash(Path(__file__)),
            "old_artifacts": {name: batch.file_hash(root / name) for name in
                              ("result.json", "groups.json", "execution.jsonl", "calibration.json")},
            "outer_cleanup_sha256": batch.file_hash(CLOSED), "previously_reserved": len(records),
            "previously_settled": len(settled), "remaining": len(remaining), "reconciled_cost_cny": str(costs)}
        batch.write_new(root / "supplement.json", supplement)
        official.append(root, "async_resume", supplement_sha256=batch.file_hash(root / "supplement.json"))
        def settle(record: dict) -> None:
            official.append(root, "settle", run_id=record["run_id"], cost_cny=record["cost_cny"],
                            score=record["score"], steps=record["steps_recorded"], artifacts=record["artifacts"])
        for record in records:
            if record["run_id"] not in settled:
                settle(record)
        held, pending, offset, stop = {}, {}, 0, None
        started = time.monotonic()
        try:
            with ProcessPoolExecutor(max_workers=6, mp_context=multiprocessing.get_context("spawn")) as pool:
                while pending or offset < len(remaining):
                    while stop is None and len(pending) < 6 and offset < len(remaining):
                        if opening + carried + costs + sum(held.values(), Decimal(0)) + official.CHILD_CAP > 200:
                            break
                        row = remaining[offset]
                        tau = calibration[f"{row['game']}/{row['model']}"]
                        held[row["run_id"]] = official.CHILD_CAP
                        official.append(root, "reserve", run_id=row["run_id"], cap_cny=str(official.CHILD_CAP), tau=tau)
                        pending[pool.submit(official.execute_one, str(root), plan, row, tau, env_file,
                                            row.get("fake_case", "valid"))] = (row, tau)
                        offset += 1
                    if not pending:
                        if offset < len(remaining) and stop is None:
                            stop = "study_budget_censored"
                        break
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        row, tau = pending.pop(future)
                        try:
                            code = future.result()
                            batch.require(code == 0, f"child_exit:{code}")
                            record = official.inspect(root, plan, row, tau)
                            settle(record)
                            costs += batch.money(record["cost_cny"])
                            held.pop(row["run_id"])
                            records.append(record)
                        except Exception as exc:
                            stop = f"{row['run_id']}:{type(exc).__name__}:{exc}"
                            held[row["run_id"]] = max(official.CHILD_CAP, batch.observed_commitment(root / row["run_id"]))
                            official.append(root, "unresolved", run_id=row["run_id"], reason=stop)
                    print(json.dumps({"completed": len(records), "planned": 384,
                                      "study_cny": str(opening + costs), "pending": len(pending), "stop": stop}), flush=True)
                    if stop and not pending:
                        break
        except BaseException as exc:
            stop = f"{type(exc).__name__}:{exc}"
        for run_id in held:
            held[run_id] = max(held[run_id], batch.observed_commitment(root / run_id))
        report = {"paid": plan["paid"], "complete": stop is None and len(records) == 384,
            "planned": 384, "completed": len(records), "stop_reason": stop, "batch_cost_cny": str(costs),
            "study_known_cny": str(opening + costs), "held_cny": str(carried + sum(held.values(), Decimal(0))),
            "elapsed_s": time.monotonic() - started, "elapsed_scope": "asynchronous continuation only",
            "scheduling_change": supplement, "calibration": calibration,
            "records": [{k: v for k, v in row.items() if k != "official_trajectory"} for row in records]}
        batch.write_new(root / "async-result.json", report)
        official.append(root, "async_close", complete=report["complete"], cost_cny=str(costs),
                        held_cny=report["held_cny"], stop=stop)
        if any(not (root / f"{run_id}.process.closed.json").is_file()
               or batch.read_json(root / f"{run_id}.process.closed.json").get("cleanup_verified") is not True
               for run_id in held):
            raise batch.ProcessCleanupError("async_child_cleanup_uncertain_lock_retained")
        batch.write_new(root / "async-groups.json", official.aggregate(plan, records))
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true", required=True)
    args = parser.parse_args()
    result = run(args.root, env_file=str(args.env_file.resolve()), execute_paid=args.execute_paid)
    print(json.dumps({k: v for k, v in result.items() if k not in {"records", "scheduling_change"}}, indent=2))
    return int(not result["complete"])


if __name__ == "__main__":
    raise SystemExit(main())
