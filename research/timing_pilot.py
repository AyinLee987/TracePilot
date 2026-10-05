"""Small serial wall-clock pilot. Fake dry-runs never contact a provider or sleep.

Deadlines/safety caps stop new dispatch. The 60s HTTP timeout applies to network
operations, not total response duration; an in-flight request can drain past either
cap. Reported CNY is a bounded peak-price planning estimate, not a provider invoice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
MODEL = "deepseek-flash"
URL = "https://api.deepseek.com/chat/completions"
INPUT_BOUND = 25_024
OUTPUT_BOUND = 256
CONTEXT_CHARS = 24_000
SAFETY_SECONDS = 180.0
RATES = {"input_miss": 0.30, "input_hit": 0.006, "output": 1.20}
CNY_PER_USD = 8.0  # Conservative planning conversion, not an exchange-rate claim.
RESERVATION = (INPUT_BOUND * RATES["input_miss"] + OUTPUT_BOUND * RATES["output"]) / 1e6 * CNY_PER_USD
SYSTEM = """You solve synthetic archive tasks. Return exactly one JSON object per turn.
Available actions:
{"action":"search","query":"entity identifier"} searches record titles only.
{"action":"fetch","id":"record identifier"} retrieves the full record.
{"action":"answer","value":"terminal value","evidence":["record identifiers"]}
Follow successor relations to a terminal value. Cite every fetched record on the chain.
Only information returned by tools is evidence. Never invent identifiers or values.
You have at most 12 model calls. Return an answer when sufficient evidence is available.
"""
NO_TOOL_SYSTEM = """Solve the synthetic archive question without tools or external data.
Return one JSON object: {"action":"answer","value":"your answer or UNKNOWN","evidence":[]}.
"""


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2)
        handle.write("\n")


def task_for(seed):
    rng = random.Random(seed)
    used = set()

    def opaque(prefix):
        while True:
            value = prefix + f"{rng.getrandbits(64):016x}"
            if value not in used:
                used.add(value)
                return value

    chain_length = rng.choice((2, 3))
    entities = [opaque("e_") for _ in range(chain_length)]
    identifiers = [opaque("r_") for _ in entities]
    value = opaque("v_")
    records = []
    for index, entity in enumerate(entities):
        content = {"entity": entity}
        content.update({"successor": entities[index + 1]} if index + 1 < chain_length else {"value": value})
        records.append({"id": identifiers[index], "title": "Entity " + entity, "content": content})
    for _ in range(12):
        entity = opaque("e_")
        records.append({"id": opaque("r_"), "title": "Entity " + entity,
                        "content": {"entity": entity, "value": opaque("v_")}})
    rng.shuffle(records)
    return {"seed": seed, "question": f"Starting at entity {entities[0]}, follow successor links until a terminal value. Return that value and cite every chain record.",
            "records": records, "gold_value": value, "gold_evidence": identifiers,
            "phase": random.Random(f"latency-phase:{seed}").randrange(12)}


def delays_for(task, pattern):
    if pattern == "none":
        return [0.0] * 12
    values = [0.15, 2.85] * 6 if pattern == "alternating" else [0.15] * 6 + [2.85] * 6
    phase = task["phase"]
    return values[phase:] + values[:phase]


def tool_result(task, action):
    if action["action"] == "search":
        terms = action["query"].lower().split()
        return {"results": [{"id": record["id"], "title": record["title"]}
                            for record in task["records"] if all(term in record["title"].lower() for term in terms)][:8]}
    record = next((record for record in task["records"] if record["id"] == action["id"]), None)
    return record if record else {"error": "unknown_record"}


def parse_action(content, tools_enabled):
    try:
        action = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(action, dict):
        return None
    kind = action.get("action")
    if kind == "answer":
        valid = (set(action) == {"action", "value", "evidence"} and isinstance(action["value"], str)
                 and isinstance(action["evidence"], list) and all(isinstance(item, str) for item in action["evidence"]))
    elif kind in ("search", "fetch") and tools_enabled:
        field = "query" if kind == "search" else "id"
        valid = set(action) == {"action", field} and isinstance(action[field], str) and 0 < len(action[field]) <= 256
    else:
        valid = False
    return action if valid else None


def usage_record(response):
    source = response.get("usage") or {}
    fields = {"input": "prompt_tokens", "output": "completion_tokens", "cache_hit": "prompt_cache_hit_tokens", "cache_miss": "prompt_cache_miss_tokens"}
    usage = {key: source.get(field) for key, field in fields.items()}
    known = all(isinstance(number, int) and not isinstance(number, bool) and number >= 0 for number in usage.values())
    if known and usage["cache_hit"] + usage["cache_miss"] != usage["input"]:
        known = False
    if not known:
        return {**usage, "state": "unknown", "cost_cny": None}
    cost = (usage["cache_hit"] * RATES["input_hit"] + usage["cache_miss"] * RATES["input_miss"] + usage["output"] * RATES["output"]) / 1e6 * CNY_PER_USD
    return {**usage, "state": "known", "cost_cny": cost}


class Batch:
    """Own the sole HTTP client and append-only request ledger for a serial batch."""

    def __init__(self, directory, budget, max_calls, fake, api_key=None):
        self.directory, self.budget, self.max_calls, self.fake = directory, budget, max_calls, fake
        self.calls, self.charged, self.stop_reason = 0, 0.0, None
        self.handle = (directory / "events.jsonl").open("x", encoding="utf-8")
        self.client = None
        if not fake:
            import httpx
            self.client = httpx.Client(timeout=60.0, transport=httpx.HTTPTransport(retries=0), trust_env=False)
        self.api_key = api_key

    def log(self, kind, **fields):
        self.handle.write(canonical({"event": kind, "utc": datetime.now(timezone.utc).isoformat(), **fields}) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self):
        if self.client is not None:
            self.client.close()
        self.handle.close()

    def request(self, payload, run_id, step, now, cutoff, fake_response):
        if self.stop_reason:
            return None
        if self.calls >= self.max_calls or self.charged + RESERVATION > self.budget + 1e-12:
            self.stop_reason = "call_cap" if self.calls >= self.max_calls else "budget_cap"
            return None
        self.log("request_prepared", run_id=run_id, step=step, request=payload, reservation_cny=RESERVATION)
        # Check after synchronous persistence, immediately before dispatch.
        if now() >= cutoff:
            self.log("request_not_dispatched", run_id=run_id, step=step, reason="cutoff")
            return None
        started = now()
        self.calls += 1
        self.charged += RESERVATION
        try:
            if self.fake:
                response = fake_response()
            else:
                reply = self.client.post(URL, headers={"Authorization": "Bearer " + self.api_key}, json=payload)
                reply.raise_for_status()
                response = reply.json()
                if not isinstance(response, dict):
                    raise ValueError("invalid_response")
            completed = now()
            usage = usage_record(response)
            if usage["state"] == "known":
                self.charged += usage["cost_cny"] - RESERVATION
                if usage["input"] > INPUT_BOUND or usage["output"] > OUTPUT_BOUND:
                    self.stop_reason = "usage_exceeds_reserved_bound"
            else:
                self.stop_reason = "unknown_usage"
            self.log("request_completed", run_id=run_id, step=step, started_s=started, completed_s=completed,
                     request_seconds=completed - started, late=completed >= cutoff, usage=usage,
                     charged_cny=self.charged, response_model=response.get("model"), response=response)
            return response
        except Exception as error:
            self.stop_reason = "api_error"
            # No exception message/body/headers: these may contain credentials or provider details.
            self.log("request_failed", run_id=run_id, step=step, started_s=started, completed_s=now(),
                     error_type=type(error).__name__, usage={"state": "unknown", "input": None, "output": None,
                     "cache_hit": None, "cache_miss": None}, charged_cny=self.charged, reservation_retained_cny=RESERVATION)
            return None


def run_one(batch, task, condition, deadline):
    run_id = f"s{task['seed']}-{condition['policy']}-{condition['pattern']}-{'tools' if condition['tools'] else 'no-tools'}"
    real_start, fake_elapsed = time.perf_counter(), [0.0]

    def now():
        return fake_elapsed[0] if batch.fake else time.perf_counter() - real_start

    cutoff = min(deadline if deadline is not None else math.inf, SAFETY_SECONDS)
    cutoff_reason = "deadline" if deadline is not None and deadline <= SAFETY_SECONDS else "safety_cap"
    waits, exposed, fetched, seen = delays_for(task, condition["pattern"]), [], set(), set()
    calls, tool_calls, answer, answer_time = 0, 0, None, None
    status, actions = "call_limit", []
    start_charge = batch.charged
    initial = task["question"] + (f" Your total time limit is {deadline:.3f} seconds." if deadline is not None else "")
    messages = [{"role": "system", "content": SYSTEM if condition["tools"] else NO_TOOL_SYSTEM},
                {"role": "user", "content": initial}]
    batch.log("run_started", run_id=run_id, seed=task["seed"], condition=condition, deadline_s=deadline,
              safety_cap_s=SAFETY_SECONDS, delays=waits, synthetic=batch.fake)

    for step in range(1, (12 if condition["tools"] else 1) + 1):
        if batch.stop_reason:
            status = batch.stop_reason
            break
        if now() >= cutoff:
            status = cutoff_reason
            break
        outgoing = [dict(message) for message in messages]
        suffix = f"\nStep {step}. Status: active."
        if condition["policy"] == "countdown" and deadline is not None:
            suffix += f" Remaining wall-clock time: {max(0.0, deadline - now()):.3f} seconds."
        outgoing[-1]["content"] += suffix
        if len(canonical(outgoing)) > CONTEXT_CHARS:
            status = "context_cap"
            break
        payload = {"model": MODEL, "messages": outgoing, "temperature": 0, "max_tokens": OUTPUT_BOUND,
                   "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "stream": False}

        def fake_response():
            fake_elapsed[0] += 0.05
            remaining = [identifier for identifier in task["gold_evidence"] if identifier not in fetched]
            if not condition["tools"]:
                action = {"action": "answer", "value": "UNKNOWN", "evidence": []}
            elif not remaining:
                action = {"action": "answer", "value": task["gold_value"], "evidence": list(task["gold_evidence"])}
            elif remaining[0] in seen:
                action = {"action": "fetch", "id": remaining[0]}
            else:
                record = next(record for record in task["records"] if record["id"] == remaining[0])
                action = {"action": "search", "query": record["content"]["entity"]}
            content = canonical(action)
            inputs, outputs = math.ceil(len(canonical(outgoing)) / 4), math.ceil(len(content) / 4)
            return {"model": "FAKE-NOT-A-MODEL", "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": inputs, "completion_tokens": outputs,
                              "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": inputs}}

        before_calls = batch.calls
        response = batch.request(payload, run_id, step, now, cutoff, fake_response)
        calls += batch.calls - before_calls
        if response is None:
            status = batch.stop_reason or cutoff_reason
            break
        try:
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("invalid_content")
        except (KeyError, IndexError, TypeError, ValueError):
            status = batch.stop_reason or "invalid_response"
            batch.stop_reason = batch.stop_reason or "invalid_response"
            break
        action = parse_action(content, condition["tools"])
        actions.append(action)
        if action and action["action"] == "answer":
            answer, answer_time = action, now()
            status = "answered" if answer_time < cutoff else cutoff_reason
            break
        if now() >= cutoff:
            status = cutoff_reason
            break
        if batch.stop_reason:
            status = batch.stop_reason
            break
        messages.append({"role": "assistant", "content": content})
        if action is None:
            messages.append({"role": "user", "content": "Invalid action. Return one JSON action matching the specified schema."})
            continue
        tool_start = now()
        batch.log("tool_prepared", run_id=run_id, step=step, action=action, at_s=tool_start)
        if now() >= cutoff:
            status = cutoff_reason
            break
        computation_start = now()
        observation = tool_result(task, action)
        computation_end = now()
        delay = waits[tool_calls]
        tool_calls += 1
        sleep_for = max(0.0, min(delay, cutoff - now()))
        sleep_started = now()
        if batch.fake:
            fake_elapsed[0] += sleep_for
        elif sleep_for:
            time.sleep(sleep_for)
        sleep_end = now()
        delivered = sleep_end < cutoff and sleep_for >= delay
        exposed.append({"planned_s": delay, "sleep_s": sleep_end - sleep_started, "delivered": delivered})
        batch.log("tool_completed", run_id=run_id, step=step, tool_index=tool_calls - 1, action=action,
                  compute_seconds=computation_end - computation_start, planned_delay_s=delay,
                  sleep_seconds=sleep_end - sleep_started, completed_s=sleep_end, delivered=delivered,
                  observation=observation if delivered else None)
        if not delivered:
            status = cutoff_reason
            break
        if action["action"] == "fetch" and "error" not in observation:
            fetched.add(action["id"])
        if action["action"] == "search":
            seen.update(item["id"] for item in observation["results"])
        messages.append({"role": "user", "content": "Tool result: " + canonical(observation)})

    elapsed = now()
    gold = set(task["gold_evidence"])
    cited = set(answer["evidence"]) if answer else set()
    answer_correct = answer is not None and answer["value"] == task["gold_value"]
    evidence_complete = gold.issubset(fetched) and gold.issubset(cited)
    on_time = answer_time is not None and answer_time < cutoff
    result = {"run_id": run_id, "seed": task["seed"], **condition, "synthetic": batch.fake, "status": status,
              "deadline_s": deadline, "effective_cutoff_s": cutoff, "answer": answer, "answer_correct": answer_correct,
              "evidence_complete": evidence_complete, "fully_evidenced_success": answer_correct and evidence_complete and on_time,
              "on_time": on_time, "fetched": sorted(fetched), "cited": sorted(cited),
              "evidence_coverage": len(gold.intersection(fetched)) / len(gold), "actions": actions,
              "model_calls": calls, "tool_calls": tool_calls, "answer_latency_s": answer_time,
              "elapsed_s": elapsed, "drain_s": max(0.0, elapsed - cutoff), "delays_exposed": exposed,
              "charged_cny": batch.charged - start_charge, "batch_stop_reason": batch.stop_reason}
    write_json(batch.directory / (run_id + ".json"), result)
    batch.log("run_completed", **result)
    return result


def analyze(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("s[0-9]*.json"))]
    groups = {}
    for run in runs:
        key = f"{run['policy']}/{run['pattern']}/{'tools' if run['tools'] else 'no-tools'}"
        group = groups.setdefault(key, {"n": 0, "answer_correct": 0, "fully_evidenced_success": 0, "on_time": 0,
                                       "model_calls": 0, "tool_calls": 0, "charged_cny": 0.0})
        for field in group:
            group[field] += 1 if field == "n" else run[field]
    successful = [run for run in runs if run["tools"] and run["fully_evidenced_success"]]
    no_tools = [run for run in runs if not run["tools"]]
    tools_runs = [run for run in runs if run["tools"]]
    complete_dev = manifest["mode"] == "dev" and len(tools_runs) == 4 and len(no_tools) == 4
    dev_gate = complete_dev and len(successful) >= 3 and not all(run["answer_correct"] for run in no_tools)
    suggested = math.ceil(statistics.median(run["answer_latency_s"] for run in successful)
                          + 1.5 * statistics.median(run["tool_calls"] for run in successful)) if dev_gate else None
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    completed_batch = next((event for event in reversed(events) if event["event"] == "batch_completed"), None)
    summary = {"synthetic": manifest["synthetic"], "mode": manifest["mode"], "planned_runs": len(manifest["run_order"]),
               "batch_finalized": completed_batch is not None,
               "stop_reason": completed_batch["stop_reason"] if completed_batch else "incomplete_ledger_inspect_before_resuming",
               "calls": completed_batch["calls"] if completed_batch else None,
               "charged_cny": completed_batch["charged_cny"] if completed_batch else None,
               "cost_basis": "bounded_peak_price_planning_estimate_not_invoice",
               "completed_runs": len(runs), "groups": groups, "development_gate_passed": dev_gate,
               "suggested_deadline_s": suggested,
               "task_paired": [{"seed": seed, "runs": [{key: run[key] for key in ("policy", "pattern", "tools", "status", "answer_correct", "fully_evidenced_success", "tool_calls", "actions")}
                                                       for run in runs if run["seed"] == seed]}
                               for seed in sorted({run["seed"] for run in runs})]}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-run", "dev", "probe", "analyze"))
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source", type=Path, help="Existing batch directory for read-only analysis")
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--budget-cny", type=float, default=20.0)
    parser.add_argument("--max-calls", type=int, default=400)
    args = parser.parse_args()
    if args.mode == "analyze":
        if args.source is None:
            parser.error("analyze requires --source")
        print(json.dumps(analyze(args.source.resolve()), indent=2))
        return
    if not math.isfinite(args.budget_cny) or not 0 < args.budget_cny <= 200:
        parser.error("budget must be positive and at most CNY 200")
    if not 0 < args.max_calls <= 400:
        parser.error("max-calls must be between 1 and 400")
    if args.deadline is not None and (not math.isfinite(args.deadline) or not 0 < args.deadline <= SAFETY_SECONDS):
        parser.error("deadline must be positive and at most 180 seconds")
    if args.mode == "probe" and args.deadline is None:
        parser.error("probe requires a development-frozen --deadline")
    if args.mode == "dev" and args.deadline is not None:
        parser.error("dev has no research deadline; omit --deadline")
    fake = args.mode == "dry-run"
    if not fake and not args.execute_paid:
        parser.error("dev/probe require explicit --execute-paid")
    api_key = None
    if not fake:
        if args.env_file:
            from dotenv import dotenv_values
            api_key = dotenv_values(args.env_file).get("DEEPSEEK_API_KEY")
        else:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not isinstance(api_key, str) or not api_key.strip():
            parser.error("DEEPSEEK_API_KEY is missing")
    directory = (args.output or (LOCAL / "timing-pilot" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.mode + "-" + uuid4().hex[:8]))).resolve()
    if not directory.is_relative_to(LOCAL.resolve()) or directory == LOCAL.resolve():
        parser.error("output must be a new directory inside this worktree's .local")
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir(exist_ok=False)
    except FileExistsError:
        parser.error("output already exists; select a unique new directory")
    deadline = args.deadline if args.deadline is not None else (6.0 if fake else None)
    seeds = range(101, 105) if args.mode == "dev" else range(201, 209)
    tasks = [task_for(seed) for seed in seeds]
    order, shuffle = [], random.Random(20261005)
    for task in tasks:
        conditions = ([{"policy": "deadline-only", "pattern": "none", "tools": enabled} for enabled in (True, False)]
                      if args.mode == "dev" else [{"policy": policy, "pattern": pattern, "tools": True}
                                                 for policy in ("deadline-only", "countdown") for pattern in ("alternating", "grouped")])
        shuffle.shuffle(conditions)
        order.extend({"seed": task["seed"], **condition} for condition in conditions)
    protocol = ROOT / "docs" / "research" / "pilot-protocol.md"
    manifest = {"schema": 1, "mode": args.mode, "synthetic": fake, "created_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version,
                "model": MODEL, "url": URL, "max_retries": 0, "network_timeout_s": 60, "deadline_s": deadline,
                "timeout_semantics": "network_operation_timeout_not_total_duration; cutoff_stops_dispatch_not_inflight_drain",
                "cost_basis": "bounded_peak_price_planning_estimate_not_invoice",
                "safety_cap_s": SAFETY_SECONDS, "budget_cny": args.budget_cny, "max_calls": args.max_calls,
                "max_run_calls": 12, "max_output_tokens": OUTPUT_BOUND, "max_context_ascii_chars": CONTEXT_CHARS,
                "reserved_input_tokens": INPUT_BOUND, "price_usd_per_million": RATES, "planning_cny_per_usd": CNY_PER_USD,
                "reservation_per_call_cny": RESERVATION, "prompts": {"tools": SYSTEM, "no_tools": NO_TOOL_SYSTEM},
                "tasks": tasks, "tasks_sha256": digest(tasks), "run_order": order,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest()}
    write_json(directory / "manifest.json", manifest)
    batch = Batch(directory, args.budget_cny, args.max_calls, fake, api_key)
    try:
        for item in order:
            if batch.stop_reason:
                break
            task = next(task for task in tasks if task["seed"] == item["seed"])
            run_one(batch, task, {key: value for key, value in item.items() if key != "seed"}, deadline)
        batch.log("batch_completed", calls=batch.calls, charged_cny=batch.charged, stop_reason=batch.stop_reason)
    finally:
        batch.close()
    summary = analyze(directory)
    summary.update({"calls": batch.calls, "charged_cny": batch.charged, "stop_reason": batch.stop_reason})
    write_json(directory / "summary.json", summary)
    print(json.dumps({"output": str(directory), "synthetic": fake, "completed_runs": summary["completed_runs"],
                      "calls": batch.calls, "charged_cny": batch.charged, "stop_reason": batch.stop_reason,
                      "suggested_deadline_s": summary["suggested_deadline_s"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted; inspect the persisted ledger before another paid batch.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"Pilot stopped ({type(error).__name__}); no exception body logged.", file=sys.stderr)
        raise SystemExit(1)
