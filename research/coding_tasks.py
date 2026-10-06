"""Small, zero-model HumanEval+ public-check / offline-judge bridge.

Only the eight explicitly selected development tasks are supported. Public
checks use frozen prompt examples; hidden checking is a separate parent-owned
entry point. Candidate code and canonical references run only in fresh Docker
containers through coding_environment_smoke.execute_isolated.

This is preparation, not the full EvalPlus evaluator or an R3 experiment.
The timeout covers one worker batch, not a shared agent deadline or EvalPlus's
canonical-relative per-input timeout. Hidden raw evidence must never be fed
back to a model. Docker isolates the host, but a hostile candidate can inspect
its worker and input stream; this is not a tamper-proof in-container protocol.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import sys
import time
import uuid
import zipfile

import coding_environment_smoke as sandbox


DEV_IDS = (55, 32, 7, 56)
EXTENSION_IDS = (16, 99, 18, 31)
SELECTED_IDS = DEV_IDS + EXTENSION_IDS
# Held-out task contents are never selected, evaluated, or used as fixtures.
HELDOUT_IDS = (43, 25, 156, 145)
ASSETS = sandbox.LOCAL / "assets"
SPECIAL_ORACLE_SHA = "92b126b907ee493121b55de06f6a34058b6e18adc8cf1c48737eedcd83f24cdd"
EVALUATOR_SHA = "76857b678cddca08dcaf54d7927b9a77826715cf657654ca5baf6c2b267f4c34"
SOURCE_CAP = 256 * 1024
STATUSES = {"pass", "fail", "timeout", "infra"}
BOUNDARIES = {
    "scope": "eight development tasks; no held-out task execution; not a full R3 experiment",
    "timeouts": "worker-batch wall time only; not EvalPlus per-input limits or the future common agent deadline",
    "outputs": "finite JSON-native scalar/list values; no arbitrary object deserialization",
    "hidden_visibility": "aggregate verdict only; raw hidden worker evidence is parent-only",
    "state": "each checker call requires a fresh empty directory; fresh container/module per evaluation; module state persists between inputs",
    "security": "worker and candidate share a container/process; protocol is not resistant to introspective forgery",
    "infrastructure": "missing pre-candidate ready handshake or verified setup/cleanup failures are infra; after ready, nonzero exit is candidate failure unless Docker reports ambiguous execution failure",
    "public_diagnostics": "parent compile-only syntax location/message and allowlisted builtin exception classes; no exception messages from candidate execution",
    "input_mutation": "comparisons use original parent inputs; pinned EvalPlus find_zero instead checks the candidate-mutated in-worker copy; not full evaluator equivalence",
    "timing": "reference generation and Docker startup are recorded separately; this bridge does not make deadline-comparison claims",
}

# Inputs and expected values below are transcribed only from the published
# prompt, never base_input / plus_input / canonical_solution. Prompt SHA pins
# make that provenance fail closed. The numeric residual tolerance is an
# explicit public checker policy for the prompt's 'any zero point' contract;
# matching the example's particular root would reject other valid roots.
PUBLIC = {
    55: ("b99ee738edd1466c976259cf4271917d52d9a0df5220d566646b476a4400a336", [
        ([10], 55, "doctest 1"), ([1], 1, "doctest 2"), ([8], 21, "doctest 3")]),
    32: ("17c137edab480f3be30b47bb48eea2748f23b120a73b2bb80c7901112e1b223f", [
        ([[1, 2]], {"polynomial_residual_at_most": 0.0001, "example_round_2": -0.5}, "doctest 1 and any-zero specification"),
        ([[-6, 11, -6, 1]], {"polynomial_residual_at_most": 0.0001, "example_round_2": 1.0}, "doctest 2 and any-zero specification")]),
    7: ("5eecb2c6bb2b4fcd70989d66291a7c4c02d3afbf31591ad684e926a1e60ee969", [
        ([[], "a"], [], "doctest 1"),
        ([["abc", "bacd", "cde", "array"], "a"], ["abc", "bacd", "array"], "doctest 2")]),
    56: ("4d14ffd571dae1770eb5e26636b128c8520cee2173f2f4a592277c6cd094e644", [
        (["<"], False, "doctest 1"), (["<>"], True, "doctest 2"),
        (["<<><>>"], True, "doctest 3"), (["><<>"], False, "doctest 4")]),
    16: ("33374da5d17599a9d2b60a77489c71576ed0c7230529febb273810fe327d80f9", [
        (["xyzXYZ"], 3, "doctest 1"), (["Jerry"], 4, "doctest 2")]),
    99: ("53ad185333496f1faa011070d323b24af3e23506e32f52ced0b3c0f9867d2719", [
        (["10"], 10, "doctest 1"), (["15.3"], 15, "doctest 2"),
        (["14.5"], 15, "explicit specification example"), (["-14.5"], -15, "explicit specification example")]),
    18: ("6fc9c00aa6b110ecf79f34e36f14b6b4c9a27128463ef6733b948e32a35c2bfc", [
        (["", "a"], 0, "doctest 1"), (["aaa", "a"], 3, "doctest 2"), (["aaaa", "aa"], 3, "doctest 3")]),
    31: ("453ca5e2c63fdbba8afa4208d797faeb371744b7de1e5c401d89664050bcc613", [
        ([6], False, "doctest 1"), ([101], True, "doctest 2"), ([11], True, "doctest 3"),
        ([13441], True, "doctest 4"), ([61], True, "doctest 5"),
        ([4], False, "doctest 6"), ([1], False, "doctest 7")]),
}

SAFE_ERROR_TYPES = frozenset({
    "ArithmeticError", "AssertionError", "AttributeError", "EOFError", "ImportError", "IndexError",
    "KeyError", "LookupError", "MemoryError", "ModuleNotFoundError", "NameError", "NotImplementedError",
    "OSError", "OverflowError", "RecursionError", "RuntimeError", "StopIteration", "SyntaxError",
    "IndentationError", "TabError", "SystemExit", "TypeError", "UnboundLocalError", "UnicodeError",
    "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeTranslateError", "ValueError", "ZeroDivisionError",
    "KeyboardInterrupt", "CandidateException",
})

WORKER = r'''
import contextlib, json, math, os, sys
encode, decode, out = json.dumps, json.loads, sys.stdout
import builtins
error_types = {getattr(builtins, name): name for name in (
    "ArithmeticError", "AssertionError", "AttributeError", "EOFError", "ImportError", "IndexError",
    "KeyError", "LookupError", "MemoryError", "ModuleNotFoundError", "NameError", "NotImplementedError",
    "OSError", "OverflowError", "RecursionError", "RuntimeError", "StopIteration", "SyntaxError",
    "IndentationError", "TabError", "SystemExit", "TypeError", "UnboundLocalError", "UnicodeError",
    "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeTranslateError", "ValueError", "ZeroDivisionError",
    "KeyboardInterrupt")}
header = decode(sys.stdin.readline())
source, entry = header.pop("source"), header.pop("entry_point")
if header:
    raise ValueError("unexpected worker header")
with open("/work/candidate.py", "x") as stream:
    stream.write(source)
namespace = {"__name__": "candidate"}
def emit(value):
    out.write(encode(value, allow_nan=False) + "\n")
    out.flush()
def plain(value, depth=0):
    if depth > 32:
        raise ValueError("output nesting limit")
    if type(value) in (type(None), bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [plain(item, depth + 1) for item in value]
    raise TypeError("unsupported output type")
emit({"kind": "ready"})
try:
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        exec(compile(source, "/work/candidate.py", "exec"), namespace)
        function = namespace[entry]
except BaseException as exc:
    emit({"kind": "initialization_error", "error_type": error_types.get(type(exc), "CandidateException")})
    raise SystemExit(0)
for line in sys.stdin:
    case = decode(line)
    try:
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            value = plain(function(*case["arguments"]))
        emit({"index": case["index"], "value": value})
    except BaseException as exc:
        emit({"index": case["index"], "error_type": error_types.get(type(exc), "CandidateException")})
'''


def task_number(task_id: str | int) -> int:
    number = int(str(task_id).removeprefix("HumanEval/"))
    if number not in SELECTED_IDS:
        raise ValueError("only the selected development tasks are enabled")
    return number


def load_tasks() -> tuple[dict[int, dict], dict]:
    """Read only cached, fixed-hash assets. Never download or access credentials."""
    hashes = {}
    for filename, (_, expected) in sandbox.DOWNLOADS.items():
        raw = (ASSETS / filename).read_bytes()
        if sandbox.sha(raw) != expected:
            raise ValueError("cached asset does not match the fixed SHA256: " + filename)
        hashes[filename] = expected
    raw = gzip.decompress((ASSETS / "HumanEvalPlus-v0.1.10.jsonl.gz").read_bytes())
    if sandbox.sha(raw) != sandbox.DATASET_SHA:
        raise ValueError("expanded dataset SHA256 differs")
    selected = {f"HumanEval/{n}" for n in SELECTED_IDS}
    # Only selected rows are decoded into task objects. Held-out rows remain
    # bytes in the verified public release, never experiment/test fixtures.
    tasks = {}
    for line in raw.splitlines():
        if any(('"task_id": "' + key + '"').encode() in line for key in selected):
            row = json.loads(line)
            number = task_number(row["task_id"])
            if number in tasks:
                raise ValueError("duplicate selected task")
            if sandbox.sha(row["prompt"].encode()) != PUBLIC[number][0]:
                raise ValueError("public prompt provenance differs")
            tasks[number] = row
    if set(tasks) != set(SELECTED_IDS):
        raise ValueError("missing selected task in the fixed dataset")
    with zipfile.ZipFile(ASSETS / "evalplus-source.zip") as archive:
        prefix = f"evalplus-{sandbox.COMMIT}/"
        evaluator = archive.read(prefix + "evalplus/eval/__init__.py")
        special = archive.read(prefix + "evalplus/eval/_special_oracle.py")
    if sandbox.sha(evaluator) != EVALUATOR_SHA or sandbox.sha(special) != SPECIAL_ORACLE_SHA:
        raise ValueError("official comparator source differs")
    provenance = {"dataset_version": "HumanEval+ v0.1.10", "evalplus_version": "v0.3.1",
                  "source_commit": sandbox.COMMIT, "downloads_sha256": hashes,
                  "dataset_decompressed_sha256": sandbox.DATASET_SHA,
                  "evaluator_source_sha256": EVALUATOR_SHA, "special_oracle_source_sha256": SPECIAL_ORACLE_SHA,
                  "public_fixture_sha256": sandbox.sha(json.dumps(PUBLIC, sort_keys=True).encode()),
                  "selected_dev_ids": list(DEV_IDS), "extension_ids": list(EXTENSION_IDS),
                  "heldout_used": False, "model_calls": 0, "api_spend_cny": "0"}
    return tasks, provenance


def official_poly():
    """Import only the verified official special-oracle module, never a candidate.

    Its _poly is the actual helper used by EvalPlus's find_zero residual check.
    The other seven selected tasks use the evaluator's exact equality branch
    (their canonical results are integers, booleans, or lists of strings).
    """
    with zipfile.ZipFile(ASSETS / "evalplus-source.zip") as archive:
        raw = archive.read(f"evalplus-{sandbox.COMMIT}/evalplus/eval/_special_oracle.py")
    if sandbox.sha(raw) != SPECIAL_ORACLE_SHA:
        raise ValueError("official special oracle hash mismatch")
    namespace = {"__name__": "tracepilot_pinned_special_oracle"}
    exec(compile(raw, "<verified_evalplus_special_oracle>", "exec"), namespace)
    return namespace["_poly"]


def visible_task(task: dict) -> dict:
    number = task_number(task["task_id"])
    if sandbox.sha(task["prompt"].encode()) != PUBLIC[number][0]:
        raise ValueError("public prompt provenance differs")
    return {"task_id": task["task_id"], "entry_point": task["entry_point"], "prompt": task["prompt"],
            "public_checks": [{"arguments": args, "expected": expected, "source": origin}
                              for args, expected, origin in PUBLIC[number][1]],
            "provenance": {"dataset": "HumanEval+ v0.1.10", "prompt_sha256": PUBLIC[number][0],
                           "checks_source": "published prompt examples/specification only"}}


def compare(number: int, arguments: list, observed: object, expected: object, poly, atol: float) -> bool:
    # Selected comparison expressions from pinned unsafe_execute. Unlike its
    # find_zero branch, arguments here are original inputs, never mutated ones.
    # /32 accepts ANY sufficiently accurate root, not the canonical root.
    try:
        if number == 32:
            return abs(poly(*arguments, observed)) <= atol
        return observed == expected
    except (ArithmeticError, TypeError, ValueError):
        return False


class CandidateInitializationError(ValueError):
    def __init__(self, error_type: str):
        super().__init__("candidate_initialization")
        self.error_type = error_type


def parse_rows(raw: bytes, count: int) -> list[dict]:
    def no_constant(_):
        raise ValueError("non-finite JSON constant")
    rows = [json.loads(line, parse_constant=no_constant) for line in raw.splitlines() if line.strip()]
    if not rows or rows.pop(0) != {"kind": "ready"}:
        raise ValueError("missing_worker_ready")
    if len(rows) == 1 and isinstance(rows[0], dict) and rows[0].get("kind") == "initialization_error":
        row = rows[0]
        if (set(row) != {"kind", "error_type"} or not isinstance(row["error_type"], str)
                or row["error_type"] not in SAFE_ERROR_TYPES):
            raise ValueError("candidate_protocol")
        raise CandidateInitializationError(row["error_type"])
    if len(rows) != count:
        raise ValueError("candidate_protocol")
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] != index
                or set(row) not in ({"index", "value"}, {"index", "error_type"})):
            raise ValueError("candidate_protocol")
        if "error_type" in row and (not isinstance(row["error_type"], str) or row["error_type"] not in SAFE_ERROR_TYPES):
            raise ValueError("candidate_protocol")
    return rows


def execution_status(execution: dict) -> tuple[str | None, str | None]:
    if (not execution.get("execution_ok") or execution.get("error")
            or not execution.get("limits_verified_before_code")
            or not execution.get("cleanup", {}).get("removed")):
        return "infra", "isolation_or_execution_infrastructure"
    if not execution.get("worker_ready"):
        return "infra", "candidate_not_started"
    if execution["output_limit_exceeded"]:
        return "fail", "candidate_output_limit"
    if execution["timed_out"]:
        return "timeout", "candidate_worker_deadline"
    if execution["worker_cli_exit_code"] in (125, 126, 127):
        return "infra", "docker_exec_or_candidate_exit_ambiguous"
    if execution["worker_cli_exit_code"] != 0:
        return "fail", "candidate_worker_exit"
    return None, None


def check_source(source: str) -> None:
    if not isinstance(source, str):
        raise ValueError("candidate_source_type")
    try:
        raw = source.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("candidate_source_encoding") from None
    if len(raw) > SOURCE_CAP:
        raise ValueError("candidate_source_size")


def source_failure(source: str) -> dict | None:
    """Inspect bounded source without executing it in the parent."""
    try:
        check_source(source)
    except ValueError as exc:
        return {"status": "fail", "reason": str(exc)}
    try:
        compile(source, "candidate.py", "exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        diagnostic = {"error_type": type(exc).__name__}
        if isinstance(exc, SyntaxError):
            diagnostic.update({"line": exc.lineno, "column": exc.offset,
                               "message": str(exc.msg)[:240]})
        return {"status": "fail", "reason": "candidate_source_syntax", "diagnostic": diagnostic}
    return None


def claim_output(output: Path) -> None:
    """Accept a new path or empty existing directory, once per checker call.

    Reuse, including public then hidden in one directory, is a caller error.
    The exclusive marker rejects concurrent collisions before any Docker work.
    """
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("checker_output_must_be_fresh_and_empty")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with (output / ".checker-entry").open("x", encoding="ascii") as stream:
            stream.write("one checker invocation\n")
    except FileExistsError:
        raise ValueError("checker_output_already_claimed") from None


def dump_result(path: Path, value: dict) -> None:
    # Candidate strings may legally contain lone surrogates. JSON escapes are
    # lossless and keep both persisted evidence and model-facing JSON UTF-8 safe.
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def run_values(task: dict, source: str, arguments: list, image_id: str,
               output: Path, label: str, timeout: float) -> tuple[dict, list[dict]]:
    invalid = source_failure(source)
    if invalid:
        return invalid, []
    execution, raw = sandbox.execute_isolated(label, source, task["entry_point"], arguments,
                                              image_id, output, timeout, worker_code=WORKER)
    try:
        first = raw.split(b"\n", 1)[0]
        execution["worker_ready"] = json.loads(first) == {"kind": "ready"}
    except (ValueError, UnicodeError, RecursionError):
        execution["worker_ready"] = False
    if (output / label).is_dir():
        dump_result(output / label / "worker-protocol.json", {
            "worker_ready": execution["worker_ready"],
            "meaning": "worker emitted ready after setup, immediately before candidate compilation/execution",
            "legacy_candidate_started_means": "sandbox dispatch attempted; use worker_ready for candidate-stage evidence",
        })
    status, reason = execution_status(execution)
    if status:
        return {"status": status, "reason": reason, "execution": execution}, []
    try:
        rows = parse_rows(raw, len(arguments))
    except CandidateInitializationError as exc:
        return {"status": "fail", "reason": "candidate_initialization", "execution": execution,
                "diagnostic": {"error_type": exc.error_type}}, []
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return {"status": "fail", "reason": "candidate_protocol_or_initialization", "execution": execution}, []
    return {"status": "pass", "reason": "worker_values_received", "execution": execution}, rows


def public_check(task: dict, source: str, image_id: str, output: Path, *, timeout: float = 30) -> dict:
    """Model-facing checker; output must be new or an existing empty directory."""
    claim_output(output)
    started = time.monotonic()
    visible = visible_task(task)
    checks = visible["public_checks"]
    number = task_number(task["task_id"])
    execution, rows = run_values(task, source, [case["arguments"] for case in checks],
                                 image_id, output, "candidate", timeout)
    result = {"task_id": task["task_id"], "visibility": "public", "status": execution["status"],
              "reason": execution["reason"], "checked": len(rows), "total": len(checks), "passed": 0,
              "checks": []}
    if "diagnostic" in execution:
        result["diagnostic"] = execution["diagnostic"]
    if rows:
        poly = official_poly() if number == 32 else None
        for case, row in zip(checks, rows):
            passed = "value" in row and compare(number, case["arguments"], row.get("value"), case["expected"], poly, 0.0001)
            detail = {**case, "passed": passed}
            if "value" in row:
                detail["observed"] = row["value"]
            else:
                detail["error"] = "candidate_exception"
                detail["error_type"] = row["error_type"]
            result["checks"].append(detail)
        result["passed"] = sum(case["passed"] for case in result["checks"])
        result["status"] = "pass" if result["passed"] == len(checks) else "fail"
        result["reason"] = "public_checks_complete"
    result["wall_s"] = time.monotonic() - started
    dump_result(output / "public-result.json", result)
    return result


def hidden_check(task: dict, source: str, image_id: str, output: Path, *, timeout: float = 30) -> dict:
    """Offline parent-owned judge. Never call this as a model feedback tool.

    Expected values are generated in a separate fresh canonical container.
    Only candidate source, entry-point name, and inputs enter the candidate
    container. The returned and saved result is a fixed aggregate allowlist.
    Each call requires its own new or existing empty output directory.
    """
    claim_output(output)
    started = time.monotonic()
    number = task_number(task["task_id"])
    arguments = task["base_input"] + task["plus_input"]
    expected = [None] * len(arguments)
    result = {"task_id": task["task_id"], "visibility": "offline_hidden", "status": "infra",
              "reason": "reference_unavailable", "checked": 0, "total": len(arguments), "passed": 0,
              "base_total": len(task["base_input"]), "plus_total": len(task["plus_input"]),
              "base_passed": 0, "plus_passed": 0, "reference_wall_s": 0.0}
    try:
        invalid = source_failure(source)
        if invalid:
            # Public-only syntax details must not expand this aggregate schema.
            result.update({key: invalid[key] for key in ("status", "reason")})
            return result
        if number != 32:
            reference_start = time.monotonic()
            reference, reference_rows = run_values(task, task["prompt"] + task["canonical_solution"],
                arguments, image_id, output, "reference", timeout)
            result["reference_wall_s"] = time.monotonic() - reference_start
            if reference["status"] != "pass" or any("value" not in row for row in reference_rows):
                result["reason"] = "reference_execution_failed"
                return result
            expected = [row["value"] for row in reference_rows]
            # The selected exact-match tasks have no float-valued references;
            # fail closed if that scope changes instead of approximating np.allclose.
            if any(type(value) not in (int, bool, list) for value in expected):
                result["reason"] = "unsupported_reference_type"
                return result
        poly = official_poly() if number == 32 else None
        execution, rows = run_values(task, source, arguments, image_id, output, "candidate", timeout)
        result.update({"status": execution["status"], "reason": execution["reason"], "checked": len(rows)})
        if rows:
            correct = ["value" in row and compare(number, args, row.get("value"), exp, poly, task["atol"])
                       for args, exp, row in zip(arguments, expected, rows)]
            boundary = len(task["base_input"])
            result.update({"passed": sum(correct), "base_passed": sum(correct[:boundary]),
                           "plus_passed": sum(correct[boundary:]),
                           "status": "pass" if all(correct) else "fail", "reason": "hidden_checks_complete"})
        return result
    finally:
        result["wall_s"] = time.monotonic() - started
        dump_result(output / "hidden-result.json", result)


def existing_image(output: Path) -> str:
    image = json.loads(sandbox.command(["docker", "image", "inspect", sandbox.IMAGE]).stdout)[0]
    expected = "sha256:83712435c2675d4426381b7ac449347f834a1f0b820c945b4cb9b92ab46b9e8d"
    if image["Id"] != expected or image["Os"] != "linux" or image["Architecture"] != "amd64":
        raise ValueError("prepared image identity differs; do not build/pull implicitly")
    sandbox.dump(output / "image.json", {"id": image["Id"], "tag": sandbox.IMAGE, "base_digest": sandbox.BASE})
    return image["Id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("public", "hidden"))
    parser.add_argument("--task", required=True, type=task_number)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    output = sandbox.LOCAL / "task-checks" / uuid.uuid4().hex
    output.mkdir(parents=True, mode=0o700)
    result = {"task_id": f"HumanEval/{args.task}", "visibility": args.mode,
              "status": "infra", "reason": "setup_failed"}
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "output": str(output),
               "boundaries": BOUNDARIES, "model_calls": 0, "api_spend_cny": "0",
               "script_sha256": sandbox.sha(Path(__file__).read_bytes())}
    try:
        # Bound source-file reads before decoding; never import candidate code.
        with args.candidate.open("rb") as stream:
            raw = stream.read(SOURCE_CAP + 1)
        if len(raw) > SOURCE_CAP:
            result.update({"status": "fail", "reason": "candidate_source_size"})
            return 1
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            result.update({"status": "fail", "reason": "candidate_source_encoding"})
            return 1
        tasks, provenance = load_tasks()
        sandbox.dump(output / "provenance.json", provenance)
        sandbox.dump(output / "visible-task.json", visible_task(tasks[args.task]))
        sandbox.verify_daemon(output, summary)
        image_id = existing_image(output)
        checker = public_check if args.mode == "public" else hidden_check
        result = checker(tasks[args.task], source, image_id, output / "check", timeout=args.timeout)
    except KeyboardInterrupt:
        result.update({"status": "infra", "reason": "interrupted"})
    except Exception as exc:
        # Parent-only diagnostics. No exception message/raw output in stdout.
        summary["error_type"] = type(exc).__name__
    finally:
        summary["result"] = result
        dump_result(output / "summary.json", summary)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 2 if result["status"] == "infra" else 1


if __name__ == "__main__":
    raise SystemExit(main())
