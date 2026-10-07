"""Audited succession for the single CNY 200 Timely study; never calls a model.

``prepare-revision`` creates an inert, complete 24-row replacement matrix.
``activate`` requires its exact plan digest and a separately reviewed file hash.
The original registry, plans, ledgers and raw runs are never rewritten. The
transition chain is published atomically under the existing study lock. There
is one small-matrix revision, one coding first-draft batch, one predefined
 coding extension, one explicitly reviewed deadline development batch, and one
 official Timely successor after that batch has settled.
Historical version migration requires archived source bytes for a terminal
parent; active execution always checks the current code hashes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import os
import json
import hashlib
import math
from pathlib import Path
import sys
import uuid

import timely_batch as batch

REVISION = "r2-small-revision-1"
EXTENSIONS = ("r2-four-game-v1", "r3-coding-v1")
CODING_STAGE = "r3-coding-first-draft-16-v1"
CODING_EXTENSION = "r3-coding-first-draft-extension16-v1"
DEADLINE_STAGE = "r3-coding-deadline-dev-v1"
OFFICIAL_STAGE = "timely-official-four-game-v1"
ML_STAGE = "timely-agentic-ml-v1"
ML_CORRECTED_STAGE = "timely-agentic-ml-libgomp-v2"
DEADLINE_CAP = Decimal("120")
DEADLINE_KNOWN_STOPS = (None, "budget_censored", "public_infrastructure_failure", "request_or_context_failure")
DEADLINE_REQUEST_GUARDS = ("per_request_cap", "message_limit_no_code_truncation", "feedback_projection_limit")
CODING_IDS = {"first16": (55, 32, 7, 56), "extension16": (16, 99, 18, 31)}
CODING_CAP = Decimal("3.20")
CODING_FILES = ("coding_pilot.py", "coding_tasks.py", "coding_environment_smoke.py", "timely_transport.py")
DEADLINE_FILES = ("coding_deadline.py", "coding_deadline_worker.py", "coding_deadline_calibration.py", *CODING_FILES)


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
        revision = event["kind"] == "revise-small" and event["stage_name"] == REVISION and not result["revision_used"]
        coding = (event["kind"] == "advance-coding-first-draft" and event["stage_name"] == CODING_STAGE
                  and result["stage_name"] == REVISION and result["revision_used"])
        extension = (event["kind"] == "advance-coding-extension16" and event["stage_name"] == CODING_EXTENSION
                     and result["stage_name"] == CODING_STAGE and result["revision_used"])
        deadline = (event["kind"] == "advance-coding-deadline" and event["stage_name"] == DEADLINE_STAGE
                    and result["stage_name"] == CODING_EXTENSION and result["revision_used"])
        official = (event["kind"] == "advance-timely-official" and event["stage_name"] == OFFICIAL_STAGE
                    and result["stage_name"] == DEADLINE_STAGE and result["revision_used"])
        ml = (event["kind"] == "advance-timely-ml" and event["stage_name"] == ML_STAGE
              and result["stage_name"] == OFFICIAL_STAGE and result["revision_used"])
        corrected_ml = (event["kind"] == "correct-timely-ml-libgomp" and event["stage_name"] == ML_CORRECTED_STAGE
                        and result["stage_name"] == ML_STAGE and result["revision_used"])
        batch.require(event["parent_root"] == result["root"] and (revision or coding or extension or deadline or official or ml or corrected_ml),
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


def _check_seal(seal: dict, seen: set[str] | None = None) -> None:
    seen = set() if seen is None else seen
    batch.require(seal["root"] not in seen, "cyclic_parent_seal")
    seen.add(seal["root"])
    batch.require(_files(Path(seal["root"])) == seal["files"], "sealed_parent_changed")
    archive = seal.get("source_archive")
    if archive:
        batch.require(batch.file_hash(Path(archive["manifest"]["path"])) == archive["manifest"]["sha256"]
                      and all(batch.file_hash(Path(path)) == sha for path, sha in archive["files"].items()),
                      "historical_source_archive_changed")
    if "parent-seal.json" in seal["files"]:
        _check_seal(batch.read_json(Path(seal["root"]) / "parent-seal.json"), seen)


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


def _source_archive(path: Path, plan: dict, event: dict) -> dict:
    """Verify explicit archived bytes without executing them or invoking Git."""
    path = batch.local_path(path)
    manifest = batch.read_json(path)
    expected = {"timely_study.py": event["module_sha256"], "timely_batch.py": plan["coordinator_sha256"]}
    runtime = plan["identity"]["runner_sha256"]
    batch.require(set(runtime) == set(batch.RUNNER_NAMES), "historical_runtime_source_set_mismatch")
    # The existing archive field is explicitly a hash of exact plan.json bytes,
    # not the canonical JSON digest used by ledger plan_sha256 bindings.
    batch.require(manifest.get("source_plan_sha256") == event["plan_file_sha256"]
                  == batch.file_hash(Path(event["root"]) / "plan.json")
                  and event["plan_sha256"] == batch.digest(plan)
                  and isinstance(manifest.get("source_commit"), str) and len(manifest["source_commit"]) == 40
                  and all(c in "0123456789abcdef" for c in manifest["source_commit"])
                  and set(manifest.get("files", {})) == set(expected)
                  and set(manifest.get("runtime_files", {})) == set(runtime), "historical_source_manifest_mismatch")
    records = {**manifest["files"], **manifest["runtime_files"]}
    refs = {}
    for name, wanted in {**expected, **runtime}.items():
        record, source = records[name], path.parent / name
        batch.require(not source.is_symlink(), "historical_source_symlink_not_allowed")
        raw = source.read_bytes()
        normalized = raw.replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob " + str(len(normalized)).encode() + b"\0" + normalized).hexdigest()
        batch.require(batch.file_hash(source) == record.get("sha256") == wanted
                      and record.get("source_repository_path") == f"research/{name}"
                      and record.get("git_blob") == blob, "historical_source_bytes_mismatch")
        refs[str(source)] = wanted
    return {"manifest": {"path": str(path), "sha256": batch.file_hash(path)}, "files": refs,
            "source_commit": manifest["source_commit"], "from_module_sha256": event["module_sha256"],
            "source_plan_file_sha256": event["plan_file_sha256"], "source_plan_canonical_sha256": batch.digest(plan)}


def _basis(root: Path, kind: str, stage_name: str, *, historical_sources: Path | None = None) -> dict:
    """Caller holds study and parent locks. No old file is edited."""
    current = head()
    batch.require(current["root"] == str(root), "parent_is_not_active_head")
    plan = batch.read_json(root / "plan.json")
    ledger = batch.Ledger(root, plan)
    registry, genesis_hash = _registry()
    archive = None
    if kind == "advance-coding-first-draft":
        # This narrowly scoped migration audits a terminal historical program;
        # it never authorizes that old program to execute under changed code.
        batch.require((ledger.state["stopped"] or ledger.state["complete"]) and historical_sources is not None
                      and current["stage_name"] == REVISION and current["revision_used"]
                      and stage_name == CODING_STAGE, "coding_requires_terminal_timely_revision")
        _assert_active_record(root, plan)
        archive = _source_archive(historical_sources, plan, current["transition"])
        if plan["paid"]:
            ref = plan.get("paid_study_registry", {})
            batch.require(ref == {"path": str((batch.PAID_STUDY_ROOT / "registry.json").resolve()), "sha256": genesis_hash}
                          and registry["imports"] == batch.r1_inventory(), "historical_paid_inventory_changed")
    elif plan["paid"]:
        batch.verify_paid_study(root, plan)
    else:
        assert_active(root, plan)
    batch.require(plan["paid"] is registry.get("paid", True)
                  and plan["imports"] == registry["imports"], "study_mode_or_imports_mismatch")
    batch.require(batch.money(plan["cap_cny"]) == 200, "stage_cap_must_be_study_cap")
    if kind == "revise-small":
        batch.require(stage_name == REVISION and not current["revision_used"] and ledger.state["stopped"]
                      and not ledger.state["complete"], "small_revision_not_available")
        _full_small(plan)
    elif kind != "advance-coding-first-draft":
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
    seal = {"schema": 1, "root": str(root), "genesis_sha256": genesis_hash, "previous_head_sha256": current["sha256"],
            "kind": kind, "stage_name": stage_name, "terminal": "complete" if ledger.state["complete"] else "stopped",
            "plan_sha256": batch.digest(plan), "ledger_tip_sha256": ledger.events[-1]["sha256"],
            "files": _files(root), "costs": costs, "opening": opening,
            "released_unstarted_reservations": [rid for rid in ledger.state["reserved"] if rid not in started],
            "committed_cny": str(committed), "remaining_cny": str(Decimal(200) - committed),
            "scientific_use": "old matrix retained whole; no old trajectory or tau enters successor"}
    if archive is not None:
        seal["source_archive"] = archive
        seal["scientific_use"] = "both Timely matrices retained with original status; R3 admission does not complete R2"
    return seal


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
        if plan.get("study_admission", {}).get("kind") == "advance-timely-official":
            return _activate_official(root, plan, plan_sha256, review, review_sha256)
        if plan.get("study_admission", {}).get("kind") == "advance-coding-deadline":
            return _activate_deadline(root, plan, plan_sha256, review, review_sha256)
        if plan.get("study_admission", {}).get("kind") in {"advance-coding-first-draft", "advance-coding-extension16"}:
            return _activate_coding(root, plan, plan_sha256, review, review_sha256)
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


def _assert_active_record(root: Path, plan: dict) -> dict | None:
    current, (registry, _) = head(), _registry()
    batch.require(current["root"] == str(root), "stage_is_not_active_study_head")
    batch.require(plan["paid"] is registry.get("paid", True) and plan["imports"] == registry["imports"],
                  "active_study_mode_or_imports_mismatch")
    if current["transition"] is None:
        batch.require("study_admission" not in plan and "study_opening" not in plan, "successor_not_activated")
        return None
    event = current["transition"]
    batch.require(batch.digest(plan) == event["plan_sha256"] and batch.file_hash(root / "plan.json") == event["plan_file_sha256"]
                  and plan["study_opening"] == event["opening"], "active_stage_changed")
    seal = batch.read_json(root / "parent-seal.json")
    batch.require(batch.digest(seal) == event["parent_seal_sha256"], "parent_seal_changed")
    _check_seal(seal)
    batch.require(batch.file_hash(Path(event["review"]["path"])) == event["review"]["sha256"], "activation_review_changed")
    return event


def assert_active(root: Path, plan: dict) -> None:
    event = _assert_active_record(root, plan)
    if event:
        batch.require(batch.file_hash(Path(__file__)) == event["module_sha256"], "active_study_module_changed")


def _coding_rows(stage: str = "first16") -> list[dict]:
    batch.require(stage in CODING_IDS, "unknown_coding_stage")
    return [{"run_id": f"draft-{index:02d}-he{number}-{model}-rep{repeat}", "task_id": f"HumanEval/{number}",
             "number": number, "model": model, "repeat": repeat}
            for index, (repeat, number, model) in enumerate(
                ((repeat, number, model) for repeat in (1, 2) for number in CODING_IDS[stage] for model in batch.MODELS), 1)]


def _coding_contract(plan: dict, *, historical: bool = False) -> None:
    stage = plan.get("coding_stage", "first16")
    batch.require(stage in CODING_IDS, "unknown_coding_stage")
    expected = {"endpoint": "https://api.deepseek.com/chat/completions", "temperature": 0.7, "max_tokens": 2048,
                "thinking": {"type": "disabled"}, "stream": False, "n": 1, "requests_per_draft": 1, "retries": 0,
                "http_operation_timeout_s": 60, "whole_request_timeout_s": 65, "per_request_reservation_cap_cny": "0.20"}
    batch.require(plan.get("scope") == "R3-development-natural-first-draft-check-only"
                  and plan.get("rows") == _coding_rows(stage) and plan.get("planned_denominator") == 16
                  and plan.get("models") == list(batch.MODELS) and plan.get("dev_ids") == list(CODING_IDS[stage])
                  and plan.get("heldout_used") is False and plan.get("request_contract") == expected,
                  "coding_requires_frozen_16_first_drafts")
    if not historical:
        batch.require(plan.get("code_sha256") == {name: batch.file_hash(batch.ROOT / "research" / name) for name in CODING_FILES},
                      "coding_executor_source_changed")
    batch.require(not plan.get("paid") or not any(key in plan for key in ("fake_scenario", "simulated_transport_cap_cny")),
                  "paid_coding_plan_contains_fake_fields")


def _coding_events(root: Path, plan: dict) -> list[dict]:
    path = root / "coding-ledger.jsonl"
    if not path.exists():
        return []
    raw, events = path.read_bytes(), []
    batch.require(raw.endswith(b"\n"), "torn_coding_ledger")
    for line in raw.splitlines():
        record = json.loads(line)
        payload = {key: value for key, value in record.items() if key != "sha256"}
        batch.require(batch.canonical(record) == line and record["seq"] == len(events)
                      and record["previous_sha256"] == (events[-1]["sha256"] if events else None)
                      and batch.digest(payload) == record["sha256"], "invalid_coding_ledger_chain")
        events.append(record)
    batch.require(1 <= len(events) <= 3 and events[0]["event"] == "open"
                  and events[0]["data"] == {"plan_sha256": batch.digest(plan)}, "coding_opening_mismatch")
    if len(events) > 1:
        batch.require(events[1]["event"] == "reserve" and events[1]["data"] == {"reservation_cny": str(CODING_CAP)},
                      "coding_reservation_mismatch")
    if len(events) > 2:
        last = events[2]
        batch.require((last["event"] == "settle" and batch.money(last["data"]["cost_cny"]) <= CODING_CAP)
                      or (last["event"] == "stop" and batch.money(last["data"]["liability_cny"]) >= CODING_CAP),
                      "invalid_coding_terminal_event")
    return events


def _coding_append(root: Path, plan: dict, event: str, data: dict) -> None:
    events = _coding_events(root, plan)
    batch.require((len(events), event) in {(0, "open"), (1, "reserve"), (2, "settle"), (2, "stop")},
                  "coding_batch_cannot_resume_or_repeat")
    payload = {"seq": len(events), "previous_sha256": events[-1]["sha256"] if events else None,
               "event": event, "data": data, "utc": datetime.now(timezone.utc).isoformat()}
    with (root / "coding-ledger.jsonl").open("ab") as stream:
        stream.write(batch.canonical({**payload, "sha256": batch.digest(payload)}) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare_coding16(parent: Path, root: Path, coding_plan: dict, provenance: dict, *, historical_sources: Path) -> dict:
    """Prepare only; caller supplies the coding executor's frozen plan/data identity."""
    return _prepare_coding(parent, root, coding_plan, provenance, historical_sources, extension=False)


