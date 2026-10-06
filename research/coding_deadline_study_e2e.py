"""Isolated deadline admission E2E; all provider responses and judge proofs are fake."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx
import coding_pilot as pilot
import timely_batch as batch
import timely_study as study


def check(value, reason):
    if not value:
        raise AssertionError(reason)


def refused(function, reason):
    try:
        function()
    except batch.PilotError as exc:
        check(str(exc) == reason, f"expected {reason}, received {exc}")
    else:
        raise AssertionError(f"did not refuse {reason}")


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(batch.canonical(obj) + b"\n")


def archive_coding(root: Path, archive: Path) -> Path:
    plan, event = batch.read_json(root / "plan.json"), study.head()["transition"]
    archive.mkdir()
    files = {}
    for name in ("timely_study.py", "timely_batch.py", *study.CODING_FILES):
        raw = (batch.ROOT / "research" / name).read_bytes()
        (archive / name).write_bytes(raw)
        normalized = raw.replace(b"\r\n", b"\n")
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "source_repository_path": f"research/{name}",
            "git_blob": hashlib.sha1(b"blob " + str(len(normalized)).encode() + b"\0" + normalized).hexdigest()}
    path = archive / "manifest.json"
    write(path, {"schema": 2, "kind": "coding-terminal-source-archive", "fixture_only": True,
        "source_commit": "c" * 40, "source_plan_file_sha256": batch.file_hash(root / "plan.json"),
        "source_plan_canonical_sha256": batch.digest(plan), "activation_review": event["review"], "files": files})
    return path


@contextmanager
def isolated_parent(base: Path):
    """Real coding executor/accounting, explicitly synthetic pre-coding history and judges."""
    real_root = batch.PAID_STUDY_ROOT.resolve()
    base.mkdir()
    registry, genesis = base / "study", base / "genesis"
    registry.mkdir()
    genesis.mkdir()
    write(genesis / "fixture.json", {"synthetic_history": True})
    write(registry / "registry.json", {"schema": 1, "study": "timely-pilot-20261006", "cap_cny": "200",
        "paid": False, "fixture_only": True, "pilot_root": str(genesis), "imports": [], "blocked_unknown_history": False})
    review = base / "review.json"
    write(review, {"fixture_only": True})
    with patch.object(batch, "PAID_STUDY_ROOT", registry):
        check(registry.resolve().is_relative_to(base.resolve()) and registry.resolve() != real_root
              and batch.PAID_STUDY_ROOT == registry, "fixture cannot touch actual study")
        parent = genesis
        tasks, provenance = pilot.coding.load_tasks()
        for kind, stage, name in (("revise-small", study.REVISION, "timely"),
                                  ("advance-coding-first-draft", study.CODING_STAGE, "first"),
                                  ("advance-coding-extension16", study.CODING_EXTENSION, "extension")):
            current, root = study.head(), base / name
            root.mkdir()
            seal = {"root": str(parent), "files": study._files(parent), "fixture_only": True}
            write(root / "parent-seal.json", seal)
            plan = {"paid": False, "imports": [], "study_opening": {"known_cny": "0.296871136", "liabilities": []}}
            if stage == study.CODING_EXTENSION:
                plan.update(pilot.make_plan(paid=False, stage="extension16"))
                plan.update(stage=stage, cap_cny="200", study_batch_cap_cny="3.20",
                    provenance_sha256=batch.digest(provenance),
                    study_runtime={"python": sys.version, "executable": str(Path(sys.executable).resolve())},
                    study_admission={"kind": kind, "stage_name": stage, "previous_head_sha256": current["sha256"],
                        "parent_root": str(parent), "parent_seal_sha256": batch.digest(seal),
                        "module_sha256": batch.file_hash(Path(study.__file__)),
                        "batch_module_sha256": batch.file_hash(Path(batch.__file__))})
                write(root / "provenance.json", provenance)
            write(root / "plan.json", plan)
            event = {"schema": 1, "seq": current["count"], "previous_sha256": current["sha256"], "kind": kind,
                "stage_name": stage, "parent_root": str(parent), "root": str(root), "plan_sha256": batch.digest(plan),
                "plan_file_sha256": batch.file_hash(root / "plan.json"), "parent_seal_sha256": batch.digest(seal),
                "opening": plan["study_opening"], "module_sha256": batch.file_hash(Path(study.__file__)),
                "review": {"path": str(review), "sha256": batch.file_hash(review)}}
            study._publish({**event, "sha256": batch.digest(event)})
            parent = root
        study._coding_append(parent, plan, "open", {"plan_sha256": batch.digest(plan)})
        index = 0
        def reply(request):
            nonlocal index
            row = plan["rows"][index]
            index += 1
            task = tasks[row["number"]]
            content = "not a Python program" if index == 10 else task["prompt"] + task["canonical_solution"]
            return httpx.Response(200, json={"id": f"fixture-{index}", "model": row["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                          "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 20}})
        result = asyncio.run(pilot.execute_admitted(parent, execute_paid=False, inner=httpx.MockTransport(reply), evaluate=False))
        check(result["study_settlement"]["status"] == "known_settled", "fixture parent actual known settlement")
        for row in result["rows"]:
            if row["generation_status"] == "parse_failed":
                continue
            directory = parent / "drafts" / row["run_id"]
            failure = row["run_id"] == "draft-11-he99-deepseek-flash-rep2"
            public = {"task_id": row["task_id"], "visibility": "public", "status": "fail" if failure else "pass",
                "reason": "public_checks_complete", "total": 4, "checked": 4, "passed": 3 if failure else 4,
                "checks": [{"passed": not (failure and i == 3)} for i in range(4)], "fixture_only": True}
            row["public"] = public
            write(directory / "public-summary.json", public)
            write(directory / "public/public-result.json", public)
            for relative in ("public/candidate", "hidden/candidate", "hidden/reference"):
                write(directory / relative / "execution.json", {"worker_cli_reaped": True, "cleanup": {"removed": True},
                    "source_sha256": row["parse"]["code_sha256"], "fixture_only": True})
        write(parent / "summary.json", result)
        write(parent / "execution-process-closed.json", {"pilot_root": str(parent), "paid": False,
            "child_pid": 999999, "child_returncode": 0, "child_reaped": True, "fixture_only": True})
        archive = archive_coding(parent, base / "archive")
        yield parent, archive, review, tasks, provenance


@contextmanager
def prepared_deadline(base: Path, deadlines_s=(0.2, 0.6)):
    """Reusable temporary *real admission* for executor tests and offline calibration.

    This synthetic calibration record cannot admit a paid plan. A real loop
    calibration must emit its own measured record after using the live session.
    """
    import coding_deadline as deadline
    with isolated_parent(base) as (parent, archive, review, tasks, provenance), ExitStack() as stack:
        seed = parent / "drafts/draft-11-he99-deepseek-flash-rep2"
        for name, value in (("SEED_ROOT", parent), ("SEED_CODE_SHA", batch.file_hash(seed / "candidate.py")),
                            ("SEED_PUBLIC_SHA", batch.file_hash(seed / "public-summary.json"))):
            stack.enter_context(patch.object(deadline, name, value))
        calibration = base / "calibration-fixture.json"
        write(calibration, {"status": "passed", "fixture_only": True, "fixture_history": True,
            "meaning": "synthetic schema fixture; no claim of measured real-loop calibration", "provider_calls": 0,
            "full_loop_calibration": True, "deadlines_s": list(deadlines_s), "max_rounds": 64,
            "min_prior_http_s": 1.0, "code_sha256": deadline.identities(),
            "runtime_identity": pilot.runtime_identity(), "study_sha256": batch.file_hash(Path(study.__file__)),
            "batch_sha256": batch.file_hash(Path(batch.__file__))})
        ref = {"path": str(calibration), "sha256": batch.file_hash(calibration)}
        proposal = deadline.make_plan(list(deadlines_s), ref, paid=False, max_rounds=64)
        root = base / "deadline"
        prepared = study.prepare_deadline(parent, root, proposal, provenance, historical_sources=archive)
        yield {"root": root, "proposal": proposal, "prepared": prepared, "parent": parent, "archive": archive,
               "review": review, "tasks": tasks, "provenance": provenance, "calibration": calibration}


def backend(tasks: dict, *, unknown_second=False, long_pro_bytes=0):
    count = 0
    content = "\n".join(f"def {task['entry_point']}(*args, **kwargs):\n    return 0\n" for task in tasks.values())
    def reply(request):
        nonlocal count
        count += 1
        model = json.loads(request.content)["model"]
        source = content + ("#" + "x" * long_pro_bytes + "\n" if model == "deepseek-v4-pro" and long_pro_bytes else "")
        body = {"id": f"deadline-fixture-{count}", "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": source}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 20}}
        if unknown_second and count == 2:
            del body["usage"]
        return httpx.Response(200, json=body)
    return httpx.MockTransport(reply)


async def fake_checker(task, source, image_id, output):
    output.mkdir(parents=True)
    write(output / "public-resource-closed.json", {"closed": True, "worker_reaped": True,
        "containers_removed": True, "started": False, "fixture_only": True})
    return {"task_id": task["task_id"], "visibility": "public", "status": "pass", "reason": "public_checks_complete",
            "passed": 1, "total": 1, "checked": 1, "checks": [{"passed": True}], "fixture_only": True}


def preflight_retry(base: Path) -> int:
    """One targeted B1 check: a static failure consumes no one-shot reserve."""
    import coding_deadline as deadline
    with prepared_deadline(base / "preflight-retry", deadlines_s=(0.5, 1.5)) as fixture:
        root = fixture["root"]
        plan = batch.read_json(root / "plan.json")
        study.activate(root, plan_sha256=fixture["prepared"]["plan_sha256"], review=fixture["review"],
                       review_sha256=batch.file_hash(fixture["review"]))
        ledger = (root / "deadline-ledger.jsonl").read_bytes()
        current = study.head()
        with patch.object(deadline.coding.sandbox, "verify_daemon", side_effect=RuntimeError("fixture_daemon_unavailable")):
            try:
                deadline.static_preflight(root, plan, real_public=True)
            except RuntimeError as exc:
                check(str(exc) == "fixture_daemon_unavailable", "exact failed static preflight reason")
            else:
                raise AssertionError("static preflight unexpectedly succeeded")
        check((root / "deadline-ledger.jsonl").read_bytes() == ledger and study.head() == current
              and len(study._deadline_events(root, plan)) == 1 and not (root / "requests.jsonl").exists(),
              "failed daemon preflight leaves opening/head untouched and dispatches nothing")
        check(not (root / "pilot.lock").exists() and not (batch.PAID_STUDY_ROOT / "pilot.lock").exists(),
              "no reservation or lock held by static failure")
        prepared = deadline.static_preflight(root, plan, real_public=False)
        selected = next(row["run_id"] for row in plan["trajectories"] if row["number"] == 55
                        and row["model"] == "deepseek-flash" and row["delay_s"] == 0)
        with study.deadline_session(root) as admission:
            result = asyncio.run(deadline.execute_batch(root, plan, admission, _prepared=prepared,
                inner=backend(fixture["tasks"]), checker=fake_checker, offline_trajectory_ids=[selected]))
            settled = admission.finish()
        check(settled["status"] == "known_settled" and result["accounting"]["calls_dispatched"] > 0
              and study._deadline_events(root, plan)[-1]["event"] == "settle", "successful preflight retries same active root")
        receipts = list(root.glob("static-preflight-*"))
        check(len(receipts) == 2, "failed and successful preflight evidence retained")
        report = {"status": "passed", "checks": ["daemon_preflight_failure_zero_reserve_zero_dispatch",
            "failure_leaves_head_ledger_and_locks_unchanged", "same_root_second_preflight_live_session_known_settlement",
            "both_static_preflight_receipts_preserved"], "provider_calls": 0, "judge_containers": 0,
            "fixture_only": True, "summary": str(base / "summary.json"), "code_sha256": {
                name: batch.file_hash(batch.ROOT / "research" / name) for name in
                ("timely_study.py", "coding_deadline_study_e2e.py", *deadline.RUNTIME_FILES)}}
        write(base / "summary.json", report)
        print(batch.canonical(report).decode())
    return 0


def main() -> int:
    check(sys.platform == "linux", "run fixture in WSL")
    def guard(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("fixture_network_forbidden")
    sys.addaudithook(guard)
    base = Path(tempfile.mkdtemp(prefix="deadline-study-fixture-", dir=batch.ROOT / ".local"))
    if sys.argv[1:] == ["--preflight-retry"]:
        return preflight_retry(base)
    check(not sys.argv[1:], "only --preflight-retry or the default suite is supported")
    checks = []
    import coding_deadline as deadline
    for scenario in ("known", "unknown", "unclosed", "cap_guard", "message_guard", "feedback_guard", "public_infra", "known_context"):
      with prepared_deadline(base / scenario, deadlines_s=(0.5, 1.5)) as fixture:
        root, parent = fixture["root"], fixture["parent"]
        basis = study._coding_parent_basis(parent, fixture["archive"], deadline=True)
        check(basis["public_decision"]["parsed"] == 15 and basis["public_decision"]["public_pass"] == 14,
              "actual extension parent shape")
        before = study._files(parent)
        current = study.head()
        plan = batch.read_json(root / "plan.json")
        if scenario == "known":
            check(len(plan["trajectories"]) == 144 and 144 * plan["max_rounds"] * .20 > 120,
                  "whole guard is not multiplied by unused slots")
            def unactivated():
                with study.deadline_session(root):
                    raise AssertionError("not admitted")
            refused(unactivated, "stage_is_not_active_study_head")
            bad = json.loads(json.dumps(fixture["proposal"]))
            bad["trajectories"] = bad["trajectories"][:-1]
            refused(lambda: study.prepare_deadline(parent, base / scenario / "bad", bad, fixture["provenance"],
                historical_sources=fixture["archive"]), "deadline_requires_frozen_native128_common16")
            check(study.head() == current and not (base / scenario / "bad").exists(), "failed prepare does not claim head")
            checks += ["extension_parent_15parsed_1parsefail_public_seed_known_fees", "exact_reason_unactivated_dispatch_refused",
                       "exact_reason_no_cherry_picking_no_head_mutation", "unused_maximum_slots_not_reserved"]
            calibration = fixture["calibration"]
            original_calibration = calibration.read_bytes()
            calibration.write_bytes(original_calibration + b" ")
            refused(lambda: study._deadline_contract(fixture["proposal"]), "deadline_calibration_not_verified")
            calibration.write_bytes(original_calibration)
            bad = json.loads(json.dumps(fixture["proposal"]))
            bad["paid"] = True
            refused(lambda: study._deadline_contract(bad), "deadline_calibration_not_verified")
            bad = json.loads(json.dumps(fixture["proposal"]))
            bad["known_settlement_stop_reasons"].append("unknown_response")
            refused(lambda: study._deadline_contract(bad), "deadline_settlement_policy_changed")
            checks += ["exact_reason_calibration_tamper_refused", "exact_reason_synthetic_calibration_cannot_admit_paid"]
            checks += ["exact_reason_settlement_stop_whitelist_frozen"]
        study.activate(root, plan_sha256=fixture["prepared"]["plan_sha256"], review=fixture["review"],
                       review_sha256=batch.file_hash(fixture["review"]))
        selected = {row["run_id"] for row in plan["trajectories"] if row["number"] == 55 and row["delay_s"] == 0
                    and row["repeat"] == 1 and row["model"] == "deepseek-flash"}
        target = successor = None
        if scenario.endswith("_guard"):
            index, target = next((i, row) for i, row in enumerate(plan["trajectories"])
                if row["cohort"] == "native" and row["number"] == 55 and row["model"] == "deepseek-v4-pro"
                and row["policy"] == "repair" and row["delay_s"] == 0 and row["repeat"] == 1)
            successor = next(row for row in plan["trajectories"][index + 1:]
                             if row["model"] == "deepseek-flash" and row["delay_s"] == 0)
            selected = {target["run_id"], successor["run_id"]}
        async def checker(task, source, image_id, output):
            result = await fake_checker(task, source, image_id, output)
            if scenario == "unclosed":
                write(output / "public-resource-closed.json", {"closed": False, "worker_reaped": False,
                    "containers_removed": False, "fixture_only": True})
                result["status"] = "infra"
            elif scenario == "public_infra":
                result["status"] = "infra"
            elif scenario == "known_context":
                raise ValueError("fixture_known_public_exception")
            elif scenario == "feedback_guard" and target["run_id"] in output.parts:
                result["diagnostic"] = "x" * 13000
            return result
        try:
            with study.deadline_session(root) as admission:
                check(study._deadline_events(root, plan)[-1]["data"] == {"reservation_cny": "120"}, "120 reserved before executor")
                original_plan = (root / "plan.json").read_bytes()
                (root / "plan.json").write_bytes(original_plan + b" ")
                refused(lambda: admission.assert_live(root, plan), "deadline_admission_not_live")
                (root / "plan.json").write_bytes(original_plan)
                # Tripwire only, not an alternative admission: actual assert_live
                # must not recursively walk historical source/parent files online.
                with patch.object(study, "_check_seal", side_effect=AssertionError("online recursive history audit")):
                    admission.assert_live(root, plan)
                    outcome = asyncio.run(deadline.execute_batch(root, plan, admission,
                        inner=backend(fixture["tasks"], unknown_second=scenario == "unknown",
                                      long_pro_bytes={"cap_guard": 15000, "message_guard": 35000}.get(scenario, 0)), checker=checker,
                        offline_trajectory_ids=selected))
                settled = admission.finish()
        except batch.ProcessCleanupError as exc:
            check(scenario == "unclosed" and str(exc) == "deadline_resources_unclosed_lock_retained",
                  "only exact unclosed resource error expected")
        else:
            check(scenario != "unclosed", "unclosed resource must retain locks")
        check(len(batch.read_json(root / "trajectories.json")) == 144, "all trajectories retained")
        check(study._files(parent) == before, "parent remains immutable")
        if scenario == "known":
            check(settled["status"] == "known_settled", "variable known call count settles")
            events = [json.loads(line) for line in (root / "requests.jsonl").read_bytes().splitlines()]
            complete = [event for event in events if event.get("event") == "request_complete"]
            check(len(complete) >= 2 and outcome["accounting"]["reserved_cny"] == "0"
                  and outcome["accounting"]["committed_cny"] == outcome["accounting"]["spent_estimate_cny"],
                  "known requests release their own reserves and subsequent requests use actual remaining fees")
            def repeated():
                with study.deadline_session(root):
                    raise AssertionError("repeat admitted")
            refused(repeated, "deadline_cannot_repeat")
            checks += ["live_admission_no_online_recursive_history", "real_executor_known_variable_calls_settle",
                       "known_request_reservations_released_before_next_request", "full144_denominator",
                       "exact_reason_cannot_repeat", "paid_history_untouched"]
        elif scenario == "unknown":
            check(settled["status"] == "held" and settled["liability_cny"] == "120"
                  and settled["study_known_cny"] == plan["study_opening"]["known_cny"], "unknown holds whole guard once")
            check(outcome["accounting"]["calls_dispatched"] == 2, "unknown stops remaining requests")
            checks += ["real_executor_second_unknown_stops_all_rows", "unknown_whole120_not_plus_partial_known"]
        elif scenario == "unclosed":
            check((root / "pilot.lock").exists() and (batch.PAID_STUDY_ROOT / "pilot.lock").exists()
                  and study._deadline_events(root, plan)[-1]["data"]["liability_cny"] == "120",
                  "uncertain owned resource retains both locks and whole liability")
            checks += ["exact_reason_unclosed_public_resource_refused", "uncertain_cleanup_both_locks_and120_retained"]
        elif scenario.endswith("_guard"):
            records = {row["run_id"]: row for row in batch.read_json(root / "trajectories.json")}
            censored, later = records[target["run_id"]], records[successor["run_id"]]
            expected_guard = {"cap_guard": "per_request_cap", "message_guard": "message_limit_no_code_truncation",
                              "feedback_guard": "feedback_projection_limit"}[scenario]
            check(censored["status"] == "complete" and censored["censored"] is True
                  and censored["stop_reason"] == "request_guard_censored" and censored["guard_reason"] == expected_guard,
                  "exact request guard is local to the selected Pro repair trajectory")
            check(later["status"] == "complete" and any("dispatch_at_s" in a for a in later["attempts"])
                  and outcome["stop_reason"] is None and settled["status"] == "known_settled",
                  "later trajectory executes and known usage settles despite request guard")
            check(study._deadline_events(root, plan)[-1]["event"] == "settle"
                  and not (root / "pilot.lock").exists() and not (batch.PAID_STUDY_ROOT / "pilot.lock").exists(),
                  "scientific censoring is not an unknown whole-batch liability")
            checks += [scenario + "_local_pro_repair_censor_later_row_runs", scenario + "_known_cost_settles"]
        else:
            expected_stop = "public_infrastructure_failure" if scenario == "public_infra" else "request_or_context_failure"
            check(outcome["stop_reason"] == settled["scientific_stop_reason"] == expected_stop
                  and outcome["accounting"]["calls_dispatched"] == 1 and settled["status"] == "known_settled",
                  "closed known scientific failure settles actual cost and preserves reason")
            check(study._deadline_events(root, plan)[-1]["event"] == "settle"
                  and not (root / "pilot.lock").exists() and not (batch.PAID_STUDY_ROOT / "pilot.lock").exists(),
                  "closed known failure releases whole reserve without permitting another execution")
            checks += [scenario + "_closed_known_settles_without_scientific_success"]
    report = {"status": "passed", "checks": checks, "provider_calls": 0, "judge_containers": 0,
              "fixture_only": True, "code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name)
                  for name in ("timely_study.py", "coding_deadline_study_e2e.py")}}
    write(base / "summary.json", report)
    print(batch.canonical({"summary": str(base / "summary.json"), **report}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
