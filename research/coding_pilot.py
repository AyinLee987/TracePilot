"""Offline-only preparation of 16 independent coding first drafts.

Four development tasks x two fixed models x two independent requests. Public
and hidden evaluation start only after the complete generation phase closes.
There are no model repair calls, retries, shared deadlines, or held-out tasks.
The paid entry is deliberately refused: the audited cumulative study has not
admitted a coding executor. No credentials are read and no new paid allowance
is created. Future admission must be supplied by that study, not a CLI budget.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

import coding_tasks as coding
import timely_transport as budget


MODELS = ("deepseek-flash", "deepseek-v4-pro")
ENDPOINT = "https://api.deepseek.com/chat/completions"
REQUEST_CAP_CNY = Decimal("0.20")
SIMULATED_CAP_CNY = "3.20"
PARSER_VERSION = "python-file-or-function-v1"
SYSTEM = """Write one independent first-draft Python solution for the supplied task.
Return either a complete Python file defining the named function, or just its
complete function definition. A function-only answer receives the imports and
helpers that appear before that function in the published task prompt. A full
file receives no additions. Return raw Python or exactly one fenced Python
block, without surrounding prose. Do not return a function body alone.
You have no tool access or previous attempts. Subsequent public checks use only
the published examples/specification. Their results are not available during
this single draft and will not trigger a repair request. Preserve the named
function signature and behavior described in the prompt."""
PARSER_POLICY = {
    "version": PARSER_VERSION,
    "accepted": "raw Python or exactly one python/untagged fence; a top-level target def is required",
    "function_only": "prepend only the public prompt prefix before its target definition",
    "full_file": "use unchanged; one top-level target def; imports and helper definitions allowed",
    "reject": "prose, multiple fences, body-only, syntax errors, async target, tool calls, non-stop finish, empty content",
    "repair_calls": 0,
    "source_cap_bytes": coding.SOURCE_CAP,
}


class PaidNotAdmitted(RuntimeError):
    pass


def require_paid_admission(admission: object = None) -> None:
    # timely_study currently exposes an audit-only extension basis, not a
    # coding activation/settlement protocol. A user JSON/number cannot stand
    # in for a live, sealed cumulative opening and exclusive stage admission.
    raise PaidNotAdmitted("coding_executor_not_admitted_by_audited_cumulative_study")


def install_offline_guard() -> list[str]:
    blocked = []

    def guard(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            blocked.append(event)
            raise RuntimeError("offline_network_blocked")

    sys.addaudithook(guard)
    return blocked


def dump(path: Path, value: object) -> None:
    # Public candidate observations may contain isolated surrogates. Preserve
    # them as JSON escapes rather than failing UTF-8 artifact serialization.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write("\n")


def digest(value: object) -> str:
    return coding.sandbox.sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False).encode())


def identities() -> dict:
    return {Path(module.__file__).name: coding.sandbox.sha(Path(module.__file__).read_bytes())
            for module in (sys.modules[__name__], coding, coding.sandbox, budget)}


def rows() -> list[dict]:
    return [{"run_id": f"draft-{len_index:02d}-he{number}-{model}-rep{repeat}",
             "task_id": f"HumanEval/{number}", "number": number, "model": model, "repeat": repeat}
            for len_index, (repeat, number, model) in enumerate(
                ((repeat, number, model) for repeat in (1, 2) for number in coding.DEV_IDS for model in MODELS), 1)]


def request_body(row: dict, task: dict) -> dict:
    visible = coding.visible_task(task)
    return {"model": row["model"], "stream": False, "thinking": {"type": "disabled"},
            "max_tokens": 2048, "temperature": 0.7, "n": 1,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Task: {visible['task_id']}\nEntry point: {visible['entry_point']}\n\n{visible['prompt']}"}]}


def parse_candidate(body: dict, task: dict) -> dict:
    """Parse syntax only. Candidate code is never evaluated/imported here."""
    try:
        choice = body["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") != "stop":
            raise ValueError("completion_not_finished")
        if message.get("tool_calls") or message.get("function_call"):
            raise ValueError("unexpected_tool_call")
        content = message["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty_completion")
        coding.check_source(content)
        code = content.strip()
        if "```" in code:
            match = re.fullmatch(r"```(?:python)?\r?\n([\s\S]*?)\r?\n```", code)
            if not match or "```" in match.group(1):
                raise ValueError("ambiguous_or_surrounded_fence")
            code = match.group(1)
        tree = ast.parse(code)
        target = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == task["entry_point"]]
        if len(target) != 1 or isinstance(target[0], ast.AsyncFunctionDef):
            raise ValueError("one_sync_target_definition_required")
        kind = "full_file"
        scaffold = ""
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef):
            prompt_tree = ast.parse(task["prompt"])
            entry = next(node for node in prompt_tree.body if isinstance(node, ast.FunctionDef)
                         and node.name == task["entry_point"])
            scaffold = "".join(task["prompt"].splitlines(keepends=True)[:entry.lineno - 1])
            code = scaffold + code
            kind = "function_with_public_scaffold"
        code = code.rstrip() + "\n"
        coding.check_source(code)
        # Compile to a code object to reject invalid top-level return/yield;
        # no code object is executed, and no AST nodes are interpreted.
        compile(code, "<candidate-syntax-only>", "exec", dont_inherit=True)
        return {"status": "parsed", "kind": kind, "code": code,
                "code_sha256": coding.sandbox.sha(code.encode()),
                "public_scaffold_sha256": coding.sandbox.sha(scaffold.encode()), "parser": PARSER_VERSION}
    except (KeyError, IndexError, StopIteration, TypeError, ValueError, SyntaxError,
            RecursionError, UnicodeError, OverflowError) as exc:
        safe = str(exc) if type(exc) is ValueError and str(exc) in {
            "completion_not_finished", "unexpected_tool_call", "empty_completion",
            "ambiguous_or_surrounded_fence", "one_sync_target_definition_required"} else "invalid_python_or_encoding"
        return {"status": "parse_failed", "reason": safe, "parser": PARSER_VERSION}


def event(output: Path, name: str, **fields) -> None:
    with (output / "phases.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": name, "monotonic_s": time.monotonic(), **fields},
                                ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()


def fake_backend(tasks: dict, planned_rows: list[dict], scenario: str = "mixed") -> httpx.MockTransport:
    calls = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        row = planned_rows[calls]
        calls += 1
        sent = json.loads(request.content)
        if sent != request_body(row, tasks[row["number"]]):
            raise AssertionError("fake backend saw a changed prompt or request contract")
        task = tasks[row["number"]]
        finish = "stop"
        if row["repeat"] == 1 and row["model"] == MODELS[0]:
            # This fixture knows the canonical source; it is never placed in a
            # model request. The response is explicitly synthetic evidence.
            source = task["prompt"] + task["canonical_solution"]
            if row["number"] == 7:
                source = source[source.index("def filter_by_substring"):]
            content = "```python\n" + source.rstrip() + "\n```"
        elif row["repeat"] == 1:
            content = f"def {task['entry_point']}(*args):\n    return None\n"
        elif row["model"] == MODELS[0]:
            content = "Here is my answer, but no Python function."
        else:
            content = f"def {task['entry_point']}(*args):\n    return None\n"
            finish = "length"
        body = {"id": f"offline-coding-{calls}", "model": row["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 180, "total_tokens": 380,
                          "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 200}}
        if scenario == "missing-usage" and calls == 1:
            body.pop("usage")
        if scenario == "http-error" and calls == 1:
            return httpx.Response(503, json={"error": "offline fixture"})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(reply)


async def generate(output: Path, tasks: dict, plan: dict, *, inner: httpx.MockTransport,
                   simulated_cap: str = SIMULATED_CAP_CNY) -> tuple[list[dict], dict]:
    if type(inner) is not httpx.MockTransport:
        raise ValueError("this unadmitted executor only accepts offline MockTransport")
    records = [{**row, "generation_status": "not_attempted", "reason": "generation_not_reached",
                "parse": None, "public": {"status": "not_evaluated"}, "hidden": {"status": "not_evaluated"}}
               for row in plan["rows"]]
    for row in records:
        (output / "drafts" / row["run_id"]).mkdir(parents=True)
    transport = budget.BudgetedTimelyTransport(log_path=output / "requests.jsonl",
        batch_budget_cny=simulated_cap, max_calls=16, inner=inner)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False, timeout=60)
    interrupted = False
    event(output, "generation_started", denominator=16)
    try:
        for row in records:
            directory = output / "drafts" / row["run_id"]
            if transport.snapshot()["stop_reason"]:
                row["reason"] = "transport_stopped"
                continue
            payload = request_body(row, tasks[row["number"]])
            dump(directory / "request.json", payload)
            row["request_sha256"] = digest(payload)
            started = time.monotonic()
            row["generation_status"] = "attempt_started"
            try:
                request = client.build_request("POST", ENDPOINT, json=payload)
                input_upper = len(request.content) + len(payload["messages"]) * budget.MESSAGE_OVERHEAD_TOKENS
                reservation = budget._cost(row["model"], input_upper, 0, payload["max_tokens"])
                row["request_reservation_upper_cny"] = str(reservation)
                if reservation > REQUEST_CAP_CNY:
                    row.update({"generation_status": "not_attempted", "reason": "request_reservation_cap"})
                    # This deterministic contract must fit every predeclared
                    # slot; a mismatch is not a reason to sample a subset.
                    raise ValueError("request_reservation_cap")
                with budget.run_context(run_id=row["run_id"], task_id=row["task_id"], model=row["model"],
                                        repeat=row["repeat"], phase="independent_first_draft"):
                    response = await asyncio.wait_for(client.send(request), timeout=65)
                # The transport already enforces its wire/decoded size cap.
                raw = response.content
                (directory / "response.raw.json").write_bytes(raw)
                row["raw_response_sha256"] = coding.sandbox.sha(raw)
                row["raw_response_source"] = "returned_decoded_http_bytes"
                body = response.json()
                row["usage"] = body["usage"]
                row["synthetic_usage_estimate_cny"] = str(budget._usage_amount(body, row["model"])[1])
                parsed = parse_candidate(body, tasks[row["number"]])
                if parsed["status"] == "parsed":
                    (directory / "candidate.py").write_text(parsed.pop("code"), encoding="utf-8", newline="\n")
                row.update({"generation_status": parsed["status"], "parse": parsed, "reason": "response_received"})
            except (budget.TransportBlocked, httpx.HTTPError, TimeoutError) as exc:
                row.update({"generation_status": "transport_failed", "reason": type(exc).__name__,
                            "raw_response_source": "see_transport_journal_if_body_was_decodable"})
            except asyncio.CancelledError:
                row.update({"generation_status": "interrupted", "reason": "generation_cancelled"})
                interrupted = True
                raise
            finally:
                row["generation_wall_s"] = time.monotonic() - started
                row["synthetic_accounting_after_attempt"] = transport.snapshot()
                dump(directory / "generation.json", row)
    finally:
        try:
            await client.aclose()
        finally:
            snapshot = transport.snapshot()
            # The complete denominator persists even if cancellation/setup
            # fails. The closure marker is not permission to resume requests.
            for row in records:
                path = output / "drafts" / row["run_id"] / "generation.json"
                if not path.exists():
                    dump(path, row)
            closure = {"denominator": 16, "records_sha256": digest(records),
                       "transport": snapshot, "interrupted": interrupted,
                       "requests_sha256": coding.sandbox.sha((output / "requests.jsonl").read_bytes())}
            dump(output / "generation-closed.json", closure)
            event(output, "generation_closed", calls_dispatched=snapshot["calls_dispatched"],
                  active_calls=snapshot["active_calls"], interrupted=interrupted)
    return records, snapshot


def judge_after_generation(output: Path, tasks: dict, plan: dict, records: list[dict]) -> None:
    closure = json.loads((output / "generation-closed.json").read_text())
    if (closure["records_sha256"] != digest(records) or closure["transport"]["active_calls"] != 0
            or not closure["transport"]["closing"] or closure["interrupted"]
            or plan["code_sha256"] != identities()):
        raise ValueError("generation_or_code_not_closed_and_frozen")
    environment = {}
    coding.sandbox.verify_daemon(output, environment)
    dump(output / "environment.json", environment)
    image_id = coding.existing_image(output)
    for mode, checker in (("public", coding.public_check), ("hidden", coding.hidden_check)):
        event(output, mode + "_evaluation_started")
        for row in records:
            if row["generation_status"] != "parsed":
                row[mode] = {"status": "not_evaluated", "reason": "no_parsed_candidate"}
                continue
            directory = output / "drafts" / row["run_id"]
            raw = (directory / "candidate.py").read_bytes()
            if coding.sandbox.sha(raw) != row["parse"]["code_sha256"]:
                raise ValueError("candidate_changed_after_generation")
            destination = directory / mode
            destination.mkdir()
            event(output, mode + "_candidate_started", run_id=row["run_id"])
            try:
                result = checker(tasks[row["number"]], raw.decode(), image_id, destination, timeout=30)
                row[mode] = result
            except Exception as exc:
                row[mode] = {"status": "infra", "reason": "judge_exception", "error_type": type(exc).__name__}
            dump(directory / (mode + "-summary.json"), row[mode])
            event(output, mode + "_candidate_finished", run_id=row["run_id"], status=row[mode]["status"])
            if row[mode]["status"] == "infra":
                # Avoid new containers after an uncertain cleanup/setup error.
                raise RuntimeError("judge_infrastructure_failure; remaining denominator retained")
        event(output, mode + "_evaluation_closed")


async def run_offline(output: Path, *, evaluate: bool = False, scenario: str = "mixed",
                      simulated_cap: str = SIMULATED_CAP_CNY) -> dict:
    if output.exists():
        raise ValueError("fresh output directory required")
    output.mkdir(parents=True)
    tasks, provenance = coding.load_tasks()
    plan = {"schema": 1, "scope": "R3-development-natural-first-draft-check-only", "paid": False,
            "model_calls_actual": 0, "api_spend_cny_actual": "0", "planned_denominator": 16,
            "created_at": datetime.now(timezone.utc).isoformat(), "rows": rows(),
            "models": list(MODELS), "dev_ids": list(coding.DEV_IDS), "heldout_used": False,
            "independence": "fresh messages; no previous draft/result/hidden data in any request; no provider seed guarantee",
            "request_contract": {"endpoint": ENDPOINT, "temperature": 0.7, "max_tokens": 2048,
                                 "thinking": {"type": "disabled"}, "stream": False, "n": 1,
                                 "requests_per_draft": 1, "retries": 0, "http_operation_timeout_s": 60,
                                 "whole_request_timeout_s": 65,
                                 "per_request_reservation_cap_cny": str(REQUEST_CAP_CNY)},
            "parse_policy": PARSER_POLICY, "system_prompt": SYSTEM, "code_sha256": identities(),
            "study_admission": "unavailable; paid execution always refused; no new study allowance",
            "simulated_transport_cap_cny": simulated_cap, "fake_scenario": scenario,
            "judging": "after all generation ends and HTTP transport closes; public phase then independent hidden phase",
            "timing_claim": "not a shared-deadline/feedback-repair experiment", "judge_boundaries": coding.BOUNDARIES}
    dump(output / "plan.json", plan)
    dump(output / "provenance.json", provenance)
    summary = {"output": str(output), "planned_denominator": 16, "paid": False,
               "model_calls_actual": 0, "api_spend_cny_actual": "0", "rows": [], "finished": False,
               "evaluation_requested": evaluate, "plan_sha256": digest(plan)}
    started = time.monotonic()
    try:
        inner = fake_backend(tasks, plan["rows"], scenario)
        records, snapshot = await generate(output, tasks, plan, inner=inner, simulated_cap=simulated_cap)
        summary.update({"rows": records, "synthetic_accounting": snapshot})
        if evaluate:
            judge_after_generation(output, tasks, plan, records)
        summary["finished"] = True
    except (Exception, asyncio.CancelledError) as exc:
        summary["error_type"] = type(exc).__name__
        if not summary["rows"]:
            summary["rows"] = [json.loads(path.read_text()) for path in sorted((output / "drafts").glob("*/generation.json"))]
    finally:
        if not summary.get("synthetic_accounting") and (output / "generation-closed.json").exists():
            summary["synthetic_accounting"] = json.loads((output / "generation-closed.json").read_text())["transport"]
        summary["wall_s"] = time.monotonic() - started
        summary["denominator_retained"] = len(summary["rows"]) == 16
        summary["generation_counts"] = {status: sum(row["generation_status"] == status for row in summary["rows"])
            for status in ("parsed", "parse_failed", "transport_failed", "not_attempted", "interrupted", "attempt_started")}
        summary["all_16_responses_received"] = sum(summary["generation_counts"][key]
            for key in ("parsed", "parse_failed")) == 16
        dump(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute-offline", action="store_true")
    mode.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--evaluate", action="store_true", help="run public then hidden Docker checks after offline generation")
    parser.add_argument("--scenario", choices=("mixed", "missing-usage", "http-error"), default="mixed")
    args = parser.parse_args()
    if args.execute_paid:
        try:
            require_paid_admission()
        except PaidNotAdmitted as exc:
            print(json.dumps({"status": "refused", "reason": str(exc), "model_calls_actual": 0,
                              "api_spend_cny_actual": "0"}))
            return 2
    output = coding.sandbox.LOCAL / "first-drafts" / uuid.uuid4().hex
    with asyncio.Runner() as runner:
        # Windows asyncio creates its local wakeup socket pair when the loop
        # starts. Install the provider-network guard after that initialization.
        blocked = install_offline_guard()
        summary = runner.run(run_offline(output, evaluate=args.evaluate, scenario=args.scenario))
    print(json.dumps({"output": str(output), "finished": summary["finished"],
                      "denominator_retained": summary["denominator_retained"],
                      "model_calls_actual": 0, "api_spend_cny_actual": "0", "blocked_network_attempts": len(blocked)}))
    return 0 if summary["finished"] and summary["denominator_retained"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