def prepare_coding_extension16(parent: Path, root: Path, coding_plan: dict, provenance: dict, *, historical_sources: Path) -> dict:
    """The sole predefined extension, admitted only from the completed first 16."""
    return _prepare_coding(parent, root, coding_plan, provenance, historical_sources, extension=True)


def _prepare_coding(parent: Path, root: Path, coding_plan: dict, provenance: dict,
                    historical_sources: Path, *, extension: bool) -> dict:
    parent, root = batch.local_path(parent), batch.local_path(root)
    batch.require(not root.exists() and not root.is_relative_to(parent) and not parent.is_relative_to(root),
                  "coding_requires_fresh_root")
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(parent):
        kind = "advance-coding-extension16" if extension else "advance-coding-first-draft"
        stage = CODING_EXTENSION if extension else CODING_STAGE
        seal = (_coding_parent_basis(parent, historical_sources) if extension else
                _basis(parent, kind, stage, historical_sources=historical_sources))
        registry, _ = _registry()
        _coding_contract(coding_plan)
        batch.require(coding_plan.get("coding_stage", "first16") == ("extension16" if extension else "first16"),
                      "coding_plan_stage_mismatch")
        if extension:
            _same_coding_protocol(batch.read_json(parent / "plan.json"), coding_plan, provenance)
        batch.require(coding_plan.get("paid") is registry.get("paid", True), "coding_paid_fake_mismatch")
        batch.require(batch.money(seal["committed_cny"]) + CODING_CAP <= 200, "whole_coding_batch_does_not_fit")
        plan = {**coding_plan, "stage": stage, "cap_cny": "200", "imports": registry["imports"],
                "study_batch_cap_cny": str(CODING_CAP), "study_opening": seal["opening"],
                "provenance_sha256": batch.digest(provenance),
                "study_runtime": {"python": sys.version, "executable": str(Path(sys.executable).resolve())},
                "study_admission": {"kind": kind, "stage_name": stage,
                    "previous_head_sha256": seal["previous_head_sha256"], "parent_root": str(parent),
                    "parent_seal_sha256": batch.digest(seal), "module_sha256": batch.file_hash(Path(__file__)),
                    "batch_module_sha256": batch.file_hash(Path(batch.__file__))}}
        root.mkdir(parents=True, exist_ok=False)
        batch.write_new(root / "parent-seal.json", seal)
        batch.write_new(root / "plan.json", plan)
        batch.write_new(root / "provenance.json", provenance)
        _coding_append(root, plan, "open", {"plan_sha256": batch.digest(plan)})
        return {"status": "prepared_not_active", "pilot_root": str(root), "plan_sha256": batch.digest(plan),
                "opening": seal["opening"], "remaining_cny": seal["remaining_cny"], "model_calls": 0}


def _coding_identity(root: Path, plan: dict) -> None:
    _coding_contract(plan)
    if plan["paid"]:
        registry, _ = _registry()
        batch.require(plan["imports"] == registry["imports"] == batch.r1_inventory(), "coding_historical_inventory_changed")
    stage = CODING_EXTENSION if plan.get("coding_stage") == "extension16" else CODING_STAGE
    kind = "advance-coding-extension16" if stage == CODING_EXTENSION else "advance-coding-first-draft"
    batch.require(plan["stage"] == plan["study_admission"]["stage_name"] == stage
                  and plan["study_admission"]["kind"] == kind and batch.money(plan["cap_cny"]) == 200
                  and batch.money(plan["study_batch_cap_cny"]) == CODING_CAP
                  and plan["study_admission"]["module_sha256"] == batch.file_hash(Path(__file__))
                  and plan["study_admission"]["batch_module_sha256"] == batch.file_hash(Path(batch.__file__))
                  and plan["study_runtime"] == {"python": sys.version, "executable": str(Path(sys.executable).resolve())}
                  and plan["provenance_sha256"] == batch.digest(batch.read_json(root / "provenance.json")),
                  "coding_execution_identity_changed")


