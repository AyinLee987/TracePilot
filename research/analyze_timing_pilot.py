"""Recompute redacted pilot evidence from local manifests and raw event ledgers."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--development", type=Path, required=True)
parser.add_argument("--probe", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()


def action_hash(actions):
    return hashlib.sha256(json.dumps(actions, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()


result = {"kind": "real API engineering pilot on synthetic archive tasks", "batches": []}
for label, path in [("development", args.development), ("probe", args.probe)]:
    name = path.name
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    assert summary["stop_reason"] is None
    assert summary["completed_runs"] == summary["planned_runs"]
    events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    calls = [e for e in events if e["event"] == "request_completed"]
    runs = [e for e in events if e["event"] == "run_completed"]
    assert len(calls) == summary["calls"]
    assert all(c["usage"]["state"] == "known" for c in calls)
    assert abs(sum(c["usage"]["cost_cny"] for c in calls) - summary["charged_cny"]) < 1e-8
    assert {c["response_model"] for c in calls} == {"deepseek-flash"}
    for r in runs:
        rc = [c for c in calls if c["run_id"] == r["run_id"]]
        assert all(c["started_s"] < r["effective_cutoff_s"] for c in rc)
        assert not r["fully_evidenced_success"] or (r["on_time"] and r["answer_correct"] and r["evidence_complete"])
    groups = {}
    for r in runs:
        key = f"{r['policy']}/{r['pattern']}/{'tools' if r['tools'] else 'no-tools'}"
        groups.setdefault(key, []).append(r)
    aggregate = {}
    for key, rs in groups.items():
        aggregate[key] = {
            "n": len(rs), "answer_correct_including_late": sum(r["answer_correct"] for r in rs),
            "on_time_answer_correct": sum(r["answer_correct"] and r["on_time"] for r in rs),
            "on_time_fully_evidenced_success": sum(r["fully_evidenced_success"] for r in rs),
            "status_counts": dict(collections.Counter(r["status"] for r in rs)),
            "mean_model_calls": statistics.mean(r["model_calls"] for r in rs),
            "mean_tool_calls": statistics.mean(r["tool_calls"] for r in rs),
            "mean_evidence_coverage": statistics.mean(r["evidence_coverage"] for r in rs),
            "mean_observation_duration_s": statistics.mean(r["elapsed_s"] for r in rs),
            "peak_price_estimated_cny": sum(r["charged_cny"] for r in rs),
        }
    comparisons = []
    if label == "probe":
        for seed in range(201, 209):
            for pattern in ("alternating", "grouped"):
                pair = [next(r for r in runs if r["seed"] == seed and r["pattern"] == pattern and r["policy"] == policy)
                        for policy in ("deadline-only", "countdown")]
                kinds = [[a.get("action") if a else "invalid" for a in r["actions"]] for r in pair]
                common = min(map(len, kinds))
                full_prefix = [r["actions"][:common] for r in pair]
                timely_actions = []
                for r in pair:
                    rc = [c for c in calls if c["run_id"] == r["run_id"]]
                    timely_actions.append([a for a, c in zip(r["actions"], rc, strict=True)
                                           if not c["late"]])
                timely_common = min(map(len, timely_actions))
                timely_hashes = [action_hash(actions[:timely_common]) for actions in timely_actions]
                comparisons.append({"seed": seed, "pattern": pattern,
                    "deadline_only_actions": kinds[0], "countdown_actions": kinds[1],
                    "common_prefix_action_kind_diverged": kinds[0][:common] != kinds[1][:common],
                    "common_full_action_prefix_hashes": [action_hash(actions) for actions in full_prefix],
                    "common_full_action_prefix_equal": full_prefix[0] == full_prefix[1],
                    "on_time_response_common_prefix_hashes": timely_hashes,
                    "on_time_response_common_prefix_equal": timely_hashes[0] == timely_hashes[1],
                    "fully_evidenced_success": [r["fully_evidenced_success"] for r in pair]})
    result["batches"].append({
        "label": label, "local_batch_name": name, "real_api": True, "model_requested": manifest["model"],
        "response_models": sorted({c["response_model"] for c in calls}), "python_version": manifest["python_version"],
        "runs": len(runs), "requests": len(calls), "deadline_s": manifest["deadline_s"],
        "development_gate_passed": summary["development_gate_passed"],
        "suggested_deadline_s": summary["suggested_deadline_s"],
        "input_tokens": sum(c["usage"]["input"] for c in calls),
        "output_tokens": sum(c["usage"]["output"] for c in calls),
        "cache_hit_tokens": sum(c["usage"]["cache_hit"] for c in calls),
        "peak_price_estimated_cny": summary["charged_cny"],
        "api_request_median_s": statistics.median(c["request_seconds"] for c in calls),
        "api_request_max_s": max(c["request_seconds"] for c in calls),
        "requests_completing_after_cutoff": sum(c["late"] for c in calls),
        "invalid_actions": sum(a is None for r in runs for a in r["actions"]),
        "script_sha256": manifest["script_sha256"], "protocol_sha256": manifest["protocol_sha256"],
        "tasks_sha256": manifest["tasks_sha256"],
        "raw_events_sha256": hashlib.sha256((path / "events.jsonl").read_bytes()).hexdigest(),
        "groups": aggregate, "paired_action_kind_checks": comparisons,
    })
result["limitations"] = [
    "Single model alias, 4 development tasks and 8 probe tasks; one invocation per condition",
    "Synthetic nearly fixed action chains, not a meaningful optional-verification choice",
    "E1 neither validates nor falsifies informative-latency-history hypothesis C",
    "Full common-prefix equality includes completed late responses; a separate on-time-only check is also given. Neither proves identical policies",
    "Peak pricing with planning conversion 8 CNY/USD; estimates not invoices; Claude reviews separate",
    "No claims of statistical significance, model rankings, real production delay distribution, or Timely-RL reproduction",
]
result["total_requests"] = sum(b["requests"] for b in result["batches"])
result["total_peak_price_estimated_cny"] = sum(b["peak_price_estimated_cny"] for b in result["batches"])
out = args.output
with out.open("x", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
    handle.write("\n")
print(json.dumps(result, indent=2))
