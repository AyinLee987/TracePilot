"""Audit pinned public evaluator code using deterministic, dependency-free fakes.

No API clients, model weights, ML datasets, or training packages are imported.
Selected unchanged AST definitions are loaded from the verified upstream Git
commit; third-party source is not copied into this artifact. Responses, execution,
correctness scoring, and clocks are fakes. Results establish code-path behavior,
not the frequency of a problem with real models or its impact on paper results.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Literal
from unittest.mock import patch

COMMIT = "e13af2b8c98d799857ace789ebcfdfd4ea6c2985"
RL = "rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class Source:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.hashes: dict[str, str] = {}
        self.texts: dict[str, str] = {}
        head = self.git("rev-parse", "HEAD").decode().strip()
        require(head == COMMIT, f"Expected source commit {COMMIT}; got {head}")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout

    def read(self, relative: str) -> str:
        if relative not in self.texts:
            blob = self.git("show", f"{COMMIT}:{relative}")
            text = blob.decode("utf-8").replace("\r\n", "\n")
            actual = (self.root / relative).read_text(encoding="utf-8")
            require(actual == text, f"Audited upstream file differs from commit: {relative}")
            self.hashes[relative] = hashlib.sha256(blob).hexdigest()
            self.texts[relative] = text
        return self.texts[relative]

    def module(self, relative: str, names: set[str], scope: dict[str, Any]) -> dict[str, Any]:
        tree = ast.parse(self.read(relative), filename=relative)
        nodes = [node for node in tree.body if getattr(node, "name", None) in names]
        require({node.name for node in nodes} == names, f"Missing definitions: {relative}")
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        selected = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
        exec(compile(selected, relative, "exec"), scope)
        return scope

    def has(self, relative: str, fragment: str) -> None:
        require(fragment in self.read(relative), f"Pinned structural assertion failed: {relative}: {fragment}")


class FixedTimer:
    value = 0.0

    def __init__(self, **kwargs: Any):
        pass

    def start(self) -> None:
        pass

    def call(self, return_format: str = "text") -> str | float:
        return self.value if return_format == "value" else f"{self.value} seconds."


class FakeAgent:
    def __init__(self, response: str):
        self.response = response

    async def generate_response(self, messages: list, **kwargs: Any) -> str:
        return self.response


class FakeGame:
    def __init__(self, *args: Any):
        self.score = 0

    def get_current_state(self) -> tuple:
        return ("initial",)

    def get_max_score(self) -> str:
        return "10"

    def get_score(self) -> str:
        return str(self.score)

    def step(self, action: str) -> str:
        self.score = 10
        return "scored"

    def check_game_termination(self) -> str:
        return "The game is not terminated."


def forbidden_judge(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("Remote judging is prohibited in this deterministic audit")


async def audit(source: Source) -> dict[str, Any]:
    parsing = source.module("src/timely_eval/parsing.py", {
        "extract_tag_values", "extract_last_tag", "extract_answer_or_tool_call",
        "extract_judge_result", "parse_tool_call_content", "extract_tool_calls",
    }, dict(re=re, json=json, TAG_RE_TEMPLATE=r"<{tag}>\s*(.*?)\s*</{tag}>"))
    scope = dict(parsing, Timer=FixedTimer, append_jsonl=lambda *_: None,
                 compute_score=lambda answer, expected: float(answer == expected),
                 TIME_AWARE_GENERAL_SYSTEM="stub", TIME_TOOL_PROMPT="stub",
                 INTERACTIVE_SYSTEM="stub", INTERACTIVE_TOOL_PROMPT="stub",
                 AGENTIC_ML_SYSTEM="stub", AGENTIC_ML_TOOL_PROMPT="stub")
    source.has("src/timely_eval/parsing.py", 'TAG_RE_TEMPLATE = r"<{tag}>\\s*(.*?)\\s*</{tag}>"')
    source.has("src/timely_eval/general.py", "within_time_limit = duration <= 1.1 * time_limit")
    source.has("src/timely_eval/general.py", "baseline_duration * multiplier")
    source.has("src/timely_eval/agentic_ml.py", 'item.get("current_duration", 0.0) <= 1.5 * time_limit')
    source.has("src/timely_eval/interactive.py", "result = await self._execute_tool(tool_call, env)")
    source.has("src/timely_eval/interactive.py", "final_score = _first_int(env.get_score())")
    source.has(RL + "__init__.py", "from .Basic_timer_reward_calculator import LlmTimerRewardCalculator")
    results: dict[str, Any] = {"kind": "deterministic stubbed code-path checks, not LLM evaluation",
        "source_repository": "https://github.com/Entarochuan/Timely-Machine", "source_commit": COMMIT,
        "controls": ["No provider or ML execution imports; fake responses and scoring",
            "Evaluator/scorer AST definitions are unchanged; constructors are bypassed",
            "No real time, sleep, network, datasets, or external judge",
            "Per-run evaluator outputs only; downstream interactive/ML aggregation not audited",
            "General/ML checks establish grace-window eligibility, not absence of all cutoffs",
            "Scorer input checks cover the inspected methods and base dispatch, not upstream deadline enforcement",
            "No statement about effect size or published paper results"]}

    general = source.module("src/timely_eval/general.py", {"GeneralReasoningEvaluator"}, dict(scope))
    cls = general["GeneralReasoningEvaluator"]
    ev = cls.__new__(cls)
    ev.config = SimpleNamespace(max_turns=1, time_limit_multipliers=[1.0])
    ev.solver_agent = FakeAgent("<answer>4</answer>")
    ev.solver_sem = None
    ev.judge_agent = None
    FixedTimer.value = 10.5
    result = await ev._run_item_with_time_limit({"id": "toy", "question": "2+2", "answer": "4"}, 10.0)
    results["general_deadline"] = {k: result[k] for k in ("duration", "time_limit", "within_time_limit", "is_correct")}
    require(result["within_time_limit"] and result["duration"] > result["time_limit"], "General deadline check changed")

    interactive = source.module("src/timely_eval/interactive.py", {
        "InteractiveEvaluator", "_has_conclusion", "_first_int",
    }, dict(scope, JerichoToolEnvironment=FakeGame, DEFAULT_TOOL_DURATIONS={"step": 0.0}))
    cls = interactive["InteractiveEvaluator"]
    iv = cls.__new__(cls)
    iv.config = SimpleNamespace(game_path="not-used", tool_durations={"step": 0.0})
    iv.solver_agent = FakeAgent('<tool_call>{"name":"step","arguments":{"action":"score"}}</tool_call>')
    iv.sem = None
    iv.output_dir = Path("unused-output")
    FixedTimer.value = 12.0
    game = await iv._run_game(max_steps=1, time_limit=10.0)
    results["interactive_deadline"] = {k: game[k] for k in ("time_limit", "total_actural_time_duration", "final_score")}
    require(game["final_score"] == 10 and game["total_actural_time_duration"] == 12, "Late action check changed")
    interactive_text = source.read("src/timely_eval/interactive.py")
    action_at = interactive_text.index("result = await self._execute_tool(tool_call, env)")
    read_at = interactive_text.index('elapsed = float(timer.call(return_format="value"))', action_at)
    check_at = interactive_text.index("if time_limit is not None and elapsed >= 1.001 * time_limit:", read_at)
    score_at = interactive_text.index("final_score = _first_int(env.get_score())", check_at)
    require(action_at < read_at < check_at < score_at, "Interactive source order changed")
    results["interactive_static_order"] = {
        "source": "src/timely_eval/interactive.py",
        "lines": {name: interactive_text.count("\n", 0, offset) + 1 for name, offset in
                  (("execute_action", action_at), ("read_elapsed", read_at),
                   ("check_deadline", check_at), ("retain_final_score", score_at))},
        "evidence": "static source order; the separate FixedTimer check demonstrates retained late score",
    }

    ml = source.module("src/timely_eval/agentic_ml.py", {"AgenticMLEvaluator"}, dict(scope))
    cls = ml["AgenticMLEvaluator"]
    mv = cls.__new__(cls)
    mv.config = SimpleNamespace(max_turns=1, benchmark_name="stub", batch_size=1, workers=1)
    mv.solver_agent = FakeAgent("<code>pass</code>")
    mv.sem = None
    mv.task_prompt = "stub"
    mv.output_dir = Path("unused-output")
    mv._extract_code_from_response = lambda _: "pass"
    async def fake_execution(*args: Any) -> dict:
        return {"execution": SimpleNamespace(work_dir="unused"),
                "evaluation": {"is_valid_submission": True, "accuracy": 0.8}}
    mv._execute_and_evaluate = fake_execution
    FixedTimer.value = 14.0
    result = await mv._time_limited_one(multiplier=1.0, average_time=10.0)
    results["ml_deadline"] = {k: result[k] for k in ("time_limit", "duration", "best_accuracy")}
    require(result["best_accuracy"] == 0.8 and result["duration"] > result["time_limit"], "ML deadline check changed")

    rewards = {}
    base_reward_path = "rl/internbootcamp_v2/internbootcamp/src/base_reward_calculator.py"
    source.has(base_reward_path, "extract_solution = cls.extract_output(model_output)")
    source.has(base_reward_path, "judge =  cls._verify_correction(extract_solution, identity, **kwargs)")
    for filename in ("Basic_timer_reward_calculator.py", "Basic_timer_reward_calculator_orig.py"):
        source.has(RL + filename, "if last_time_call_duration <= (1.0 + 1e-3) * required_time:")
        source.has(RL + filename, "time_call = all_matches[-1].strip()")
        source.has(RL + filename, "if not last_time_call_duration == total_duration:")
        tree = ast.parse(source.read(RL + filename))
        calculator = next(node for node in tree.body if getattr(node, "name", None) == "LlmTimerRewardCalculator")
        verify = next(node for node in calculator.body if getattr(node, "name", None) == "_verify_correction")
        require([arg.arg for arg in verify.args.args] == ["cls", "extracted_output", "identity"]
                and verify.args.kwarg.arg == "kwargs", "Scorer signature changed")
        require(not any(isinstance(node, ast.Name) and node.id == "kwargs"
                        for statement in verify.body for node in ast.walk(statement)),
                "Scorer now consumes additional keyword inputs")
        reward = source.module(RL + filename, {"LlmTimerRewardCalculator"}, dict(
            re=re, math=math, json=json, mean=statistics.mean, BaseRewardCalculator=object,
            compute_score=lambda answer, expected: float(answer == expected), call_judge_model=forbidden_judge,
        ))["LlmTimerRewardCalculator"]
        identity = {"data_type": "general_reasoning", "answer": "4", "required_time": 10.0, "with_time_limit": True}

        def score_case(reads: list[float], conclusion: float) -> dict[str, Any]:
            transcript = "".join(f"<tool_response>{value:.1f} seconds.</tool_response>" for value in reads)
            transcript += f"<conclusion>total duration: {conclusion:.1f} seconds</conclusion><answer>4</answer>"
            item = reward.extract_output(transcript)
            parsed = item["reasoning_RM_extracted_infos"]
            require(parsed["time_call"] == f"{reads[-1]:.1f} seconds.", "Last-read extraction changed")
            require(parsed["time_conclusion"] == f"total duration: {conclusion:.1f} seconds", "Conclusion extraction changed")
            with contextlib.redirect_stdout(io.StringIO()):
                score = reward._verify_correction(item, identity)
            return {"tool_reads_s": reads, "conclusion_s": conclusion,
                    "parsed_last_tool_read": parsed["time_call"], "reward": score}

        cases = {"single8_match": score_case([8.0], 8.0),
                 "single20_match": score_case([20.0], 20.0),
                 "20_then8_match": score_case([20.0, 8.0], 8.0),
                 "8_then20_match": score_case([8.0, 20.0], 20.0),
                 "tool8_conclusion20": score_case([8.0], 20.0),
                 "tool20_conclusion8": score_case([20.0], 8.0)}
        require(cases["20_then8_match"]["reward"] == cases["single8_match"]["reward"]
                and cases["8_then20_match"]["reward"] == cases["single20_match"]["reward"],
                "Earlier timer reads now affect matched-conclusion reward")
        require(cases["single8_match"]["reward"] > cases["tool8_conclusion20"]["reward"]
                and math.isclose(cases["tool8_conclusion20"]["reward"], 0.5)
                and math.isclose(cases["tool20_conclusion8"]["reward"], 0.5)
                and cases["single20_match"]["reward"] > 0.0, "Reward consistency/overtime check changed")
        rewards[filename] = {"last_read_controls": {key: cases[key] for key in
                               ("single8_match", "single20_match", "20_then8_match", "8_then20_match")},
                             "conclusion_consistency_controls": {key: cases[key] for key in
                               ("tool8_conclusion20", "tool20_conclusion8")},
                             "input_scope": {"positional_inputs": ["extracted_output", "identity"],
                                             "extra_kwargs_consumed": False,
                                             "base_dispatch_source": base_reward_path}}
    results["reward_uses_transcript_timer"] = rewards

    source.has("src/timely_eval/timer.py", "elapsed = real_elapsed * self.speed_factor * self._noise()")
    source.has("src/timely_eval/timer.py", "noise_range: tuple[float, float] = (0.99, 1.01)")
    source.has("src/timely_eval/timer.py", "return random.uniform(*self.noise_range)")
    times = iter([0.0, 100.0, 100.1])
    noise_values = (1.005, 0.995)
    module_name = "_timely_audit_clock"
    timer_module = ModuleType(module_name)
    timer_module.__dict__.update(dataclass=dataclass, field=field, Literal=Literal,
                                random=random, time=SimpleNamespace(time=lambda: next(times)))
    sys.modules[module_name] = timer_module
    try:
        timer_class = source.module("src/timely_eval/timer.py", {"Timer"}, timer_module.__dict__)["Timer"]
        clock = timer_class(mode="static", speed_factor=1.0)
        require(clock.noise_range == (0.99, 1.01), "Default noise support changed")
        require(all(clock.noise_range[0] < value < clock.noise_range[1] for value in noise_values),
                "Controlled noise factors are not strictly inside upstream support")
        with patch.object(random, "uniform", side_effect=noise_values) as draw_noise:
            clock.start()
            readings = [clock.call(return_format="value"), clock.call(return_format="value")]
            require(draw_noise.call_count == 2 and all(call.args == clock.noise_range for call in draw_noise.call_args_list),
                    "Upstream _noise did not draw independently from the asserted support")
    finally:
        del sys.modules[module_name]
    results["static_clock_readings"] = readings
    results["static_clock_control"] = {"noise_range": clock.noise_range, "forced_noise_factors": noise_values,
                                       "elapsed_seconds": [100.0, 100.1], "sampling": "deterministic interior-support draws, not a frequency estimate"}
    require(readings[1] < readings[0], "Noisy clock check changed")
    results["source_sha256"] = dict(sorted(source.hashes.items()))
    results["status"] = "all deterministic assertions passed"
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Unchanged official checkout at pinned commit")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/timely-audit.json")
    args = parser.parse_args()
    results = asyncio.run(audit(Source(args.source)))
    encoded = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
