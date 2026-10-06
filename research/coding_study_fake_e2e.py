"""Zero-network coding study admission/accounting checks; no judge containers."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from decimal import Decimal
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
import timely_transport as transport_module
from timely_batch_fake_e2e import check, expect_error, prefix


def coding_plan() -> dict:
    return pilot.make_plan(paid=False)


def old_version_fixture(root: Path, archive: Path) -> Path:
    """Construct a synthetic prior version; never execute the archived bytes.

    The process/billing evidence comes from real offline child processes. Only
    the fixture's historical code identity and associated plan/chain bindings
    are rebound to different explicit bytes, modeling an actual code upgrade.
    """
    source = Path(study.__file__).read_bytes() + b"\n# Older synthetic fixture version.\n"
    old_sha = hashlib.sha256(source).hexdigest()
    plan = batch.read_json(root / "plan.json")
    plan["study_admission"]["module_sha256"] = old_sha
    (root / "plan.json").write_bytes(batch.canonical(plan) + b"\n")
    records = [json.loads(line) for line in (root / "ledger.jsonl").read_bytes().splitlines()]
    previous = None
    for record in records:
        if record["event"] == "open":
            record["data"]["plan_sha256"] = batch.digest(plan)
        elif record["event"] == "start":
            binding_path = root / "bindings" / f"{record['data']['run_id']}.json"
            binding = batch.read_json(binding_path)
            binding["plan_sha256"] = batch.digest(plan)
            binding_path.write_bytes(batch.canonical(binding) + b"\n")
            record["data"]["binding_sha256"] = batch.file_hash(binding_path)
        record["previous_sha256"] = previous
        record["sha256"] = batch.digest({key: value for key, value in record.items() if key != "sha256"})
        previous = record["sha256"]
    (root / "ledger.jsonl").write_bytes(b"".join(batch.canonical(record) + b"\n" for record in records))
    chain = batch.PAID_STUDY_ROOT / "transitions.jsonl"
    event = json.loads(chain.read_bytes())
    event.update(module_sha256=old_sha, plan_sha256=batch.digest(plan), plan_file_sha256=batch.file_hash(root / "plan.json"))
    event["sha256"] = batch.digest({key: value for key, value in event.items() if key != "sha256"})
    chain.write_bytes(batch.canonical(event) + b"\n")
    archive.mkdir()
    files = {}
    sources = {"timely_study.py": source, "timely_batch.py": Path(batch.__file__).read_bytes(),
               **{name: (batch.RUNNER.parent / name).read_bytes() for name in batch.RUNNER_NAMES}}
    for name, raw in sources.items():
        (archive / name).write_bytes(raw)
        normalized = raw.replace(b"\r\n", b"\n")
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "source_repository_path": f"research/{name}",
                       "git_blob": hashlib.sha1(b"blob " + str(len(normalized)).encode() + b"\0" + normalized).hexdigest()}
    manifest = archive / "manifest.json"
    batch.write_new(manifest, {"schema": 1, "source_commit": "a" * 40, "source_plan_sha256": batch.file_hash(root / "plan.json"),
                              "files": {name: files[name] for name in ("timely_study.py", "timely_batch.py")},
                              "runtime_files": {name: files[name] for name in batch.RUNNER_NAMES}, "fixture_only": True})
    return manifest


async def fake_generation(root: Path, plan: dict, scenario: str) -> None:
    calls = 0
    def reply(request):
        nonlocal calls
        calls += 1
        model = json.loads(request.content)["model"]
        prompt = 10_000_000 if scenario == "overcap" and calls == 1 else 20
        usage = {"prompt_tokens": prompt, "completion_tokens": 5, "total_tokens": prompt + 5,
                 "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": prompt}
        body = {"id": f"fixture-{calls}", "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "def fixture(): pass"}}], "usage": usage}
        if scenario == "unknown" and calls == 3:
            del body["usage"]
        return httpx.Response(200, json=body)
    class ClosingFailure(httpx.MockTransport):
        async def aclose(self):
            raise RuntimeError("offline closure fixture")
    inner = ClosingFailure(reply) if scenario == "close-failure" else httpx.MockTransport(reply)
    transport = transport_module.BudgetedTimelyTransport(log_path=root / "requests.jsonl", batch_budget_cny="3.20",
                                                        max_calls=16, inner=inner)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False)
    interrupted, closed = False, False
    try:
        for index, row in enumerate(plan["rows"]):
            if scenario == "partial" and index == 3:
                break
            if scenario == "cancel" and index == 2:
                interrupted = True
                raise asyncio.CancelledError()
            payload = {key: plan["request_contract"][key] for key in ("stream", "thinking", "max_tokens", "temperature", "n")}
            payload.update(model=row["model"], messages=[{"role": "user", "content": "Explicit offline synthetic accounting fixture; no real task or provider."}])
            with transport_module.run_context(run_id=row["run_id"], task_id=row["task_id"], model=row["model"],
                                               repeat=row["repeat"], phase="independent_first_draft"):
                await client.post(plan["request_contract"]["endpoint"], json=payload)
    except (transport_module.TransportBlocked, asyncio.CancelledError):
        pass
    finally:
        try:
            await client.aclose()
            closed = True
        except RuntimeError:
            pass
        account = transport.snapshot()
        sha = batch.file_hash(root / "requests.jsonl")
        batch.write_new(root / "generation-closed.json", {"denominator": 16, "transport": account,
                        "interrupted": interrupted, "requests_sha256": sha})
        if scenario != "missing-result":
            batch.write_new(root / "result.json", {"schema": 1, "paid": False, "plan_sha256": batch.digest(plan),
                "denominator": 16, "http_closed": closed, "interrupted": interrupted, "accounting": account,
                "requests_sha256": sha})


def main() -> int:
    check(sys.platform == "linux", "WSL process ownership required")
    # Audit guard: even accidental real transport/socket use cannot dispatch.
    def network_guard(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("fixture_network_forbidden")
    sys.addaudithook(network_guard)
    parent = Path(tempfile.mkdtemp(prefix="coding-study-fixture-", dir=batch.ROOT / ".local"))
    source, game = parent / "source", parent / "fixture.z5"
    package = source / "src" / "timely_eval"
    package.mkdir(parents=True)
    (package / "interactive.py").write_text("# Explicit offline fixture.\n")
    (package / "prompts.py").write_text('INTERACTIVE_SYSTEM = "Fixture system"\nINTERACTIVE_TOOL_PROMPT = "Fixture tools"\n')
    game.write_bytes(b"synthetic game identity")
    tasks, provenance = pilot.coding.load_tasks()
    checks = []

    @contextmanager
    def fixture(name: str, *, unknown_parent=False, clean_stop=False):
        directory = parent / name
        directory.mkdir()
        original = directory / "original"
        plan = batch.create_plan(original, source, game)
        registry = directory / "study"
        registry.mkdir()
        batch.write_new(registry / "registry.json", {"schema": 1, "study": "timely-pilot-20261006", "cap_cny": "200",
            "paid": False, "fixture_only": True, "pilot_root": str(original), "imports": [], "blocked_unknown_history": False})
        review = directory / "review.json"
        batch.write_new(review, {"fixture_only": True})
        with patch.object(batch, "PAID_STUDY_ROOT", registry):
            expect_error(lambda: batch.run_pilot(original, execute_offline=True, fixture_prefix=prefix(original, "unusable")), "first Timely fail")
            revised = directory / "timely-revision"
            prepared = study.prepare_revision(original, revised, tool_format="single-json-v2")
            study.activate(revised, plan_sha256=prepared["plan_sha256"], review=review, review_sha256=batch.file_hash(review))
            if clean_stop:
                batch.run_pilot(revised, execute_offline=True, max_runs=1, fixture_prefix=prefix(revised))
            else:
                expect_error(lambda: batch.run_pilot(revised, execute_offline=True,
                    fixture_prefix=prefix(revised, "unknown" if unknown_parent else "unusable")), "second Timely fail")
            archive = old_version_fixture(revised, directory / "archive")
            yield directory, original, revised, archive, review

    def prepare(directory, revised, archive, *, plan=None):
        root = directory / "coding"
        result = study.prepare_coding16(revised, root, coding_plan() if plan is None else plan,
                                       provenance, historical_sources=archive)
        return root, result

    def activate(root, prepared, review):
        return study.activate(root, plan_sha256=prepared["plan_sha256"], review=review, review_sha256=batch.file_hash(review))

    with fixture("known") as (directory, original, revised, archive, review):
        before = (study._files(original), study._files(revised))
        old_plan = batch.read_json(revised / "plan.json")
        expect_error(lambda: study.assert_active(revised, old_plan), "old executable hash still refused")
        root, prepared = prepare(directory, revised, archive)
        check(prepared["opening"] == {"known_cny": "0.04", "liabilities": []}, "two failed stage costs once")
        check(batch.read_json(root / "parent-seal.json")["terminal"] == "stopped", "R2 remains stopped")
        expect_error(lambda: study.CodingAdmission(root, {}, object()), "forged admission")
        try:
            with study.coding_session(root):
                raise AssertionError("unactivated session")
        except batch.PilotError:
            pass
        check(len(study._coding_events(root, batch.read_json(root / "plan.json"))) == 1, "unactivated no reserve")
        activate(root, prepared, review)
        expect_error(lambda: activate(root, prepared, review), "duplicate coding activation")
        plan = batch.read_json(root / "plan.json")
        with study.coding_session(root) as admission:
            admission.assert_live(root, plan)
            check(study._coding_events(root, plan)[-1]["data"] == {"reservation_cny": "3.20"}, "whole reserve before HTTP")
            try:
                with study.coding_session(root):
                    raise AssertionError("concurrent session")
            except batch.PilotError:
                pass
            records, snapshot = asyncio.run(pilot.generate(root, tasks, plan,
                inner=pilot.fake_backend(tasks, plan["rows"], "mixed"), admission=admission))
            check(len(records) == 16 and snapshot["calls_dispatched"] == 16, "real coding generator complete denominator")
            settled = admission.finish()
        expected = Decimal("0.04") + Decimal(settled["batch_cost_cny"])
        check(Decimal(settled["study_known_cny"]) == expected, "cumulative known balance")
        expect_error(lambda: admission.assert_live(root, plan), "expired admission")
        try:
            with study.coding_session(root):
                raise AssertionError("repeat session")
        except batch.PilotError:
            pass
        check((study._files(original), study._files(revised)) == before, "both legacy matrices preserved")
        expect_error(lambda: study.prepare_revision(revised, directory / "forbidden-third", tool_format="single-json-v2"), "no third Timely matrix")
        # Ancestor hashes remain checked after the coding transition.
        old_path = original / "plan.json"
        raw = old_path.read_bytes()
        old_path.write_bytes(raw + b" ")
        expect_error(lambda: study.assert_active(root, plan), "ancestor changed")
        old_path.write_bytes(raw)
        checks += ["terminal_version_upgrade_requires_archived_source", "old_code_cannot_execute_under_new_hash",
                   "two_failed_matrices_preserved_and_charged_once", "unactivated_coding_cannot_reserve",
                   "fixed_3_20_reserved_before_http", "single_study_lock_and_unforgeable_live_session",
                   "real_coding_generate_mock16_known_settlement", "completed_batch_cannot_repeat",
                   "coding_does_not_reopen_timely_revision", "recursive_ancestor_hash_guard"]

    with fixture("execute-admitted-known") as (directory, original, revised, archive, review):
        root, prepared = prepare(directory, revised, archive)
        activate(root, prepared, review)
        plan = batch.read_json(root / "plan.json")
        result = asyncio.run(pilot.execute_admitted(root, execute_paid=False,
            inner=pilot.fake_backend(tasks, plan["rows"], "mixed"), evaluate=False))
        check(result["study_settlement"]["status"] == "known_settled" and result["denominator_retained"]
              and result["all_16_responses_received"] and result["finished"], "real admitted wrapper known branch")
        checks.append("real_execute_admitted_known16")

    for scenario in ("unknown", "overcap", "partial", "cancel", "close-failure", "missing-result"):
        with fixture(scenario, unknown_parent=scenario == "unknown") as (directory, original, revised, archive, review):
            root, prepared = prepare(directory, revised, archive)
            activate(root, prepared, review)
            plan = batch.read_json(root / "plan.json")
            opening = plan["study_opening"]
            if scenario == "unknown":
                check(opening["known_cny"] == "0.02" and len(opening["liabilities"]) == 1, "old unknown carried once")
            if scenario == "unknown":
                backend = pilot.fake_backend(tasks, plan["rows"], "mixed")
                call_count = 0
                def second_unknown(request):
                    nonlocal call_count
                    call_count += 1
                    response = backend.handle_request(request)
                    if call_count == 2:
                        body = response.json()
                        del body["usage"]
                        return httpx.Response(200, json=body)
                    return response
                result = asyncio.run(pilot.execute_admitted(root, execute_paid=False,
                    inner=httpx.MockTransport(second_unknown), evaluate=False))
                check(result["study_settlement"]["status"] == "held" and result["denominator_retained"]
                      and result["rows"][0]["generation_status"] == "parsed" and call_count == 2,
                      "real admitted unknown branch keeps first candidate and all slots")
                checks.append("real_execute_admitted_second_unknown_preserves_first_candidate")
            else:
                try:
                    with study.coding_session(root) as admission:
                        asyncio.run(fake_generation(root, plan, scenario))
                        outcome = admission.finish()
                        check(outcome["status"] == "held" and outcome["requests_allowed"] is False, "closed unknown permits offline judging only")
                        expect_error(lambda: admission.assert_live(root, plan), "no further requests after held close")
                except batch.PilotError:
                    check(scenario in {"close-failure", "missing-result"}, "only uncertain cleanup raises")
                else:
                    check(scenario not in {"close-failure", "missing-result"}, "uncertain cleanup must retain locks")
            events = study._coding_events(root, plan)
            check([e["event"] for e in events] == ["open", "reserve", "stop"], "whole batch terminal liability")
            held = Decimal(events[-1]["data"]["liability_cny"])
            check(held == max(Decimal("3.20"), batch.observed_commitment(root)), "no partial cost double count")
            if scenario == "overcap":
                check(held > Decimal("3.20"), "higher observed liability retained")
            uncertain = scenario in {"close-failure", "missing-result"}
            check((batch.PAID_STUDY_ROOT / "pilot.lock").exists() is uncertain
                  and (root / "pilot.lock").exists() is uncertain, "locks retained exactly for uncertain HTTP close")
            checks.append(f"{scenario}_whole_batch_liability_and_cleanup")

    with fixture("source-gates") as (directory, original, revised, archive, review):
        source_file = archive.parent / "timely_study.py"
        raw = source_file.read_bytes()
        source_file.write_bytes(raw + b" ")
        expect_error(lambda: prepare(directory, revised, archive), "archive tamper")
        source_file.write_bytes(raw)
        check(not (directory / "coding").exists(), "bad archive no preparation")
        bad = coding_plan()
        bad["rows"] = bad["rows"][:-1]
        expect_error(lambda: prepare(directory, revised, archive, plan=bad), "15 row cherry pick")
        check(not (directory / "coding").exists(), "bad plan no binding")
        checks += ["historical_source_tamper_refused", "fixed_16_plan_cannot_cherry_pick"]

    with fixture("resumable-source", clean_stop=True) as (directory, original, revised, archive, review):
        expect_error(lambda: prepare(directory, revised, archive), "nonterminal historical version")
        check(not (directory / "coding").exists(), "running or clean-stop stage cannot upgrade")
        checks.append("nonterminal_version_upgrade_refused")

    summary = {"status": "passed", "checks": checks, "check_count": len(checks), "provider_calls": 0,
               "judge_containers": 0, "code_sha256": {name: batch.file_hash(Path(__file__).with_name(name))
                    for name in ("timely_study.py", "coding_study_fake_e2e.py")},
               "integrated_code_sha256": {name: batch.file_hash(batch.ROOT / "research" / name)
                    for name in (*study.CODING_FILES, "timely_batch.py")}}
    batch.write_new(parent / "summary.json", summary)
    print(batch.canonical({"summary": str(parent / "summary.json"), **summary}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
