"""Offline analysis of the frozen corrected ML batch; no provider calls or replay.

One iteration is one model response, including responses without executable code.
Intent labels are conservative rule-based hypotheses, distinct from outcomes.
Raw text/code remains private; public outputs contain numeric/structural evidence.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import statistics as stats
import warnings

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local/timely-ml-corrected-paid-20261007"
OUTPUT = ROOT / "research/results/timely-ml-analysis"
MODELS = ("deepseek-flash", "deepseek-v4-pro")
TASKS = ("leaf-classification", "spaceship-titanic", "random-acts-of-pizza",
         "detecting-insults-in-social-commentary")
INTENTS = {
    "initial_solution": "构建初始方案",
    "repair_attempt": "尝试修复失败",
    "format_repair": "补充可执行代码",
    "improve_quality": "尝试提高质量",
    "reduce_runtime": "尝试降低耗时",
    "change_model": "建模器组合变化",
    "rerun_unchanged": "重复相同代码",
    "report_result": "解释或报告结果",
    "unknown": "unknown（意图不明）",
}
ALGORITHMS = {"LogisticRegression", "RandomForestClassifier", "ExtraTreesClassifier",
              "HistGradientBoostingClassifier", "GradientBoostingClassifier", "SVC",
              "LinearSVC", "LGBMClassifier", "XGBClassifier", "CatBoostClassifier",
              "KNeighborsClassifier", "GaussianNB", "MultinomialNB", "MLPClassifier",
              "LinearDiscriminantAnalysis", "QuadraticDiscriminantAnalysis"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def code_models(code):
    if not code:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    return sorted({name for node in ast.walk(tree) if isinstance(node, ast.Call)
                   for name in ([node.func.id] if isinstance(node.func, ast.Name) else
                                [node.func.attr] if isinstance(node.func, ast.Attribute) else [])
                   if name in ALGORITHMS})


def intent(response, code, previous_code, previous_outcome, turn):
    """Never reads scores, subsequent responses, or final task results."""
    # Code/comments and duplicated tool arguments do not count as self-report.
    fence = chr(96) * 3
    prose = re.sub(re.escape(fence) + r".*?" + re.escape(fence), "", response, flags=re.S)
    prose = re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", prose, flags=re.S)
    prose = re.split(r"<[^>\n]*DSML", prose, maxsplit=1)[0]
    prose = prose.split(fence, 1)[0].lower()[:1800]
    if turn == 1 and code is not None:
        return "initial_solution", "medium", ["first_response_contains_executable_candidate"]
    if turn == 1 and re.search(r"\b(?:i'll|i will|we'll|we will|let me) (?:build|create|train|implement|develop)\b", prose):
        return "initial_solution", "medium", ["response_self_report"]
    evidence = []
    flags = {
        "format_repair": bool(re.search(r"\b(?:provide (?:the )?(?:complete (?:solution )?)?code (?:properly|again)|"
                                        r"write (?:it|the code) in (?:a )?fenced python code block)\b", prose)),
        "repair_attempt": bool(re.search(r"\b(?:fix(?:ing)?|correct(?:ing)?|resolv(?:e|ing)) "
                                        r"(?:the|this|that|it|my|escaping|missing|error|code|issue)\b|修复|修正", prose)),
        "reduce_runtime": bool(re.search(r"\b(reduc(?:e|ing) (?:the )?(?:time|runtime|training)|"
                                        r"speed up|faster (?:model|approach|solution)|"
                                        r"simplif(?:y|ied) (?:the )?(?:model|approach))\b|减少耗时|加快", prose)),
        "improve_quality": bool(re.search(r"\b(improv(?:e|ing) (?:the )?(?:accuracy|performance|score|model)|"
                                         r"boost (?:the )?(?:accuracy|performance)|"
                                         r"(?:let me|i'll|i will|try to|we can|i can) (?:try to )?"
                                         r"(?:improve|enhance|boost))\b|提高准确率|提升性能", prose)),
    }
    explicit = [key for key, value in flags.items() if value]
    if len(explicit) > 1:
        return "unknown", "unknown", ["multiple_explicit_goals"]
    if explicit:
        return explicit[0], "medium", ["response_self_report"]
    if code is None:
        if re.search(r"<conclusion>|<accuracy>|\b(final result|achieved|best accuracy|"
                     r"successfully (?:created|saved|generated)|submission (?:is|has been) saved)\b", prose):
            return "report_result", "medium", ["result_reporting_language_without_executable_code"]
        return "unknown", "unknown", ["no_clear_goal"]
    if previous_outcome == "no_code":
        return "format_repair", "low", ["previous_response_unparseable", "now_contains_code"]
    if previous_code is not None and code == previous_code:
        return "rerun_unchanged", "low", ["identical_extracted_code_to_previous_execution"]
    if previous_outcome in {"execution_error", "execution_timeout", "no_submission", "scoring_error"}:
        return "repair_attempt", "low", ["previous_feedback_reports_failure", "code_changed"]
    before, after = code_models(previous_code), code_models(code)
    if before and after and before != after:
        evidence = ["different_recognized_estimator_constructors"]
        return "change_model", "low", evidence
    return "unknown", "unknown", ["changed_code_without_clear_goal"]


def error_category(execution, evaluation):
    if execution is None:
        return "no_code"
    if execution["timeout"]:
        return "execution_timeout"
    err = execution["stderr"]
    patterns = [
        ("feature_mismatch", r"features.*expect|number of features|features.*same"),
        ("nan_features", r"Input X contains (?:NaN|infinity)|contains NaN"),
        ("invalid_stratified_split", r"test_size.*number of classes"),
        ("missing_column", r"KeyError:"),
        ("unsupported_argument", r"unexpected keyword argument"),
        ("syntax_error", r"SyntaxError:|IndentationError:"),
        ("invalid_dtype", r"pandas dtypes must|bad pandas dtypes"),
        ("missing_dependency", r"ModuleNotFoundError:|libgomp.so.1: cannot"),
        ("resource_limit", r"Cannot allocate memory|can't start new thread|No space left"),
    ]
    for name, pattern in patterns:
        if re.search(pattern, err, re.I | re.S):
            return name
    if execution["returncode"] != 0:
        return "other_execution_error"
    if not execution["submission_path"]:
        return "no_submission"
    return "none" if evaluation.get("is_valid_submission") else "scoring_error"


def mean(values):
    return stats.mean(values) if values else None


def mean_ci(values, rng):
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(2000))
    return [samples[49], samples[1949]]


def segment_rows(rows):
    """Coalesce adjacent labels; continue a repair only until a scored outcome."""
    segments = []
    repair = {"repair_attempt", "format_repair"}
    for row in rows:
        previous = segments[-1] if segments else None
        same = previous and previous["run_id"] == row["run_id"]
        merge = same and ((previous["possible_intent"] == row["possible_intent"] and
                          (previous["possible_intent"] not in repair or previous["outcomes"][-1] != "scored")) or
                         (previous["possible_intent"] in repair and row["possible_intent"] in repair
                          and previous["outcomes"][-1] != "scored"))
        if not merge:
            previous = {"run_id":row["run_id"], "start_iteration":row["iteration"],
                        "end_iteration":row["iteration"], "possible_intent":row["possible_intent"],
                        "intent_confidence":row["intent_confidence"], "intent_evidence":[],
                        "subintents":[], "outcomes":[], "responses":0, "executions":0,
                        "response_latency_s":0.0, "cost_cny":"0", "best_eligible_score":0}
            segments.append(previous)
        if previous["possible_intent"] != row["possible_intent"]:
            previous["possible_intent"] = "repair_attempt"
        previous["end_iteration"] = row["iteration"]
        if row["intent_confidence"] in ("unknown", "low"):
            previous["intent_confidence"] = row["intent_confidence"]
        previous["intent_evidence"] = sorted(set(previous["intent_evidence"] + row["intent_evidence"]))
        previous["subintents"] = sorted(set(previous["subintents"] + [row["possible_intent"]]))
        previous["outcomes"].append(row["outcome"])
        previous["responses"] += 1
        previous["executions"] += row["code_sha256"] is not None
        previous["response_latency_s"] += row["response_latency_s"]
        previous["cost_cny"] = str(Decimal(previous["cost_cny"])+Decimal(row["cost_cny"]))
        previous["best_eligible_score"] = row["best_eligible_so_far"]
    require(sum(x["responses"] for x in segments) == len(rows), "segment coverage mismatch")
    return segments


def analyze(source, output):
    source, output = source.resolve(), output.resolve()
    require(source != output and source not in output.parents and output not in source.parents,
            "analysis output must be separate from frozen evidence")
    completion = read(ROOT / "research/results/timely-ml-corrected-completion.json")
    for name, wanted in completion["raw_sha256"].items():
        if name.startswith(".local/timely-ml-corrected-paid-20261007/"):
            require(sha(source / Path(name).name) == wanted, f"frozen input changed: {name}")
    plan, final = read(source / "plan.json"), read(source / "result.json")
    require(final["complete"] and final["completed"] == 384, "expected completed matrix")
    upstream = ROOT / ".local/timely-machine-audit"
    for name in ("src/timely_eval/parsing.py", "src/timely_eval/agentic_ml.py"):
        require(sha(upstream / name) == plan["upstream_files"][name], "upstream parser changed")
    spec = importlib.util.spec_from_file_location("frozen_ml_parsing", upstream / "src/timely_eval/parsing.py")
    parsing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parsing)

    def extract(response):
        code = parsing.extract_python_code(response)
        if code is not None:
            return code
        has_call, _, call, _ = parsing.extract_answer_or_tool_call(response)
        if has_call and call:
            try:
                return json.loads(call).get("arguments", {}).get("code")
            except Exception:
                return None
        return None

    requests, dispatched, settled = defaultdict(list), set(), set()
    with (source / "requests.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event["event"] == "request_dispatch":
                require(event["request_id"] not in dispatched, "duplicate dispatch")
                dispatched.add(event["request_id"])
            if event["event"] == "request_complete":
                require(event["request_id"] not in settled, "duplicate settlement")
                settled.add(event["request_id"])
                requests[event["run_id"]].append(event)
            require(event["event"] != "request_unknown", "unknown usage")
    require(dispatched == settled and len(settled) == 1034, "request closure mismatch")
    runs, iterations, failures, hashes = [], [], [], {}
    for planned in plan["rows"]:
        rid = planned["run_id"]
        directory = source / rid
        result = read(directory / "result.json")
        require(all(result[k] == v for k, v in planned.items()), f"row mismatch {rid}")
        trace = read(directory / "model-trace.json")
        ep = directory / "workspace/executions.json"
        executions = read(ep) if ep.exists() else []
        raw, calls = result["raw"], requests[rid]
        require(len(trace) == len(calls) == result["requests"], f"request alignment {rid}")
        require(len(executions) == result["executions"], f"execution count {rid}")
        hashes[rid] = {p.relative_to(directory).as_posix(): sha(p)
                       for p in (directory / "result.json", directory / "model-trace.json", ep) if p.exists()}
        timed = planned["phase"] == "timed"
        limit = raw["time_limit"] if timed else None
        evaluations = raw["collected_eval_results"] if timed else []
        ex_index, previous_code, previous_outcome = 0, None, None
        rows = []
        for i, (step, call) in enumerate(zip(trace, calls)):
            response = step["response"]
            require(response == (call["response_body"]["choices"][0]["message"]["content"] or ""),
                    f"trace/API response mismatch {rid}/{i}")
            code = extract(response)
            execution, evaluation, feedback = None, {}, ""
            if timed:
                assistant_index = 2 + 2*i
                require(raw["messages"][assistant_index]["content"] == response, "upstream message alignment")
                feedback = raw["messages"][assistant_index+1]["content"]
            elif i+1 < len(trace):
                feedback = trace[i+1]["messages"][-1]["content"]
            if code is not None:
                require(isinstance(code, str), "non-string executable candidate")
                execution = executions[ex_index]
                code_path = directory / f"workspace/code-{ex_index+1:02}.py"
                require(code_path.read_text(encoding="utf-8") == code, f"extracted code mismatch {rid}/{i}")
                hashes[rid][code_path.relative_to(directory).as_posix()] = sha(code_path)
                if timed:
                    evaluation = evaluations[ex_index]
                elif i == len(trace)-1:
                    evaluation = raw["evaluation"]
                else:
                    # Calibration returns immediately on a valid submission.
                    evaluation = {"is_valid_submission": False,
                                  "reason": feedback.split("\n")[0].removeprefix("Execution/evaluation failed: ")}
                ex_index += 1
            if not timed and i == len(trace)-1:
                evaluation = raw["evaluation"]
            elapsed = evaluation.get("current_duration")
            precision = "exact" if elapsed is not None else None
            if elapsed is None:
                match = re.search(r"You have spent ([\d.]+) seconds", feedback)
                if match:
                    elapsed, precision = float(match.group(1)), "rounded_0.01s"
            if code is None:
                outcome = "no_code"
            elif execution["timeout"]:
                outcome = "execution_timeout"
            elif execution["returncode"] != 0:
                outcome = "execution_error"
            elif not execution["submission_path"]:
                outcome = "no_submission"
            elif not evaluation.get("is_valid_submission"):
                outcome = "scoring_error"
            else:
                outcome = "scored"
            scored = outcome == "scored"
            eligible = scored and (not timed or elapsed <= 1.5*limit)
            label, confidence, evidence = intent(response, code, previous_code, previous_outcome, i+1)
            old_models, new_models = code_models(previous_code), code_models(code)
            row = {**planned, "iteration":i+1, "possible_intent":label, "intent_confidence":confidence,
                   "intent_evidence":evidence, "outcome":outcome,
                   "error_category":error_category(execution, evaluation),
                   "response_latency_s":step["latency_s"], "elapsed_s":elapsed, "elapsed_precision":precision,
                   "accuracy":evaluation.get("accuracy") if scored else None, "eligible":eligible,
                   "nominal_eligible":scored and (not timed or elapsed <= limit),
                   "budget_s":limit, "acceptance_cutoff_s":1.5*limit if timed else None,
                   "code_sha256":hashlib.sha256(code.encode()).hexdigest() if code is not None else None,
                   "same_code_as_previous_execution":code is not None and previous_code is not None and code == previous_code,
                   "previous_outcome":previous_outcome,
                   "observed_action":"no_executable_code" if code is None else
                       "first_executable_code" if previous_code is None else
                       "same_code" if code == previous_code else "changed_code",
                   "recognized_estimators":new_models, "previous_estimators":old_models,
                   "prompt_tokens":call["usage"]["prompt_tokens"], "output_tokens":call["usage"]["completion_tokens"],
                   "cost_cny":call["provider_usage_peak_estimate_cny"],
                   "finish_reason":call["response_body"]["choices"][0]["finish_reason"],
                   "feedback_is_generic_exit_code":bool(re.search(r"Code execution failed with return code -?\d+", feedback)),
                   "has_next_response":i+1 < len(trace)}
            rows.append(row)
            if code is not None:
                previous_code = code
            previous_outcome = outcome
        require(ex_index == len(executions), f"unaligned execution {rid}")
        if timed:
            require(ex_index == len(evaluations), f"unaligned evaluation {rid}")
        accepted = [r for r in rows if r["eligible"]]
        recomputed = max((r["accuracy"] for r in accepted), default=0)
        require(bool(accepted) == result["valid"] and abs(recomputed-result["score"]) < 1e-10,
                f"score/validity reconstruction mismatch {rid}")
        model_s = sum(r["response_latency_s"] for r in rows)
        require(model_s <= result["duration"] + .03, f"model time exceeds episode {rid}")
        cost = sum((Decimal(r["cost_cny"]) for r in rows), Decimal(0))
        best_so_far, best_nominal = 0.0, 0.0
        for row in rows:
            if row["eligible"]:
                best_so_far = max(best_so_far, row["accuracy"])
            if row["nominal_eligible"]:
                best_nominal = max(best_nominal, row["accuracy"])
            row["best_eligible_so_far"] = best_so_far
        first = rows[0]["accuracy"] if rows[0]["eligible"] else 0
        category = None
        if not result["valid"]:
            if any(r["outcome"] == "scored" for r in rows):
                category = "valid_only_after_cutoff"
            elif any(r["outcome"] == "execution_timeout" for r in rows):
                category = "execution_timeout"
            elif any(r["outcome"] == "execution_error" for r in rows):
                category = "code_or_data_error"
            elif not executions:
                category = "no_executable_code"
            elif any(r["outcome"] == "scoring_error" for r in rows):
                category = "scoring_error"
            else:
                category = "no_submission_file"
        run = {**planned, "valid":result["valid"], "score":result["score"],
               "duration_s":result["duration"], "model_s":model_s,
               "other_s":max(0, result["duration"]-model_s),
               "budget_s":limit, "cost_cny":str(cost), "iterations":len(rows), "executions":len(executions),
               "prompt_tokens":sum(r["prompt_tokens"] for r in rows),
               "output_tokens":sum(r["output_tokens"] for r in rows),
               "first_response_score":first, "later_gain":result["score"]-first,
               "recovered_after_first_response":not rows[0]["eligible"] and result["valid"],
               "strict_nominal_posthoc_score":best_nominal, "failure_category":category}
        if category:
            failures.append({**run, "error_categories":sorted({r["error_category"] for r in rows if r["error_category"] != "none"}),
                             "outcomes":[r["outcome"] for r in rows]})
        runs.append(run)
        iterations.extend(rows)
    require(len(runs) == 384 and len(iterations) == 1034, "incomplete analysis")
    require(sum(Decimal(r["cost_cny"]) for r in runs) == Decimal(final["batch_cost_cny"]), "cost mismatch")
    rng, groups = random.Random(20261007), []
    for task in TASKS:
        for model in MODELS:
            for multiplier in range(6):
                cell = [r for r in runs if r["task"] == task and r["model"] == model and r["multiplier"] == multiplier]
                require(len(cell) == 8, "cell denominator changed")
                groups.append({"task":task, "model":model, "multiplier":multiplier, "n":8,
                    "valid":sum(r["valid"] for r in cell), "mean_score":mean([r["score"] for r in cell]),
                    "score_ci95":mean_ci([r["score"] for r in cell], rng),
                    "mean_duration_s":mean([r["duration_s"] for r in cell]),
                    "median_duration_s":stats.median(r["duration_s"] for r in cell),
                    "mean_model_s":mean([r["model_s"] for r in cell]),
                    "mean_other_s":mean([r["other_s"] for r in cell]),
                    "mean_cost_cny":float(sum(Decimal(r["cost_cny"]) for r in cell)/8),
                    "mean_iterations":mean([r["iterations"] for r in cell]),
                    "budget_s":cell[0]["budget_s"],
                    "first_response_score":mean([r["first_response_score"] for r in cell]),
                    "strict_nominal_posthoc_score":mean([r["strict_nominal_posthoc_score"] for r in cell])})
    timed_runs = [r for r in runs if r["phase"] == "timed"]
    timed_steps = [r for r in iterations if r["phase"] == "timed"]
    segments = segment_rows(iterations)
    by_task = []
    for task in TASKS:
        for model in MODELS:
            cell = [r for r in timed_runs if r["task"] == task and r["model"] == model]
            by_task.append({"task":task, "model":model, "n":len(cell), "valid":sum(r["valid"] for r in cell),
                           "mean_score":mean([r["score"] for r in cell]),
                           "valid_only_mean_score":mean([r["score"] for r in cell if r["valid"]]),
                           "first_response_score":mean([r["first_response_score"] for r in cell]),
                           "mean_duration_s":mean([r["duration_s"] for r in cell]),
                           "mean_model_s":mean([r["model_s"] for r in cell]),
                           "mean_other_s":mean([r["other_s"] for r in cell]),
                           "mean_cost_cny":float(sum(Decimal(r["cost_cny"]) for r in cell)/len(cell)),
                           "mean_iterations":mean([r["iterations"] for r in cell]),
                           "calibration_tau_s":final["calibration"][task+"/"+model]})
    summary = {"episodes":len(runs), "responses":len(iterations), "executions":sum(r["executions"] for r in runs),
        "batch_cost_cny":final["batch_cost_cny"], "task_models":by_task, "groups":groups,
        "failure_counts":dict(Counter(r["failure_category"] for r in failures)),
        "intent_counts_all":dict(Counter(r["possible_intent"] for r in iterations)),
        "segments":len(segments), "multi_response_segments":sum(r["responses"] > 1 for r in segments),
        "segment_intent_counts":dict(Counter(r["possible_intent"] for r in segments)),
        "intent_counts_timed":{m:dict(Counter(r["possible_intent"] for r in timed_steps if r["model"] == m)) for m in MODELS},
        "outcomes_all":dict(Counter(r["outcome"] for r in iterations)),
        "timed_recovered_after_first_response":sum(r["recovered_after_first_response"] for r in timed_runs),
        "timed_improved_after_first_response":sum(r["later_gain"] > 1e-10 for r in timed_runs),
        "timed_positive_score_reduced_by_nominal_cutoff":sum(r["score"] > r["strict_nominal_posthoc_score"]+1e-10 for r in timed_runs),
        "timed_zero_under_nominal_cutoff_but_official_valid":sum(r["valid"] and r["strict_nominal_posthoc_score"] == 0 for r in timed_runs),
        "failure_feedback_with_next_response":sum(r["feedback_is_generic_exit_code"] and r["has_next_response"] for r in iterations),
        "same_code_responses":sum(r["same_code_as_previous_execution"] for r in iterations),
        "timed_model_diagnostics":{m:{
            "later_gain_episodes":sum(r["later_gain"] > 1e-10 for r in timed_runs if r["model"]==m),
            "recovered_episodes":sum(r["recovered_after_first_response"] for r in timed_runs if r["model"]==m),
            "no_code_responses":sum(r["outcome"]=="no_code" for r in timed_steps if r["model"]==m),
            "responses":sum(r["model"]==m for r in timed_steps),
            "report_then_format_or_repeat":sum(
                a["possible_intent"]=="report_result" and b["possible_intent"] in {"format_repair","rerun_unchanged"}
                for a,b in zip(timed_steps,timed_steps[1:]) if a["run_id"]==b["run_id"] and a["model"]==m)
        } for m in MODELS},
        "length_limited_responses":sum(r["finish_reason"] == "length" for r in iterations),
        "notes":{"score":"Original private-test accuracy; invalid=0; all planned repetitions retained.",
                 "ci":"Percentile bootstrap of episode scores, 2000 resamples, seed=20261007; n=8 per cell. Descriptive uncertainty within these fixed tasks only.",
                 "time":"Windows host-clock episode duration. Request interval starts before the per-episode semaphore (serial and uncontended here), and includes SDK, admission, network and provider time. Episode time excludes waiting in the batch queue. Other time includes execution, startup, grading, I/O, clock bridging and scheduling/resource contention; not pure training time. Guest execution durations are excluded.",
                 "intent":"Rule-based possible intent, never mental-state ground truth. Uses only current response/code and previous feedback; not outcomes or future scores. Unknown is retained.",
                 "segments":"Retrospective display groups use execution outcomes to mark repair boundaries; not online features. Intent counts measure rule hits, not true intent prevalence.",
                 "budget":"Model-specific calibration. Equal multipliers are not equal deadlines. Nominal-cutoff sensitivity is retrospective on unchanged trajectories.",
                 "iteration":"One model response. No-code responses still count. Some calibration no-code elapsed times are unrecorded (null)."}}
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("summary.json",summary),("runs.json",runs),("iterations.json",iterations),
                       ("segments.json",segments),("failures.json",failures)):
        write(output / name, data)
    with (output / "iterations.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f,fieldnames=list(iterations[0]))
        writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in iterations)
    provenance = {"schema":1, "provider_calls":0, "replay":False, "source_batch":source.name,
                  "source_plan_sha256":sha(source/"plan.json"), "source_result_sha256":sha(source/"result.json"),
                  "source_requests_sha256":sha(source/"requests.jsonl"), "analysis_sha256":sha(Path(__file__)),
                  "inputs":hashes, "intent_labels":INTENTS,
                  "validation":{"aligned_responses":1034, "reconstructed_episode_scores":384,
                                "planned_cells":48,"episodes_per_cell":8,"cost_reconciled":True}}
    write(output/"provenance.json",provenance)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("groups","task_models","notes")},ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    analyze(args.source, args.output)
