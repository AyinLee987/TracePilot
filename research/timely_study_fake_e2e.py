"""Focused succession checks with real subprocess fixtures and zero API calls."""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import timely_batch as batch
import timely_study as study
from timely_batch_fake_e2e import check, expect_error, prefix


def main() -> int:
    check(sys.platform == "linux", "WSL process ownership required")
    parent = Path(tempfile.mkdtemp(prefix="timely-study-fixture-", dir=batch.ROOT / ".local"))
    source, game = parent / "source", parent / "fixture.z5"
    package = source / "src" / "timely_eval"
    package.mkdir(parents=True)
    (package / "interactive.py").write_text("# Synthetic provenance fixture.\n")
    (package / "prompts.py").write_text('INTERACTIVE_SYSTEM = "Fixture system"\nINTERACTIVE_TOOL_PROMPT = "Fixture tools"\n')
    game.write_bytes(b"synthetic game identity")
    checks = []

    @contextmanager
    def fixture(name: str, history: str = "0.008655072"):
        directory = parent / name
        directory.mkdir()
        root = directory / "original"
        plan = batch.create_plan(root, source, game)
        historical = directory / "historical"
        historical.mkdir()
        batch.write_new(historical / "billing.json", {"paid": False, "cost_cny": history})
        # Seed an explicitly offline historical expense. These files are fixture
        # inputs, never imported into or confused with the real paid study.
        plan["imports"] = [{"directory": str(historical), "run_id": "offline-history", "paid": False,
                            "cost_cny": history, "billing_known": True,
                            "artifacts": {"billing.json": batch.file_hash(historical / "billing.json")}}]
        (root / "plan.json").unlink()
        (root / "ledger.jsonl").unlink()
        batch.write_new(root / "plan.json", plan)
        batch.Ledger(root, plan).append("open", {"plan_sha256": batch.digest(plan)})
        registry = directory / "study"
        registry.mkdir()
        batch.write_new(registry / "registry.json", {"schema": 1, "study": "timely-pilot-20261006", "cap_cny": "200",
            "paid": False, "fixture_only": True, "pilot_root": str(root), "imports": plan["imports"], "blocked_unknown_history": False})
        review = directory / "review.json"
        batch.write_new(review, {"fixture_review": "offline only; explicit plan-hash gate exercised by caller"})
        with patch.object(batch, "PAID_STUDY_ROOT", registry):
            yield directory, root, plan, review

    def stopped(root: Path, scenario: str = "unusable") -> None:
        expect_error(lambda: batch.run_pilot(root, execute_offline=True, fixture_prefix=prefix(root, scenario)), scenario)
        check(batch.Ledger(root, batch.read_json(root / "plan.json")).state["stopped"] is not None, "terminal source")

    def activate(root: Path, review: Path):
        return study.activate(root, plan_sha256=batch.digest(batch.read_json(root / "plan.json")),
                              review=review, review_sha256=batch.file_hash(review))

    with fixture("known-protocol-failure") as (directory, root, plan, review):
        stopped(root)
        before = study._files(root)
        genesis_hash = batch.file_hash(batch.PAID_STUDY_ROOT / "registry.json")
        ledger = batch.Ledger(root, plan)
        check(ledger.state["next"] == 1 and ledger.state["reserved"], "known failed source with unstarted reservation")
        revised, branch = directory / "revision", directory / "branch"
        prepared = study.prepare_revision(root, revised, tool_format="single-json-v2")
        study.prepare_revision(root, branch, tool_format="single-json-v2")
        newplan = batch.read_json(revised / "plan.json")
        check(newplan["identity"]["tool_format"] == "single-json-v2" and newplan["rows"] == plan["rows"]
              and len(newplan["rows"]) == 24 and all(row["mode"] == "speed" for row in newplan["rows"][:8]), "full v2 revision")
        check(newplan["study_admission"]["module_sha256"] == batch.file_hash(Path(study.__file__)), "module frozen")
        check(newplan["study_opening"] == {"known_cny": "0.028655072", "liabilities": []}, "known cost counted once")
        seal = batch.read_json(revised / "parent-seal.json")
        check(set(seal["released_unstarted_reservations"]) == set(ledger.state["reserved"]), "only unstarted holds released")
        check(study._files(root) == before and batch.file_hash(batch.PAID_STUDY_ROOT / "registry.json") == genesis_hash,
              "legacy bytes preserved")
        checks += ["known_protocol_failure_settles_actual_once", "full_independent_24_rows_v2",
                   "study_module_hash_frozen", "unstarted_reservations_released_after_cleanup", "legacy_files_and_genesis_unchanged"]
        check(batch.run_pilot(revised)["status"] == "dry", "prepared dry")
        expect_error(lambda: batch.run_pilot(revised, execute_offline=True, fixture_prefix=prefix(revised)), "inert prepared plan")
        check(not (revised / "runs").exists(), "unactivated zero dispatch")
        for plan_hash, review_hash in (("0" * 64, batch.file_hash(review)), (prepared["plan_sha256"], "0" * 64)):
            expect_error(lambda: study.activate(revised, plan_sha256=plan_hash, review=review, review_sha256=review_hash), "review gate")
        check(not (batch.PAID_STUDY_ROOT / "transitions.jsonl").exists(), "failed gates publish no head")
        checks += ["prepare_is_inert_and_dry", "explicit_plan_and_review_hash_gates"]
        # Rebuild only this inert fixture's opening event after manual edits;
        # even a caller supplying the edited digest cannot raise the study cap
        # or erase historical imports at activation.
        for key, value in (("cap_cny", "201"), ("imports", [])):
            bad = dict(newplan)
            bad[key] = value
            (revised / "plan.json").unlink()
            (revised / "ledger.jsonl").unlink()
            batch.write_new(revised / "plan.json", bad)
            batch.Ledger(revised, bad).append("open", {"plan_sha256": batch.digest(bad)})
            expect_error(lambda: activate(revised, review), "edited invariant")
            (revised / "plan.json").unlink()
            (revised / "ledger.jsonl").unlink()
            batch.write_new(revised / "plan.json", newplan)
            batch.Ledger(revised, newplan).append("open", {"plan_sha256": batch.digest(newplan)})
        checks.append("reviewed_hash_cannot_raise_cap_or_drop_history")
        with patch.object(study.os, "replace", side_effect=OSError("injected before atomic publication")):
            expect_error(lambda: activate(revised, review), "crash before publication")
        check(study.head()["root"] == str(root), "failed publication keeps original active head")
        result = activate(revised, review)
        chain_hash = batch.file_hash(batch.PAID_STUDY_ROOT / "transitions.jsonl")
        check(result["model_calls"] == 0 and study.head()["root"] == str(revised), "atomic activation")
        expect_error(lambda: activate(revised, review), "duplicate activation")
        expect_error(lambda: activate(branch, review), "fork activation")
        expect_error(lambda: batch.verify_active_stage(root, plan), "old head must not spend")
        check(batch.file_hash(batch.PAID_STUDY_ROOT / "transitions.jsonl") == chain_hash, "refused branches never append")
        checks += ["failed_atomic_publication_has_no_binding", "exact_activation_retry_after_inert_temp",
                   "duplicate_and_fork_activation_refused", "old_head_refused"]
        raw_review = review.read_bytes()
        review.write_bytes(raw_review + b" ")
        expect_error(lambda: batch.run_pilot(revised, execute_offline=True, fixture_prefix=prefix(revised)), "review tamper")
        review.write_bytes(raw_review)
        check(not (revised / "runs").exists(), "review tamper zero dispatch")
        checks.append("activation_review_tamper_refused")
        first = batch.run_pilot(revised, execute_offline=True, max_runs=4, fixture_prefix=prefix(revised))
        check(first["settled_runs"] == 4 and not (revised / "calibrations").exists(), "no old tau borrowed")
        finished = batch.run_pilot(revised, execute_offline=True, fixture_prefix=prefix(revised))
        check(finished["status"] == "complete" and finished["settled_runs"] == 24
              and finished["spent_estimate_cny"] == "0.748655072", "fresh full matrix executable")
        basis = study.extension_basis(revised, "r2-four-game-v1")
        check(basis["opening"] == {"known_cny": "0.748655072", "liabilities": []}
              and basis["remaining_cny"] == "199.251344928", "complete stage carries cumulative budget")
        expect_error(lambda: study.extension_basis(revised, "r3-coding-v1"), "cannot skip named stage")
        check(study.head()["root"] == str(revised), "extension seam alone grants no executor")
        check(study._files(root) == before, "completed revision leaves legacy unchanged")
        checks += ["fresh_calibration_before_timed", "full_revised_matrix_subprocess_e2e",
                   "complete_extension_basis_carries_cumulative_budget", "extension_is_audit_only_no_hidden_executor"]
        # Verify the complete-stage seal is not a way to ignore altered origins.
        old_result = root / "runs" / plan["rows"][0]["run_id"] / "result.json"
        raw_result = old_result.read_bytes()
        old_result.write_bytes(raw_result + b" ")
        expect_error(lambda: study.extension_basis(revised, "r2-four-game-v1"), "old raw changed")
        old_result.write_bytes(raw_result)
        checks.append("sealed_old_raw_tamper_refused")

    with fixture("unknown-overcap") as (directory, root, plan, review):
        stopped(root, "overcap")
        old = batch.Ledger(root, plan)
        rid = plan["rows"][0]["run_id"]
        held = old.state["reserved"][rid]
        revised = directory / "revision"
        study.prepare_revision(root, revised, tool_format="single-json-v2")
        activate(revised, review)
        newplan = batch.read_json(revised / "plan.json")
        opening = newplan["study_opening"]
        check(opening["known_cny"] == "0.008655072" and len(opening["liabilities"]) == 1
              and opening["liabilities"][0]["held_cny"] == held
              and Decimal(held) > Decimal(plan["rows"][0]["cap_cny"]), "unknown and overcap liability retained")
        check(batch.Ledger(revised, newplan).committed() == Decimal("0.008655072") + Decimal(held), "unknown not counted twice")
        stopped(revised)
        expect_error(lambda: study.prepare_revision(revised, directory / "second", tool_format="single-json-v2"), "one revision only")
        check(not (directory / "second").exists(), "second failure ends adaptation")
        checks += ["unknown_overcap_liability_carried_without_double_count", "second_small_revision_refused"]

    with fixture("missing-result") as (directory, root, plan, review):
        stopped(root, "missing-result")
        revised = directory / "revision"
        study.prepare_revision(root, revised, tool_format="single-json-v2")
        opening = batch.read_json(revised / "plan.json")["study_opening"]
        check(opening["liabilities"][0]["held_cny"] == plan["rows"][0]["cap_cny"], "missing result retains full guard")
        checks.append("missing_result_retains_full_guard")

    with fixture("uncertain-cleanup") as (directory, root, plan, review):
        stopped(root)
        proof = root / "processes" / f"{plan['rows'][0]['run_id']}.closed.json"
        proof.unlink()
        expect_error(lambda: study.prepare_revision(root, directory / "revision", tool_format="single-json-v2"), "missing cleanup")
        check(not (directory / "revision").exists() and not (batch.PAID_STUDY_ROOT / "transitions.jsonl").exists(),
              "uncertain cleanup has no release or new binding")
        checks.append("uncertain_cleanup_blocks_all_migration")

    with fixture("clean-stop-not-terminal") as (directory, root, plan, review):
        batch.run_pilot(root, execute_offline=True, max_runs=1, fixture_prefix=prefix(root))
        expect_error(lambda: study.prepare_revision(root, directory / "revision", tool_format="single-json-v2"), "clean stop")
        check(not (directory / "revision").exists(), "resumable stage cannot branch")
        checks.append("resumable_clean_stop_cannot_migrate")

    with fixture("preparation-io-failure") as (directory, root, plan, review):
        stopped(root)
        revised = directory / "revision"
        extra = root / "runs" / "unregistered-attempt"
        extra.mkdir()
        expect_error(lambda: study.prepare_revision(root, revised, tool_format="single-json-v2"), "unregistered attempt")
        check(not revised.exists(), "unknown attempt cannot be omitted")
        extra.rmdir()
        checks.append("unregistered_attempt_inventory_blocks_migration")
        original_write = batch.write_new
        def fail_plan(path, value):
            if path == revised / "plan.json":
                raise OSError("injected preparation failure")
            original_write(path, value)
        with patch.object(batch, "write_new", side_effect=fail_plan):
            expect_error(lambda: study.prepare_revision(root, revised, tool_format="single-json-v2"), "prepare failure")
        check(study.head()["root"] == str(root) and not (batch.PAID_STUDY_ROOT / "transitions.jsonl").exists(),
              "failed preparation never binds registry")
        expect_error(lambda: activate(revised, review), "partial preparation inert")
        checks.append("failed_preparation_never_binds_registry")

    with fixture("residual-block-cap", history="170") as (directory, root, plan, review):
        stopped(root)
        expect_error(lambda: study.prepare_revision(root, directory / "revision", tool_format="single-json-v2"), "whole block residual")
        check(not (directory / "revision").exists(), "residual cap checked before writes")
        checks.append("whole_first_block_must_fit_residual_cap")

    summary = {"status": "passed", "checks": checks, "check_count": len(checks), "provider_calls": 0,
               "fake_children_only": True, "real_evaluator_rerun": False,
               "code_sha256": {name: batch.file_hash(Path(__file__).with_name(name)) for name in
                   ("timely_batch.py", "timely_study.py", "timely_batch_fake_e2e.py", "timely_study_fake_e2e.py")}}
    batch.write_new(parent / "summary.json", summary)
    print(batch.canonical({"summary": str(parent / "summary.json"), **summary}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
