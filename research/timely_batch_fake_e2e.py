"""Offline subprocess-fixture checks for timely_batch.py; zero provider calls.

The child below is an explicit billing/artifact fixture, not a Timely/game/model
result. It exercises the coordinator's real file journal and process boundary.
For real-game offline coverage use timely_batch.py run --execute-offline in
the WSL Jericho environment; that path always invokes timely_reproduce.py.
All generated evidence is retained under one fresh .local fixture directory.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import timely_batch as batch


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def expect_error(callback, label: str) -> str:
    try:
        callback()
    except (batch.PilotError, OSError, ValueError) as exc:
        return str(exc)
    raise AssertionError(f"expected failure: {label}")


def jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def fixture_episode(output: Path, identity: dict, row: dict, *, paid: bool = False,
                    tau: float | None = None, scenario: str = "valid") -> None:
    """Synthetic provider artifacts with unequal calibration denominators."""
    output.mkdir(parents=True, exist_ok=False)
    if scenario == "missing-result":
        return
    count = 2 if row.get("repeat", 1) == 1 else 4
    actual = 2.0 if count == 2 else 12.0
    total = actual + count * row["tool_delay"]
    cost = Decimal("0.01") * count
    manifest = {**identity, "paid": paid, "run_id": output.name,
                "mode": row["mode"], "model": row["model"], "steps": row["steps"],
                "tool_durations": {name: row["tool_delay"] for name in batch.TOOLS},
                "max_calls": row["steps"], "budget_cny": row["cap_cny"],
                "python_random_seed": row["seed"], "average_duration_per_step": tau,
                "time_limit": row["steps"] * tau if tau is not None else None,
                "fixture_only": True}
    account = {"calls_dispatched": count, "unknown_calls": 0, "active_calls": 0,
               "stop_reason": None, "reserved_cny": "0", "spent_estimate_cny": str(cost)}
    events = [{"event": "batch_open"}]
    for index in range(count):
        events += [{"event": "request_dispatch", "request_id": str(index)},
                   {"event": "request_complete", "request_id": str(index),
                    "start_monotonic_s": index * 0.2, "end_monotonic_s": index * 0.2 + 0.1,
                    "provider_usage_peak_estimate_cny": "0.01"}]
    if scenario in {"unknown", "overcap"}:
        events[-1] = {"event": "request_unknown", "request_id": str(count - 1)}
        account.update(unknown_calls=1, reserved_cny=str(Decimal(row["cap_cny"]) + 1) if scenario == "overcap" else "0.2",
                       stop_reason="unknown_usage")
    events.append({"event": "batch_close", **account})
    trajectory = {"total_steps": count, "steps": [{"step": i, "tool_results": [
                      {"tool": "step", "duration": row["tool_delay"]}]} for i in range(count)],
                  "total_actural_time_duration": total, "time_limit": manifest["time_limit"],
                  "total_tool_duration": count * row["tool_delay"],
                  "all_responses": ["fixture"] * count}
    summary = {"total_steps": count, "total_games": 1, "failed_games": 0,
               "average_duration_per_step": total / count}
    official = summary if row["mode"] == "speed" else [summary]
    payload = {"run_id": output.name, "paid": paid, "failure_type": None,
               "measured_evaluator_wall_s": actual + 0.5,
               "accounting": account, "official_result": official,
               "evidence": {"technical_ok": True, "calibration_usable": scenario != "unusable"},
               "fixture_only": True, "cost_interpretation": "synthetic fixture; zero API spend"}
    if scenario == "clock-jump":
        payload["measured_evaluator_wall_s"] = 0.01
    elif scenario == "tool-duration":
        trajectory["steps"][0]["tool_results"][0]["duration"] += 1
    batch.write_new(output / "manifest.json", manifest)
    batch.write_new(output / "result.json", payload)
    batch.write_new(output / "environment.json", {"fixture_only": True})
    jsonl(output / "requests.jsonl", events)
    jsonl(output / "official" / f"trajectories_max_steps_{row['steps']}.jsonl", [trajectory])
    name = "speed_summary.json" if row["mode"] == "speed" else f"max_steps_{row['steps']}_summary.json"
    batch.write_new(output / "official" / name, summary)


def fixture_child(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-plan", type=Path, required=True)
    parser.add_argument("--fixture-scenario", default="valid")
    parser.add_argument("--source")
    parser.add_argument("--game")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--mode")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--tool-delay", type=float)
    parser.add_argument("--tool-format", choices=("official", "single-json-v1"), default="official")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--budget-cny")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--average-duration-per-step", type=float)
    args = parser.parse_args(arguments)
    plan = batch.read_json(args.fixture_plan)
    check(plan["paid"] is False, "fixture child forbids paid execution")
    row = next(r for r in plan["rows"] if r["run_id"] == args.output.name)
    check(args.model == row["model"] and args.mode == row["mode"] and args.steps == row["steps"]
          and args.max_calls == row["steps"] and args.budget_cny == row["cap_cny"]
          and args.tool_delay == row["tool_delay"] and args.seed == row["seed"], "child CLI contract")
    check(args.tool_format == plan["identity"]["tool_format"], "frozen tool-format passed to child")
    if args.fixture_scenario in {"tree-timeout", "tree-interrupt", "tree-hangup", "tree-quit"}:
        args.output.mkdir(parents=True)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        grandchild = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(300)"])
        batch.write_new(args.output / "fixture-processes.json", {"child": os.getpid(), "grandchild": grandchild.pid})
        cancel_signal = {"tree-interrupt": signal.SIGTERM, "tree-hangup": signal.SIGHUP,
                         "tree-quit": signal.SIGQUIT}.get(args.fixture_scenario)
        if cancel_signal is not None:
            time.sleep(0.2)
            os.kill(os.getppid(), cancel_signal)
        time.sleep(300)
        return 0
    fixture_episode(args.output, plan["identity"], row,
                    tau=args.average_duration_per_step, scenario=args.fixture_scenario)
    return 0


def prefix(root: Path, scenario: str = "valid") -> list[str]:
    return [sys.executable, "-B", str(Path(__file__).resolve()), "--fixture-child",
            "--fixture-plan", str(root / "plan.json"), "--fixture-scenario", scenario]


def main() -> int:
    check(sys.platform == "linux", "run process-tree fixtures in the supported Linux/WSL execution environment")
    (batch.ROOT / ".local").mkdir(exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="timely-batch-fixture-", dir=batch.ROOT / ".local"))
    source, game = parent / "source", parent / "fixture.z5"
    package = source / "src" / "timely_eval"
    package.mkdir(parents=True)
    (package / "interactive.py").write_text("# Offline provenance fixture, not official source.\n", encoding="utf-8")
    (package / "prompts.py").write_text('INTERACTIVE_SYSTEM = "Fixture system"\nINTERACTIVE_TOOL_PROMPT = "Fixture tool prompt"\n', encoding="utf-8")
    game.write_bytes(b"offline game identity fixture")
    checks = []

    prompt_path = package / "prompts.py"
    original_prompt = prompt_path.read_text(encoding="utf-8")
    canary = parent / "source-code-was-executed"
    for label, extra in (
        ("raise", '\nraise RuntimeError("source must never execute")\n'),
        ("write", f'\n__import__("pathlib").Path({str(canary)!r}).write_text("executed")\n'),
    ):
        try:
            prompt_path.write_text(original_prompt + extra, encoding="utf-8")
            expect_error(lambda: batch.environment_identity(source, game), f"reject source {label}")
            check(not canary.exists(), "source code has no side effects")
        finally:
            prompt_path.write_text(original_prompt, encoding="utf-8")
        checks.append(f"prompt_source_{label}_not_executed")

    def plan(name: str, cap: str = "200") -> tuple[Path, dict]:
        root = parent / name
        return root, batch.create_plan(root, source, game, cap_cny=cap)

    root, frozen = plan("complete-and-resume")
    check(frozen["identity"]["tool_format"] == "official" and frozen["identity"]["tool_format_note"] == ""
          and frozen["identity"]["prompt_sha256"]["base_system_message"] == frozen["identity"]["prompt_sha256"]["actual_system_message"],
          "default official prompt condition preserved")
    check(len(frozen["rows"]) == 24 and [len(b["run_ids"]) for b in frozen["blocks"]] == [4, 4, 8, 8], "full matrix")
    check(all(row["cap_cny"] == ("5" if row["model"] == "deepseek-flash" else "10" if row["steps"] == 32 else "20")
              for row in frozen["rows"]), "model and step dependent liability guards")
    check([sum(Decimal(row["cap_cny"]) for row in frozen["rows"] if row["block"] == block["block_id"])
           for block in frozen["blocks"]] == [30, 30, 80, 80], "full block liability guards")
    checks.append("model_step_child_caps_and_balanced_block_guards")
    check(all(r["steps"] == 32 for r in frozen["rows"][:8]), "independent calibration size")
    check([r["run_id"] for r in frozen["rows"][:4]] == frozen["blocks"][0]["run_ids"], "frozen order")
    result = subprocess.run([sys.executable, "-B", str(Path(batch.__file__)), "run", "--pilot-root", str(root)],
                            capture_output=True, text=True, check=False)
    check(result.returncode == 0 and json.loads(result.stdout)["status"] == "dry" and not (root / "runs").exists(), "CLI defaults dry")
    result = batch.run_pilot(root, execute_offline=True, max_runs=3, fixture_prefix=prefix(root))
    check(result["status"] == "clean_stop" and result["settled_runs"] == 3, "clean stop")
    check(not (root / "pilot.lock").exists(), "normal exit releases owned lock")
    result = batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root))
    check(result["status"] == "complete" and result["settled_runs"] == 24, "resume completes exact matrix")
    ledger = batch.Ledger(root, frozen)
    starts = [e["data"]["run_id"] for e in ledger.events if e["event"] == "start"]
    check(starts == [r["run_id"] for r in frozen["rows"]], "no skipped or duplicated child")
    for item in (root / "calibrations").glob("*.json"):
        document = batch.read_json(item)
        delay = document["identity"]["tool_durations"]["step"]
        check(document["denominator_recorded_steps"] == 6 and document["numerator_official_time_s"] == 14 + 6 * delay,
              "raw weighted calibration denominator")
        check(abs(document["tau"] - (14 / 6 + delay)) < 1e-12 and document["tau"] != 2 + delay, "weighted rather than average of averages")
        check(len(document["sources"]) == 2, "all planned independent repeats")
    for row in frozen["rows"][8:]:
        binding = batch.read_json(root / "bindings" / f"{row['run_id']}.json")
        check(binding["average_duration_per_step"] == (14 + 6 * row["tool_delay"]) / 6 and binding["calibration"]["sha256"], "timed provenance binding")
    check(batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root))["status"] == "complete", "completed resume is idempotent")
    checks += ["full_frozen_matrix", "dry_cli", "clean_resume", "weighted_tau", "timed_binding", "complete_idempotency"]
    document_path = next((root / "calibrations").glob("*.json"))
    original = document_path.read_bytes()
    document_path.write_bytes(original + b" \n")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "completed calibration hash tamper")
    document_path.write_bytes(original)
    document_path.unlink()
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "completed calibration missing")
    checks += ["completed_calibration_tamper", "completed_calibration_missing"]

    adapted = parent / "single-json-v1-matrix"
    adapted_plan = batch.create_plan(adapted, source, game, tool_format="single-json-v1")
    result = batch.run_pilot(adapted, execute_offline=True, fixture_prefix=prefix(adapted))
    check(result["status"] == "complete", "adapted complete matrix")
    for row in adapted_plan["rows"]:
        manifest = batch.read_json(adapted / "runs" / row["run_id"] / "manifest.json")
        check(manifest["tool_format"] == "single-json-v1" and manifest["prompt_condition_id"] == "timely-interactive:single-json-v1",
              "all calibration and timed rows use one variant")
        check(manifest["prompt_sha256"]["actual_system_message"] != manifest["prompt_sha256"]["base_system_message"],
              "adapted prompt hash differs explicitly")
    incompatible = {**adapted_plan["identity"], "tool_format": "official"}
    first = adapted_plan["rows"][0]
    expect_error(lambda: batch.episode(adapted / "runs" / first["run_id"], False, expected=incompatible, row=first),
                 "cannot cross-calibrate prompt variants")
    checks += ["default_official_condition", "adapted_full_matrix", "prompt_variant_calibration_isolation"]

    root, frozen = plan("insufficient-whole-block", "29")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "whole block reserve")
    ledger = batch.Ledger(root, frozen)
    check(len(ledger.events) == 1 and not (root / "runs").exists(), "no partial block dispatch")
    checks.append("whole_block_reservation")

    for scenario in ("unknown", "missing-result", "overcap"):
        root, frozen = plan(scenario)
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root, scenario)), scenario)
        ledger = batch.Ledger(root, frozen)
        check(ledger.state["next"] == 0 and ledger.state["started"] == frozen["rows"][0]["run_id"], "unresolved child stays started")
        check(ledger.committed() == (Decimal("31.02") if scenario == "overcap" else 30), "full or larger observed liability retained")
        check(Decimal(ledger.state["reserved"][frozen["rows"][0]["run_id"]]) >= Decimal(frozen["rows"][0]["cap_cny"]),
              "full child reservation retained")
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "blocked resume")
        check(len(list((root / "runs").iterdir())) == 1, "no retry or later child")
        checks.append(scenario)

    root, frozen = plan("unusable-calibration")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root, "unusable")), "unusable calibration")
    ledger = batch.Ledger(root, frozen)
    check(ledger.state["next"] == 1 and ledger.state["stopped"] == "calibration_not_usable"
          and not (root / "calibrations").exists(), "cannot create tau from unusable source")
    checks.append("unusable_calibration_stops")

    for scenario in ("clock-jump", "tool-duration"):
        root, frozen = plan(scenario)
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root, scenario)), scenario)
        check(batch.Ledger(root, frozen).state["next"] == 0, "invalid clock cannot produce calibration")
        checks.append(scenario)

    for scenario in ("tree-timeout", "tree-interrupt", "tree-hangup", "tree-quit"):
        root, frozen = plan(scenario)
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
        try:
            try:
                batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root, scenario),
                                fixture_timeout_s=1.0 if scenario == "tree-timeout" else 10.0)
                raise AssertionError("expected process timeout or cancellation")
            except (batch.PilotError, KeyboardInterrupt):
                pass
            pids = batch.read_json(root / "runs" / frozen["rows"][0]["run_id"] / "fixture-processes.json")
            check(all(not Path(f"/proc/{pid}").exists() for pid in pids.values()), "owned child and grandchild fully reaped")
            check(unrelated.poll() is None, "unrelated process was not signalled")
            ledger = batch.Ledger(root, frozen)
            check(ledger.committed() == 30 and ledger.state["stopped"], "interrupted child liability retained")
            check(not (root / "pilot.lock").exists(), "lock released only after verified process cleanup")
            expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "no retry after timeout")
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)
        checks.append(scenario)

    root, frozen = plan("interrupt-after-settle-fsync")
    fsync = os.fsync
    interrupted = False
    def interrupt_after_settle(fd: int) -> None:
        nonlocal interrupted
        fsync(fd)
        if not interrupted and Path(os.readlink(f"/proc/self/fd/{fd}")) == root / "ledger.jsonl":
            event = json.loads((root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            if event["event"] == "settle":
                interrupted = True
                os.kill(os.getpid(), signal.SIGINT)
    try:
        with patch.object(batch.os, "fsync", side_effect=interrupt_after_settle):
            batch.run_pilot(root, execute_offline=True, max_runs=1, fixture_prefix=prefix(root))
        raise AssertionError("expected real SIGINT after durable settlement")
    except KeyboardInterrupt:
        pass
    ledger = batch.Ledger(root, frozen)
    check(interrupted and [event["event"] for event in ledger.events] ==
          ["open", "reserve_block", "start", "settle", "stop"], "durable ledger sequence recovered after interrupt")
    check(ledger.state["next"] == 1 and ledger.committed() == 30 - Decimal(frozen["rows"][0]["cap_cny"]) + Decimal("0.02"),
          "known settlement counted once with unstarted reservations retained")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "interrupted pilot remains stopped")
    checks.append("settle_fsync_sigint_recovers_durable_sequence")

    root, frozen = plan("torn-settlement-journal")
    torn = False
    def tear_settlement(fd: int) -> None:
        nonlocal torn
        fsync(fd)
        path = root / "ledger.jsonl"
        if not torn and Path(os.readlink(f"/proc/self/fd/{fd}")) == path:
            raw = path.read_bytes()
            if json.loads(raw.splitlines()[-1])["event"] == "settle":
                torn = True
                path.write_bytes(raw[:-10])
                raise OSError("fixture torn settlement write")
    with patch.object(batch.os, "fsync", side_effect=tear_settlement):
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, max_runs=1, fixture_prefix=prefix(root)),
                     "torn settlement blocks further journal writes")
    raw = (root / "ledger.jsonl").read_bytes()
    check(torn and not raw.endswith(b"\n") and b'"event":"stop"' not in raw,
          "torn journal retained without appending another event")
    prefix_events = [json.loads(line) for line in raw.splitlines()[:-1]]
    check([event["event"] for event in prefix_events] == ["open", "reserve_block", "start"],
          "last intact prefix retains the unresolved reservation")
    expect_error(lambda: batch.Ledger(root, frozen), "torn journal requires operator inspection")
    checks.append("torn_settlement_fail_closed_no_further_append")

    root, frozen = plan("calibration-tamper")
    batch.run_pilot(root, execute_offline=True, max_runs=8, fixture_prefix=prefix(root))
    first = root / "runs" / frozen["rows"][0]["run_id"] / "result.json"
    first.write_bytes(first.read_bytes() + b" \n")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "raw calibration changed")
    check(len(list((root / "runs").iterdir())) == 8, "no timed dispatch after tamper")
    checks.append("calibration_raw_hash_tamper")

    root, frozen = plan("calibration-document-tamper")
    batch.run_pilot(root, execute_offline=True, max_runs=9, fixture_prefix=prefix(root))
    document_path = next((root / "calibrations").glob("*.json"))
    document = batch.read_json(document_path)
    document["tau"] = 1.0
    document_path.write_bytes(batch.canonical(document))
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "derived calibration changed")
    check(len(list((root / "runs").iterdir())) == 9, "no further timed run after changed tau")
    checks.append("calibration_document_hash_tamper")

    root, frozen = plan("binding-tamper")
    batch.run_pilot(root, execute_offline=True, max_runs=1, fixture_prefix=prefix(root))
    binding_path = next((root / "bindings").glob("*.json"))
    binding_path.write_bytes(binding_path.read_bytes() + b" \n")
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "outer binding changed")
    check(len(list((root / "runs").iterdir())) == 1, "no dispatch after binding tamper")
    checks.append("binding_hash_tamper")

    root, frozen = plan("stale-lock")
    batch.write_new(root / "pilot.lock", {"token": "operator-only", "pid": -1})
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "existing lock")
    check((root / "pilot.lock").exists() and not (root / "runs").exists(), "never guesses stale lock")
    checks.append("exclusive_lock_preserved")

    root, frozen = plan("unsettled-ledger")
    with batch.exclusive(root):
        ledger = batch.Ledger(root, frozen)
        ledger.append("reserve_block", frozen["blocks"][0])
        ledger.append("start", {"run_id": frozen["rows"][0]["run_id"], "binding_sha256": "interrupted-fixture"})
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "interrupted start")
    check(batch.Ledger(root, frozen).committed() == 30 and not (root / "runs").exists(), "no automatic result adoption")
    checks.append("unsettled_resume_refused")

    root, frozen = plan("plan-tamper")
    changed = batch.read_json(root / "plan.json")
    changed["rows"][0]["model"] = "other-model"
    (root / "plan.json").write_bytes(batch.canonical(changed))
    expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "plan changed")
    check(not (root / "runs").exists(), "plan hash checked before child")
    checks.append("frozen_plan_hash")

    # Synthetic paid markers exercise import accounting only; never dispatch a paid child.
    inventory_root = parent / "r1-inventory"
    r1 = inventory_root / "synthetic-r1-accounting-fixture"
    row = {"mode": "speed", "model": "deepseek-flash", "tool_delay": 0,
           "steps": 8, "cap_cny": "5", "seed": 1, "repeat": 1}
    fixture_episode(r1, batch.environment_identity(source, game), row, paid=True)
    failed = inventory_root / "failed-paid-r1"
    fixture_episode(failed, batch.environment_identity(source, game), row, paid=True)
    failed_result = batch.read_json(failed / "result.json")
    failed_result["evidence"]["technical_ok"] = False
    failed_result["failure_type"] = "KnownFixtureFailure"
    (failed / "result.json").write_bytes(batch.canonical(failed_result))
    live = parent / "live-plan-dry-only"
    with patch.object(batch, "R1_ROOT", inventory_root), patch.object(batch, "PAID_STUDY_ROOT", parent / "study-registry-fixture"):
        for name, imports in (("invalid-omitted-r1", [r1]), ("invalid-duplicate-r1", [r1, failed, r1])):
            rejected = parent / name
            expect_error(lambda: batch.create_plan(rejected, source, game, paid=True, imports=imports), name)
            check(not (batch.PAID_STUDY_ROOT / "registry.json").exists() and not rejected.exists(),
                  "invalid explicit imports do not bind the paid study")
        frozen = batch.create_plan(live, source, game, paid=True, imports=[r1, failed])
        check(batch.run_pilot(live)["committed_cny"] == "0.04", "known successful and failed R1 both charged exactly once")
        expect_error(lambda: batch.create_plan(parent / "second-paid-pilot", source, game, paid=True, imports=[r1, failed]), "one paid pilot per study")
        expect_error(lambda: batch.create_plan(parent / "missing-import", source, game, paid=True), "missing explicit R1")
        expect_error(lambda: batch.create_plan(parent / "offline-import", source, game, imports=[r1]), "offline import forbidden")
        expect_error(lambda: batch.run_pilot(live, execute_offline=True, fixture_prefix=prefix(live)), "fake/live mismatch")
        batch.verify_paid_study(live, frozen)
        with batch.exclusive(batch.PAID_STUDY_ROOT):
            expect_error(lambda: batch.create_plan(parent / "concurrent-study", source, game, paid=True, imports=[r1, failed]), "shared study lock")
        (r1 / "result.json").write_bytes((r1 / "result.json").read_bytes() + b" \n")
        expect_error(lambda: batch.verify_paid_study(live, frozen), "frozen historical artifacts changed")
    checks += ["r1_known_failed_accounting", "r1_duplicate_rejected", "r1_omission_rejected", "invalid_imports_leave_study_unbound", "offline_live_separation",
               "one_paid_pilot_per_study", "shared_study_lock", "frozen_complete_r1_inventory"]

    unknown_inventory = parent / "unknown-inventory"
    unknown = unknown_inventory / "unknown-paid-r1"
    fixture_episode(unknown, batch.environment_identity(source, game), row, paid=True, scenario="overcap")
    with patch.object(batch, "R1_ROOT", unknown_inventory), patch.object(batch, "PAID_STUDY_ROOT", parent / "unknown-study"):
        expect_error(lambda: batch.create_plan(parent / "unknown-live", source, game, paid=True, imports=[unknown]), "unknown prior attempt blocks study")
        registry = batch.read_json(batch.PAID_STUDY_ROOT / "registry.json")
        check(registry["blocked_unknown_history"] and Decimal(registry["historical_committed_cny"]) == Decimal("6.02"), "higher unknown historical liability frozen")
        expect_error(lambda: batch.create_plan(parent / "unknown-live-reset", source, game, paid=True, imports=[unknown]), "cannot reset blocked study with new root")
    checks.append("unknown_history_retained_and_blocks_study")

    root, frozen = plan("cleanup-uncertain-lock")
    with patch.object(batch, "run_owned_child", side_effect=batch.ProcessCleanupError("fixture_uncertain_cleanup")):
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root)), "uncertain cleanup")
    check((root / "pilot.lock").exists() and batch.Ledger(root, frozen).committed() == 30, "uncertain cleanup keeps lock and liability")
    checks.append("cleanup_uncertainty_preserves_lock")

    batch.write_new(parent / "summary.json", {"status": "ok", "checks": checks, "provider_calls": 0,
                    "kind": "subprocess fixtures, not official evaluator or model results"})
    print(json.dumps({"status": "ok", "checks": len(checks), "provider_calls": 0,
                      "output": str(parent), "validation": "offline subprocess fixtures"}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture-child":
        raise SystemExit(fixture_child(sys.argv[2:]))
    raise SystemExit(main())