def _activate_coding(root: Path, plan: dict, plan_sha256: str, review: Path, review_sha256: str) -> dict:
    """Caller already owns study and successor locks; publication is last."""
    admission = plan["study_admission"]
    parent = batch.local_path(Path(admission["parent_root"]))
    with batch.exclusive(parent):
        batch.require(batch.digest(plan) == plan_sha256 and review.is_file() and review.stat().st_size > 0
                      and batch.file_hash(review) == review_sha256, "coding_plan_or_review_hash_mismatch")
        _coding_identity(root, plan)
        seal = batch.read_json(root / "parent-seal.json")
        sources = Path(seal["source_archive"]["manifest"]["path"])
        extension = admission["kind"] == "advance-coding-extension16"
        basis = (_coding_parent_basis(parent, sources) if extension else
                 _basis(parent, "advance-coding-first-draft", CODING_STAGE, historical_sources=sources))
        batch.require(batch.digest(seal) == admission["parent_seal_sha256"]
                      and basis == seal
                      and plan["study_opening"] == seal["opening"], "coding_parent_or_opening_changed")
        if extension:
            _same_coding_protocol(batch.read_json(parent / "plan.json"), plan, batch.read_json(root / "provenance.json"))
        registry, _ = _registry()
        batch.require(plan["paid"] is registry.get("paid", True) and plan["imports"] == registry["imports"]
                      and batch.money(seal["committed_cny"]) + CODING_CAP <= 200, "coding_study_budget_mismatch")
        batch.require(len(_coding_events(root, plan)) == 1 and set(_files(root)) == {
            "parent-seal.json", "plan.json", "provenance.json", "coding-ledger.jsonl"}, "coding_successor_not_pristine")
        current = head()
        batch.require(current["sha256"] == admission["previous_head_sha256"], "coding_parent_head_changed")
        payload = {"schema": 1, "seq": current["count"], "previous_sha256": current["sha256"],
                   "kind": admission["kind"], "stage_name": admission["stage_name"], "parent_root": str(parent),
                   "root": str(root), "plan_sha256": plan_sha256, "plan_file_sha256": batch.file_hash(root / "plan.json"),
                   "parent_seal_sha256": admission["parent_seal_sha256"], "opening": seal["opening"],
                   "module_sha256": admission["module_sha256"], "source_archive": seal["source_archive"],
                   "review": {"path": str(review), "sha256": review_sha256}, "utc": datetime.now(timezone.utc).isoformat()}
        record = {**payload, "sha256": batch.digest(payload)}
        _publish(record)
        return {"status": "activated_no_model_calls", "head_sha256": record["sha256"], "pilot_root": str(root),
                "opening": seal["opening"], "model_calls": 0}


def _http_closed(root: Path, plan: dict) -> bool:
    try:
        result = batch.read_json(root / "result.json")
        closure = batch.read_json(root / "generation-closed.json")
        raw = (root / "requests.jsonl").read_bytes()
        last = json.loads(raw.splitlines()[-1])
        return (raw.endswith(b"\n") and last.get("event") == "batch_close" and last.get("active_calls") == 0
                and result.get("http_closed") is True and result.get("plan_sha256") == batch.digest(plan)
                and result.get("paid") is plan["paid"] and result.get("denominator") == closure.get("denominator") == 16
                and result.get("requests_sha256") == closure.get("requests_sha256") == batch.file_hash(root / "requests.jsonl")
                and result.get("accounting", {}).get("active_calls") == closure.get("transport", {}).get("active_calls") == 0)
    except (OSError, ValueError, KeyError, IndexError, TypeError, batch.PilotError):
        return False


def _coding_closed_cost(root: Path, plan: dict) -> Decimal:
    batch.require(_http_closed(root, plan), "coding_http_cleanup_not_confirmed")
    events = [json.loads(line) for line in (root / "requests.jsonl").read_bytes().splitlines()]
    dispatch = [e for e in events if e.get("event") == "request_dispatch"]
    completed = [e for e in events if e.get("event") == "request_complete"]
    ids = [e.get("request_id") for e in dispatch]
    batch.require(events[0].get("event") == "batch_open"
                  and sum(e.get("event") == "batch_open" for e in events) == 1
                  and sum(e.get("event") == "batch_close" for e in events) == 1
                  and len(ids) == len(set(ids)) == 16 and all(isinstance(i, str) and i for i in ids)
                  and ids == [e.get("request_id") for e in completed]
                  and not any(e.get("event") in {"request_unknown", "request_rejected"} for e in events),
                  "coding_batch_not_fully_known")
    contract = plan["request_contract"]
    for row, event in zip(plan["rows"], dispatch):
        labels, body = event.get("labels", {}), event.get("request_body", {})
        batch.require(all(labels.get(key) == row[key] for key in ("run_id", "task_id", "model", "repeat"))
                      and labels.get("phase") == "independent_first_draft" and body.get("model") == row["model"]
                      and all(body.get(key) == contract[key] for key in ("stream", "thinking", "max_tokens", "temperature", "n"))
                      and batch.money(event["reservation_cny"]) <= Decimal("0.20"), "coding_dispatch_plan_mismatch")
    cost = sum((batch.money(e["provider_usage_peak_estimate_cny"]) for e in completed), Decimal(0))
    result, closure = batch.read_json(root / "result.json"), batch.read_json(root / "generation-closed.json")
    batch.require(result.get("interrupted") is False and closure.get("interrupted") is False, "coding_generation_interrupted")
    for account in (events[-1], result["accounting"], closure["transport"]):
        batch.require(account.get("calls_dispatched") == account.get("max_calls") == 16
                      and account.get("unknown_calls") == account.get("active_calls") == 0
                      and account.get("stop_reason") is None and batch.money(account["reserved_cny"]) == 0
                      and batch.money(account["spent_estimate_cny"]) == cost
                      and batch.money(account["batch_budget_cny"]) == CODING_CAP, "coding_closure_accounting_mismatch")
    batch.require(cost <= CODING_CAP, "coding_cost_exceeds_reserved_batch")
    return cost


def _coding_refs(root: Path) -> dict:
    return {name: batch.file_hash(root / name) for name in ("requests.jsonl", "result.json", "generation-closed.json")
            if (root / name).is_file()}


def _coding_source_archive(path: Path, plan: dict, event: dict, *, deadline: bool = False) -> dict:
    """Audit the explicit historical source set; never execute old code."""
    path = batch.local_path(path)
    manifest = batch.read_json(path)
    expected = {"timely_study.py": event["module_sha256"],
                "timely_batch.py": plan["study_admission"]["batch_module_sha256"], **plan["code_sha256"]}
    commit = manifest.get("source_commit", "")
    batch.require(manifest.get("schema") == 2 and manifest.get("kind") == "coding-terminal-source-archive"
                  and manifest.get("source_plan_file_sha256") == event["plan_file_sha256"]
                  and manifest.get("source_plan_canonical_sha256") == event["plan_sha256"] == batch.digest(plan)
                  and manifest.get("activation_review") == event["review"]
                  and len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
                  and set(manifest.get("files", {})) == set(expected)
                  and set(plan["code_sha256"]) == set(DEADLINE_FILES if deadline else CODING_FILES),
                  "coding_historical_manifest_mismatch")
    refs = {}
    for name, wanted in expected.items():
        source, record = path.parent / name, manifest["files"][name]
        batch.require(not source.is_symlink(), "historical_source_symlink_not_allowed")
        normalized = source.read_bytes().replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob " + str(len(normalized)).encode() + b"\0" + normalized).hexdigest()
        batch.require(batch.file_hash(source) == record.get("sha256") == wanted
                      and record.get("git_blob") == blob and record.get("source_repository_path") == f"research/{name}",
                      "coding_historical_source_bytes_mismatch")
        refs[str(source)] = wanted
    return {"manifest": {"path": str(path), "sha256": batch.file_hash(path)}, "files": refs,
            "source_commit": commit, "source_plan_file_sha256": event["plan_file_sha256"],
            "source_plan_canonical_sha256": event["plan_sha256"], "from_module_sha256": event["module_sha256"]}


def _same_coding_protocol(parent: dict, plan: dict, provenance: dict) -> None:
    unchanged = ("scope", "system_prompt", "parse_policy", "request_contract", "models", "planned_denominator",
                 "heldout_used", "independence", "judging", "judge_boundaries", "preflight_policy", "timing_claim",
                 "runtime_identity")
    batch.require(all(plan.get(key) == parent.get(key) for key in unchanged)
                  and batch.digest(provenance) == parent["provenance_sha256"], "extension_changed_first_draft_protocol")


