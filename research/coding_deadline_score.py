"""Offline hidden scoring of a closed R3 batch; never dispatches model requests.

The default command only validates and inventories evidence. --execute-hidden
uses the existing fresh-container checker and writes a separate new directory.
Scores describe the frozen public selections; they never select a candidate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re

import coding_tasks as coding
import timely_batch as batch
import timely_study as study

REF_KEYS = ("candidate_id", "code_sha256", "candidate_path", "public_path",
            "public_passed", "public_total", "available_at_s")
GRADER_FILES = ("coding_tasks.py", "coding_environment_smoke.py")
LIMITATIONS = {
    "scope": "fixed eight development tasks; no held-out evaluation; not full EvalPlus",
    "denominators": "144 trajectories and 288 correlated deadline snapshots, including missing/censored results",
    "identity": "one fresh hidden check per (run_id, candidate_id); identical source across attempts is not cached",
    "seed": "one separately identified common-state seed check, reused only as the declared seed baseline",
    "timing": "post-hoc hidden checking is outside the agent deadline; late HTTP is never parsed here",
    "selection": "baseline is attempt 1; snapshots retain the public online selector, never an offline oracle",
    "transitions": "timeout is an observed hidden failure for fail-to-pass/pass-to-fail transitions; infra and absent scores are unknown",
    "he32": "retain HumanEval/32 polynomial-residual/input-mutation limitation and the known 881/888 reference result; report exclusion sensitivity",
    "grader": coding.BOUNDARIES,
}


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(batch.canonical(value) + b"\n")


def inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    batch.require(not path.is_absolute() and ".." not in path.parts, "score_path_escape")
    resolved = (root / path).resolve()
    batch.require(resolved.is_relative_to(root) and resolved != root, "score_path_escape")
    return resolved


def inventory(root: Path) -> dict:
    """Read-only terminal evidence gate, independent of the current study head."""
    root = batch.local_path(root)
    batch.require(not (root / "pilot.lock").exists(), "score_generation_lock_present")
    batch.require(not (batch.PAID_STUDY_ROOT / "pilot.lock").exists(), "score_live_study_present")
    files = study._files(root)  # Reject symlinks before following artifact references.
    plan = batch.read_json(root / "plan.json")
    events = study._deadline_events(root, plan)
    batch.require(len(events) == 3, "score_deadline_not_terminal")
    batch.require(events[-1]["data"]["artifacts"] == study._deadline_refs(root), "score_terminal_artifacts_changed")
    batch.require(study._deadline_closed(root, plan), "score_generation_not_closed")
    batch.require(all(plan["code_sha256"].get(name) == batch.file_hash(batch.ROOT / "research" / name)
                      for name in GRADER_FILES), "score_grader_source_changed")
    tasks, provenance = coding.load_tasks()
    batch.require(batch.digest(provenance) == plan["provenance_sha256"], "score_task_provenance_changed")
    records = batch.read_json(root / "trajectories.json")
    deadlines = plan.get("deadlines_s", [])
    batch.require(len(deadlines) == 2 and all(type(d) in (int, float) and math.isfinite(d) and d > 0 for d in deadlines)
                  and deadlines[0] < deadlines[1], "score_deadlines_changed")
    expected = Counter((cohort, n, model, policy, delay, repeat)
        for cohort, numbers in (("native", (55, 32, 7, 56, 16, 99, 18, 31)), ("common", (99,)))
        for n in numbers for model in batch.MODELS for policy in ("resample", "repair")
        for delay in (0, 1) for repeat in (1, 2))
    batch.require(len(records) == len(plan["trajectories"]) == 144 and Counter(
        (r["cohort"], r["number"], r["model"], r["policy"], r["delay_s"], r["repeat"])
        for r in plan["trajectories"]) == expected, "score_denominator_changed")
    candidates, attempts, baselines, snapshots, seen_paths = {}, [], [], [], set()
    seed = plan["seed_ref"]
    seed_path = root / "common-seed.py"
    original_public = Path(seed["parent_root"]) / "drafts" / seed["run_id"] / "public-summary.json"
    batch.require(seed_path.stat().st_size <= coding.SOURCE_CAP and batch.file_hash(seed_path) == seed["candidate_sha256"]
                  and batch.file_hash(original_public) == seed["public_summary_sha256"]
                  and batch.read_json(original_public) == batch.read_json(root / "common-seed-public.json"),
                  "score_common_seed_changed")
    candidates["common-seed"] = {"identity": "common-seed", "run_id": None, "candidate_id": "seed",
        "number": 99, "task_id": "HumanEval/99", "path": "common-seed.py", "code_sha256": seed["candidate_sha256"],
        "role": "independent_common_seed_baseline"}
    seed_public = batch.read_json(root / "common-seed-public.json")
    seed_ref = {"candidate_id": "seed", "code_sha256": seed["candidate_sha256"], "candidate_path": "common-seed.py",
        "public_path": "common-seed-public.json", "public_passed": seed_public["passed"],
        "public_total": seed_public["total"], "available_at_s": 0.0}

    def selected(row, ref, *, cutoff=None, baseline=False):
        if ref is None:
            return None
        key = "common-seed" if ref.get("candidate_id") == "seed" else row["run_id"] + "/" + ref["candidate_id"]
        batch.require(key in candidates, "score_selection_unknown_candidate")
        if key == "common-seed":
            batch.require(row["cohort"] == "common" and not baseline and ref == seed_ref, "score_seed_selection_changed")
        else:
            attempt = next(a for a in row["attempts"] if a["candidate_id"] == ref["candidate_id"])
            batch.require(attempt["status"] == "eligible" and ref == {k: attempt[k] for k in REF_KEYS}
                          and (not baseline or ref["candidate_id"] == "attempt-01"), "score_selection_not_eligible")
        when = ref["available_at_s"]
        batch.require(type(when) in (int, float) and math.isfinite(when) and when >= 0
                      and (cutoff is None or when < cutoff), "score_selection_at_or_after_deadline")
        return key

    for frozen, row in zip(plan["trajectories"], records):
        batch.require(all(row.get(k) == v for k, v in frozen.items())
                      and row["status"] in {"complete", "stopped", "interrupted", "not_started"}, "score_trajectory_identity_changed")
        run_id = row["run_id"]
        batch.require(Path(run_id).name == run_id and run_id not in {".", ".."}, "score_path_escape")
        for index, attempt in enumerate(row["attempts"], 1):
            cid = attempt["candidate_id"]
            batch.require(cid == f"attempt-{index:02d}", "score_attempt_identity_changed")
            key = run_id + "/" + cid
            item = {**frozen, "candidate_id": cid, "attempt_status": attempt["status"], "score_identity": None,
                    "public_status": attempt.get("public_status"), "available_at_s": attempt.get("available_at_s")}
            if "candidate_path" in attempt:
                relative = f"trajectories/{run_id}/{cid}/candidate.py"
                batch.require(attempt["candidate_path"] == relative and attempt.get("parse", {}).get("status") == "parsed"
                              and attempt["parse"]["code_sha256"] == attempt["code_sha256"], "score_candidate_binding_changed")
                path = inside(root, relative)
                batch.require(path.stat().st_size <= coding.SOURCE_CAP and batch.file_hash(path) == attempt["code_sha256"],
                              "score_candidate_bytes_changed")
                path.read_text(encoding="utf-8")
                seen_paths.add(path)
                candidates[key] = {"identity": key, "run_id": run_id, "candidate_id": cid,
                    "number": row["number"], "task_id": row["task_id"], "path": relative,
                    "code_sha256": attempt["code_sha256"], "role": "persisted_attempt"}
                item["score_identity"] = key
            attempts.append(item)
        batch.require(row["status"] == "not_started" or "baseline" in row, "score_started_baseline_missing")
        baseline = row.get("baseline", {"attempt": 1, "outcome": "not_started", "candidate": None})
        batch.require(baseline["attempt"] == 1, "score_baseline_not_first_attempt")
        baselines.append({**frozen, "trajectory_status": row["status"], "baseline": baseline,
            "score_identity": selected(row, baseline.get("candidate"), baseline=True),
            "first_eligible_identity": selected(row, row.get("first_eligible")),
            "first_attempt_posthoc_identity": run_id + "/attempt-01" if run_id + "/attempt-01" in candidates else None})
        batch.require(len(row["snapshots"]) == 2, "score_snapshot_denominator_changed")
        for index, (snapshot, cutoff) in enumerate(zip(row["snapshots"], plan["deadlines_s"])):
            key = None
            if snapshot is not None:
                path = inside(root, snapshot["path"])
                doc = batch.read_json(path)
                batch.require(batch.file_hash(path) == snapshot["sha256"] and doc["index"] == index
                              and doc["deadline_s"] == cutoff and all(snapshot.get(k) == v for k, v in doc.items()),
                              "score_snapshot_changed")
                key = selected(row, doc["selected"], cutoff=cutoff)
            else:
                batch.require(row["status"] == "not_started", "score_missing_started_snapshot")
            snapshots.append({**frozen, "snapshot_index": index, "deadline_s": cutoff,
                "trajectory_status": row["status"], "stop_reason": row.get("stop_reason"),
                "snapshot": snapshot, "score_identity": key})
    batch.require(seen_paths == set((root / "trajectories").rglob("candidate.py")), "score_candidate_inventory_changed")
    batch.require(len({r["run_id"] for r in records}) == 144 and len(snapshots) == 288, "score_denominator_changed")
    return {"root": root, "plan": plan, "files": files, "terminal": events[-1], "candidates": candidates,
            "attempts": attempts, "baselines": baselines, "snapshots": snapshots, "tasks": tasks}


def frozen_image(source: dict) -> tuple[str, dict]:
    refs, identities = {}, set()
    for path in source["root"].glob("static-preflight-*/preflight.json"):
        doc = batch.read_json(path)
        if doc.get("status") != "passed":
            continue
        batch.require(doc.get("plan_sha256") == batch.digest(source["plan"])
                      and doc.get("paid") is source["plan"]["paid"] and doc.get("real_public") is True,
                      "score_preflight_image_not_bound")
        image = doc.get("image_id", "")
        batch.require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None, "score_preflight_image_not_bound")
        identities.add(image)
        refs[path.relative_to(source["root"]).as_posix()] = batch.file_hash(path)
    batch.require(len(identities) == 1, "score_preflight_image_not_bound")
    return identities.pop(), refs


def recover_hidden(directory: Path | None) -> list[dict]:
    """Recover only UUID container names recorded by this scorer's owned checker."""
    recovery = []
    if directory is None:
        return recovery
    with coding.sandbox.cleanup_without_sigint():
        for path in sorted(directory.rglob("create-command.json")):
            record = {"create_command": str(path), "removed": False, "worker_cli_reaped": False}
            try:
                args = batch.read_json(path)
                name = args[args.index("--name") + 1]
                batch.require(args[:2] == ["docker", "create"] and re.fullmatch(r"tracepilot-coding-[0-9a-f]{32}", name),
                              "score_invalid_owned_container_name")
                record.update(container=name, create_sha256=batch.file_hash(path))
                removed = coding.sandbox.command(["docker", "rm", "--force", name], check=False)
                remaining = coding.sandbox.command(["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"], check=False)
                execution = path.parent / "execution.json"
                doc = batch.read_json(execution) if execution.exists() else {}
                record.update(remove_exit_code=removed.returncode, verify_exit_code=remaining.returncode,
                    removed=remaining.returncode == 0 and not remaining.stdout.strip(),
                    worker_cli_reaped=doc.get("worker_cli_reaped") is True)
            except (Exception, KeyboardInterrupt) as exc:
                record["error_type"] = type(exc).__name__
            recovery.append(record)
    return recovery


