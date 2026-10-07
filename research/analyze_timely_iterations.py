"""Offline per-response analysis of the frozen official 384-episode batch.

No model calls, no replay, no changes to source evidence. Exact score changes
come from environment observations; repeated text is not identical game state.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def observation(text):
    match = re.search(r"The response is:\s*(.*?)\nThe step reward is:", text, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def format_flags(response, finish):
    flags = []
    if finish == "length":
        flags.append("output_limit")
    if response.count("<tool_call>") != response.count("</tool_call>"):
        flags.append("unbalanced_tool_tags")
    if "<step>" in response:
        flags.append("step_tag_dialect")
    if "DSML" in response:
        flags.append("dsml_dialect")
    return flags


def analyze(source: Path, output: Path):
    require(source.resolve() != output.resolve() and source.resolve() not in output.resolve().parents,
            "output must not mutate the source batch")
    result, plan = read(source / "async-result.json"), read(source / "plan.json")
    require(result["complete"] and result["completed"] == 384, "incomplete batch")
    require(len(result["records"]) == len({r["run_id"] for r in result["records"]}) == 384,
            "expected 384 unique records")
    require({r["run_id"] for r in result["records"]} == {r["run_id"] for r in plan["rows"]}, "plan IDs differ")
    runs, iterations, input_hashes = [], [], {}
    category_counts, flag_counts = Counter(), Counter()
    request_events, tool_counts = Counter(), Counter()
    for record in sorted(result["records"], key=lambda r: r["run_id"]):
        run_id = record["run_id"]
        directory = source / run_id
        paths = {"environment": directory / "environment.json", "requests": directory / "requests.jsonl",
                 "trajectory": directory / f"official/trajectories_max_steps_{record['steps']}.jsonl"}
        input_hashes[run_id] = {name: sha(path) for name, path in paths.items()}
        envs = read(paths["environment"])["environments"]
        require(len(envs) == 1, f"{run_id}: environment count")
        env = envs[0]
        trajectories = [json.loads(line) for line in paths["trajectory"].read_text(encoding="utf-8").splitlines()]
        require(len(trajectories) == 1, f"{run_id}: trajectory count")
        trajectory = trajectories[0]
        completed, run_events = [], Counter()
        with paths["requests"].open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                run_events[event["event"]] += 1
                if event["event"] == "request_complete":
                    completed.append(event)
        require(set(run_events) <= {"batch_open", "batch_close", "request_dispatch", "request_complete"},
                f"{run_id}: unsupported request event; do not silently exclude failures")
        require(run_events["request_dispatch"] == run_events["request_complete"], f"{run_id}: unsettled request")
        request_events.update(run_events)
        responses = trajectory["all_responses"]
        steps = trajectory["steps"]
        require(len(completed) == len(responses), f"{run_id}: response count")
        step_index, op_index = 0, 0
        initial_score = env["initial"]["score"]
        current_score = initial_score
        start = completed[0]["start_monotonic_s"]
        previous_obs, seen_obs = None, set()
        rows, error_streaks, streak = [], [], []
        for index, (response, request) in enumerate(zip(responses, completed), 1):
            choice = request["response_body"]["choices"][0]
            require(choice["message"]["content"] == response, f"{run_id}: response identity")
            conclusion = bool(re.search(r"<conclusion>\s*(.*?)\s*</conclusion>", response, re.S))
            step = None if conclusion else steps[step_index]
            if step is not None:
                require(step["agent_response"] == response and step["step"] == step_index, f"{run_id}: step mapping")
                step_index += 1
            tools = step["tool_results"] if step else []
            calls = step["tool_calls"] if step else []
            require(len(tools) <= 1, f"{run_id}: unexpected multiple execution")
            tool = tools[0]["tool"] if tools else None
            require(tool in {None, "step", "get_available_actions", "end_game", "get_score", "get_max_score"},
                    f"{run_id}: unknown tool; classification needs explicit handling")
            tool_counts[tool or "no_tool_result"] += 1
            arguments = tools[0].get("arguments", {}) if tools else {}
            action = arguments.get("action", "")
            argument_error = tool == "step" and not action
            before, after, tool_s = current_score, current_score, None
            score_source = "carried_no_environment_mutation"
            feedback = tools[0]["result"] if tools else ""
            if tool in {"step", "get_available_actions", "end_game"} and not argument_error:
                operation = env["operations"][op_index]
                op_index += 1
                require(operation["tool"] == tool and operation["exception_type"] is None, f"{run_id}: operation mapping")
                before, after = operation["before"]["score"], operation["after"]["score"]
                require(before == current_score, f"{run_id}: unobserved score change")
                require(after - before == operation["score_delta"], f"{run_id}: delta mismatch")
                tool_s = operation["duration_s"]
                score_source = "observed_environment"
            current_score = after
            obs = observation(feedback) if tool == "step" else None
            same_previous = bool(obs and previous_obs == obs)
            seen_before = bool(obs and obs in seen_obs)
            if obs:
                previous_obs = obs
                seen_obs.add(obs)
            delta = after - before
            category = ("conclusion" if conclusion else "no_tool" if not tools else
                        "argument_error" if argument_error else
                        "score_gain" if delta > 0 else "score_loss" if delta < 0 else
                        "query" if tool in {"get_available_actions", "get_score", "get_max_score"} else
                        "end_game" if tool == "end_game" else
                        "repeated_observation" if same_previous else "other_action")
            usage = request["response_body"]["usage"]
            flags = format_flags(response, choice.get("finish_reason"))
            row = {"run_id": run_id, "iteration": index, "recorded_step": step_index if step else None,
                   "category": category, "tool": tool, "action": str(action)[:160],
                   "parsed_calls": len(calls), "executed_calls": len(tools),
                   "discarded_calls": max(0, len(calls) - len(tools)), "format_flags": flags,
                   "score_before": before, "score_after": after, "score_delta": delta,
                   "score_source": score_source, "same_observation_as_previous_action": same_previous,
                   "observation_seen_before": seen_before,
                   "observation_hash": hashlib.sha256(obs.encode()).hexdigest()[:16] if obs else None,
                   "http_s": request["end_monotonic_s"] - request["start_monotonic_s"],
                   "http_start_s": request["start_monotonic_s"] - start,
                   "http_end_s": request["end_monotonic_s"] - start,
                   "observed_tool_s": tool_s, "virtual_tool_s": tools[0]["duration"] if tools else 0,
                   "logical_elapsed_s": step.get("cumulative_actural_time_duration") if step else None,
                   "input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"],
                   "finish_reason": choice.get("finish_reason"),
                   "feedback_summary": ("No valid tool call; error feedback" if category == "no_tool" else
                       "Missing action argument; environment not called" if argument_error else
                       "Model-declared conclusion" if conclusion else
                       f"Environment score {before} -> {after}" if delta else
                       "Same observation text as previous action; state identity unknown" if same_previous else
                       "Information query" if category == "query" else "Action executed; immediate score unchanged")}
            rows.append(row)
            category_counts[category] += 1
            flag_counts.update(flags)
            if category == "no_tool":
                streak.append(row)
            elif streak:
                error_streaks.append({"start": streak[0]["iteration"], "length": len(streak),
                    "open_at_run_end": False,
                    "recovered_next": bool(tools) and not argument_error, "following_score_delta": delta if tools else None,
                    "http_s": sum(r["http_s"] for r in streak)})
                streak = []
        if streak:
            error_streaks.append({"start": streak[0]["iteration"], "length": len(streak),
                                 "open_at_run_end": True,
                                 "recovered_next": False, "following_score_delta": None,
                                 "http_s": sum(r["http_s"] for r in streak)})
        require(step_index == len(steps) and op_index == len(env["operations"]), f"{run_id}: unmatched observations")
        require(current_score == env["final"]["score"] == record["game_state"]["signed_score"], f"{run_id}: final score")
        require(sum(r["score_delta"] for r in rows) == current_score - initial_score, f"{run_id}: score conservation")
        require(sum(r["category"] == "no_tool" for r in rows) == record["counts"]["no_tool_steps"], f"{run_id}: no-tool count")
        run = {k: record[k] for k in ("run_id", "game", "model", "mode", "steps", "repeat", "wall_s", "logical_s", "clock_consistent", "cost_cny")}
        run.update(initial_score=initial_score, final_score=current_score, net_gain=current_score-initial_score,
                   max_score=env["initial"]["max_score"], victory=env["final"]["victory"],
                   scheduler="chunk-six" if int(run_id.split("-")[-1]) <= 256 else "continuous-six",
                   requests=len(rows), recorded_steps=len(steps), categories=dict(Counter(r["category"] for r in rows)),
                   discarded_calls=sum(r["discarded_calls"] for r in rows),
                   http_s=sum(r["http_s"] for r in rows),
                   no_tool_http_s=sum(r["http_s"] for r in rows if r["category"] == "no_tool"),
                   observed_tool_s=sum(r["observed_tool_s"] or 0 for r in rows),
                   no_tool_output_tokens=sum(r["output_tokens"] for r in rows if r["category"] == "no_tool"),
                   output_tokens=sum(r["output_tokens"] for r in rows), error_streaks=error_streaks,
                   time_limit_logical_s=trajectory["time_limit"])
        runs.append(run)
        iterations.extend(rows)
    summary = {"schema": 1, "episodes": len(runs), "requests": len(iterations),
               "recorded_steps": sum(r["recorded_steps"] for r in runs), "categories_all": dict(category_counts),
               "format_flags_all": dict(flag_counts), "api_calls_for_analysis": 0,
               "request_event_counts": dict(request_events), "tool_result_counts": dict(tool_counts),
               "initial_scores": {g: sorted({r["initial_score"] for r in runs if r["game"] == g})
                                  for g in sorted({r["game"] for r in runs})},
               "limitations": ["Descriptive, not causal; eight runs per condition.",
                   "No full game-state snapshots; repeated observation is a proxy only.",
                   "Zero immediate reward is not proof of useless exploration.",
                   "Score carried across no-call/query/conclusion responses is not a fresh measurement.",
                   "HTTP durations exclude tool execution; virtual delays are not wall-clock costs.",
                   "Within-game repetition does not establish transfer to unseen tasks.",
                   "Existing model-specific budgets, scheduler phases and clock flags remain."]}
    by_run = {r["run_id"]: r for r in runs}
    timed_rows = [r for r in iterations if by_run[r["run_id"]]["mode"] == "timed"]
    summary["timed"] = {}
    for model in plan["models"]:
        rr = [r for r in runs if r["mode"] == "timed" and r["model"] == model]
        ii = [r for r in timed_rows if by_run[r["run_id"]]["model"] == model]
        streaks = [s for r in rr for s in r["error_streaks"]]
        summary["timed"][model] = {"runs": len(rr), "recorded_steps": sum(r["recorded_steps"] for r in rr),
            "responses": len(ii), "categories": dict(Counter(r["category"] for r in ii)),
            "http_s": sum(r["http_s"] for r in ii),
            "no_tool_http_s": sum(r["http_s"] for r in ii if r["category"] == "no_tool"),
            "observed_tool_s": sum(r["observed_tool_s"] or 0 for r in ii),
            "no_tool_length_responses": sum(r["category"] == "no_tool" and r["finish_reason"] == "length" for r in ii),
            "discarded_calls": sum(r["discarded_calls"] for r in ii),
            "multi_call_responses": sum(r["parsed_calls"] > 1 for r in ii),
            "error_streaks": len(streaks), "next_call_recovered": sum(s["recovered_next"] for s in streaks),
            "error_streaks_open_at_run_end": sum(s["open_at_run_end"] for s in streaks),
            "closed_error_streaks": sum(not s["open_at_run_end"] for s in streaks),
            "recovery_immediate_gain": sum(s["recovered_next"] and s["following_score_delta"] > 0 for s in streaks),
            "zero_net_gain_runs": sum(r["net_gain"] == 0 for r in rr),
            "negative_net_gain_runs": sum(r["net_gain"] < 0 for r in rr),
            "runs_with_score_loss": sum(r["categories"].get("score_loss", 0) > 0 for r in rr)}
    summary["groups"] = []
    for game in plan["games"]:
        for model in plan["models"]:
            for budget in plan["timed_steps"]:
                rr = [r for r in runs if (r["game"], r["model"], r["mode"], r["steps"]) == (game, model, "timed", budget)]
                require(len(rr) == 8, "condition denominator changed")
                summary["groups"].append({"game": game, "model": model, "budget": budget, "n": len(rr),
                    "mean_net_gain": statistics.mean(r["net_gain"] for r in rr),
                    "net_gain_sd": statistics.stdev(r["net_gain"] for r in rr),
                    "mean_final_score": statistics.mean(r["final_score"] for r in rr),
                    "zero_gain_runs": sum(r["net_gain"] == 0 for r in rr)})
    cases = []
    def choose(reason, candidates, key):
        if candidates:
            selected = sorted(candidates, key=key)[0]
            cases.append({"reason": reason, "run_id": selected["run_id"], "selection": "post-hoc illustrative; not representative"})
    timed_runs = [r for r in runs if r["mode"] == "timed"]
    choose("previously_random_example", [r for r in timed_runs if r["run_id"] == "episode-234"], lambda r: r["run_id"])
    choose("actual_victory", [r for r in timed_runs if r["victory"]], lambda r: r["run_id"])
    choose("largest_score_loss_count", [r for r in timed_runs if r["categories"].get("score_loss")], lambda r: (-r["categories"]["score_loss"], r["run_id"]))
    choose("most_no_tool_responses", timed_runs, lambda r: (-r["categories"].get("no_tool", 0), r["run_id"]))
    choose("most_discarded_calls", timed_runs, lambda r: (-r["discarded_calls"], r["run_id"]))
    choose("most_adjacent_repeated_observations", timed_runs, lambda r: (-r["categories"].get("repeated_observation", 0), r["run_id"]))
    summary["cases"] = cases
    write(output / "summary.json", summary)
    write(output / "runs.json", runs)
    with (output / "iterations.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in iterations:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(output / "provenance.json", {"source_plan_sha256": sha(source / "plan.json"),
        "source_result_sha256": sha(source / "async-result.json"), "analysis_sha256": sha(Path(__file__)),
        "inputs": input_hashes, "checks": ["384 planned unique runs", "request/response/step exact joins",
        "environment operations in order", "no unobserved score changes; final signed scores match",
        "no-tool totals match", "40 timed conditions each n=8", "known request events only; all dispatched requests completed",
        "known tool names only"], "request_event_counts": dict(request_events), "api_calls": 0})
    print(json.dumps({k: summary[k] for k in ("episodes", "requests", "recorded_steps", "categories_all", "initial_scores", "timed", "cases")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".local/timely-official-paid-20261006")
    parser.add_argument("--output", type=Path, default=ROOT / "research/results/timely-iterations")
    args = parser.parse_args()
    analyze(args.source, args.output)
