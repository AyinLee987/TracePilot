"""Focused fake-HTTP first-draft E2E; optional sequential real Docker judging.

No provider calls or paid admission. Only the mixed 16-slot fixture enters
Docker; budget/unknown/error fixtures stop at the generation boundary.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
from collections import Counter
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import coding_pilot as pilot


def body(content: str, finish="stop") -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


def parser_checks(tasks: dict, output: Path) -> list[str]:
    for module in (pilot, sys.modules[__name__]):
        ast.parse(Path(module.__file__).read_text())
    marker = output / "candidate-must-not-execute-in-parent.txt"
    poison = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\ndef fib(n):\n    return 1\n"
    assert pilot.parse_candidate(body(poison), tasks[55])["status"] == "parsed"
    assert not marker.exists()
    source = "def filter_by_substring(strings: List[str], substring: str) -> List[str]:\n    return [s for s in strings if substring in s]\n"
    parsed = pilot.parse_candidate(body(source), tasks[7])
    assert parsed["status"] == "parsed" and parsed["kind"] == "function_with_public_scaffold"
    assert parsed["code"].startswith("from typing import List")
    assert pilot.parse_candidate(body("```\ndef fib(n):\n    return 1\n```"), tasks[55])["status"] == "parsed"
    for text, finish in (("Here is code:\n```python\ndef fib(n):\n return 1\n```", "stop"),
                         ("```python\ndef fib(n):\n return 1\n```\n```python\nx=1\n```", "stop"),
                         ("return 1", "stop"), ("def fib(n):\n return 1", "length"),
                         ("async def fib(n):\n return 1", "stop"),
                         ("def fib(n):\n return 1\ndef fib(n):\n return 2", "stop"),
                         ("\ud800", "stop")):
        assert pilot.parse_candidate(body(text, finish), tasks[55])["status"] == "parse_failed"
    for admission in (None, {"known_cny": "0", "cap_cny": "200", "admitted": True}):
        try:
            pilot.require_paid_admission(admission)
        except pilot.PaidNotAdmitted:
            pass
        else:
            raise AssertionError("unadmitted paid path accepted")
    return ["syntax_only_never_executes_candidate", "public_scaffold_only", "fixed_format_policy",
            "surrogate_and_truncation_rejected", "forged_or_missing_paid_admission_refused"]


def inspect_generation(directory: Path, summary: dict, expected_dispatch: int) -> None:
    assert summary["finished"] and summary["denominator_retained"] and len(summary["rows"]) == 16
    plan = json.loads((directory / "plan.json").read_text())
    assert plan["rows"] == pilot.rows() and plan["planned_denominator"] == 16
    assert {row["number"] for row in plan["rows"]} == set(pilot.coding.DEV_IDS)
    assert plan["paid"] is False and plan["model_calls_actual"] == 0
    events = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    dispatched = [item for item in events if item["event"] == "request_dispatch"]
    assert len(dispatched) == expected_dispatch
    assert len({item["run_id"] for item in dispatched}) == expected_dispatch
    assert events[-1]["event"] == "batch_close" and events[-1]["active_calls"] == 0
    assert summary["synthetic_accounting"]["calls_dispatched"] == expected_dispatch
    tasks, _ = pilot.coding.load_tasks()
    for item in dispatched:
        row = next(row for row in plan["rows"] if row["run_id"] == item["run_id"])
        assert item["request_body"] == pilot.request_body(row, tasks[row["number"]])
        assert len(item["request_body"]["messages"]) == 2
        assert "base_input" not in json.dumps(item["request_body"])
        assert Decimal(item["reservation_cny"]) <= pilot.REQUEST_CAP_CNY
    assert len(list((directory / "drafts").glob("*/generation.json"))) == 16


def inspect_judging(directory: Path, summary: dict) -> dict:
    phases = [json.loads(line) for line in (directory / "phases.jsonl").read_text().splitlines()]
    names = [item["event"] for item in phases]
    assert names.index("generation_closed") < names.index("public_evaluation_started")
    assert names.index("public_evaluation_closed") < names.index("hidden_evaluation_started")
    assert names[-1] == "hidden_evaluation_closed"
    public = Counter(row["public"]["status"] for row in summary["rows"])
    hidden = Counter(row["hidden"]["status"] for row in summary["rows"])
    assert public == {"pass": 4, "fail": 4, "not_evaluated": 8}
    # /32 canonical is a recorded numerical failure (881/888); do not bless it.
    assert hidden == {"pass": 3, "fail": 5, "not_evaluated": 8}
    executions = [json.loads(path.read_text()) for path in directory.rglob("execution.json")]
    assert len(executions) == 22
    assert all(item["cleanup"]["removed"] and item["worker_cli_reaped"] for item in executions)
    assert all(item["expected_results_sent_to_worker"] is False for item in executions)
    assert all(item["limits_verified_before_code"] for item in executions)
    for row in summary["rows"]:
        if row["generation_status"] == "parsed":
            path = directory / "drafts" / row["run_id"]
            assert pilot.coding.sandbox.sha((path / "candidate.py").read_bytes()) == row["parse"]["code_sha256"]
            assert set(row["hidden"]).isdisjoint({"arguments", "expected", "observed", "checks", "error_type", "diagnostic"})
    return {"public": dict(public), "hidden": dict(hidden), "owned_executions_cleaned": len(executions)}


async def checks(output: Path, docker: bool) -> dict:
    tasks, _ = pilot.coding.load_tasks()
    report = {"output": str(output), "passed": False, "model_calls_actual": 0, "api_spend_cny_actual": "0",
              "docker_requested": docker, "cases": [], "scripts_sha256": pilot.identities()}
    report["parser_checks"] = parser_checks(tasks, output)
    mixed = await pilot.run_offline(output / "mixed", evaluate=docker)
    inspect_generation(output / "mixed", mixed, 16)
    assert Counter(row["generation_status"] for row in mixed["rows"]) == {"parsed": 8, "parse_failed": 8}
    assert len(list((output / "mixed/drafts").glob("*/response.raw.json"))) == 16
    assert Decimal(mixed["synthetic_accounting"]["spent_estimate_cny"]) == Decimal("0.0801792")
    report["cases"].append({"name": "mixed_16", "passed": True, "denominator": 16,
                            "parsed": 8, "parse_failed": 8})
    if docker:
        report["judging"] = inspect_judging(output / "mixed", mixed)
    for scenario, cap, dispatch in (("missing-usage", "3.20", 1), ("http-error", "3.20", 1),
                                    ("mixed", "0.0000001", 0)):
        label = "budget-refused" if dispatch == 0 else scenario
        summary = await pilot.run_offline(output / label, scenario=scenario, simulated_cap=cap)
        inspect_generation(output / label, summary, dispatch)
        accounting = summary["synthetic_accounting"]
        assert accounting["stop_reason"] is not None
        assert sum(row["generation_status"] == "not_attempted" for row in summary["rows"]) == 15
        if dispatch:
            assert Decimal(accounting["unknown_reserved_cny"]) > 0 and accounting["unknown_calls"] == 1
        else:
            assert Decimal(accounting["committed_cny"]) == 0
        report["cases"].append({"name": label, "passed": True, "denominator": 16,
                                "synthetic_dispatches": dispatch, "stop_reason": accounting["stop_reason"]})
    # Real CLI refusal; the child has a minimal environment with no keys.
    child_env = pilot.coding.sandbox.process_env()
    if sys.platform == "win32":
        # Winsock/asyncio initialization needs the OS root, not user secrets.
        child_env["SystemRoot"] = os.environ["SystemRoot"]
    child = subprocess.run([sys.executable, "-B", str(Path(pilot.__file__).resolve()), "--execute-paid"],
                           env=child_env, capture_output=True, timeout=15)
    (output / "paid-refusal-stdout.txt").write_bytes(child.stdout)
    (output / "paid-refusal-stderr.txt").write_bytes(child.stderr)
    refusal = json.loads(child.stdout)
    assert child.returncode == 2 and refusal["status"] == "refused" and refusal["model_calls_actual"] == 0
    report["cases"].append({"name": "paid_cli_refused", "passed": True, "child_exit": child.returncode})
    # Cancel an actual in-flight fake HTTP attempt. No timer/sleep is needed:
    # the mock signals when dispatch has reached it and remains pending.
    cancel_dir = output / "cancelled-generation"
    cancel_dir.mkdir()
    ready = asyncio.Event()

    async def pending(request):
        ready.set()
        await asyncio.Event().wait()

    call = asyncio.create_task(pilot.generate(cancel_dir, tasks, {"rows": pilot.rows()},
                                              inner=pilot.httpx.MockTransport(pending)))
    await ready.wait()
    call.cancel()
    try:
        await call
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancelled generation unexpectedly returned normally")
    closure = json.loads((cancel_dir / "generation-closed.json").read_text())
    assert closure["interrupted"] and closure["transport"]["active_calls"] == 0
    assert closure["transport"]["closing"] and closure["transport"]["unknown_calls"] == 1
    assert Decimal(closure["transport"]["unknown_reserved_cny"]) > 0
    assert len(list((cancel_dir / "drafts").glob("*/generation.json"))) == 16
    assert not list(cancel_dir.rglob("execution.json"))
    report["cases"].append({"name": "cancelled_generation_retains_16_and_closes", "passed": True})
    report["passed"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-docker", action="store_true")
    args = parser.parse_args()
    output = pilot.coding.sandbox.LOCAL / "first-draft-e2e" / uuid.uuid4().hex
    output.mkdir(parents=True)
    blocked = []
    report = {"output": str(output), "passed": False}
    try:
        with asyncio.Runner() as runner:
            blocked = pilot.install_offline_guard()
            report = runner.run(checks(output, args.execute_docker))
        assert not blocked, "unexpected network attempt in the offline executor"
    except BaseException as exc:
        report.update({"passed": False, "error_type": type(exc).__name__, "error": str(exc)[:300]})
    finally:
        report["blocked_network_attempts"] = len(blocked)
        pilot.dump(output / "summary.json", report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
