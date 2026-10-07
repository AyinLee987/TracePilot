"""Original Timely ML loop, reconstructed original tasks, existing study budget.

prepare/activate are inert; run needs --execute-paid and an explicit env file.
No automatic resume: interrupted runs retain evidence and their reservation.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import time

import timely_batch as batch
import timely_study as study
from prepare_timely_ml import TASKS, LOCAL as DATA, SOURCE
from timely_ml_sandbox import ACTIVE, Sandbox, command, execute_in_context
from timely_transport import BudgetedTimelyTransport, run_context
import timely_ml_clock as host_clock

ROOT = batch.ROOT
PARENT = ROOT / ".local/timely-official-paid-20261006"
DEST = ROOT / ".local/timely-ml-paid-20261007"
CAP = Decimal("50")
UPSTREAM = "e13af2b8c98d799857ace789ebcfdfd4ea6c2985"
FILES = ("timely_ml.py", "timely_ml_sandbox.py", "prepare_timely_ml.py", "timely_transport.py",
         "timely_batch.py", "timely_study.py", "timely_official.py", "timely_ml_e2e.py", "timely_ml_clock.py", "docker/TimelyML.Dockerfile")


def rows():
    return [{"run_id":f"ml-{i:03}", "phase":phase, "task":task, "model":model,
             "repeat":repeat, "multiplier":multiplier}
        for i, (phase, multiplier, repeat, task, model) in enumerate(
            ((phase, multiplier, repeat, task, model)
             for phase, multipliers in (("speed", (0,)), ("timed", (1,2,3,4,5)))
             for repeat in range(1,9) for multiplier in multipliers
             for task in TASKS for model in batch.MODELS), 1)]


def read(path):
    return batch.read_json(path)


def identity(plan):
    batch.require(plan["clock"] == "Windows time.perf_counter via local read-only bridge", "ML host clock required")
    host_clock.configure()
    batch.require(host_clock.now() > 0, "ML host clock unavailable")
    batch.require(plan["rows"] == rows() and plan["workers"] == 2 and plan["batch_cap_cny"] == "50"
                  and plan["max_calls"] == 1088 and plan["stage"] == study.ML_STAGE, "ML protocol changed")
    for name, sha in plan["sources"].items():
        batch.require(batch.file_hash(ROOT / "research" / name) == sha, "ML source changed")
    batch.require(batch.file_hash(DATA / "manifest.json") == plan["data_manifest_sha256"], "ML data manifest changed")
    for task in read(DATA / "manifest.json")["tasks"]:
        directory = DATA / task["task"]
        batch.require(not directory.is_symlink() and not any(p.is_symlink() for p in directory.rglob("*")), "ML data symlink")
        batch.require({p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()} == set(task["files"]),
                      "ML unexpected data file")
        for name, sha in task["files"].items():
            path = DATA / task["task"] / name
            batch.require(not path.is_symlink() and batch.file_hash(path) == sha, "ML data changed")
    for name, sha in plan["upstream_files"].items():
        batch.require(batch.file_hash(SOURCE / name) == sha, "upstream source changed")
    image = subprocess.check_output(["docker", "image", "inspect", plan["image"], "--format", "{{.Id}}"], text=True).strip()
    batch.require(image == plan["image"], "ML image missing")


def parent_basis():
    from timely_official import inspect
    parent_plan = read(PARENT / "plan.json")
    event = study._assert_active_record(PARENT, parent_plan)
    result = read(PARENT / "async-result.json")
    batch.require(event["stage_name"] == study.OFFICIAL_STAGE and result["complete"] is True
                  and result["completed"] == result["planned"] == 384 and result["stop_reason"] is None
                  and batch.money(result["held_cny"]) == 0, "ML requires settled original games")
    actual = []
    for row in parent_plan["rows"]:
        tau = result["calibration"][f"{row['game']}/{row['model']}"] if row["mode"] == "timed" else None
        actual.append(inspect(PARENT, parent_plan, row, tau))
    cost = sum((batch.money(r["cost_cny"]) for r in actual), Decimal(0))
    known = batch.money(parent_plan["study_opening"]["known_cny"]) + cost
    batch.require(cost == batch.money(result["batch_cost_cny"]) and known == batch.money(result["study_known_cny"])
                  and not parent_plan["study_opening"]["liabilities"] and known + CAP <= 200, "ML carryover mismatch")
    archive = ROOT / ".local/timely-ml-history-20261007/timely_study.py"
    batch.require(batch.file_hash(archive) == event["module_sha256"], "ML previous study bytes missing")
    return {"root":str(PARENT), "files":study._files(PARENT), "opening":{"known_cny":str(known), "liabilities":[]},
            "previous_head_sha256":study.head()["sha256"], "historical_study":{"path":str(archive), "sha256":batch.file_hash(archive)}}


def prepare():
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(PARENT):
        batch.require(not DEST.exists(), "ML destination exists; cannot overwrite")
        seal = parent_basis()
        batch.require(subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip() == UPSTREAM,
                      "wrong upstream revision")
        image = subprocess.check_output(["docker", "image", "inspect", "tracepilot-timely-ml:20261007", "--format", "{{.Id}}"], text=True).strip()
        registry, _ = study._registry()
        plan = {"paid":True, "stage":study.ML_STAGE, "cap_cny":"200", "batch_cap_cny":"50", "max_calls":1088,
            "clock":"Windows time.perf_counter via local read-only bridge",
            "workers":2, "rows":rows(), "image":image, "upstream_commit":UPSTREAM,
            "data_manifest_sha256":batch.file_hash(DATA / "manifest.json"),
            "upstream_files":{p.relative_to(SOURCE).as_posix():batch.file_hash(p) for p in sorted((SOURCE / "src").rglob("*.py"))},
            "sources":{name:batch.file_hash(ROOT / "research" / name) for name in FILES},
            "study_opening":seal["opening"], "imports":registry["imports"],
            "settings":{"temperature":0.7, "max_tokens":2048, "thinking":"disabled", "max_turns":3,
                        "execution_timeout_s":180, "http_timeout_s":60, "retries":0},
            "protocol_sha256":batch.file_hash(ROOT / "docs/research/timely-ml.md")}
        identity(plan)
        DEST.mkdir()
        batch.write_new(DEST / "parent-seal.json", seal)
        batch.write_new(DEST / "plan.json", plan)
        return {"status":"prepared_no_model_calls", "plan_sha256":batch.digest(plan), "opening":seal["opening"]}


def activate(review: Path):
    review = review.resolve()
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(PARENT), batch.exclusive(DEST):
        plan, seal = read(DEST / "plan.json"), read(DEST / "parent-seal.json")
        identity(plan)
        batch.require(seal == parent_basis() and set(study._files(DEST)) == {"parent-seal.json", "plan.json"}, "ML preparation changed")
        evidence = read(review)
        batch.require(evidence.get("approved") is True and evidence.get("actual_model") == "claude-opus-5-5"
                      and evidence.get("sources") == plan["sources"] and evidence.get("protocol_sha256") == plan["protocol_sha256"],
                      "ML completed review does not bind exact sources")
        batch.require(batch.file_hash(Path(evidence["raw_review_path"])) == evidence["raw_review_sha256"], "ML raw review changed")
        current = study.head()
        payload = {"schema":1, "seq":current["count"], "previous_sha256":current["sha256"],
            "kind":"advance-timely-ml", "stage_name":study.ML_STAGE, "parent_root":str(PARENT), "root":str(DEST),
            "plan_sha256":batch.digest(plan), "plan_file_sha256":batch.file_hash(DEST / "plan.json"),
            "parent_seal_sha256":batch.digest(seal), "opening":seal["opening"],
            "module_sha256":plan["sources"]["timely_study.py"], "review":{"path":str(review), "sha256":batch.file_hash(review)},
            "utc":datetime.now(timezone.utc).isoformat()}
        study._publish({**payload, "sha256":batch.digest(payload)})
        return {"status":"activated_no_model_calls", "opening":seal["opening"]}


def upstream():
    sys.path.insert(0, str(SOURCE / "src"))
    import timely_eval.agentic_ml as ml
    # Install once, before any concurrent episode; per-episode state is a ContextVar.
    ml.run_python_code_in_isolation = execute_in_context
    host_clock.configure()
    ml.Timer = host_clock.HostTimer
    return ml


class InfrastructureError(RuntimeError):
    pass


async def episode(root, plan, row, client, key, tau=None, accounting=None):
    import timely_eval.agentic_ml as ml
    info = TASKS[row["task"]]
    directory = root / row["run_id"]
    directory.mkdir(exist_ok=False)
    sandbox = Sandbox(plan["image"], DATA / row["task"] / "public", directory / "workspace")
    config = ml.AgenticMLConfig(benchmark_name=row["task"], data_dir=DATA / row["task"],
        private_test_path=DATA / row["task"] / "private/test.csv", prompt_template=DATA / row["task"] / "prompt.txt",
        output_dir=directory / "official", id_column=info["id"], is_binary=info["label"] is not None,
        binary_label_column=info["label"], batch_size=1, workers=1, max_turns=3, execution_timeout=180,
        solver=ml.ChatModelConfig(model=row["model"], api_base="https://api.deepseek.com", api_key=key,
            max_tokens=2048, temperature=0.7, extra_params={"stream":False,"extra_body":{"thinking":{"type":"disabled"}}}))
    evaluator = ml.AgenticMLEvaluator(config)
    await evaluator.solver_agent.client.close()
    evaluator.solver_agent.client = client
    evaluator.solver_agent.retries = 1
    generate = evaluator.solver_agent.generate_response
    trace = []
    async def recorded(messages, **kwargs):
        start = host_clock.now()
        response = await generate(messages, **kwargs)
        trace.append({"messages":json.loads(json.dumps(messages)), "response":response, "latency_s":host_clock.now()-start})
        (directory / "model-trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        state = accounting() if accounting else {}
        if state.get("stop_reason") or response == "Error: failed to generate response after 1 attempts.":
            raise InfrastructureError(state.get("stop_reason") or "provider_response_failed")
        return response
    evaluator.solver_agent.generate_response = recorded
    start_wall, start_mono, start_host = time.time(), time.perf_counter(), host_clock.now()
    token = ACTIVE.set(sandbox)
    try:
        with run_context(run_id=row["run_id"], task_id=row["task"], phase=row["phase"], model=row["model"],
                         repeat=row["repeat"], deadline_s=row["multiplier"]*tau if tau else None):
            if row["phase"] == "speed":
                response, duration, execution, evaluation = await evaluator._speed_test_one()
                raw = {"response":response, "duration":duration, "execution":execution, "evaluation":evaluation}
                valid = bool(evaluation.get("is_valid_submission")) and "accuracy" in evaluation
                score = float(evaluation.get("accuracy", 0)) if valid else 0
            else:
                raw = await evaluator._time_limited_one(row["multiplier"], tau)
                duration = raw["duration"]
                valid = raw["best_accuracy"] != "None"
                score = float(raw["best_accuracy"]) if valid else 0
        wall, mono = time.time()-start_wall, time.perf_counter()-start_mono
        result = {**row, "status":"evaluated", "valid":valid, "score":score, "duration":duration, "wall_s":wall, "monotonic_s":mono,
                  "host_elapsed_s":host_clock.now()-start_host,
                  "clock_gap_s":wall-mono, "requests":len(trace), "executions":len(sandbox.records), "raw":raw}
        batch.write_new(directory / "result.json", result)
        return result
    finally:
        try:
            await asyncio.shield(sandbox.close())
        finally:
            ACTIVE.reset(token)


async def execute(plan, key, *, root=DEST, inner=None):
    import httpx
    from openai import AsyncOpenAI
    upstream()
    transport = BudgetedTimelyTransport(log_path=root / "requests.jsonl", batch_budget_cny=CAP, max_calls=1088, inner=inner)
    client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com", max_retries=0,
        http_client=httpx.AsyncClient(transport=transport, timeout=60, follow_redirects=False), timeout=60)
    results, calibration = [], {}
    stop, cleanup_uncertain = None, False
    lag = {"samples":0,"max_s":0.0,"sum_s":0.0}
    async def monitor():
        while True:
            started = time.perf_counter()
            await asyncio.sleep(0.1)
            delay = max(0.0,time.perf_counter()-started-0.1)
            lag["samples"] += 1
            lag["max_s"] = max(lag["max_s"],delay)
            lag["sum_s"] += delay
    monitor_task = asyncio.create_task(monitor())
    started_wall, started_mono = time.time(), time.perf_counter()
    try:
        for phase in ("speed", "timed"):
            queue = asyncio.Queue()
            for row in plan["rows"]:
                if row["phase"] == phase:
                    queue.put_nowait(row)
            async def worker():
                nonlocal stop, cleanup_uncertain
                while not queue.empty() and stop is None:
                    if transport.snapshot()["stop_reason"]:
                        stop = transport.snapshot()["stop_reason"]
                        return
                    row = queue.get_nowait()
                    tau = calibration.get(row["task"] + "/" + row["model"])
                    if phase == "timed" and not tau:
                        results.append({**row,"status":"missing_no_calibration","valid":False,"score":None})
                        continue
                    try:
                        result = await episode(root, plan, row, client, key, tau, accounting=transport.snapshot)
                        results.append(result)
                        print(json.dumps({"completed":len(results), "planned":384, "run_id":row["run_id"],
                            "phase":phase, "valid":result["valid"], "score":result["score"],
                            "duration":result["duration"], "cny":transport.snapshot()["spent_estimate_cny"]}), flush=True)
                    except asyncio.CancelledError:
                        directory=root / row["run_id"]
                        trace=directory / "model-trace.json"
                        executions=directory / "workspace/executions.json"
                        results.append({**row,"status":"censored_interrupted","valid":False,"score":None,
                            "responses_recorded":len(read(trace)) if trace.exists() else 0,
                            "executions_recorded":len(read(executions)) if executions.exists() else 0})
                        raise
                    except Exception as exc:
                        stop = type(exc).__name__
                        cleanup_uncertain |= isinstance(exc, batch.ProcessCleanupError)
                        results.append({**row,"status":"censored_infrastructure","valid":False,"score":None,"error_type":stop})
            async with asyncio.TaskGroup() as group:
                for _ in range(2):
                    group.create_task(worker())
            if phase == "speed":
                for task in TASKS:
                    for model in batch.MODELS:
                        cell = [r for r in results if r["task"] == task and r["model"] == model]
                        samples = [r for r in cell if r["valid"] and r["duration"] > 0]
                        complete_cell = len(cell)==8 and all(r["status"]=="evaluated" for r in cell)
                        calibration[task + "/" + model] = sum(r["duration"] for r in samples)/len(samples) if samples and complete_cell else None
                batch.write_new(root / "calibration.json", {"partial":bool(stop),"values":calibration})
            if stop:
                break
    except BaseException as exc:
        stop = type(exc).__name__
        cleanup_uncertain = True
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task,return_exceptions=True)
        try:
            await client.close()
        except BaseException:
            cleanup_uncertain = True
            stop = stop or "client_close_failed"
    try:
        rc, containers, _, _ = await command("docker","ps","-a","--filter","label=tracepilot.experiment=timely-ml","--format","{{.Names}}")
        if rc != 0 or containers.strip():
            cleanup_uncertain = True
            stop = stop or "container_cleanup_unverified"
    except BaseException:
        cleanup_uncertain = True
        stop = stop or "container_scan_failed"
    account = transport.snapshot()
    unknown = account["unknown_calls"] or account["active_calls"] or cleanup_uncertain
    completed = sum(r["status"]=="evaluated" for r in results)
    done = {r["run_id"] for r in results}
    results.extend({**row,"status":"not_run_after_stop","valid":False,"score":None} for row in plan["rows"] if row["run_id"] not in done)
    report = {"paid":inner is None, "planned":len(plan["rows"]), "completed":completed,
        "terminal_rows":len(results), "complete":completed==len(plan["rows"]) and stop is None and account["stop_reason"] is None,
        "protocol_complete":stop is None and account["stop_reason"] is None,
        "stop_reason":stop or account["stop_reason"], "accounting":account, "calibration":calibration,
        "batch_cost_cny":account["spent_estimate_cny"], "held_cny":str(max(Decimal(0), CAP-batch.money(account["spent_estimate_cny"]))) if unknown else "0",
        "study_known_cny":str(batch.money(plan["study_opening"]["known_cny"])+batch.money(account["spent_estimate_cny"])),
        "wall_s":time.time()-started_wall, "monotonic_s":time.perf_counter()-started_mono,
        "event_loop_lag":lag,
        "host_clock_reads":dict(host_clock.STATS),
        "records":[{k:v for k,v in row.items() if k != "raw"} for row in results]}
    batch.write_new(root / "result.json", report)
    if cleanup_uncertain:
        raise batch.ProcessCleanupError("ML interrupted or cleanup uncertain; reservation and locks retained")
    return {k:v for k,v in report.items() if k != "records"}


def run(env_file):
    from dotenv import dotenv_values
    key = dotenv_values(env_file).get("DEEPSEEK_API_KEY")
    batch.require(isinstance(key,str) and bool(key.strip()), "ML API credential missing")
    with batch.exclusive(batch.PAID_STUDY_ROOT), batch.exclusive(DEST):
        plan = read(DEST / "plan.json")
        study.assert_active(DEST, plan)
        identity(plan)
        batch.require(not any((DEST / name).exists() for name in ("reservation.json", "requests.jsonl", "result.json")), "ML cannot repeat")
        batch.require(batch.money(plan["study_opening"]["known_cny"])+CAP <= 200 and not plan["study_opening"]["liabilities"], "ML cap does not fit")
        batch.write_new(DEST / "reservation.json", {"cap_cny":"50", "plan_sha256":batch.digest(plan), "utc":datetime.now(timezone.utc).isoformat()})
        return asyncio.run(execute(plan,key))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "activate", "run"))
    parser.add_argument("--review", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
    elif args.action == "activate":
        batch.require(args.review is not None, "review required")
        result = activate(args.review)
    else:
        batch.require(args.execute_paid and args.env_file and args.env_file.is_file(), "explicit paid flag and credential file required")
        result = run(args.env_file)
    print(json.dumps(result, indent=2))
    return int(result.get("complete") is False)


if __name__ == "__main__":
    raise SystemExit(main())