def _coding_public_extension_evidence(root: Path, plan: dict, *, deadline: bool = False) -> dict:
    """Require all first drafts publicly pass; inspect hidden cleanup, not scores."""
    closed = batch.read_json(root / "execution-process-closed.json")
    batch.require(closed.get("pilot_root") == str(root) and closed.get("paid") is plan["paid"]
                  and closed.get("child_reaped") is True and type(closed.get("child_pid")) is int
                  and closed["child_pid"] > 0 and closed.get("child_returncode") == 0,
                  "coding_parent_process_not_terminal")
    summary = batch.read_json(root / "summary.json")
    batch.require(summary.get("paid") is plan["paid"] and summary.get("plan_sha256") == batch.digest(plan)
                  and summary.get("output") == str(root), "coding_parent_summary_identity_changed")
    rows = summary.get("rows", [])
    batch.require(summary.get("finished") is True and summary.get("denominator_retained") is True
                  and summary.get("all_16_responses_received") is True and len(rows) == 16
                  and not summary.get("error_type") and not summary.get("generation_error_type"),
                  "coding_parent_public_denominator_incomplete")
    generations, evidence, executions = [], [], set()
    for expected, row in zip(plan["rows"], rows):
        directory = root / "drafts" / expected["run_id"]
        generation = batch.read_json(directory / "generation.json")
        batch.require(all(row.get(key) == generation.get(key) == value for key, value in expected.items())
                      and all(row.get(key) == value for key, value in generation.items() if key not in {"public", "hidden"})
                      and row.get("generation_status") in ({"parsed", "parse_failed"} if deadline else {"parsed"}),
                      "coding_parent_candidate_changed_or_unparsed")
        generations.append(generation)
        if row["generation_status"] == "parse_failed":
            batch.require(row.get("public", {}).get("status") == row.get("hidden", {}).get("status") == "not_evaluated"
                          and not (directory / "candidate.py").exists(), "coding_parse_failure_evidence_changed")
            continue
        batch.require(batch.file_hash(directory / "candidate.py") == row["parse"]["code_sha256"],
                      "coding_parent_candidate_changed_or_unparsed")
        public = batch.read_json(directory / "public-summary.json")
        batch.require(public == row.get("public") == batch.read_json(directory / "public" / "public-result.json")
                      and public.get("task_id") == expected["task_id"] and public.get("visibility") == "public"
                      and public.get("status") in ({"pass", "fail"} if deadline else {"pass"})
                      and public.get("reason") == "public_checks_complete"
                      and type(public.get("total")) is int and public["total"] > 0
                      and public.get("checked") == public["total"]
                      and type(public.get("passed")) is int and 0 <= public["passed"] <= public["total"]
                      and len(public.get("checks", [])) == public["total"]
                      and all(type(check.get("passed")) is bool for check in public["checks"])
                      and sum(check["passed"] for check in public["checks"]) == public["passed"]
                      and (public["status"] == "pass") == (public["passed"] == public["total"]),
                      "extension_requires_all_16_public_pass")
        # The archived checker uses the fixed polynomial residual for task 32;
        # all other first16 tasks launch a separate reference worker.
        expected_executions = ["public/candidate/execution.json", "hidden/candidate/execution.json"]
        if expected["number"] != 32:
            expected_executions.append("hidden/reference/execution.json")
        for relative in expected_executions:
            path = directory / relative
            execution = batch.read_json(path)
            batch.require(execution.get("worker_cli_reaped") is True and execution.get("cleanup", {}).get("removed") is True,
                          "coding_judge_cleanup_not_confirmed")
            if relative == "public/candidate/execution.json":
                batch.require(execution.get("source_sha256") == row["parse"]["code_sha256"], "public_judge_candidate_changed")
            executions.add(path)
        evidence.append({"run_id": expected["run_id"], "candidate_sha256": row["parse"]["code_sha256"],
                         "public_summary_sha256": batch.file_hash(directory / "public-summary.json")})
    batch.require(set((root / "drafts").glob("*/**/execution.json")) == executions,
                  "coding_unregistered_judge_execution")
    batch.require(batch.digest(generations) == batch.read_json(root / "generation-closed.json").get("records_sha256"),
                  "coding_generation_records_changed")
    decision = {"rule": "complete_first16_parsed_and_public_pass_v1", "planned_denominator": 16,
            "parsed": len(evidence), "public_pass": sum(row.get("public", {}).get("status") == "pass" for row in rows),
            "hidden_scores_used": False, "candidates": evidence,
            "process_closed_sha256": batch.file_hash(root / "execution-process-closed.json"),
            "summary_sha256": batch.file_hash(root / "summary.json")}
    if deadline:
        selected = next((row for row in rows if row["run_id"] == "draft-11-he99-deepseek-flash-rep2"), None)
        batch.require(selected is not None and selected["generation_status"] == "parsed"
                      and selected["public"]["status"] == "fail" and selected["public"]["passed"] == 3
                      and selected["public"]["total"] == 4 and len(evidence) == 15 and decision["public_pass"] == 14,
                      "deadline_requires_frozen_natural_public_seed")
        decision.update(rule="extension16_public_failed_seed_v1", seed={
            "run_id": selected["run_id"], "task_id": selected["task_id"], "source_model": selected["model"],
            "candidate_sha256": selected["parse"]["code_sha256"],
            "public_summary_sha256": batch.file_hash(root / "drafts" / selected["run_id"] / "public-summary.json")})
    return decision


def _coding_parent_basis(root: Path, historical_sources: Path, *, deadline: bool = False) -> dict:
    """Caller owns study/parent locks. Only first16 may admit the sole extension."""
    current = head()
    parent_stage = CODING_EXTENSION if deadline else CODING_STAGE
    batch.require(current["root"] == str(root) and current["stage_name"] == parent_stage,
                  "coding_extension_requires_first16_head")
    plan = batch.read_json(root / "plan.json")
    event = _assert_active_record(root, plan)
    _coding_contract(plan, historical=True)
    batch.require(plan["stage"] == parent_stage
                  and plan.get("coding_stage", "first16") == ("extension16" if deadline else "first16")
                  and batch.money(plan["cap_cny"]) == 200 and batch.money(plan["study_batch_cap_cny"]) == CODING_CAP,
                  "coding_parent_stage_changed")
    archive = _coding_source_archive(historical_sources, plan, event)
    batch.require(plan["provenance_sha256"] == batch.digest(batch.read_json(root / "provenance.json")),
                  "coding_parent_provenance_changed")
    registry, genesis = _registry()
    if plan["paid"]:
        batch.require(plan["imports"] == registry["imports"] == batch.r1_inventory(), "coding_historical_inventory_changed")
    for item in plan["imports"]:
        batch.check_refs(Path(item["directory"]), item["artifacts"])
    events = _coding_events(root, plan)
    batch.require(len(events) == 3 and _http_closed(root, plan), "coding_parent_billing_not_terminal")
    terminal = events[-1]
    batch.require(terminal["event"] == "settle", "coding_extension_requires_known_settled_parent")
    batch.require(terminal["data"]["artifacts"] == _coding_refs(root), "coding_terminal_artifacts_changed")
    known, liabilities = batch.money(plan["study_opening"]["known_cny"]), list(plan["study_opening"]["liabilities"])
    cost = _coding_closed_cost(root, plan)
    batch.require(cost == batch.money(terminal["data"]["cost_cny"]), "coding_parent_settled_cost_changed")
    known += cost
    origins = [(item["origin_plan_sha256"], item["run_id"]) for item in liabilities]
    batch.require(len(origins) == len(set(origins)), "duplicate_carried_liability")
    decision = _coding_public_extension_evidence(root, plan, deadline=deadline)
    committed = known + sum((batch.money(item["held_cny"]) for item in liabilities), Decimal(0))
    batch.require(committed + (DEADLINE_CAP if deadline else CODING_CAP) <= 200, "whole_coding_batch_does_not_fit")
    return {"schema": 1, "root": str(root), "genesis_sha256": genesis, "previous_head_sha256": current["sha256"],
            "kind": "advance-coding-deadline" if deadline else "advance-coding-extension16",
            "stage_name": DEADLINE_STAGE if deadline else CODING_EXTENSION,
            "terminal": terminal["event"], "plan_sha256": batch.digest(plan), "ledger_tip_sha256": terminal["sha256"],
            "files": _files(root), "source_archive": archive, "public_decision": decision,
            "opening": {"known_cny": str(known), "liabilities": liabilities},
            "committed_cny": str(committed), "remaining_cny": str(Decimal(200) - committed),
            "scientific_use": ("native128 and public-seed common16 deadline development; R2 remains incomplete" if deadline else
                               "one predefined first-draft extension; hidden scores do not choose the branch")}


