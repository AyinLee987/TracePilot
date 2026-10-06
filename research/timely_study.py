"""Audited succession for the single CNY 200 Timely study; never calls a model.

``prepare-revision`` creates an inert, complete 24-row replacement matrix.
``activate`` requires its exact plan digest and a separately reviewed file hash.
The original registry, plans, ledgers and raw runs are never rewritten. The
transition chain is published atomically under the existing study lock. There
is one allowed small-matrix revision; future four-game/coding executors have an
explicit complete-stage audit seam, not an implemented execution path here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import os
import json
from pathlib import Path
import sys
import uuid

import timely_batch as batch

REVISION = "r2-small-revision-1"
EXTENSIONS = ("r2-four-game-v1", "r3-coding-v1")


def _registry() -> tuple[dict, str]:
    path = batch.PAID_STUDY_ROOT / "registry.json"
    record = batch.read_json(path)
    batch.require(record.get("study") == "timely-pilot-20261006" and batch.money(record["cap_cny"]) == 200,
                  "wrong_study_or_cap")
    batch.require(not record.get("blocked_unknown_history"), "unknown_genesis_history")
    return record, batch.file_hash(path)


def head() -> dict:
    """Read the immutable genesis and verify every append-only transition."""
    registry, previous = _registry()
    result = {"sha256": previous, "root": registry["pilot_root"], "revision_used": False,
              "stage_name": "r2-small-original", "transition": None, "count": 0}
    path = batch.PAID_STUDY_ROOT / "transitions.jsonl"
    raw = path.read_bytes() if path.exists() else b""
    batch.require(not raw or raw.endswith(b"\n"), "torn_study_chain")
    for seq, line in enumerate(raw.splitlines()):
        # Reuse strict JSON parsing through a decoder is unnecessary here: the
        # canonical bytes must match, rejecting duplicate keys and alternate encodings.
        event = json.loads(line)
        payload = {key: value for key, value in event.items() if key != "sha256"}
        batch.require(batch.canonical(event) == line and event.get("seq") == seq
                      and event.get("previous_sha256") == previous
                      and batch.digest(payload) == event.get("sha256"), "invalid_study_chain")
        batch.require(event["parent_root"] == result["root"] and event["kind"] == "revise-small"
                      and event["stage_name"] == REVISION and not result["revision_used"],
                      "invalid_or_duplicate_study_transition")
        previous = event["sha256"]
        result = {"sha256": previous, "root": event["root"], "revision_used": True,
                  "stage_name": event["stage_name"], "transition": event, "count": seq + 1}
    return result


def _files(root: Path) -> dict[str, str]:
    refs = {}
    for path in sorted(root.rglob("*")):
        batch.require(not path.is_symlink(), "stage_symlinks_not_allowed")
        if path.is_file() and path != root / "pilot.lock":
            refs[path.relative_to(root).as_posix()] = batch.file_hash(path)
    return refs


def _check_seal(seal: dict) -> None:
    batch.require(_files(Path(seal["root"])) == seal["files"], "sealed_parent_changed")


def _closed_cost(directory: Path, row: dict, paid: bool) -> Decimal:
    """Billing closure only: failed gameplay is neither free nor calibration."""
    manifest = batch.read_json(directory / "manifest.json")
    result = batch.read_json(directory / "result.json")
    batch.require(manifest.get("run_id") == result.get("run_id") == directory.name
                  and manifest.get("paid") is paid and result.get("paid") is paid
                  and manifest.get("model") == row["model"]
                  and batch.money(manifest["budget_cny"]) == batch.money(row["cap_cny"]), "billing_identity_mismatch")
    raw = (directory / "requests.jsonl").read_bytes()
    batch.require(raw.endswith(b"\n"), "torn_child_billing")
    events = [json.loads(line) for line in raw.splitlines()]
    batch.require(events and events[0].get("event") == "batch_open" and events[-1].get("event") == "batch_close"
                  and sum(e.get("event") == "batch_open" for e in events) == 1
                  and sum(e.get("event") == "batch_close" for e in events) == 1, "unclosed_child_billing")
    dispatched = [e.get("request_id") for e in events if e.get("event") == "request_dispatch"]
    completed = [e for e in events if e.get("event") == "request_complete"]
    batch.require(all(isinstance(value, str) and value for value in dispatched)
                  and len(dispatched) == len(set(dispatched))
                  and dispatched == [e.get("request_id") for e in completed]
                  and not any(e.get("event") == "request_unknown" for e in events), "unknown_child_billing")
    cost = sum((batch.money(e["provider_usage_peak_estimate_cny"]) for e in completed), Decimal(0))
    for account in (events[-1], result["accounting"]):
        batch.require(account.get("unknown_calls") == 0 and account.get("active_calls") == 0
                      and account.get("calls_dispatched") == len(dispatched)
                      and batch.money(account["reserved_cny"]) == 0
                      and batch.money(account["spent_estimate_cny"]) == cost, "billing_not_fully_known")
    return cost


def _full_small(plan: dict) -> None:
    cells = Counter((r["mode"], r["model"], r["tool_delay"], r["steps"], r["repeat"]) for r in plan["rows"])
    expected = Counter((mode, model, delay, steps, repeat) for mode, sizes in (("speed", (32,)), ("timed", (32, 64)))
                       for model in batch.MODELS for delay in (0, 10) for steps in sizes for repeat in (1, 2))
    ids = [r["run_id"] for r in plan["rows"]]
    batch.require(batch.money(plan["cap_cny"]) == 200 and plan["stage"] == "R2-small" and cells == expected and len(set(ids)) == 24
                  and [r["mode"] for r in plan["rows"][:8]] == ["speed"] * 8
                  and plan["calibration_repeats"] == 2 and plan["calibration_steps"] == 32
                  and [len(b["run_ids"]) for b in plan["blocks"]] == [4, 4, 8, 8]
                  and [rid for block in plan["blocks"] for rid in block["run_ids"]] == ids,
                  "revision_requires_entire_24_row_small_matrix")
    for block in plan["blocks"]:
        rows = [r for r in plan["rows"] if r["run_id"] in block["run_ids"]]
        batch.require(len({(r["mode"], r["repeat"]) for r in rows}) == 1
                      and all(r["block"] == block["block_id"] for r in rows)
                      and all(r["cap_cny"] == batch.CHILD_CAPS[r["model"]][r["steps"]] for r in rows),
                      "invalid_balanced_revision_block")


def _basis(root: Path, kind: str, stage_name: str) -> dict:
    """Caller holds study and parent locks. No old file is edited."""
    current = head()
    batch.require(current["root"] == str(root), "parent_is_not_active_head")
    plan = batch.read_json(root / "plan.json")
    if plan["paid"]:
        batch.verify_paid_study(root, plan)
    else:
        assert_active(root, plan)
    ledger = batch.Ledger(root, plan)
    registry, genesis_hash = _registry()
    batch.require(plan["paid"] is registry.get("paid", True)
                  and plan["imports"] == registry["imports"], "study_mode_or_imports_mismatch")
    batch.require(batch.money(plan["cap_cny"]) == 200, "stage_cap_must_be_study_cap")
    if kind == "revise-small":
        batch.require(stage_name == REVISION and not current["revision_used"] and ledger.state["stopped"]
                      and not ledger.state["complete"], "small_revision_not_available")
        _full_small(plan)
    else:
        batch.require(kind == "extend-complete" and stage_name in EXTENSIONS and ledger.state["complete"],
                      "extension_requires_completed_stage")
        expected = "r3-coding-v1" if current["stage_name"] == "r2-four-game-v1" else "r2-four-game-v1"
        batch.require(stage_name == expected, "invalid_next_named_stage")
    for item in plan["imports"]:
        batch.check_refs(Path(item["directory"]), item["artifacts"])
    known = batch.money(plan["study_opening"]["known_cny"]) if "study_opening" in plan else sum(
        (batch.money(item["cost_cny"]) for item in plan["imports"]), Decimal(0))
    liabilities = list(plan.get("study_opening", {}).get("liabilities", []))
    started = {e["data"]["run_id"]: e["data"] for e in ledger.events if e["event"] == "start"}
    runs = root / "runs"
    batch.require(not runs.exists() or all(path.is_dir() and path.name in started for path in runs.iterdir()),
                  "unregistered_run_inventory_requires_reconciliation")
    processes = root / "processes"
    owned_names = {f"{rid}{suffix}" for rid in started for suffix in (".json", ".closed.json")}
    batch.require(not processes.exists() or all(path.is_file() and path.name in owned_names for path in processes.iterdir()),
                  "unregistered_process_inventory_requires_reconciliation")
    costs = []
    for row in plan["rows"]:
        rid, directory = row["run_id"], root / "runs" / row["run_id"]
        process = root / "processes" / f"{rid}.json"
        if rid not in started:
            batch.require(not directory.exists() and not process.exists() and not process.with_suffix(".closed.json").exists(),
                          "unstarted_row_has_possible_dispatch_evidence")
            continue
        binding = root / "bindings" / f"{rid}.json"
        batch.require(batch.file_hash(binding) == started[rid]["binding_sha256"], "parent_binding_changed")
        owner, closed = batch.read_json(process), batch.read_json(process.with_suffix(".closed.json"))
        batch.require(owner.get("ownership") == "new_linux_session" and closed.get("cleanup_verified") is True
                      and closed.get("pid") == owner.get("pid") and type(closed.get("returncode")) is int,
                      "parent_cleanup_not_confirmed")
        saved = ledger.state["settled"].get(rid)
        if saved:
            batch.check_refs(directory, saved["artifacts"])
        try:
            cost = _closed_cost(directory, row, plan["paid"])
        except (OSError, ValueError, KeyError, TypeError, batch.PilotError):
            held = max(batch.money(row["cap_cny"]), batch.money(ledger.state["reserved"].get(rid, "0")),
                       batch.observed_commitment(directory))
            liabilities.append({"origin_plan_sha256": batch.digest(plan), "run_id": rid, "held_cny": str(held)})
            costs.append({"run_id": rid, "billing_known": False, "held_cny": str(held)})
        else:
            batch.require(saved is None or cost == batch.money(saved["cost_cny"]), "settled_cost_changed")
            known += cost
            costs.append({"run_id": rid, "billing_known": True, "cost_cny": str(cost)})
    origins = [(x["origin_plan_sha256"], x["run_id"]) for x in liabilities]
    batch.require(len(set(origins)) == len(origins), "duplicate_carried_liability")
    opening = {"known_cny": str(known), "liabilities": liabilities}
    committed = known + sum((batch.money(item["held_cny"]) for item in liabilities), Decimal(0))
    batch.require(committed <= 200, "prior_liability_exceeds_study_cap")
    return {"schema": 1, "root": str(root), "genesis_sha256": genesis_hash, "previous_head_sha256": current["sha256"],
            "kind": kind, "stage_name": stage_name, "terminal": "complete" if ledger.state["complete"] else "stopped",
            "plan_sha256": batch.digest(plan), "ledger_tip_sha256": ledger.events[-1]["sha256"],
            "files": _files(root), "costs": costs, "opening": opening,
            "released_unstarted_reservations": [rid for rid in ledger.state["reserved"] if rid not in started],
            "committed_cny": str(committed), "remaining_cny": str(Decimal(200) - committed),
            "scientific_use": "old matrix retained whole; no old trajectory or tau enters successor"}


def prepare_revision(parent: Path, root: Path, *, tool_format: str) -> dict:
    parent, root = batch.local_path(parent), batch.local_path(root)
    batch.require(not root.is_relative_to(parent) and not parent.is_relative_to(root) and not root.exists(),
                  "successor_requires_fresh_root")
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(parent):
        seal = _basis(parent, "revise-small", REVISION)
        old = batch.read_json(parent / "plan.json")
        # Retain every predeclared cell and its order; only the explicitly
        # reviewed condition and executable environment receive fresh hashes.
        plan = dict(old)
        plan.update(pilot_id=root.name, identity=batch.environment_identity(Path(old["source"]), Path(old["game_path"]), tool_format),
                    python=str(Path(sys.executable).resolve()), python_version=sys.version,
                    runner=str(batch.RUNNER.resolve()), coordinator_sha256=batch.file_hash(Path(batch.__file__)),
                    study_opening=seal["opening"], study_admission={"kind": "revise-small", "stage_name": REVISION,
                        "previous_head_sha256": seal["previous_head_sha256"], "parent_root": str(parent),
                        "parent_seal_sha256": batch.digest(seal), "module_sha256": batch.file_hash(Path(__file__))})
        _full_small(plan)
        first_cap = sum((batch.money(row["cap_cny"]) for row in plan["rows"] if row["block"] == plan["blocks"][0]["block_id"]), Decimal(0))
        batch.require(batch.money(seal["committed_cny"]) + first_cap <= 200, "first_balanced_block_does_not_fit")
        # Preparation has no registry side effect. A failed preparation is an
        # inert directory; it can never spend without a final activation record.
        root.mkdir(parents=True, exist_ok=False)
        batch.write_new(root / "parent-seal.json", seal)
        batch.write_new(root / "plan.json", plan)
        batch.Ledger(root, plan).append("open", {"plan_sha256": batch.digest(plan)})
        return {"status": "prepared_not_active", "pilot_root": str(root), "plan_sha256": batch.digest(plan),
                "plan_file_sha256": batch.file_hash(root / "plan.json"), "opening": seal["opening"], "model_calls": 0}


def extension_basis(parent: Path, stage_name: str) -> dict:
    """Read-only seam for future named executors; this does not activate them."""
    parent = batch.local_path(parent)
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(parent):
        return _basis(parent, "extend-complete", stage_name)


def _publish(event: dict) -> None:
    path = batch.PAID_STUDY_ROOT / "transitions.jsonl"
    old = path.read_bytes() if path.exists() else b""
    temporary = path.with_name(f".transition-{uuid.uuid4().hex}.tmp")
    # Preserve the exact previous bytes; atomically publish one entire new head.
    with temporary.open("xb") as stream:
        stream.write(old + batch.canonical(event) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if sys.platform == "linux":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def activate(root: Path, *, plan_sha256: str, review: Path, review_sha256: str) -> dict:
    root, review = batch.local_path(root), batch.local_path(review)
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(root):
        plan = batch.read_json(root / "plan.json")
        admission = plan["study_admission"]
        parent = batch.local_path(Path(admission["parent_root"]))
        with batch.exclusive(parent):
            batch.require(batch.digest(plan) == plan_sha256, "reviewed_plan_hash_mismatch")
            batch.require(review.is_file() and review.stat().st_size > 0 and batch.file_hash(review) == review_sha256,
                          "review_file_missing_or_changed")
            batch.require(admission["module_sha256"] == batch.file_hash(Path(__file__))
                          and plan["coordinator_sha256"] == batch.file_hash(Path(batch.__file__)), "prepared_code_changed")
            batch.require(plan["identity"] == batch.environment_identity(Path(plan["source"]), Path(plan["game_path"]),
                          plan["identity"]["tool_format"]), "prepared_environment_changed")
            seal = batch.read_json(root / "parent-seal.json")
            batch.require(batch.digest(seal) == admission["parent_seal_sha256"]
                          and _basis(parent, admission["kind"], admission["stage_name"]) == seal,
                          "prepared_parent_changed")
            batch.require(plan["study_opening"] == seal["opening"], "opening_balance_changed")
            parent_plan = batch.read_json(parent / "plan.json")
            batch.require(all(plan[key] == parent_plan[key] for key in
                          ("paid", "imports", "source", "game_path", "rows", "blocks", "request_contract")),
                          "revision_changed_scope_or_historical_imports")
            _full_small(plan)
            ledger = batch.Ledger(root, plan)
            batch.require(len(ledger.events) == 1 and ledger.events[0]["event"] == "open"
                          and set(_files(root)) == {"plan.json", "ledger.jsonl", "parent-seal.json"},
                          "successor_not_pristine")
            current = head()
            batch.require(current["sha256"] == admission["previous_head_sha256"], "parent_head_changed")
            payload = {"schema": 1, "seq": current["count"], "previous_sha256": current["sha256"],
                       "kind": admission["kind"], "stage_name": admission["stage_name"], "parent_root": str(parent),
                       "root": str(root), "plan_sha256": plan_sha256, "plan_file_sha256": batch.file_hash(root / "plan.json"),
                       "parent_seal_sha256": admission["parent_seal_sha256"], "opening": seal["opening"],
                       "module_sha256": admission["module_sha256"], "review": {"path": str(review), "sha256": review_sha256},
                       "utc": datetime.now(timezone.utc).isoformat()}
            event = {**payload, "sha256": batch.digest(payload)}
            _publish(event)
            return {"status": "activated_no_model_calls", "head_sha256": event["sha256"],
                    "pilot_root": str(root), "opening": seal["opening"], "model_calls": 0}


def assert_active(root: Path, plan: dict) -> None:
    current, (registry, _) = head(), _registry()
    batch.require(current["root"] == str(root), "stage_is_not_active_study_head")
    batch.require(plan["paid"] is registry.get("paid", True) and plan["imports"] == registry["imports"],
                  "active_study_mode_or_imports_mismatch")
    if current["transition"] is None:
        batch.require("study_admission" not in plan and "study_opening" not in plan, "successor_not_activated")
        return
    event = current["transition"]
    batch.require(batch.digest(plan) == event["plan_sha256"] and batch.file_hash(root / "plan.json") == event["plan_file_sha256"]
                  and batch.file_hash(Path(__file__)) == event["module_sha256"]
                  and plan["study_opening"] == event["opening"], "active_stage_changed")
    seal = batch.read_json(root / "parent-seal.json")
    batch.require(batch.digest(seal) == event["parent_seal_sha256"], "parent_seal_changed")
    _check_seal(seal)
    batch.require(batch.file_hash(Path(event["review"]["path"])) == event["review"]["sha256"], "activation_review_changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-revision")
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--pilot-root", type=Path, required=True)
    prepare.add_argument("--tool-format", choices=("official", "single-json-v1", "single-json-v2"), required=True)
    activate_parser = commands.add_parser("activate")
    activate_parser.add_argument("--pilot-root", type=Path, required=True)
    activate_parser.add_argument("--plan-sha256", required=True)
    activate_parser.add_argument("--review", type=Path, required=True)
    activate_parser.add_argument("--review-sha256", required=True)
    extension = commands.add_parser("extension-basis")
    extension.add_argument("--parent", type=Path, required=True)
    extension.add_argument("--stage-name", choices=EXTENSIONS, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare-revision":
            result = prepare_revision(args.parent, args.pilot_root, tool_format=args.tool_format)
        elif args.command == "activate":
            result = activate(args.pilot_root, plan_sha256=args.plan_sha256, review=args.review, review_sha256=args.review_sha256)
        else:
            result = {"status": "audit_only_no_executor_admitted", "basis": extension_basis(args.parent, args.stage_name), "model_calls": 0}
        print(batch.canonical(result).decode())
        return 0
    except (batch.PilotError, OSError, ValueError, KeyError, TypeError) as exc:
        print(batch.canonical({"status": "refused", "reason": str(exc) if isinstance(exc, batch.PilotError) else "inspect_local_evidence",
                               "model_calls": 0}).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
