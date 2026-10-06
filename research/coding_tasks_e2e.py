"""Focused zero-model checks for the eight-task judge bridge.

Default is a light, Docker-free boundary check. --execute-docker runs the real
prepared native-WSL image sequentially. No builds, downloads, model calls,
held-out task execution, candidate execution on the host, or pytest.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from unittest.mock import patch

import coding_tasks as coding


def assert_hidden_aggregate(result: dict) -> None:
    allowed = {"task_id", "visibility", "status", "reason", "checked", "total", "passed",
               "base_total", "plus_total", "base_passed", "plus_passed", "reference_wall_s", "wall_s"}
    assert set(result) == allowed, "hidden result schema is not the aggregate allowlist"
    assert all(not isinstance(value, (dict, list)) for value in result.values())
    assert result["visibility"] == "offline_hidden"


def static_checks(tasks: dict) -> list[str]:
    passed = []
    for path in (Path(__file__), Path(coding.__file__), Path(coding.sandbox.__file__)):
        ast.parse(path.read_text(encoding="utf-8"))
    passed.append("three_sources_parse")
    assert set(tasks) == set(coding.SELECTED_IDS)
    for number in coding.HELDOUT_IDS:
        try:
            coding.task_number(number)
        except ValueError:
            pass
        else:
            raise AssertionError("held-out task enabled")
    passed.append("heldout_ids_rejected_without_execution")
    for task in tasks.values():
        visible = coding.visible_task(task)
        assert set(visible) == {"task_id", "entry_point", "prompt", "public_checks", "provenance"}
        assert set(visible).isdisjoint({"base_input", "plus_input", "canonical_solution", "atol", "contract"})
        contaminated = {**task, "prompt": task["prompt"] + "\nchanged"}
        try:
            coding.visible_task(contaminated)
        except ValueError:
            pass
        else:
            raise AssertionError("changed prompt accepted against frozen public provenance")
    passed.append("public_allowlist_and_prompt_provenance")
    poly = coding.official_poly()
    assert coding.compare(32, [[-6, 11, -6, 1]], 3.0, 1.0, poly, 1e-4)
    assert coding.compare(32, [[1, 2]], -0.5, None, poly, 1e-4)
    assert not coding.compare(32, [[1, 2]], 0.0, None, poly, 1e-4)
    assert not coding.compare(32, [[1, 2]], float("nan"), None, poly, 1e-4)
    assert coding.compare(55, [1], 1.0, 1, None, 0)
    assert not coding.compare(55, [1], 1.0000001, 1, None, 0)
    passed.append("official_numeric_root_and_exact_equality_boundaries")
    for raw in (b'{"index":0,"value":NaN}\n', b'{"index":true,"value":1}\n',
                b'{"index":0,"value":1,"passed":true}\n', b'{"index":1,"value":1}\n'):
        try:
            coding.parse_rows(b'{"kind":"ready"}\n' + raw, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed candidate protocol accepted")
    passed.append("candidate_protocol_cannot_supply_verdict_fields")
    try:
        coding.check_source("x" * (coding.SOURCE_CAP + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("unbounded candidate accepted")
    passed.append("source_size_bounded_before_execution")
    base = {"execution_ok": True, "limits_verified_before_code": True,
            "cleanup": {"removed": True}, "output_limit_exceeded": False,
            "timed_out": False, "worker_cli_exit_code": 0, "worker_ready": True}
    assert coding.execution_status({**base, "execution_ok": False})[0] == "infra"
    assert coding.execution_status({**base, "cleanup": {"removed": False}})[0] == "infra"
    assert coding.execution_status({**base, "timed_out": True})[0] == "timeout"
    assert coding.execution_status({**base, "output_limit_exceeded": True})[0] == "fail"
    passed.append("candidate_timeout_output_failure_and_infra_are_distinct")
    return passed


def delta_fake_checks(tasks: dict, output: Path) -> list[str]:
    """Exercise classification and safe feedback without a model or Docker."""
    passed = []
    base = {"execution_ok": True, "limits_verified_before_code": True,
            "cleanup": {"removed": True}, "output_limit_exceeded": False,
            "timed_out": False, "worker_cli_exit_code": 0}
    source = "def fib(n):\n    return 1\n"
    ready = b'{"kind":"ready"}\n'
    cases = (
        ("missing-ready-exit", {"worker_cli_exit_code": 1}, b"", "infra", "candidate_not_started"),
        ("missing-ready-timeout", {"timed_out": True}, b"", "infra", "candidate_not_started"),
        ("missing-ready-output", {"output_limit_exceeded": True}, b"x", "infra", "candidate_not_started"),
        ("ready-exit", {"worker_cli_exit_code": 1}, ready, "fail", "candidate_worker_exit"),
        ("ready-timeout", {"timed_out": True}, ready, "timeout", "candidate_worker_deadline"),
        ("ready-output", {"output_limit_exceeded": True}, ready, "fail", "candidate_output_limit"),
    )
    for label, changes, raw, status, reason in cases:
        with patch.object(coding.sandbox, "execute_isolated", return_value=({**base, **changes}, raw)):
            result = coding.public_check(tasks[55], source, "fake-only", output / label)
        assert (result["status"], result["reason"]) == (status, reason)
    passed.append("pre_ready_infra_vs_post_ready_failure_timeout_output")
    with patch.object(coding.sandbox, "execute_isolated") as execution:
        syntax = coding.public_check(tasks[55], "def fib(:\n", "fake-only", output / "syntax")
        assert syntax["status"] == "fail" and syntax["diagnostic"]["error_type"] == "SyntaxError"
        assert syntax["diagnostic"]["line"] == 1
        invalid = coding.public_check(tasks[55], "\ud800", "fake-only", output / "source-surrogate")
        assert invalid["status"] == "fail" and invalid["reason"] == "candidate_source_encoding"
        hidden = coding.hidden_check(tasks[55], "\ud800", "fake-only", output / "hidden-source-surrogate")
        assert_hidden_aggregate(hidden)
        assert hidden["status"] == "fail" and hidden["reason"] == "candidate_source_encoding"
        hidden_syntax = coding.hidden_check(tasks[55], "def fib(:\n", "fake-only", output / "hidden-syntax")
        assert_hidden_aggregate(hidden_syntax)
        assert hidden_syntax["status"] == "fail"
        for checker in (coding.public_check, coding.hidden_check):
            try:
                checker(tasks[55], source, "fake-only", output / "syntax")
            except ValueError:
                pass
            else:
                raise AssertionError("reused output directory accepted")
        execution.assert_not_called()
    passed.append("source_encoding_syntax_and_directory_collisions_fail_before_docker")
    raw = ready + b'{"kind":"initialization_error","error_type":"NameError"}\n'
    with patch.object(coding.sandbox, "execute_isolated", return_value=(dict(base), raw)):
        result = coding.public_check(tasks[55], source, "fake-only", output / "init-error")
    assert result["diagnostic"] == {"error_type": "NameError"}
    raw = ready + b"".join((json.dumps({"index": i, "value": "\ud800"}) + "\n").encode() for i in range(3))
    with patch.object(coding.sandbox, "execute_isolated", return_value=(dict(base), raw)):
        result = coding.public_check(tasks[55], source, "fake-only", output / "result-surrogate")
    persisted = json.loads((output / "result-surrogate/public-result.json").read_text(encoding="utf-8"))
    assert persisted == result and result["checks"][0]["observed"] == "\ud800"
    assert json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8")
    passed.append("safe_initialization_diagnostic_and_lossless_surrogate_result")
    poly = coding.official_poly()
    assert tasks[32]["atol"] == 1e-4
    assert not coding.compare(32, [[1, 2]], 0, None, poly, tasks[32]["atol"])
    assert abs(poly([0, 1], 0)) <= tasks[32]["atol"]
    passed.append("root_atol_matches_public_but_original_vs_mutated_input_policy_differs")
    return passed


def judge_delta_checks(tasks: dict, output: Path) -> list[str]:
    """Only the paid-admission judge fixes, using controlled metadata."""
    passed = []
    base = {"execution_ok": True, "limits_verified_before_code": True,
            "cleanup": {"removed": True, "remove_exit_code": 0},
            "output_limit_exceeded": False, "timed_out": False, "worker_cli_exit_code": 126}
    ready = b'{"kind":"ready"}\n'
    source = "def fib(n):\n    return 1\n"
    for code in (125, 126, 127):
        with patch.object(coding.sandbox, "execute_isolated", return_value=({**base, "worker_cli_exit_code": code}, ready)):
            result = coding.public_check(tasks[55], source, "fake-only", output / f"exit-{code}")
        assert (result["status"], result["reason"]) == ("fail", "candidate_worker_exit")
    vanished = {**base, "cleanup": {"removed": True, "remove_exit_code": 1}}
    with patch.object(coding.sandbox, "execute_isolated", return_value=(vanished, ready)):
        result = coding.public_check(tasks[55], source, "fake-only", output / "vanished")
    assert (result["status"], result["reason"]) == ("infra", "container_vanished_before_cleanup")
    passed.append("all_post_ready_exit_codes_fail_but_confirmed_early_container_loss_is_infra")
    for error_type, expected in (("TypeError", "candidate_exception"), ("UnsupportedOutputType", "unsupported_output_type")):
        raw = ready + b"".join((json.dumps({"index": i, "error_type": error_type}) + "\n").encode() for i in range(3))
        with patch.object(coding.sandbox, "execute_isolated", return_value=({**base, "worker_cli_exit_code": 0}, raw)):
            result = coding.public_check(tasks[55], source, "fake-only", output / error_type)
        assert all(row["error"] == expected and row["error_type"] == error_type for row in result["checks"])
    passed.append("unsupported_output_contract_is_distinct_from_candidate_typeerror")
    worker_tree = ast.parse(coding.WORKER)
    mapping = next(node.value for node in worker_tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "error_types" for target in node.targets))
    builtin_names = set(ast.literal_eval(mapping.generators[0].iter))
    extra_names = {ast.literal_eval(node.value) for node in worker_tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                           and target.value.id == "error_types" for target in node.targets)}
    assert builtin_names | extra_names | {"CandidateException"} == coding.SAFE_ERROR_TYPES
    passed.append("worker_and_parent_exception_allowlists_identical")
    assert all(tasks[n]["atol"] == 0 for n in coding.SELECTED_IDS if n != 32)
    assert coding.exact_reference_supported(["a", "b", [1, True, "c"]])
    assert not coding.exact_reference_supported(["a", [1.0]])
    assert not coding.exact_reference_supported({"value": 1})
    task = {**tasks[7], "base_input": [[["ab"], "a"]], "plus_input": []}
    with patch.object(coding, "run_values") as run:
        result = coding.hidden_check({**task, "atol": 0.1}, source, "fake-only", output / "nonzero-atol")
        assert_hidden_aggregate(result)
        assert (result["status"], result["reason"]) == ("infra", "unsupported_reference_tolerance")
        run.assert_not_called()
    for label, value, expected_status in (("strings-list", ["ab"], "pass"), ("nested-float", [[1.0]], "infra")):
        with patch.object(coding, "run_values", return_value=({"status": "pass", "reason": "worker_values_received"}, [{"index": 0, "value": value}])) as run:
            result = coding.hidden_check(task, source, "fake-only", output / label)
            assert_hidden_aggregate(result)
            assert result["status"] == expected_status
            assert run.call_count == (2 if expected_status == "pass" else 1)
    passed.append("zero_atol_and_recursive_exact_reference_scope_accepts_task7_strings")
    return passed


def verify_execution_artifacts(directory: Path) -> None:
    for path in directory.glob("*/execution.json"):
        execution = json.loads(path.read_text())
        assert execution["cleanup"]["removed"]
        assert execution["worker_cli_reaped"]
        assert execution["limits_verified_before_code"]
        assert execution["expected_results_sent_to_worker"] is False
        assert execution["worker_header_fields"] == ["source", "entry_point"]
        assert execution["worker_case_fields"] == ["index", "arguments"]
        for stream, cap in execution["output_limits_bytes"].items():
            assert (path.parent / f"worker-{stream}.txt").stat().st_size <= cap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-docker", action="store_true")
    parser.add_argument("--review-delta", action="store_true", help="Only targeted review fixes; skip the existing 27 Docker cases")
    parser.add_argument("--judge-delta", action="store_true", help="Only later judge classification fixes; skip both previous Docker suites")
    args = parser.parse_args()
    if args.review_delta and args.judge_delta:
        parser.error("choose one delta scope")
    output = coding.sandbox.LOCAL / "task-e2e" / uuid.uuid4().hex
    output.mkdir(parents=True, mode=0o700)
    summary = {"output": str(output), "created_at": datetime.now(timezone.utc).isoformat(),
               "model_calls": 0, "api_spend_cny": "0", "heldout_used": False,
               "r3_experiment_completed": False, "docker_requested": args.execute_docker,
               "passed": False, "cases": [], "boundaries": coding.BOUNDARIES,
               "script_sha256": {p.name: coding.sandbox.sha(p.read_bytes()) for p in
                   (Path(__file__), Path(coding.__file__), Path(coding.sandbox.__file__))}}
    try:
        tasks, provenance = coding.load_tasks()
        coding.sandbox.dump(output / "provenance.json", provenance)
        summary["static_checks"] = static_checks(tasks)
        if args.review_delta:
            summary["delta_fake_checks"] = delta_fake_checks(tasks, output / "fake-delta")
        if args.judge_delta:
            summary["judge_delta_checks"] = judge_delta_checks(tasks, output / "judge-delta")
        if args.execute_docker:
            coding.sandbox.verify_daemon(output, summary)
            image_id = coding.existing_image(output)

            def check(label, number, source, mode, expected, timeout=30):
                directory = output / label
                directory.mkdir(mode=0o700)
                checker = coding.public_check if mode == "public" else coding.hidden_check
                result = checker(tasks[number], source, image_id, directory, timeout=timeout)
                if mode == "hidden":
                    assert_hidden_aggregate(result)
                verify_execution_artifacts(directory)
                passed = result["status"] == expected
                summary["cases"].append({"name": label, "task_id": result["task_id"],
                    "mode": mode, "expected_status": expected, "actual_status": result["status"],
                    "checked": result["checked"], "candidate_passed": result["passed"], "passed": passed})
                print(json.dumps(summary["cases"][-1]), flush=True)
                assert passed, label + " unexpected classification"
                return result

            if args.judge_delta:
                result = check("judge-exit-126", 55, "import os\nos._exit(126)\n", "public", "fail")
                assert result["reason"] == "candidate_worker_exit"
                result = check("judge-unsupported-tuple", 7,
                               "def filter_by_substring(strings, substring):\n    return tuple(s for s in strings if substring in s)\n",
                               "public", "fail")
                assert all(row["error_type"] == "UnsupportedOutputType" and row["error"] == "unsupported_output_type"
                           for row in result["checks"])
                summary["passed"] = True
                return 0

            if args.review_delta:
                # One correct result proves the ready envelope is accepted;
                # actual failures establish its distinction from worker startup.
                check("delta-valid", 55, tasks[55]["prompt"] + tasks[55]["canonical_solution"], "public", "pass")
                with patch.object(coding, "WORKER", "raise RuntimeError('injected worker startup failure')\n"):
                    result = check("delta-before-ready", 55, "def fib(n):\n    return 1\n", "public", "infra")
                assert result["reason"] == "candidate_not_started"
                assert json.loads((output / "delta-before-ready/candidate/worker-protocol.json").read_text())["worker_ready"] is False
                result = check("delta-runtime-error", 55,
                               "def fib(n):\n    return 1 / 0\n", "public", "fail")
                assert all(row["error_type"] == "ZeroDivisionError" for row in result["checks"])
                result = check("delta-custom-error", 55,
                               "class PrivateMessage(Exception):\n    pass\ndef fib(n):\n    raise PrivateMessage('private message')\n",
                               "public", "fail")
                assert all(row["error_type"] == "CandidateException" for row in result["checks"])
                result = check("delta-init-error", 55, "raise NameError('private message')\n", "public", "fail")
                assert result["diagnostic"] == {"error_type": "NameError"}
                result = check("delta-surrogate", 55, "def fib(n):\n    return '\\ud800'\n", "public", "fail")
                assert result["checks"][0]["observed"] == "\ud800"
                check("delta-exit", 55, "import os\nos._exit(1)\n", "public", "fail")
                check("delta-timeout", 55, "def fib(n):\n    while True:\n        pass\n", "public", "timeout", 2)
                result = check("delta-stderr-cap", 55,
                               "def fib(n):\n    import os\n    while True:\n        os.write(2, b'x' * 16384)\n",
                               "public", "fail", 10)
                assert result["reason"] == "candidate_output_limit"
                check("delta-root-input-mutation", 32,
                      "def find_zero(xs):\n    xs[:] = [0, 1]\n    return 0\n", "public", "fail")
                result = check("delta-hidden-error", 32,
                               "def find_zero(xs):\n    raise ValueError('private message')\n", "hidden", "fail")
                assert_hidden_aggregate(result)
                summary["passed"] = True
                return 0

            # All selected types and all selected hidden inputs; held-out tasks
            # are absent. Reference and candidate containers run sequentially.
            for number in coding.SELECTED_IDS:
                task = tasks[number]
                canonical = task["prompt"] + task["canonical_solution"]
                check(f"public-canonical-{number}", number, canonical, "public", "pass")
                # The pinned dataset's Newton canonical genuinely fails seven
                # plus inputs on the pinned image; do not bless it by identity.
                result = check(f"hidden-canonical-{number}", number, canonical, "hidden",
                               "fail" if number == 32 else "pass")
                if number == 32:
                    assert result["base_passed"] == 100 and result["plus_passed"] == 781

            memorizer = "def fib(n):\n    return {10: 55, 1: 1, 8: 21}.get(n, -999)\n"
            check("public-example-memorizer", 55, memorizer, "public", "pass")
            check("hidden-example-memorizer", 55, memorizer, "hidden", "fail")
            check("wrong-list", 7, "def filter_by_substring(strings, substring):\n    return []\n", "public", "fail")
            check("wrong-root", 32, "def find_zero(xs):\n    return 0.0\n", "public", "fail")
            check("alternative-valid-root", 32,
                  "def find_zero(xs):\n    return -0.5 if xs == [1, 2] else 3.0\n", "public", "pass")

            stateful = "count = 0\ndef fib(n):\n    global count\n    count += 1\n    return count\n"
            first = check("clean-state-first", 55, stateful, "public", "fail")
            second = check("clean-state-second", 55, stateful, "public", "fail")
            assert [r["observed"] for r in first["checks"]] == [1, 2, 3]
            assert [r["observed"] for r in second["checks"]] == [1, 2, 3]

            for stream, fd in (("stdout", 1), ("stderr", 2)):
                source = f"def fib(n):\n    import os\n    while True:\n        os.write({fd}, b'x' * 16384)\n"
                result = check(stream + "-flood", 55, source, "public", "fail", 10)
                assert result["reason"] == "candidate_output_limit"
                execution = json.loads((output / (stream + "-flood") / "candidate/execution.json").read_text())
                assert execution["output_limit_stream"] == stream
            result = check("infinite-loop", 55, "def fib(n):\n    while True:\n        pass\n", "public", "timeout", 1)
            assert result["reason"] == "candidate_worker_deadline"

            # A candidate can emit arbitrary messages, but hidden aggregate
            # output is constructed in the parent from a fixed field allowlist.
            result = check("hidden-candidate-input-echo", 32,
                          "def find_zero(xs):\n    print(xs)\n    return str(xs)\n", "hidden", "fail")
            assert_hidden_aggregate(result)
        summary["passed"] = True
    except KeyboardInterrupt:
        summary["error_type"] = "KeyboardInterrupt"
    except Exception as exc:
        summary["error_type"] = type(exc).__name__
        summary["error"] = str(exc)[:400]
    finally:
        coding.sandbox.dump(output / "summary.json", summary)
        print(json.dumps({"passed": summary["passed"], "output": str(output),
                          "cases": len(summary["cases"]), "docker_executed": args.execute_docker}), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