class CodingAdmission:
    """A live locked session, not a caller-supplied budget or credential."""
    def __init__(self, root: Path, plan: dict, token: object) -> None:
        batch.require(token is _CODING_TOKEN, "coding_admission_requires_live_session")
        self.root, self.plan, self.batch_cap_cny, self._live = root, plan, str(CODING_CAP), True

    def assert_live(self, root: Path, plan: dict) -> None:
        batch.require(self._live and batch.local_path(root) == self.root and batch.digest(plan) == batch.digest(self.plan)
                      and len(_coding_events(self.root, self.plan)) == 2, "coding_admission_not_live")
        assert_active(self.root, self.plan)
        _coding_identity(self.root, self.plan)

    def finish(self) -> dict:
        self.assert_live(self.root, self.plan)
        batch.require(_http_closed(self.root, self.plan), "coding_http_cleanup_not_confirmed")
        opening = self.plan["study_opening"]
        known = batch.money(opening["known_cny"])
        carried = sum((batch.money(item["held_cny"]) for item in opening["liabilities"]), Decimal(0))
        try:
            cost = _coding_closed_cost(self.root, self.plan)
        except (OSError, ValueError, KeyError, TypeError, batch.PilotError):
            held = max(CODING_CAP, batch.observed_commitment(self.root))
            _coding_append(self.root, self.plan, "stop", {"liability_cny": str(held), "artifacts": _coding_refs(self.root),
                                                        "reason": "whole_coding_batch_unresolved"})
            return {"status": "held", "liability_cny": str(held), "study_known_cny": str(known),
                    "study_committed_cny": str(known + carried + held), "requests_allowed": False, "http_closed": True}
        _coding_append(self.root, self.plan, "settle", {"cost_cny": str(cost), "artifacts": _coding_refs(self.root)})
        return {"status": "known_settled", "batch_cost_cny": str(cost),
                "study_known_cny": str(known + cost), "study_committed_cny": str(known + carried + cost),
                "requests_allowed": False, "http_closed": True}


_CODING_TOKEN = object()


@contextmanager
def coding_session(root: Path, *, execute_paid: bool = False):
    """One irreversible 16-slot attempt; transport owns all per-request accounting.

    Keep this context around generation and shielded HTTP close. Write the
    billing result after close succeeds, call admission.finish(), then leave
    the context before any judge work. An unfinished/unknown batch cannot retry.
    """
    root = batch.local_path(root)
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(root):
        plan = batch.read_json(root / "plan.json")
        batch.require(plan["paid"] is execute_paid, "coding_paid_fake_mismatch")
        assert_active(root, plan)
        _coding_identity(root, plan)
        batch.require(len(_coding_events(root, plan)) == 1 and not any((root / name).exists() for name in
                      ("requests.jsonl", "result.json", "generation-closed.json", "drafts")), "coding_batch_cannot_resume_or_repeat")
        opening = plan["study_opening"]
        committed = batch.money(opening["known_cny"]) + sum((batch.money(x["held_cny"]) for x in opening["liabilities"]), Decimal(0))
        batch.require(committed + CODING_CAP <= 200, "whole_coding_batch_does_not_fit")
        _coding_append(root, plan, "reserve", {"reservation_cny": str(CODING_CAP)})
        admission = CodingAdmission(root, plan, _CODING_TOKEN)
        try:
            yield admission
            batch.require(len(_coding_events(root, plan)) == 3 and _http_closed(root, plan), "coding_batch_not_closed")
        except BaseException:
            try:
                events = _coding_events(root, plan)
                if len(events) == 2:
                    held = max(CODING_CAP, batch.observed_commitment(root))
                    _coding_append(root, plan, "stop", {"liability_cny": str(held), "artifacts": _coding_refs(root),
                                                       "reason": "whole_coding_batch_unresolved"})
            except BaseException as exc:
                raise batch.ProcessCleanupError("coding_accounting_uncertain_lock_retained") from exc
            if not _http_closed(root, plan):
                raise batch.ProcessCleanupError("coding_http_cleanup_not_confirmed_lock_retained")
            raise
        finally:
            admission._live = False


def _deadline_contract(plan: dict) -> None:
    from coding_deadline import rows as deadline_rows, validate_plan
    rows = plan.get("trajectories", [])
    expected = Counter((cohort, number, model, policy, delay, repeat)
        for cohort, numbers in (("native", (55, 32, 7, 56, 16, 99, 18, 31)), ("common", (99,)))
        for number in numbers for model in batch.MODELS for policy in ("resample", "repair")
        for delay in (0, 1) for repeat in (1, 2))
    cells = Counter((row.get("cohort"), row.get("number"), row.get("model"), row.get("policy"),
                     row.get("delay_s"), row.get("repeat")) for row in rows)
    ids = [row.get("run_id") for row in rows]
    deadlines = plan.get("deadlines_s", [])
    batch.require(rows == deadline_rows() and cells == expected and len(rows) == len(set(ids)) == 144
                  and all(isinstance(rid, str) and rid and Path(rid).name == rid and rid not in {".", ".."} for rid in ids)
                  and all(row.get("task_id") == f"HumanEval/{row['number']}" for row in rows),
                  "deadline_requires_frozen_native128_common16")
    batch.require(type(plan.get("max_rounds")) is int and plan["max_rounds"] >= 64
                  and batch.money(plan["batch_cap_cny"]) == DEADLINE_CAP
                  and batch.money(plan["per_request_cap_cny"]) == Decimal("0.20")
                  and len(deadlines) == 2 and all(type(d) in (int, float) and math.isfinite(d) and d > 0 for d in deadlines)
                  and deadlines[0] < deadlines[1] and plan.get("heldout_used") is False,
                  "deadline_limits_not_frozen")
    contract = plan.get("request_contract", {})
    wanted = {"endpoint": "https://api.deepseek.com/chat/completions", "temperature": 0.7,
              "max_tokens": 2048, "n": 1, "stream": False, "thinking": {"type": "disabled"},
              "retries": 0, "http_operation_timeout_s": 60, "whole_request_timeout_s": 65}
    batch.require(all(contract.get(key) == value for key, value in wanted.items()), "deadline_request_contract_changed")
    batch.require(plan.get("known_settlement_stop_reasons") == list(DEADLINE_KNOWN_STOPS),
                  "deadline_settlement_policy_changed")
    batch.require(plan.get("code_sha256") == {name: batch.file_hash(batch.ROOT / "research" / name) for name in DEADLINE_FILES},
                  "deadline_executor_source_changed")
    ref = plan["calibration_ref"]
    path = batch.local_path(Path(ref["path"]))
    calibration = batch.read_json(path)
    batch.require(batch.file_hash(path) == ref["sha256"] and calibration.get("status") == "passed"
                  and calibration.get("provider_calls") == 0 and calibration.get("full_loop_calibration") is True
                  and calibration.get("deadlines_s") == deadlines
                  and calibration.get("code_sha256") == plan["code_sha256"]
                  and calibration.get("runtime_identity") == plan["runtime_identity"]
                  and calibration.get("study_sha256") == batch.file_hash(Path(__file__))
                  and calibration.get("batch_sha256") == batch.file_hash(Path(batch.__file__))
                  and (not plan["paid"] or not calibration.get("fixture_only")), "deadline_calibration_not_verified")
    minimum = calibration.get("min_prior_http_s")
    batch.require(type(minimum) in (int, float) and math.isfinite(minimum) and minimum > 0
                  and plan["max_rounds"] == calibration.get("max_rounds") == max(64, math.ceil(deadlines[-1] / minimum) + 2),
                  "deadline_round_guard_not_calibrated")
    if not calibration.get("fixture_only"):
        from coding_deadline_calibration import verify_calibration
        try:
            verify_calibration(calibration)
        except ValueError as exc:
            raise batch.PilotError("deadline_calibration_evidence_invalid") from exc
        fields = ("setup_once_p90_s", "round_other_p90_s", "prior_http_p90_s", "prior_public_p90_s")
        batch.require(all(type(calibration.get(key)) in (int, float) and math.isfinite(calibration[key])
                          and calibration[key] >= 0 for key in fields), "deadline_calibration_timings_invalid")
        short = max(5, math.ceil(sum(calibration[key] for key in fields) + 1))
        batch.require(deadlines == [short, short * 3], "deadline_seconds_not_calibrated")
    try:
        validate_plan(plan)
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise batch.PilotError("deadline_executor_plan_mismatch") from exc


def _deadline_identity(root: Path, plan: dict) -> None:
    from coding_pilot import runtime_identity
    _deadline_contract(plan)
    admission = plan["study_admission"]
    batch.require(plan["stage"] == admission["stage_name"] == DEADLINE_STAGE
                  and admission["kind"] == "advance-coding-deadline" and batch.money(plan["cap_cny"]) == 200
                  and plan["runtime_identity"] == runtime_identity(require_wsl=plan["paid"])
                  and admission["module_sha256"] == batch.file_hash(Path(__file__))
                  and admission["batch_module_sha256"] == batch.file_hash(Path(batch.__file__))
                  and batch.digest(batch.read_json(root / "provenance.json")) == plan["provenance_sha256"],
                  "deadline_execution_identity_changed")


def _deadline_seed(plan: dict, seal: dict) -> None:
    wanted = {"parent_root": seal["root"], **{key: seal["public_decision"]["seed"][key]
              for key in ("run_id", "candidate_sha256", "public_summary_sha256")}}
    batch.require(plan.get("seed_ref") == wanted, "deadline_common_seed_changed")


