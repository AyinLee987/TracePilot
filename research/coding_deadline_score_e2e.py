"""Zero-provider, zero-Docker identity/closure tests for the offline scorer."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import coding_deadline as runner
import coding_deadline_score as scorer

batch, study, coding = scorer.batch, scorer.study, scorer.coding
dump = scorer.dump


def check(condition, reason):
    if not condition:
        raise AssertionError(reason)


def refused(function, reason):
    try:
        function()
    except batch.PilotError as exc:
        check(str(exc) == reason, f"expected {reason}, received {exc}")
    else:
        raise AssertionError("did not reject " + reason)


def terminal(root, *, held=False):
    plan = batch.read_json(root / "plan.json")
    refs = {"requests_sha256": batch.file_hash(root / "requests.jsonl"),
            "trajectories_sha256": batch.file_hash(root / "trajectories.json")}
    resources = [{"path": p.relative_to(root).as_posix(), "sha256": batch.file_hash(p)}
                 for p in sorted(root.rglob("public-resource-closed.json"))]
    dump(root / "result.json", {"paid": False, "plan_sha256": batch.digest(plan), "denominator": 144,
        "http_closed": True, "public_resources_closed": True, **refs})
    dump(root / "generation-closed.json", {"denominator": 144, "http_closed": True,
        "public_resources_closed": True, "public_resources": resources, **refs})
    path = root / "deadline-ledger.jsonl"
    if path.exists():
        path.unlink()  # Only the newly constructed synthetic fixture, never research evidence.
    study._deadline_append(root, plan, "open", {"plan_sha256": batch.digest(plan)})
    study._deadline_append(root, plan, "reserve", {"reservation_cny": "120"})
    study._deadline_append(root, plan, "stop" if held else "settle",
        {"liability_cny" if held else "cost_cny": "120" if held else "0", "artifacts": study._deadline_refs(root)})


def fixture(base):
    root, parent = base / "input", base / "seed-parent"
    root.mkdir(parents=True)
    tasks, provenance = coding.load_tasks()
    seed_code = "def closest_integer(value):\n    return 0\n"
    seed_public = {"task_id": "HumanEval/99", "visibility": "public", "status": "fail", "passed": 3, "total": 4}
    seed_dir = parent / "drafts" / "synthetic-seed"
    dump(seed_dir / "public-summary.json", seed_public)
    (root / "common-seed.py").write_text(seed_code, encoding="utf-8")
    # Deliberately different JSON bytes from the verified original: semantic copy.
    (root / "common-seed-public.json").write_text(json.dumps(seed_public, indent=2), encoding="utf-8")
    rows = runner.rows()
    plan = {"paid": False, "fixture_only": True, "trajectories": rows, "deadlines_s": [1, 3],
        "code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name) for name in scorer.GRADER_FILES},
        "provenance_sha256": batch.digest(provenance), "seed_ref": {"parent_root": str(parent),
            "run_id": "synthetic-seed", "candidate_sha256": batch.file_hash(root / "common-seed.py"),
            "public_summary_sha256": batch.file_hash(seed_dir / "public-summary.json")}}
    dump(root / "plan.json", plan)
    records = [{**r, "status": "not_started", "attempts": [], "snapshots": [None, None]} for r in rows]
    chosen = [r for r in records if r["number"] == 55][:2] + [next(r for r in records if r["cohort"] == "common")]
    source = "def fib(n):\n    return 0\n"
    for row in chosen:
        common = row["cohort"] == "common"
        count = 2 if row is chosen[0] else 1
        row["status"] = "complete"
        for index in range(1, count + 1):
            cid = f"attempt-{index:02d}"
            relative = f"trajectories/{row['run_id']}/{cid}/candidate.py"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(seed_code if common else source, encoding="utf-8")
            code_hash = batch.file_hash(path)
            attempt = {"candidate_id": cid, "status": "late_parse_no_tool" if common else "eligible",
                "candidate_path": relative, "code_sha256": code_hash, "parse": {"status": "parsed", "code_sha256": code_hash}}
            if not common:
                public_path = path.parent / "public-feedback.json"
                dump(public_path, {"status": "pass", "passed": 1, "total": 1})
                receipt = path.parent / "public/public-resource-closed.json"
                dump(receipt, {"closed": True, "worker_reaped": True, "containers_removed": True, "fixture_only": True})
                attempt.update(public_started_at_s=0.01, public_status="pass", public_passed=1, public_total=1,
                    public_path=public_path.relative_to(root).as_posix(), available_at_s=index / 10,
                    public_resource={"path": receipt.relative_to(root).as_posix(), "sha256": batch.file_hash(receipt)})
            dump(path.parent / "attempt.json", attempt)
            row["attempts"].append(attempt)
        if common:
            row["attempts"].append({"candidate_id": "attempt-02", "status": "late_response_accounted_only"})
            late = root / "trajectories" / row["run_id"] / "attempt-02"
            dump(late / "response.raw.json", {"content": "Never parse this late response into a candidate."})
            ref = {"candidate_id": "seed", "code_sha256": plan["seed_ref"]["candidate_sha256"],
                "candidate_path": "common-seed.py", "public_path": "common-seed-public.json",
                "public_passed": 3, "public_total": 4, "available_at_s": 0.0}
        else:
            ref = {key: row["attempts"][0][key] for key in scorer.REF_KEYS}
        row["baseline"] = {"attempt": 1, "outcome": "no_candidate" if common else "public_pass", "candidate": None if common else ref}
        row["first_eligible"] = None if common else ref
        row["snapshots"] = []
        for index, cutoff in enumerate(plan["deadlines_s"]):
            doc = {"index": index, "deadline_s": cutoff, "selected": ref, "status": "frozen"}
            path = root / "trajectories" / row["run_id"] / f"snapshot-{index+1}.json"
            dump(path, doc)
            row["snapshots"].append({**doc, "path": path.relative_to(root).as_posix(), "sha256": batch.file_hash(path)})
    dump(root / "trajectories.json", records)
    (root / "requests.jsonl").write_bytes(batch.canonical({"event": "batch_close", "active_calls": 0}) + b"\n")
    terminal(root)
    return root


def fake_checker(calls, *, infra=False, missing_cleanup=False, timeout_second=False):
    def hidden(task, source, image_id, output, *, timeout):
        calls.append(source)
        status = "infra" if infra else "pass" if len(calls) % 2 else "fail"
        if timeout_second and len(calls) == 2:
            status = "timeout"
        result = {"task_id": task["task_id"], "visibility": "offline_hidden", "status": status,
                  "reason": "fixture", "checked": 1, "total": 1, "passed": int(status == "pass")}
        dump(output / "hidden-result.json", result)
        dump(output / "candidate/execution.json", {"worker_cli_reaped": True,
            "cleanup": {"removed": not missing_cleanup}, "fixture_only": True})
        if missing_cleanup:
            dump(output / "candidate/create-command.json",
                 ["docker", "create", "--name", "tracepilot-coding-" + "b" * 32])
        return result
    return hidden


def missing_cleanup_check(base, root):
    calls, commands = [], []
    def command(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="")
    with patch.object(coding.sandbox, "command", command):
        stopped = scorer.score(root, base / "unclosed-hidden", checker=fake_checker(calls, missing_cleanup=True), fixture_only=True)
    name = "tracepilot-coding-" + "b" * 32
    check(stopped["stop_reason"] == "hidden_resource_unclosed" and len(calls) == 1
          and stopped["hidden_resources_closed"] is True and stopped["recovery"][0]["removed"] is True
          and commands == [["docker", "rm", "--force", name],
                           ["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"]],
          "normal checker return with failed cleanup recovers exact owner then stops grading")
    return ["normal_return_unclosed_exact_owned_recovery_then_stop"]


def actual_executor_checks(base: Path) -> list[str]:
    import coding_deadline_study_e2e as admission_fixture
    checks = []
    for cancel in (False, True):
        with admission_fixture.prepared_deadline(base / ("executor-cancel" if cancel else "executor-settle")) as fixture:
            root = fixture["root"]
            plan = batch.read_json(root / "plan.json")
            study.activate(root, plan_sha256=fixture["prepared"]["plan_sha256"], review=fixture["review"],
                           review_sha256=batch.file_hash(fixture["review"]))
            selected = next(row["run_id"] for row in plan["trajectories"] if row["model"] == "deepseek-flash"
                            and row["number"] == 55 and row["delay_s"] == 0)
            async def checker(task, source, image_id, output):
                result = await admission_fixture.fake_checker(task, source, image_id, output)
                if cancel:
                    asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
                return result
            with study.deadline_session(root) as admission:
                try:
                    asyncio.run(runner.execute_batch(root, plan, admission,
                        inner=admission_fixture.backend(fixture["tasks"]), checker=checker,
                        offline_trajectory_ids=[selected]))
                except asyncio.CancelledError:
                    check(cancel, "only selected cancellation expected")
                settlement = admission.finish()
            check(settlement["status"] == ("held" if cancel else "known_settled"), "actual terminal ledger type")
            data = scorer.inventory(root)
            check(data["terminal"]["event"] == ("stop" if cancel else "settle"), "inventory accepts actual executor terminal")
            result = scorer.score(root, base / ("actual-cancel-score" if cancel else "actual-settle-score"),
                                  checker=fake_checker([]), fixture_only=True)
            check(result["status"] == "complete" and result["input_unchanged"] and result["baseline_denominator"] == 144
                  and result["snapshot_denominator"] == 288 and result["persisted_candidate_count"] >= 1,
                  "actual executor records score without schema substitution")
            checks.append("real_admission_executor_" + ("cancel_stop" if cancel else "settle") + "_inventory_and_score")
    return checks


def review_checks(base, root):
    checks = []
    missing = base / "missing-baseline"
    shutil.copytree(root, missing)
    records = batch.read_json(missing / "trajectories.json")
    del records[0]["baseline"]
    dump(missing / "trajectories.json", records)
    terminal(missing)
    refused(lambda: scorer.inventory(missing), "score_started_baseline_missing")
    registry = base / "locked-study"
    registry.mkdir()
    (registry / "pilot.lock").write_text("active timed work")
    with patch.object(batch, "PAID_STUDY_ROOT", registry):
        refused(lambda: scorer.inventory(root), "score_live_study_present")
    checks += ["no_candidate_separate_from_not_evaluated", "no_persisted_candidate_separate_from_ungraded",
               "started_missing_baseline_refused", "global_study_lock_refused"]
    timeout_result = scorer.score(root, base / "timeout-score", checker=fake_checker([], timeout_second=True), fixture_only=True)
    transitions = batch.read_json(base / "timeout-score/attempts.json")
    check(timeout_result["status"] == "complete" and "hidden_fail_to_pass" in transitions[1]["taxonomy"], "timeout counts as observed failure")
    check(coding.source_failure("def broken(:\n")["status"] == "fail", "syntax error is model failure, not infra")
    checks += ["timeout_to_pass_transition", "source_syntax_is_failure_not_infra"]
    image_root = base / "bound-image"
    shutil.copytree(root, image_root)
    plan = batch.read_json(image_root / "plan.json")
    expected_image = "sha256:" + "1" * 64
    dump(image_root / "static-preflight-fixture/preflight.json", {"status": "passed", "paid": False,
        "plan_sha256": batch.digest(plan), "real_public": True, "image_id": expected_image})
    with patch.object(coding.sandbox, "verify_daemon"), patch.object(coding, "existing_image", return_value="sha256:" + "2" * 64):
        changed_image = scorer.score(image_root, base / "image-mismatch-score")
    check(changed_image["status"] == "stopped" and changed_image["stop_reason"] == "score_hidden_image_changed"
          and changed_image["scored_identity_count"] == 0,
          "image mismatch prevents all hidden checks")
    image_calls = []
    with patch.object(coding.sandbox, "verify_daemon"), patch.object(coding, "existing_image", return_value=expected_image), \
         patch.object(coding, "hidden_check", fake_checker(image_calls)):
        image_result = scorer.score(image_root, base / "image-match-score")
    check(image_result["status"] == "complete" and batch.read_json(base / "image-match-score/manifest.json")["image_id"] == expected_image,
          "preflight-bound image persisted in manifest")
    checks += ["preflight_image_mismatch_stops_before_checker", "matching_image_bound_in_manifest"]
    calls = []
    container_name = "tracepilot-coding-" + "a" * 32
    def interrupted_checker(task, source, image_id, output, **kwargs):
        dump(output / "candidate/create-command.json", ["docker", "create", "--name", container_name])
        dump(output / "candidate/execution.json", {"worker_cli_reaped": True, "cleanup": {"removed": False}})
        raise KeyboardInterrupt()
    def command(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="")
    with patch.object(coding.sandbox, "command", command):
        try:
            scorer.score(root, base / "interrupt-score", checker=interrupted_checker, fixture_only=True)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("KeyboardInterrupt swallowed")
    interrupted = batch.read_json(base / "interrupt-score/summary.json")
    check(calls == [["docker", "rm", "--force", container_name],
        ["docker", "ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.Names}}"]]
        and interrupted["recovery"][0]["removed"] and interrupted["hidden_resources_closed"],
        "exact owned recovery completes before interruption propagates")
    checks.append("interrupt_exact_owned_recovery_summary_then_reraise")
    checks += actual_executor_checks(base)
    return checks


def main():
    def network_guard(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen"}:
            raise RuntimeError("score_fixture_forbids_network_and_processes")
    sys.addaudithook(network_guard)
    base = Path(tempfile.mkdtemp(prefix="deadline-score-fixture-", dir=batch.ROOT / ".local"))
    root = fixture(base)
    if sys.argv[1:] == ["--missing-cleanup"]:
        report = {"status": "passed", "checks": missing_cleanup_check(base, root), "provider_calls": 0,
            "judge_containers": 0, "summary": str(base / "summary.json"), "fixture_only": True,
            "code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name)
                            for name in ("coding_deadline_score.py", "coding_deadline_score_e2e.py")}}
        dump(base / "summary.json", report)
        print(batch.canonical(report).decode())
        return 0
    delta = sys.argv[1:] == ["--review-delta"]
    check(not sys.argv[1:] or delta, "only --review-delta is supported")
    checks = []
    if delta:
        result = scorer.score(root, base / "scores", checker=fake_checker([]), fixture_only=True)
        attempts = batch.read_json(base / "scores/attempts.json")
        check(result["snapshot_status_counts"]["no_candidate"] == 282
              and "not_evaluated" not in result["snapshot_status_counts"]
              and attempts[-1]["hidden_status"] == "no_persisted_candidate", "absent candidate statuses")
    else:
        before, calls = study._files(root), []
        result = scorer.score(root, base / "scores", checker=fake_checker(calls), fixture_only=True)
        check(result["status"] == "complete" and len(calls) == 5 and result["persisted_candidate_count"] == 4, "identity count")
        check(calls[1] == calls[2] == calls[3], "identical source scored separately across attempts and trajectories")
        snapshots = batch.read_json(base / "scores/snapshots.json")
        check(len(snapshots) == 288 and snapshots[0]["score_identity"] == snapshots[1]["score_identity"]
              and snapshots[0]["hidden_status"] == snapshots[1]["hidden_status"] == "fail", "snapshot reuse, no hidden oracle")
        attempts = batch.read_json(base / "scores/attempts.json")
        check(attempts[-1]["score_identity"] is None and attempts[-1]["hidden_status"] == "no_persisted_candidate"
              and attempts[-2]["hidden_status"] == "pass", "late HTTP ignored; persisted late candidate graded")
        check(result["snapshot_status_counts"]["no_candidate"] == 282
              and "not_evaluated" not in result["snapshot_status_counts"], "absent delivery differs from ungraded identity")
        check("hidden_fail_to_pass" in attempts[1]["taxonomy"], "attempt-level progression retained")
        check(len(batch.read_json(base / "scores/baselines.json")) == 144 and result["without_he32_snapshot_denominator"] == 256,
              "full denominators and HE32 sensitivity")
        check(before == study._files(root), "input untouched")
        checks = ["attempt_identity_not_sourcehash_cache", "two_snapshots_share_identity_score", "public_selector_not_hidden_oracle",
                  "late_http_never_parsed", "late_persisted_candidate_posthoc_only", "common_seed_once", "full144_288_denominators",
                  "he32_explicit_exclusion_sensitivity", "attempt_transition_taxonomy", "input_tree_immutable"]
        refused(lambda: scorer.score(root, root / "new"), "score_requires_separate_fresh_output")
        refused(lambda: scorer.score(root, base / "scores"), "score_requires_separate_fresh_output")
        refused(lambda: scorer.score(root, base / "invalid-fake", checker=fake_checker([])), "score_fake_checker_forbidden")
        checks += ["nested_output_refused", "existing_output_refused", "unlabelled_fake_checker_refused"]
        held = base / "closed-held"
        shutil.copytree(root, held)
        terminal(held, held=True)
        check(scorer.inventory(held)["terminal"]["event"] == "stop", "closed unknown billing does not forbid offline scoring")
        checks.append("closed_held_billing_accepted_without_releasing_liability")
        for name, reason in (("lock", "score_generation_lock_present"), ("unclosed", "score_generation_not_closed"),
                             ("tamper", "score_terminal_artifacts_changed"), ("nonterminal", "score_deadline_not_terminal")):
            copy = base / name
            shutil.copytree(root, copy)
            if name == "lock":
                (copy / "pilot.lock").write_text("still live")
            elif name == "unclosed":
                path = next(copy.rglob("public-resource-closed.json"))
                doc = batch.read_json(path)
                doc["closed"] = False
                dump(path, doc)
            elif name == "tamper":
                (copy / "trajectories.json").write_bytes((copy / "trajectories.json").read_bytes() + b" ")
            else:
                path = copy / "deadline-ledger.jsonl"
                path.write_bytes(b"\n".join(path.read_bytes().splitlines()[:2]) + b"\n")
            refused(lambda: scorer.inventory(copy), reason)
            checks.append(name + "_exact_reason_refused")
        calls = []
        stopped = scorer.score(root, base / "infra-score", checker=fake_checker(calls, infra=True), fixture_only=True)
        check(stopped["status"] == "stopped" and len(calls) == 1 and stopped["snapshot_denominator"] == 288,
              "offline infra stops new checks but retains denominator")
        checks.append("hidden_infra_stops_remaining_checks")
        changed = base / "candidate-tamper"
        shutil.copytree(root, changed)
        path = next((changed / "trajectories").rglob("candidate.py"))
        path.write_bytes(path.read_bytes() + b"\n")
        refused(lambda: scorer.inventory(changed), "score_candidate_bytes_changed")
        checks.append("candidate_bytes_tamper_refused")
        cutoff = base / "cutoff-equality"
        shutil.copytree(root, cutoff)
        rows = batch.read_json(cutoff / "trajectories.json")
        row = rows[0]
        row["attempts"][0]["available_at_s"] = 1
        row["baseline"]["candidate"]["available_at_s"] = row["first_eligible"]["available_at_s"] = 1
        for snapshot in row["snapshots"]:
            snapshot["selected"]["available_at_s"] = 1
            path = cutoff / snapshot["path"]
            document = batch.read_json(path)
            document["selected"]["available_at_s"] = 1
            dump(path, document)
            snapshot["sha256"] = batch.file_hash(path)
        dump(cutoff / "trajectories.json", rows)
        terminal(cutoff)
        refused(lambda: scorer.inventory(cutoff), "score_selection_at_or_after_deadline")
        checks.append("exact_cutoff_equality_refused")
        checks += missing_cleanup_check(base, root)
    checks += review_checks(base, root)
    report = {"status": "passed", "checks": checks, "provider_calls": 0, "judge_containers": 0,
              "summary": str(base / "summary.json"), "code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name)
                for name in ("coding_deadline_score.py", "coding_deadline_score_e2e.py", "timely_study.py", "timely_batch.py",
                             "coding_deadline_study_e2e.py", *runner.RUNTIME_FILES)}}
    dump(base / "summary.json", report)
    print(batch.canonical(report).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