def score(root: Path, output: Path, *, checker=None, fixture_only=False) -> dict:
    source = inventory(root)
    root, output = source["root"], batch.local_path(output)
    batch.require(not output.exists() and not output.is_relative_to(root) and not root.is_relative_to(output),
                  "score_requires_separate_fresh_output")
    batch.require(checker is None or (fixture_only and source["plan"]["paid"] is False), "score_fake_checker_forbidden")
    output.mkdir(parents=True)
    scores, reason, environment, cleanup_verified = {}, None, {}, True
    interruption, directory, recovery = None, None, []
    manifest = {"schema": 1, "input_root": str(root), "input_files": source["files"], "plan_sha256": batch.digest(source["plan"]),
        "deadline_terminal_sha256": source["terminal"]["sha256"], "fixture_only": fixture_only,
        "input_paid": source["plan"]["paid"], "image_id": None,
        "code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name) for name in
                        (Path(__file__).name, "timely_study.py", "timely_batch.py", *GRADER_FILES)},
        "limitations": LIMITATIONS, "provider_calls": 0}
    dump(output / "manifest.json", manifest)
    try:
        if checker is None:
            expected_image, image_refs = frozen_image(source)
            coding.sandbox.verify_daemon(output, environment)
            image_id = coding.existing_image(output)
            batch.require(image_id == expected_image, "score_hidden_image_changed")
            manifest["preflight_image_refs"] = image_refs
            checker = coding.hidden_check
        else:
            image_id = "fixture-no-docker"
        manifest["image_id"] = image_id
        dump(output / "manifest.json", manifest)
        for ordinal, (identity, candidate) in enumerate(source["candidates"].items(), 1):
            directory = output / "scores" / f"{ordinal:05d}"
            dump(directory / "identity.json", candidate)
            raw = inside(root, candidate["path"]).read_bytes()
            batch.require(coding.sandbox.sha(raw) == candidate["code_sha256"], "score_candidate_changed_during_scoring")
            result = checker(source["tasks"][candidate["number"]], raw.decode("utf-8"), image_id, directory / "hidden", timeout=30)
            batch.require(result.get("visibility") == "offline_hidden" and result.get("task_id") == candidate["task_id"]
                          and result.get("status") in {"pass", "fail", "timeout", "infra"}, "score_hidden_result_invalid")
            executions = sorted((directory / "hidden").rglob("execution.json"))
            closed = all((doc := batch.read_json(p)).get("worker_cli_reaped") is True
                         and doc.get("cleanup", {}).get("removed") is True for p in executions)
            closed &= all((p.parent / "execution.json") in executions
                          for p in (directory / "hidden").rglob("create-command.json"))
            closed &= result["status"] != "pass" or (directory / "hidden/candidate/execution.json") in executions
            batch.require(batch.read_json(directory / "hidden/hidden-result.json") == result, "score_hidden_result_not_persisted")
            if not closed:
                recovery = recover_hidden(directory / "hidden")
                result = {**result, "status": "infra", "reason": "hidden_resource_unclosed"}
            cleanup_verified &= closed or (bool(recovery) and all(r["removed"] and r["worker_cli_reaped"] for r in recovery))
            scores[identity] = {**candidate, "hidden": result, "resources_closed": closed,
                "evidence": {p.relative_to(output).as_posix(): batch.file_hash(p) for p in (directory / "hidden").rglob("*") if p.is_file()}}
            dump(output / "scores.json", scores)
            if not closed or result["status"] == "infra":
                reason = "hidden_resource_unclosed" if not closed else "hidden_infrastructure_failure"
                break
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, batch.PilotError) else type(exc).__name__
        cleanup_verified = False
        interruption = exc if isinstance(exc, KeyboardInterrupt) else None
        recovery = recover_hidden(directory / "hidden" if directory is not None else None)
        if recovery:
            cleanup_verified = all(r["removed"] and r["worker_cli_reaped"] for r in recovery)
    finally:
        unchanged = study._files(root) == source["files"]
        if not unchanged:
            reason = "score_input_changed"
        previous = {}
        for attempt in source["attempts"]:
            identity, run_id = attempt["score_identity"], attempt["run_id"]
            item = scores.get(identity)
            status = "no_persisted_candidate" if identity is None else item["hidden"]["status"] if item else "not_evaluated"
            attempt["hidden_status"] = status
            attempt["taxonomy"] = []
            if item:
                old = previous.get(run_id)
                if old:
                    if old["code_sha256"] == item["code_sha256"]:
                        attempt["taxonomy"].append("same_source_as_previous_attempt")
                    if old["hidden"]["status"] in {"fail", "timeout"} and status == "pass":
                        attempt["taxonomy"].append("hidden_fail_to_pass")
                    if old["hidden"]["status"] == "pass" and status in {"fail", "timeout"}:
                        attempt["taxonomy"].append("hidden_pass_to_fail")
                if attempt["attempt_status"] != "eligible":
                    attempt["taxonomy"].append("persisted_but_not_publicly_eligible")
            # Parse failures and unscored attempts break adjacency; a transition
            # label always refers to the immediately preceding attempt.
            previous[run_id] = item
        for name in ("baselines", "snapshots"):
            for item in source[name]:
                item["hidden_status"] = ("no_candidate" if item["score_identity"] is None else
                    scores.get(item["score_identity"], {}).get("hidden", {}).get("status", "not_evaluated"))
            dump(output / (name + ".json"), source[name])
        dump(output / "attempts.json", source["attempts"])
        dump(output / "scores.json", scores)
        dump(output / "environment.json", environment)
        summary = {"status": "complete" if reason is None else "stopped", "stop_reason": reason, "provider_calls": 0,
            "hidden_resources_closed": cleanup_verified,
            "recovery": recovery, "image_id": manifest["image_id"],
            "fixture_only": fixture_only, "input_unchanged": unchanged, "trajectory_denominator": 144,
            "native_denominator": 128, "common_denominator": 16, "snapshot_denominator": 288,
            "baseline_denominator": 144, "persisted_candidate_count": len(source["candidates"]) - 1,
            "independent_common_seed_count": 1, "scored_identity_count": len(scores),
            "unscored_identity_count": len(source["candidates"]) - len(scores),
            "snapshot_status_counts": dict(Counter(s["hidden_status"] for s in source["snapshots"])),
            "without_he32_snapshot_denominator": sum(s["number"] != 32 for s in source["snapshots"]),
            "without_he32_snapshot_status_counts": dict(Counter(s["hidden_status"] for s in source["snapshots"] if s["number"] != 32)),
            "manifest_sha256": batch.file_hash(output / "manifest.json"), "limitations": LIMITATIONS}
        dump(output / "summary.json", summary)
    if interruption is not None:
        raise interruption
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute-hidden", action="store_true")
    args = parser.parse_args()
    if args.execute_hidden:
        if args.output_root is None:
            parser.error("--execute-hidden requires --output-root")
        result = score(args.input_root, args.output_root)
    else:
        data = inventory(args.input_root)
        result = {"status": "inventory_only", "provider_calls": 0, "judge_containers": 0,
                  "candidate_identities": len(data["candidates"]), "trajectory_denominator": 144,
                  "snapshot_denominator": 288, "terminal_event": data["terminal"]["event"]}
    print(batch.canonical(result).decode())
    return 0 if result["status"] in {"complete", "inventory_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