def prepare_deadline(parent: Path, root: Path, deadline_plan: dict, provenance: dict, *, historical_sources: Path) -> dict:
    parent, root = batch.local_path(parent), batch.local_path(root)
    batch.require(not root.exists() and not root.is_relative_to(parent) and not parent.is_relative_to(root),
                  "deadline_requires_fresh_root")
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(parent):
        seal = _coding_parent_basis(parent, historical_sources, deadline=True)
        _deadline_contract(deadline_plan)
        _deadline_seed(deadline_plan, seal)
        registry, _ = _registry()
        old = batch.read_json(parent / "plan.json")
        batch.require(deadline_plan["paid"] is old["paid"] is registry.get("paid", True)
                      and batch.digest(provenance) == old["provenance_sha256"], "deadline_mode_or_provenance_changed")
        plan = {**deadline_plan, "stage": DEADLINE_STAGE, "cap_cny": "200", "imports": registry["imports"],
                "study_opening": seal["opening"], "provenance_sha256": batch.digest(provenance),
                "study_admission": {"kind": "advance-coding-deadline", "stage_name": DEADLINE_STAGE,
                    "previous_head_sha256": seal["previous_head_sha256"], "parent_root": str(parent),
                    "parent_seal_sha256": batch.digest(seal), "module_sha256": batch.file_hash(Path(__file__)),
                    "batch_module_sha256": batch.file_hash(Path(batch.__file__))}}
        root.mkdir(parents=True, exist_ok=False)
        for name, content in (("parent-seal.json", seal), ("plan.json", plan), ("provenance.json", provenance)):
            batch.write_new(root / name, content)
        _deadline_append(root, plan, "open", {"plan_sha256": batch.digest(plan)})
        return {"status": "prepared_not_active", "pilot_root": str(root), "plan_sha256": batch.digest(plan),
                "opening": seal["opening"], "remaining_cny": seal["remaining_cny"], "model_calls": 0}


def _activate_deadline(root: Path, plan: dict, plan_sha256: str, review: Path, review_sha256: str) -> dict:
    admission = plan["study_admission"]
    parent = batch.local_path(Path(admission["parent_root"]))
    with batch.exclusive(parent):
        batch.require(batch.digest(plan) == plan_sha256 and review.is_file() and review.stat().st_size > 0
                      and batch.file_hash(review) == review_sha256, "deadline_plan_or_review_hash_mismatch")
        _deadline_identity(root, plan)
        seal = batch.read_json(root / "parent-seal.json")
        batch.require(batch.digest(seal) == admission["parent_seal_sha256"]
                      and seal == _coding_parent_basis(parent, Path(seal["source_archive"]["manifest"]["path"]), deadline=True)
                      and plan["study_opening"] == seal["opening"], "deadline_parent_or_opening_changed")
        _deadline_seed(plan, seal)
        batch.require(len(_deadline_events(root, plan)) == 1 and set(_files(root)) == {
            "parent-seal.json", "plan.json", "provenance.json", "deadline-ledger.jsonl"}, "deadline_successor_not_pristine")
        current = head()
        registry, _ = _registry()
        batch.require(current["sha256"] == admission["previous_head_sha256"]
                      and plan["paid"] is registry.get("paid", True) and plan["imports"] == registry["imports"],
                      "deadline_parent_head_changed")
        payload = {"schema": 1, "seq": current["count"], "previous_sha256": current["sha256"],
            "kind": admission["kind"], "stage_name": DEADLINE_STAGE, "parent_root": str(parent), "root": str(root),
            "plan_sha256": plan_sha256, "plan_file_sha256": batch.file_hash(root / "plan.json"),
            "parent_seal_sha256": admission["parent_seal_sha256"], "opening": seal["opening"],
            "module_sha256": admission["module_sha256"], "source_archive": seal["source_archive"],
            "review": {"path": str(review), "sha256": review_sha256}, "utc": datetime.now(timezone.utc).isoformat()}
        record = {**payload, "sha256": batch.digest(payload)}
        _publish(record)
        return {"status": "activated_no_model_calls", "head_sha256": record["sha256"], "pilot_root": str(root),
                "opening": seal["opening"], "model_calls": 0}


def _deadline_events(root: Path, plan: dict) -> list[dict]:
    path = root / "deadline-ledger.jsonl"
    if not path.exists():
        return []
    raw, events = path.read_bytes(), []
    batch.require(raw.endswith(b"\n"), "torn_deadline_ledger")
    for line in raw.splitlines():
        record = json.loads(line)
        batch.require(batch.canonical(record) == line and record["seq"] == len(events)
            and record["previous_sha256"] == (events[-1]["sha256"] if events else None)
            and record["sha256"] == batch.digest({k: v for k, v in record.items() if k != "sha256"}), "invalid_deadline_ledger")
        events.append(record)
    batch.require(1 <= len(events) <= 3 and events[0]["event"] == "open"
                  and events[0]["data"] == {"plan_sha256": batch.digest(plan)}, "deadline_opening_mismatch")
    if len(events) > 1:
        batch.require(events[1]["event"] == "reserve" and events[1]["data"] == {"reservation_cny": str(DEADLINE_CAP)},
                      "deadline_reservation_mismatch")
    if len(events) == 3:
        last = events[-1]
        batch.require((last["event"] == "settle" and batch.money(last["data"]["cost_cny"]) <= DEADLINE_CAP)
                      or (last["event"] == "stop" and batch.money(last["data"]["liability_cny"]) >= DEADLINE_CAP),
                      "deadline_terminal_mismatch")
    return events


