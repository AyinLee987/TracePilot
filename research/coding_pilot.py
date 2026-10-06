"""Study-admitted or offline preparation of 16 independent coding first drafts.

Four development tasks x two fixed models x two independent requests. Public
and hidden evaluation start only after the complete generation phase closes.
There are no model repair calls, retries, shared deadlines, or held-out tasks.
Paid execution requires a live locked admission from the cumulative study.
This executor never creates a study allowance. Offline execution uses only
MockTransport and reads no credentials.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import platform
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


def runtime_identity(*, require_wsl: bool = False) -> dict:
    kernel = platform.release()
    if require_wsl and (sys.platform != "linux" or "microsoft" not in kernel.lower()):
        raise PaidNotAdmitted("paid_coding_requires_frozen_native_wsl_python")
    return {"python": sys.version, "executable": str(Path(sys.executable).resolve()),
            "invoked_executable": str(Path(sys.executable).absolute()),
            "prefix": str(Path(sys.prefix).resolve()), "platform": sys.platform,
            "kernel": kernel, "machine": platform.machine(), "httpx_version": httpx.__version__}


def require_paid_admission(admission: object = None, output: Path | None = None,
                           plan: dict | None = None) -> None:
    import timely_study as study
    if type(admission) is not study.CodingAdmission or output is None or plan is None:
        raise PaidNotAdmitted("coding_requires_live_audited_study_admission")
    if plan.get("paid") is not True or plan.get("runtime_identity") != runtime_identity(require_wsl=True):
        raise PaidNotAdmitted("paid_coding_runtime_or_mode_changed")
    admission.assert_live(output, plan)


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
    if (not isinstance(body, dict) or not isinstance(body.get("choices"), list)
            or len(body["choices"]) != 1 or not isinstance(body["choices"][0], dict)
            or not isinstance(body["choices"][0].get("message"), dict)
            or not isinstance(body["choices"][0]["message"].get("content"), str)
            or not isinstance(body["choices"][0].get("finish_reason"), str)):
        return {"status": "response_failed", "reason": "unexpected_response_shape", "parser": PARSER_VERSION}
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
        if ((scenario == "missing-usage" and calls == 1)
                or (scenario == "missing-usage-second" and calls == 2)):
            body.pop("usage")
        if scenario == "bad-shape" and calls == 1:
            body["choices"][0]["finish_reason"] = []
        if scenario == "http-error" and calls == 1:
            return httpx.Response(503, json={"error": "offline fixture"})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(reply)


async def preflight_requests(output: Path, tasks: dict, plan: dict, client: httpx.AsyncClient,
                             transport: budget.BudgetedTimelyTransport) -> tuple[list, dict]:
    """Preview every fixed request before the first dispatch; never reserve here."""
    report = {"accepted": False, "denominator": 16, "rows": [],
              "per_request_cap_cny": str(REQUEST_CAP_CNY), "batch_cap_cny": "3.20"}
    requests = []
    try:
        if plan["rows"] != rows():
            raise ValueError("fixed_16_rows_changed")
        for row in plan["rows"]:
            payload = request_body(row, tasks[row["number"]])
            request = client.build_request("POST", ENDPOINT, json=payload)
            preview = await transport.preview_reservation(request)
            report["rows"].append({"run_id": row["run_id"], **preview,
                "request_body_sha256": coding.sandbox.sha(request.content)})
            requests.append(request)
        total = sum((Decimal(item["reservation_cny"]) for item in report["rows"]), Decimal(0))
        report["total_reservation_cny"] = str(total)
        report["accepted"] = (all(Decimal(item["reservation_cny"]) <= REQUEST_CAP_CNY for item in report["rows"])
            and total <= Decimal("3.20") and total <= Decimal(transport.snapshot()["batch_budget_cny"]))
        if not report["accepted"]:
            report["reason"] = "whole_batch_preflight_cap"
    except (ValueError, budget.TransportBlocked) as exc:
        report["reason"] = "whole_batch_preflight_invalid_request"
        report["error_type"] = type(exc).__name__
    finally:
        dump(output / "preflight.json", report)
    return requests, report


async def generate(output: Path, tasks: dict, plan: dict, *, inner: httpx.MockTransport | None = None,
                   simulated_cap: str = SIMULATED_CAP_CNY, admission=None, env_file: Path | None = None,
                   offline_request_timeout: float | None = None) -> tuple[list[dict], dict]:
    paid = plan.get("paid", False)
    if paid:
        require_paid_admission(admission, output, plan)
        if inner is not None or offline_request_timeout is not None:
            raise PaidNotAdmitted("paid_execution_rejects_fake_overrides")
        cap = admission.batch_cap_cny
    else:
        if type(inner) is not httpx.MockTransport:
            raise ValueError("offline executor requires MockTransport")
        if admission is not None:
            admission.assert_live(output, plan)
        cap = admission.batch_cap_cny if admission is not None else simulated_cap
    records = [{**row, "generation_status": "not_attempted", "reason": "generation_not_reached",
                "parse": None, "public": {"status": "not_evaluated"}, "hidden": {"status": "not_evaluated"}}
               for row in plan["rows"]]
    for row in records:
        (output / "drafts" / row["run_id"]).mkdir(parents=True)
    transport = budget.BudgetedTimelyTransport(log_path=output / "requests.jsonl",
        batch_budget_cny=cap, max_calls=16, inner=inner)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False, timeout=60)
    interrupted = http_closed = False
    event(output, "generation_started", denominator=16)
    try:
        requests, preflight = await preflight_requests(output, tasks, plan, client, transport)
        event(output, "preflight_complete", accepted=preflight["accepted"], calls_dispatched=transport.snapshot()["calls_dispatched"])
        if preflight["accepted"] and paid:
            require_paid_admission(admission, output, plan)
            if env_file is None:
                raise PaidNotAdmitted("explicit_env_file_required")
            from dotenv import dotenv_values
            key = dotenv_values(env_file, interpolate=False).get("DEEPSEEK_API_KEY")
            if not isinstance(key, str) or not key or len(key) > 4096 or any(c in key for c in "\r\n"):
                raise PaidNotAdmitted("explicit_env_file_missing_valid_deepseek_key")
            for request in requests:
                request.headers["Authorization"] = "Bearer " + key
            del key
        for index, row in enumerate(records):
            directory = output / "drafts" / row["run_id"]
            if not preflight["accepted"]:
                row["reason"] = "whole_batch_preflight_refused"
                continue
            if transport.snapshot()["stop_reason"]:
                row["reason"] = "transport_stopped"
                continue
            request = requests[index]
            preview = preflight["rows"][index]
            if coding.sandbox.sha(request.content) != preview["request_body_sha256"]:
                raise ValueError("request_changed_after_preflight")
            if paid:
                require_paid_admission(admission, output, plan)
            payload = json.loads(request.content)
            dump(directory / "request.json", payload)
            row["request_sha256"] = digest(payload)
            row["request_reservation_upper_cny"] = preview["reservation_cny"]
            started = time.monotonic()
            row["generation_status"] = "attempt_started"
            try:
                with budget.run_context(run_id=row["run_id"], task_id=row["task_id"], model=row["model"],
                                        repeat=row["repeat"], phase="independent_first_draft"):
                    response = await asyncio.wait_for(client.send(request),
                        timeout=65 if offline_request_timeout is None else offline_request_timeout)
                raw = response.content
                (directory / "response.raw.json").write_bytes(raw)
                row["raw_response_sha256"] = coding.sandbox.sha(raw)
                row["raw_response_source"] = "returned_decoded_http_bytes"
                body = response.json()
                row["usage"] = body["usage"]
                row["cache_usage"] = {name: body["usage"][name] for name in
                                      ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}
                row["usage_peak_estimate_cny"] = str(budget._usage_amount(body, row["model"])[1])
                parsed = parse_candidate(body, tasks[row["number"]])
                if parsed["status"] == "parsed":
                    (directory / "candidate.py").write_text(parsed.pop("code"), encoding="utf-8", newline="\n")
                row.update({"generation_status": parsed["status"], "parse": parsed, "reason": "response_received"})
            except (budget.TransportBlocked, httpx.HTTPError, TimeoutError) as exc:
                row.update({"generation_status": "transport_failed", "reason": type(exc).__name__,
                            "raw_response_source": "see_transport_journal_if_body_was_decodable"})
                # Delivery can time out after transport accounting completed.
                # End this batch even when that leaves no transport stop reason.
                break
            except asyncio.CancelledError:
                row.update({"generation_status": "interrupted", "reason": "generation_cancelled"})
                interrupted = True
                raise
            finally:
                row["generation_wall_s"] = time.monotonic() - started
                row["accounting_after_attempt"] = transport.snapshot()
                dump(directory / "generation.json", row)
    finally:
        try:
            await client.aclose()
            http_closed = True
        finally:
            snapshot = transport.snapshot()
            for row in records:
                path = output / "drafts" / row["run_id"] / "generation.json"
                if not path.exists():
                    dump(path, row)
            requests_sha = coding.sandbox.sha((output / "requests.jsonl").read_bytes())
            closure = {"denominator": 16, "records_sha256": digest(records), "http_closed": http_closed,
                       "transport": snapshot, "interrupted": interrupted, "requests_sha256": requests_sha}
            dump(output / "generation-closed.json", closure)
            # http_closed is true only after actual client close succeeds, not
            # merely because the transport managed to append batch_close.
            dump(output / "result.json", {"schema": 1, "paid": paid, "plan_sha256": digest(plan),
                "denominator": 16, "http_closed": http_closed, "interrupted": interrupted,
                "accounting": snapshot, "requests_sha256": requests_sha})
            event(output, "generation_closed", calls_dispatched=snapshot["calls_dispatched"],
                  active_calls=snapshot["active_calls"], interrupted=interrupted, http_closed=http_closed)
    return records, snapshot


def judge_after_generation(output: Path, tasks: dict, plan: dict, records: list[dict]) -> None:
    closure = json.loads((output / "generation-closed.json").read_text())
    if (closure["records_sha256"] != digest(records) or closure["transport"]["active_calls"] != 0
            or not closure["transport"]["closing"] or closure.get("http_closed") is not True
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


def make_plan(*, paid: bool, scenario: str = "mixed", simulated_cap: str = SIMULATED_CAP_CNY) -> dict:
    plan = {"schema": 1, "scope": "R3-development-natural-first-draft-check-only", "paid": paid, "planned_denominator": 16,
            "created_at": datetime.now(timezone.utc).isoformat(), "rows": rows(),
            "models": list(MODELS), "dev_ids": list(coding.DEV_IDS), "heldout_used": False,
            "independence": "fresh messages; no previous draft/result/hidden data in any request; no provider seed guarantee",
            "request_contract": {"endpoint": ENDPOINT, "temperature": 0.7, "max_tokens": 2048,
                                 "thinking": {"type": "disabled"}, "stream": False, "n": 1,
                                 "requests_per_draft": 1, "retries": 0, "http_operation_timeout_s": 60,
                                 "whole_request_timeout_s": 65,
                                 "per_request_reservation_cap_cny": str(REQUEST_CAP_CNY)},
            "parse_policy": PARSER_POLICY, "system_prompt": SYSTEM, "code_sha256": identities(),
            "runtime_identity": runtime_identity(require_wsl=paid),
            "preflight_policy": "validate all 16 unchanged request bodies before any dispatch; each <=0.20 and sum <=3.20 CNY",
            "judging": "after all generation ends and HTTP transport closes; public phase then independent hidden phase",
            "timing_claim": "not a shared-deadline/feedback-repair experiment", "judge_boundaries": coding.BOUNDARIES}
    if not paid:
        plan.update({"model_calls_actual": 0, "api_spend_cny_actual": "0",
                     "simulated_transport_cap_cny": simulated_cap, "fake_scenario": scenario})
    return plan


async def run_offline(output: Path, *, evaluate: bool = False, scenario: str = "mixed",
                      simulated_cap: str = SIMULATED_CAP_CNY) -> dict:
    if output.exists():
        raise ValueError("fresh output directory required")
    output.mkdir(parents=True)
    tasks, provenance = coding.load_tasks()
    plan = make_plan(paid=False, scenario=scenario, simulated_cap=simulated_cap)
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
            for status in ("parsed", "parse_failed", "response_failed", "transport_failed", "not_attempted", "interrupted", "attempt_started")}
        summary["all_16_responses_received"] = sum(summary["generation_counts"][key]
            for key in ("parsed", "parse_failed", "response_failed")) == 16
        dump(output / "summary.json", summary)
    return summary


async def execute_admitted(output: Path, *, execute_paid: bool, env_file: Path | None = None,
                           inner: httpx.MockTransport | None = None, evaluate: bool = False) -> dict:
    """Run one live study admission; leave the locked session before judging.

    The study owns the single whole-batch reservation/settlement. The existing
    HTTP transport remains the sole owner of every request's accounting.
    """
    import timely_study as study
    output = study.batch.local_path(output)
    plan = study.batch.read_json(output / "plan.json")
    if plan.get("paid") is not execute_paid:
        raise PaidNotAdmitted("study_mode_mismatch")
    if plan.get("runtime_identity") != runtime_identity(require_wsl=execute_paid):
        raise PaidNotAdmitted("frozen_python_identity_changed")
    expected = make_plan(paid=execute_paid)
    for field in ("scope", "planned_denominator", "rows", "models", "dev_ids", "heldout_used",
                  "request_contract", "parse_policy", "system_prompt", "code_sha256", "preflight_policy"):
        if plan.get(field) != expected[field]:
            raise PaidNotAdmitted("frozen_coding_plan_changed")
    if execute_paid and inner is not None:
        raise PaidNotAdmitted("paid_execution_rejects_fake_transport")
    if not execute_paid and type(inner) is not httpx.MockTransport:
        raise ValueError("admitted offline execution requires MockTransport")
    tasks, provenance = coding.load_tasks()
    if study.batch.digest(provenance) != plan["provenance_sha256"]:
        raise PaidNotAdmitted("dataset_provenance_changed")
    summary = {"output": str(output), "planned_denominator": 16, "paid": execute_paid,
               "rows": [], "finished": False, "evaluation_requested": evaluate,
               "plan_sha256": study.batch.digest(plan)}
    started, entered = time.monotonic(), False
    cancellation = None
    try:
        with study.coding_session(output, execute_paid=execute_paid) as admission:
            entered = True
            try:
                records, snapshot = await generate(output, tasks, plan, inner=inner,
                    admission=admission, env_file=env_file)
                summary.update({"rows": records, "accounting": snapshot})
            except (Exception, asyncio.CancelledError) as exc:
                summary["generation_error_type"] = type(exc).__name__
                if isinstance(exc, asyncio.CancelledError):
                    cancellation = exc
                summary["rows"] = [json.loads(path.read_text()) for path in sorted((output / "drafts").glob("*/generation.json"))]
            # finish either settles known complete accounting or holds the
            # entire batch. Unconfirmed HTTP closure raises and retains locks.
            summary["study_settlement"] = admission.finish()
        if evaluate and cancellation is None:
            judge_after_generation(output, tasks, plan, summary["rows"])
        summary["finished"] = "generation_error_type" not in summary
    except (Exception, asyncio.CancelledError) as exc:
        if not entered:
            raise
        summary["error_type"] = type(exc).__name__
        if isinstance(exc, asyncio.CancelledError):
            cancellation = exc
    finally:
        if entered:
            if (output / "result.json").exists():
                summary["accounting"] = json.loads((output / "result.json").read_text())["accounting"]
            summary["wall_s"] = time.monotonic() - started
            summary["denominator_retained"] = len(summary["rows"]) == 16
            summary["all_16_responses_received"] = sum(row["generation_status"] in
                ("parsed", "parse_failed", "response_failed") for row in summary["rows"]) == 16
            dump(output / "summary.json", summary)
    if cancellation is not None:
        # Preserve Ctrl-C/task cancellation after closing HTTP, recording the
        # study liability, and persisting the incomplete 16-slot summary.
        raise cancellation
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute-offline", action="store_true")
    mode.add_argument("--execute-paid", action="store_true")
    mode.add_argument("--prepare-paid-plan", action="store_true", help="write plan/provenance only; no admission or calls")
    parser.add_argument("--pilot-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--evaluate", action="store_true", help="public/hidden checks after HTTP closure and study settlement/hold")
    parser.add_argument("--scenario", choices=("mixed", "missing-usage", "missing-usage-second", "http-error", "bad-shape"), default="mixed")
    args = parser.parse_args()
    if args.prepare_paid_plan:
        try:
            plan = make_plan(paid=True)
            _, provenance = coding.load_tasks()
            output = coding.sandbox.LOCAL / "first-draft-plans" / uuid.uuid4().hex
            output.mkdir(parents=True)
            dump(output / "coding-plan.json", plan)
            dump(output / "provenance.json", provenance)
            print(json.dumps({"status": "prepared_plan_not_admitted", "output": str(output), "model_calls_actual": 0}))
            return 0
        except (PaidNotAdmitted, OSError, ValueError) as exc:
            print(json.dumps({"status": "refused", "reason": type(exc).__name__, "model_calls_actual": 0}))
            return 2
    if args.execute_paid:
        if args.pilot_root is None or args.env_file is None:
            print(json.dumps({"status": "refused", "reason": "activated_pilot_root_and_explicit_env_file_required", "model_calls_actual": 0}))
            return 2
        try:
            summary = asyncio.run(execute_admitted(args.pilot_root, execute_paid=True,
                                                  env_file=args.env_file, evaluate=args.evaluate))
        except Exception as exc:
            # A late artifact-write failure can occur after paid dispatch.
            # Never label that uninspected case as zero calls or zero spend.
            print(json.dumps({"status": "execution_failed_or_refused", "reason": type(exc).__name__,
                              "model_calls_actual": None, "inspect_artifacts": str(args.pilot_root)}))
            return 2
        print(json.dumps({"output": str(args.pilot_root), "finished": summary["finished"],
                          "study_settlement": summary.get("study_settlement"),
                          "all_16_responses_received": summary.get("all_16_responses_received")}))
        return 0 if (summary["finished"] and summary.get("all_16_responses_received")
                     and summary.get("study_settlement", {}).get("status") == "known_settled") else 1
    if args.env_file is not None or args.pilot_root is not None:
        parser.error("offline mode does not read credentials or an activated paid root")
    output = coding.sandbox.LOCAL / "first-drafts" / uuid.uuid4().hex
    with asyncio.Runner() as runner:
        blocked = install_offline_guard()
        summary = runner.run(run_offline(output, evaluate=args.evaluate, scenario=args.scenario))
    print(json.dumps({"output": str(output), "finished": summary["finished"],
                      "denominator_retained": summary["denominator_retained"],
                      "model_calls_actual": 0, "api_spend_cny_actual": "0", "blocked_network_attempts": len(blocked)}))
    return 0 if summary["finished"] and summary["denominator_retained"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