def _deadline_append(root: Path, plan: dict, event: str, data: dict) -> None:
    events = _deadline_events(root, plan)
    batch.require((len(events), event) in {(0, "open"), (1, "reserve"), (2, "settle"), (2, "stop")}, "deadline_cannot_repeat")
    payload = {"seq": len(events), "previous_sha256": events[-1]["sha256"] if events else None,
               "event": event, "data": data, "utc": datetime.now(timezone.utc).isoformat()}
    with (root / "deadline-ledger.jsonl").open("ab") as stream:
        stream.write(batch.canonical({**payload, "sha256": batch.digest(payload)}) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _deadline_refs(root: Path) -> dict:
    return {name: batch.file_hash(root / name) for name in
            ("requests.jsonl", "result.json", "generation-closed.json", "trajectories.json") if (root / name).is_file()}


def _deadline_closed(root: Path, plan: dict) -> bool:
    try:
        result, closure = batch.read_json(root / "result.json"), batch.read_json(root / "generation-closed.json")
        raw = (root / "requests.jsonl").read_bytes()
        last = json.loads(raw.splitlines()[-1])
        batch.require(raw.endswith(b"\n") and last.get("event") == "batch_close" and last.get("active_calls") == 0
                      and result.get("plan_sha256") == batch.digest(plan) and result.get("paid") is plan["paid"]
                      and result.get("denominator") == closure.get("denominator") == 144, "deadline_http_not_closed")
        for document in (result, closure):
            batch.require(document.get("http_closed") is True and document.get("public_resources_closed") is True
                          and document.get("requests_sha256") == batch.file_hash(root / "requests.jsonl")
                          and document.get("trajectories_sha256") == batch.file_hash(root / "trajectories.json"),
                          "deadline_closure_artifact_mismatch")
        resources = closure["public_resources"]
        seen = set()
        for ref in resources:
            path = (root / ref["path"]).resolve()
            batch.require(path.is_relative_to(root) and not path.is_symlink() and path not in seen
                          and path.name == "public-resource-closed.json" and batch.file_hash(path) == ref["sha256"],
                          "deadline_public_resource_ref_changed")
            document = batch.read_json(path)
            batch.require(document.get("closed") is True and document.get("worker_reaped") is True
                          and document.get("containers_removed") is True, "deadline_public_resource_unclosed")
            seen.add(path)
        batch.require(seen == set(root.rglob("public-resource-closed.json")), "deadline_public_resource_inventory_changed")
        trajectories = batch.read_json(root / "trajectories.json")
        issued = [attempt for row in trajectories for attempt in row["attempts"] if "public_started_at_s" in attempt]
        batch.require(len(issued) == len(seen)
                      and {json.dumps(attempt["public_resource"], sort_keys=True) for attempt in issued}
                          == {json.dumps(ref, sort_keys=True) for ref in resources}, "deadline_public_issue_inventory_changed")
        return True
    except (OSError, ValueError, KeyError, IndexError, TypeError, batch.PilotError):
        return False


def _deadline_closed_cost(root: Path, plan: dict) -> Decimal:
    """Known billing can close even when public science stops unsuccessfully.

    This does not authorize another run or declare the matrix complete. The
    frozen whitelist never excuses unknown usage, cancellation, or cleanup.
    """
    batch.require(_deadline_closed(root, plan), "deadline_resources_not_closed")
    result, closure = batch.read_json(root / "result.json"), batch.read_json(root / "generation-closed.json")
    stop = result.get("stop_reason")
    batch.require(plan.get("known_settlement_stop_reasons") == list(DEADLINE_KNOWN_STOPS),
                  "deadline_settlement_policy_changed")
    batch.require(result.get("interrupted") is False and closure.get("interrupted") is False
                  and stop in DEADLINE_KNOWN_STOPS, "deadline_abnormal_stop")
    trajectories = batch.read_json(root / "trajectories.json")
    batch.require(isinstance(trajectories, list) and len(trajectories) == 144
                  and [row.get("run_id") for row in trajectories] == [row["run_id"] for row in plan["trajectories"]],
                  "deadline_denominator_changed")
    for frozen, row in zip(plan["trajectories"], trajectories):
        batch.require(all(row.get(key) == value for key, value in frozen.items())
                      and row.get("status") in {"complete", "stopped", "not_started"}, "deadline_trajectory_not_terminal")
        if row["status"] == "complete":
            batch.require(row.get("stop_reason") in (None, "max_rounds_censored", "request_guard_censored"),
                          "deadline_unexplained_complete_trajectory")
            if row.get("stop_reason") == "request_guard_censored":
                batch.require(row.get("censored") is True and row.get("guard_reason") in DEADLINE_REQUEST_GUARDS,
                              "deadline_request_guard_mismatch")
        else:
            batch.require((not plan["paid"] and row.get("stop_reason") == "offline_fixture_not_selected")
                          or (stop is not None and row.get("stop_reason") == (
                              "batch_stopped:" + stop if row["status"] == "not_started" else stop)),
                          "deadline_unexplained_unfinished_trajectory")
        if row["status"] != "not_started":
            snapshots = row.get("snapshots", [])
            batch.require(len(snapshots) == 2 and [s.get("deadline_s") for s in snapshots] == plan["deadlines_s"],
                          "deadline_snapshots_missing")
            for snapshot in snapshots:
                path = (root / snapshot["path"]).resolve()
                batch.require(path.is_relative_to(root) and batch.file_hash(path) == snapshot["sha256"],
                              "deadline_snapshot_changed")
    events = [json.loads(line) for line in (root / "requests.jsonl").read_bytes().splitlines()]
    dispatch = [e for e in events if e.get("event") == "request_dispatch"]
    complete = [e for e in events if e.get("event") == "request_complete"]
    ids = [e.get("request_id") for e in dispatch]
    order = {row["run_id"]: index for index, row in enumerate(plan["trajectories"])}
    indices = [order.get(e.get("labels", {}).get("run_id"), -1) for e in dispatch]
    batch.require(events[0].get("event") == "batch_open" and sum(e.get("event") == "batch_open" for e in events) == 1
                  and sum(e.get("event") == "batch_close" for e in events) == 1 and len(ids) <= 144 * plan["max_rounds"]
                  and len(ids) == len(set(ids)) and all(isinstance(rid, str) and rid for rid in ids)
                  and ids == [e.get("request_id") for e in complete]
                  and indices == sorted(indices) and all(index >= 0 for index in indices)
                  and not any(e.get("event") in {"request_unknown", "request_rejected"} for e in events),
                  "deadline_usage_not_fully_known")
    by_id, attempts = {row["run_id"]: row for row in plan["trajectories"]}, Counter()
    for event in dispatch:
        labels, body = event.get("labels", {}), event.get("request_body", {})
        row = by_id.get(labels.get("run_id"))
        batch.require(row is not None, "deadline_dispatch_unknown_trajectory")
        attempts[row["run_id"]] += 1
        batch.require(attempts[row["run_id"]] <= plan["max_rounds"] and labels.get("case_id") == f"attempt-{attempts[row['run_id']]:02d}"
                      and all(labels.get(key) == row[key] for key in ("run_id", "task_id", "model", "repeat"))
                      and labels.get("phase") == row["cohort"]
                      and labels.get("condition") == f"{row['policy']}/delay-{row['delay_s']}"
                      and labels.get("deadline_s") == plan["deadlines_s"][-1] and body.get("model") == row["model"]
                      and all(body.get(key) == plan["request_contract"][key] for key in ("stream", "thinking", "max_tokens", "temperature", "n"))
                      and batch.money(event["reservation_cny"]) <= Decimal("0.20"), "deadline_dispatch_contract_changed")
    cost = sum((batch.money(e["provider_usage_peak_estimate_cny"]) for e in complete), Decimal(0))
    for account in (events[-1], result["accounting"], closure["transport"]):
        batch.require(account.get("calls_dispatched") == len(ids) and account.get("max_calls") == 144 * plan["max_rounds"]
                      and account.get("unknown_calls") == account.get("active_calls") == 0
                      and account.get("stop_reason") is None and batch.money(account["reserved_cny"]) == 0
                      and batch.money(account["spent_estimate_cny"]) == cost
                      and batch.money(account["batch_budget_cny"]) == DEADLINE_CAP, "deadline_accounting_mismatch")
    batch.require(cost <= DEADLINE_CAP, "deadline_cost_exceeds_guard")
    return cost


def _official_parent_basis(root: Path, historical_sources: Path) -> dict:
    """Seal a settled deadline parent; caller holds the study and parent locks."""
    current = head()
    batch.require(current["root"] == str(root) and current["stage_name"] == DEADLINE_STAGE,
                  "official_requires_deadline_head")
    plan = batch.read_json(root / "plan.json")
    event = _assert_active_record(root, plan)
    batch.require(plan.get("stage") == DEADLINE_STAGE and batch.money(plan["cap_cny"]) == 200,
                  "official_parent_stage_changed")
    archive = _coding_source_archive(historical_sources, plan, event, deadline=True)
    registry, genesis = _registry()
    if plan["paid"]:
        batch.require(plan["imports"] == registry["imports"] == batch.r1_inventory(),
                      "official_historical_inventory_changed")
    for item in plan["imports"]:
        batch.check_refs(Path(item["directory"]), item["artifacts"])
    events = _deadline_events(root, plan)
    batch.require(len(events) == 3 and events[-1]["event"] == "settle",
                  "official_requires_known_settled_parent")
    terminal = events[-1]
    batch.require(terminal["data"]["artifacts"] == _deadline_refs(root), "official_parent_artifacts_changed")
    cost = _deadline_closed_cost(root, plan)
    batch.require(cost == batch.money(terminal["data"]["cost_cny"]), "official_parent_settled_cost_changed")
    known = batch.money(plan["study_opening"]["known_cny"]) + cost
    liabilities = list(plan["study_opening"]["liabilities"])
    origins = [(item["origin_plan_sha256"], item["run_id"]) for item in liabilities]
    batch.require(len(origins) == len(set(origins)), "duplicate_carried_liability")
    committed = known + sum((batch.money(item["held_cny"]) for item in liabilities), Decimal(0))
    batch.require(committed < 200, "official_no_remaining_study_budget")
    return {"schema": 1, "root": str(root), "genesis_sha256": genesis,
            "previous_head_sha256": current["sha256"], "kind": "advance-timely-official",
            "stage_name": OFFICIAL_STAGE, "terminal": "settle", "plan_sha256": batch.digest(plan),
            "ledger_tip_sha256": terminal["sha256"], "files": _files(root), "source_archive": archive,
            "opening": {"known_cny": str(known), "liabilities": liabilities},
            "committed_cny": str(committed), "remaining_cny": str(Decimal(200) - committed)}


def _official_identity(plan: dict) -> None:
    admission = plan["study_admission"]
    batch.require(plan.get("stage") == admission.get("stage_name") == OFFICIAL_STAGE
                  and admission.get("kind") == "advance-timely-official" and batch.money(plan["cap_cny"]) == 200
                  and admission.get("module_sha256") == batch.file_hash(Path(__file__))
                  and admission.get("batch_module_sha256") == batch.file_hash(Path(batch.__file__)),
                  "official_prepared_code_changed")
    batch.require(isinstance(plan.get("source"), str) and bool(plan["source"])
                  and all(isinstance(plan.get(key), list) and plan[key] for key in ("games", "models", "rows"))
                  and plan.get("tool_format") == "official", "official_protocol_missing")
    rows = plan["rows"]
    batch.require(all(isinstance(row, dict) and isinstance(row.get("run_id"), str) and row["run_id"] for row in rows)
                  and len({row["run_id"] for row in rows}) == len(rows), "official_duplicate_or_missing_run_id")
    sources = plan.get("runner_sha256")
    batch.require(isinstance(sources, dict) and "timely_official.py" in sources, "official_runner_identity_missing")
    for name, sha in sources.items():
        batch.require(isinstance(name, str) and Path(name).name == name and name.endswith(".py")
                      and isinstance(sha, str) and len(sha) == 64
                      and batch.file_hash(Path(__file__).parent / name) == sha, "official_runner_source_changed")


def prepare_official(parent: Path, root: Path, protocol: dict) -> dict:
    """Prepare one inert official successor; its runner owns execution accounting.

    protocol contains the runner's frozen configuration and a historical_sources
    manifest path. No row template or new budget is imposed by this admission.
    """
    parent, root = batch.local_path(parent), batch.local_path(root)
    batch.require(not root.exists() and not root.is_relative_to(parent) and not parent.is_relative_to(root),
                  "official_requires_fresh_root")
    config = dict(protocol)
    historical_sources = Path(config.pop("historical_sources"))
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(parent):
        seal = _official_parent_basis(parent, historical_sources)
        registry, _ = _registry()
        paid = registry.get("paid", True)
        batch.require(config.get("paid", paid) is paid and batch.money(config.get("cap_cny", "200")) == 200,
                      "official_mode_or_budget_changed")
        plan = {**config, "stage": OFFICIAL_STAGE, "paid": paid, "cap_cny": "200", "imports": registry["imports"],
                "study_opening": seal["opening"],
                "study_admission": {"kind": "advance-timely-official", "stage_name": OFFICIAL_STAGE,
                    "previous_head_sha256": seal["previous_head_sha256"], "parent_root": str(parent),
                    "parent_seal_sha256": batch.digest(seal), "module_sha256": batch.file_hash(Path(__file__)),
                    "batch_module_sha256": batch.file_hash(Path(batch.__file__))}}
        _official_identity(plan)
        root.mkdir(parents=True, exist_ok=False)
        batch.write_new(root / "parent-seal.json", seal)
        batch.write_new(root / "plan.json", plan)
        return {"status": "prepared_not_active", "pilot_root": str(root), "plan_sha256": batch.digest(plan),
                "plan_file_sha256": batch.file_hash(root / "plan.json"), "opening": seal["opening"],
                "committed_cny": seal["committed_cny"], "remaining_cny": seal["remaining_cny"], "model_calls": 0}


def _activate_official(root: Path, plan: dict, plan_sha256: str, review: Path, review_sha256: str) -> dict:
    admission = plan["study_admission"]
    parent = batch.local_path(Path(admission["parent_root"]))
    with batch.exclusive(parent):
        batch.require(batch.digest(plan) == plan_sha256 and review.is_file() and review.stat().st_size > 0
                      and batch.file_hash(review) == review_sha256, "official_plan_or_review_hash_mismatch")
        _official_identity(plan)
        seal = batch.read_json(root / "parent-seal.json")
        batch.require(batch.digest(seal) == admission["parent_seal_sha256"]
                      and seal == _official_parent_basis(parent, Path(seal["source_archive"]["manifest"]["path"]))
                      and plan["study_opening"] == seal["opening"], "official_parent_or_opening_changed")
        batch.require(set(_files(root)) == {"parent-seal.json", "plan.json"}, "official_successor_not_pristine")
        current = head()
        registry, _ = _registry()
        batch.require(current["sha256"] == admission["previous_head_sha256"]
                      and plan["paid"] is registry.get("paid", True) and plan["imports"] == registry["imports"],
                      "official_parent_head_changed")
        payload = {"schema": 1, "seq": current["count"], "previous_sha256": current["sha256"],
            "kind": admission["kind"], "stage_name": OFFICIAL_STAGE, "parent_root": str(parent), "root": str(root),
            "plan_sha256": plan_sha256, "plan_file_sha256": batch.file_hash(root / "plan.json"),
            "parent_seal_sha256": admission["parent_seal_sha256"], "opening": seal["opening"],
            "module_sha256": admission["module_sha256"], "source_archive": seal["source_archive"],
            "review": {"path": str(review), "sha256": review_sha256}, "utc": datetime.now(timezone.utc).isoformat()}
        record = {**payload, "sha256": batch.digest(payload)}
        _publish(record)
        return {"status": "activated_no_model_calls", "head_sha256": record["sha256"], "pilot_root": str(root),
                "opening": seal["opening"], "model_calls": 0}


_DEADLINE_TOKEN = object()


class DeadlineAdmission:
    """Full audit at entry/final seal; bounded checks during timed work.

    The study reserves CNY 120 once. Transport releases each known request's
    unused reservation immediately; maximum future request slots reserve no
    additional money. Unknown usage holds the whole study reservation once.
    """
    def __init__(self, root: Path, plan: dict, token: object) -> None:
        batch.require(token is _DEADLINE_TOKEN, "deadline_admission_requires_live_session")
        self.root, self.plan, self.batch_cap_cny, self._live = root, plan, str(DEADLINE_CAP), True
        self._head_sha = head()["sha256"]
        self._plan_file_sha = batch.file_hash(root / "plan.json")
        self._plan_sha = batch.digest(plan)
        self._lock_refs = {p: batch.file_hash(p) for p in (root / "pilot.lock", batch.PAID_STUDY_ROOT / "pilot.lock")}

    def assert_live(self, root: Path, plan: dict) -> None:
        batch.require(self._live and batch.local_path(root) == self.root and batch.digest(plan) == self._plan_sha
                      and batch.file_hash(self.root / "plan.json") == self._plan_file_sha
                      and len(_deadline_events(self.root, self.plan)) == 2, "deadline_admission_not_live")
        batch.require(head()["sha256"] == self._head_sha
                      and all(batch.file_hash(path) == sha for path, sha in self._lock_refs.items()), "deadline_active_head_or_lock_changed")
        sources = {**self.plan["code_sha256"], "timely_study.py": self.plan["study_admission"]["module_sha256"],
                   "timely_batch.py": self.plan["study_admission"]["batch_module_sha256"]}
        batch.require(all(batch.file_hash(batch.ROOT / "research" / name) == sha for name, sha in sources.items()),
                      "deadline_live_source_changed")

    def finish(self) -> dict:
        self.assert_live(self.root, self.plan)
        batch.require(_deadline_closed(self.root, self.plan), "deadline_resources_not_closed")
        assert_active(self.root, self.plan)
        _deadline_identity(self.root, self.plan)
        known = batch.money(self.plan["study_opening"]["known_cny"])
        carried = sum((batch.money(x["held_cny"]) for x in self.plan["study_opening"]["liabilities"]), Decimal(0))
        try:
            cost = _deadline_closed_cost(self.root, self.plan)
        except (OSError, ValueError, KeyError, TypeError, batch.PilotError):
            held = max(DEADLINE_CAP, batch.observed_commitment(self.root))
            _deadline_append(self.root, self.plan, "stop", {"liability_cny": str(held), "artifacts": _deadline_refs(self.root)})
            return {"status": "held", "liability_cny": str(held), "study_known_cny": str(known),
                    "study_committed_cny": str(known + carried + held), "requests_allowed": False}
        _deadline_append(self.root, self.plan, "settle", {"cost_cny": str(cost), "artifacts": _deadline_refs(self.root)})
        return {"status": "known_settled", "batch_cost_cny": str(cost), "study_known_cny": str(known + cost),
                "study_committed_cny": str(known + carried + cost), "requests_allowed": False,
                "scientific_stop_reason": batch.read_json(self.root / "result.json").get("stop_reason")}


@contextmanager
def deadline_session(root: Path, *, execute_paid: bool = False):
    root = batch.local_path(root)
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(root):
        plan = batch.read_json(root / "plan.json")
        batch.require(plan["paid"] is execute_paid, "deadline_paid_fake_mismatch")
        assert_active(root, plan)
        _deadline_identity(root, plan)
        batch.require(len(_deadline_events(root, plan)) == 1 and not any((root / name).exists() for name in
            ("requests.jsonl", "result.json", "generation-closed.json", "trajectories.json")), "deadline_cannot_repeat")
        opening = plan["study_opening"]
        committed = batch.money(opening["known_cny"]) + sum((batch.money(x["held_cny"]) for x in opening["liabilities"]), Decimal(0))
        batch.require(committed + DEADLINE_CAP <= 200, "deadline_guard_does_not_fit")
        _deadline_append(root, plan, "reserve", {"reservation_cny": str(DEADLINE_CAP)})
        admission = DeadlineAdmission(root, plan, _DEADLINE_TOKEN)
        try:
            yield admission
            batch.require(len(_deadline_events(root, plan)) == 3 and _deadline_closed(root, plan), "deadline_batch_not_closed")
        except BaseException:
            try:
                if len(_deadline_events(root, plan)) == 2:
                    _deadline_append(root, plan, "stop", {"liability_cny": str(max(DEADLINE_CAP, batch.observed_commitment(root))),
                                                         "artifacts": _deadline_refs(root)})
            except BaseException as exc:
                raise batch.ProcessCleanupError("deadline_accounting_uncertain_lock_retained") from exc
            if not _deadline_closed(root, plan):
                raise batch.ProcessCleanupError("deadline_resources_unclosed_lock_retained")
            raise
        finally:
            admission._live = False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-revision")
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--pilot-root", type=Path, required=True)
    prepare.add_argument("--tool-format", choices=("official", "single-json-v1", "single-json-v2"), required=True)
    for command in ("prepare-coding16", "prepare-coding-extension16", "prepare-deadline"):
        coding_prepare = commands.add_parser(command)
        coding_prepare.add_argument("--parent", type=Path, required=True)
        coding_prepare.add_argument("--pilot-root", type=Path, required=True)
        coding_prepare.add_argument("--coding-plan", type=Path, required=True)
        coding_prepare.add_argument("--provenance", type=Path, required=True)
        coding_prepare.add_argument("--historical-sources", type=Path, required=True)
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
        elif args.command in {"prepare-coding16", "prepare-coding-extension16", "prepare-deadline"}:
            prepare_function = {"prepare-coding16": prepare_coding16, "prepare-coding-extension16": prepare_coding_extension16,
                                "prepare-deadline": prepare_deadline}[args.command]
            result = prepare_function(args.parent, args.pilot_root, batch.read_json(args.coding_plan),
                                      batch.read_json(args.provenance), historical_sources=args.historical_sources)
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
