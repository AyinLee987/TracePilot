"""Pinned mini-SWE-agent smoke; fake by default, explicit --live after review.

Only synthetic fixtures enter a disposable, network-disabled Docker container.
The official DefaultAgent loop is unchanged. A fixed-provider Model adapter and
DockerEnvironment subclass supply bounded calls, event timing and Windows cleanup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/oss/mini"
VERSION = "2.4.6"
COMMIT = "a83fcae82d2a08f0ee0c688f9d137b3566c097f8"
IMAGE = "python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_CALLS, MAX_OUTPUT, MAX_INPUT_BYTES = 8, 1024, 15360
INPUT_RESERVE = MAX_INPUT_BYTES + 1024
RATES = {"input_miss": 0.30, "input_hit": 0.006, "output": 1.20}
CNY_PER_USD = 8.0  # Conservative planning conversion, not an exchange-rate claim.
CALL_RESERVE = (INPUT_RESERVE * RATES["input_miss"] + MAX_OUTPUT * RATES["output"]) / 1e6 * CNY_PER_USD
assert MAX_CALLS * CALL_RESERVE <= 2.0

SYSTEM = """You repair a small Python function inside /work in a disposable Linux container.
Reply with exactly one bash command block per turn. Commands run in separate shells.
Read and edit tags.py. The external acceptance checker is an adapter action, not a shell executable.
To run it, reply with a bash block containing exactly `validate` and nothing else.
Never combine validate with cd, &&, pipes, or other commands. The environment starts in /work.
When finished, run: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
Do not install dependencies. You have at most 8 model calls. Keep changes small.
"""
CORRECT = """def normalize_tags(tags):
    result = []
    seen = set()
    for tag in tags:
        value = tag.strip().lower()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
"""
CHECKER = """import importlib.util, json
spec = importlib.util.spec_from_file_location('candidate', '/work/tags.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [([], []), ([' A ', 'a', ' B ', '', '  '], ['a', 'b']),
         (['z', 'A', 'z', 'b', 'a'], ['z', 'a', 'b']),
         (['  X\\t', '\\n', 'Y', 'x'], ['x', 'y']),
         (['Straße', 'STRASSE', 'straße'], ['straße', 'strasse'])]
for original, expected in cases:
    before = list(original)
    actual = module.normalize_tags(original)
    assert actual == expected and type(actual) is list
    assert original == before and actual is not original
print(json.dumps({'passed': True, 'cases': len(cases)}))
"""


def safe_process_env(include_key: bool = False) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    if include_key:
        env["DEEPSEEK_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    return env


def http_worker() -> None:
    """One HTTP attempt; the parent owns a hard 45-second process deadline."""
    import httpx
    payload = json.load(sys.stdin)
    try:
        with httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(retries=0), trust_env=False) as client:
            with client.stream("POST", URL, json=payload, headers={
                "Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]
            }) as response:
                if response.status_code != 200:
                    print(json.dumps({"error": "http_error", "status": response.status_code}))
                    return
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 131072:
                        raise ValueError("response_size_limit")
                data = json.loads(content)
                choice = data["choices"][0]
                print(json.dumps({"content": choice["message"].get("content"),
                                  "usage": data.get("usage"), "model": data.get("model"),
                                  "finish_reason": choice.get("finish_reason")}))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))  # Never echo headers/body/exception text.


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run paid calls only after runner review")
    args = parser.parse_args()
    if args.live and not os.environ.get("DEEPSEEK_API_KEY"):
        parser.error("DEEPSEEK_API_KEY must be supplied by the parent process")
    run_dir = LOCAL / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = str(run_dir / "empty-config")
    os.environ["MSWEA_SILENT_STARTUP"] = "1"
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.exceptions import Submitted

    assert importlib.metadata.version("mini-swe-agent") == VERSION
    agent_source = Path(sys.modules[DefaultAgent.__module__].__file__).read_bytes()
    assert hashlib.sha256(agent_source).hexdigest() == "e8ef8aa365942d739c2ec5cb0879f60f377d2dc2de8ec670aaedf3bafb45a4c2"
    logging.getLogger("minisweagent").disabled = True
    quiet_logger = logging.getLogger("mini-smoke-environment")
    quiet_logger.disabled = True
    events: list[dict] = []

    def event(kind: str, **fields) -> None:
        record = {"event": kind, "at_seconds": time.perf_counter() - started,
                  "utc": datetime.now(timezone.utc).isoformat(), **fields}
        events.append(record)
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    class TracedDocker(DockerEnvironment):
        def _start_container(self):
            self.container_id = "tracepilot-mini-" + uuid4().hex[:12]
            command = ["docker", "run", "-d", "--name", self.container_id, "-w", "/work",
                       *self.config.run_args, self.config.image, "sleep", self.config.container_timeout]
            try:
                subprocess.run(command, capture_output=True, timeout=30, check=True, env=safe_process_env())
            except Exception:
                try:
                    self.cleanup()
                except Exception:
                    event("startup_cleanup_unconfirmed")
                raise RuntimeError("container_start_failed") from None

        def get_template_vars(self, **kwargs):
            return {"cwd": "/work", **kwargs}

        def cleanup(self):
            if getattr(self, "container_id", None):
                container_id = self.container_id
                try:
                    result = subprocess.run(["docker", "rm", "-f", container_id], capture_output=True,
                                            timeout=15, env=safe_process_env())
                    if result.returncode:
                        raise RuntimeError("container_cleanup_failed")
                except Exception:
                    event("cleanup_failed", owned_container_id=container_id)
                    raise
                self.container_id = None

        def __del__(self):
            pass  # main/failure paths own cleanup; no unmeasured destructor work.

        def execute(self, action: dict, cwd: str = "", *, phase="tool", **kwargs):
            command = action.get("command", "")
            if command == "validate":
                command = "python -I -S -c " + shlex.quote(CHECKER)
            if not isinstance(command, str) or len(command.encode()) > 16384:
                raise RuntimeError("tool_command_size_limit")
            output_path = "/tmp/output-" + uuid4().hex
            wrapped = ("timeout --signal=KILL 10 bash -lc " + shlex.quote(command)
                       + " > " + output_path + " 2>&1; status=$?; head -c 8192 "
                       + output_path + "; rm -f " + output_path + "; exit $status")
            before = time.perf_counter()
            event("tool_start", phase=phase)
            status = None
            try:
                # Same DockerEnvironment contract, with an explicit credential-free process environment.
                process = subprocess.run(["docker", "exec", "-w", "/work", self.container_id,
                                          "bash", "-lc", wrapped], capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=15, env=safe_process_env())
                result = {"output": process.stdout + process.stderr, "returncode": process.returncode,
                          "exception_info": ""}
                status = result["returncode"]
                if status in (-1, 124, 137):
                    self.cleanup()  # Also kills any still-running container descendants.
                    raise RuntimeError("tool_timeout_or_kill")
                self._check_finished(result)
                return result
            except subprocess.TimeoutExpired:
                self.cleanup()
                raise RuntimeError("docker_exec_timeout") from None
            except Submitted:
                status = 0
                raise
            finally:
                event("tool_end", phase=phase, duration_seconds=time.perf_counter() - before, returncode=status)

    class TracedModel:
        config = {"model_name": MODEL}

        def __init__(self):
            self.calls = 0
            self.reserved = 0.0
            self.estimated = 0.0
            self.unknown_calls = 0

        def format_message(self, **kwargs):
            return kwargs

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [{"role": "user", "content": json.dumps(output, ensure_ascii=False)} for output in outputs]

        def get_template_vars(self, **kwargs):
            return {"model_name": MODEL}

        def serialize(self):
            return {"info": {"provider": "official_deepseek", "requested_model": MODEL,
                             "paid": args.live, "reserved_cny": self.reserved,
                             "known_cost_subtotal_cny": self.estimated if args.live else None,
                             "estimated_total_cny": self.estimated if args.live and not self.unknown_calls else None,
                             "unknown_charged_requests": self.unknown_calls,
                             "unknown_reserved_cny": self.unknown_calls * CALL_RESERVE}}

        def query(self, messages, **kwargs):
            wire = [{"role": m["role"], "content": m["content"]} for m in messages]
            input_bytes = len(json.dumps(wire, ensure_ascii=False).encode("utf-8"))
            if self.calls >= MAX_CALLS or input_bytes > MAX_INPUT_BYTES:
                raise RuntimeError("model_call_or_input_limit")
            self.calls += 1
            self.reserved += CALL_RESERVE if args.live else 0.0
            self.unknown_calls += int(args.live)
            payload = {"model": MODEL, "messages": wire, "max_tokens": MAX_OUTPUT,
                       "stream": False, "thinking": {"type": "disabled"}}
            before = time.perf_counter()
            event("model_start", call=self.calls, input_bytes=input_bytes,
                  reserved_cny=self.reserved, max_output_tokens=MAX_OUTPUT, thinking="disabled", retries=0)
            if args.live:
                try:
                    process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--http-worker"],
                                             input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True,
                                             timeout=45, env=safe_process_env(include_key=True))
                    response = json.loads(process.stdout) if process.returncode == 0 else {"error": "worker_failed"}
                except (subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                    response = {"error": type(error).__name__}
            else:
                actions = ["cat tags.py", "cat > tags.py <<'PY'\n" + CORRECT + "PY", "validate",
                           "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
                response = {"content": "```bash\n" + actions[self.calls - 1] + "\n```", "usage": None,
                            "model": "fake-scripted", "finish_reason": "stop"}
            usage = response.get("usage") or {}
            names = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
            metrics = {key: usage.get(key) for key in names}
            known = all(type(value) is int and value >= 0 for value in metrics.values())
            known = known and metrics["prompt_cache_hit_tokens"] + metrics["prompt_cache_miss_tokens"] == metrics["prompt_tokens"]
            cost = None
            if known and response.get("model") == MODEL:
                cost = (metrics["prompt_cache_hit_tokens"] * RATES["input_hit"]
                        + metrics["prompt_cache_miss_tokens"] * RATES["input_miss"]
                        + metrics["completion_tokens"] * RATES["output"]) / 1e6 * CNY_PER_USD
                self.estimated += cost
                self.unknown_calls -= int(args.live)
            event("model_end", call=self.calls, duration_seconds=time.perf_counter() - before,
                  actual_model=response.get("model"), usage=metrics, usage_state="known" if known else "unknown",
                  estimated_cny=cost, error=response.get("error"), http_status=response.get("status"),
                  finish_reason=response.get("finish_reason"), time_to_first_token=None)
            if response.get("error") or (args.live and not known):
                raise RuntimeError("provider_failure_or_unknown_usage_stop")
            if args.live and response.get("model") != MODEL:
                raise RuntimeError("unexpected_provider_model_stop")
            if known and (metrics["prompt_tokens"] > INPUT_RESERVE or metrics["completion_tokens"] > MAX_OUTPUT):
                raise RuntimeError("provider_usage_exceeded_reservation_stop")
            content = response.get("content") or ""
            actions = re.findall(r"```bash\s*\n(.*?)```", content, re.DOTALL)
            if len(actions) != 1:
                raise RuntimeError("expected_one_bash_action")
            return {"role": "assistant", "content": content,
                    "extra": {"actions": [{"command": actions[0].strip()}], "cost": cost / CNY_PER_USD if cost is not None else 0.0}}

    env = None
    model = TracedModel()
    passed, exit_status, cleanup_ok = False, "not_started", False
    fixture_dir = Path(__file__).parent / "fixtures"
    initial = (fixture_dir / "tags.py").read_text(encoding="utf-8")
    task = (fixture_dir / "task.txt").read_text(encoding="utf-8")
    provenance = {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
                  "task_sha256": hashlib.sha256(task.encode()).hexdigest()}
    event("run_start", paid=args.live, version=VERSION, source_commit=COMMIT, container_image=IMAGE,
          initial_code_sha256=hashlib.sha256(initial.encode()).hexdigest(), **provenance)
    previous_key = os.environ.get("DEEPSEEK_API_KEY")
    if not args.live:
        os.environ["DEEPSEEK_API_KEY"] = "tracepilot-fake-key-canary"
    try:
        env = TracedDocker(image=IMAGE, cwd="/work", logger=quiet_logger, executable="docker",
                           timeout=15, pull_timeout=30, container_timeout="600",
                           env={}, forward_env=[], interpreter=["bash", "-lc"],
                           run_args=["--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                                     "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=256m", "--cpus=1",
                                     "--user=65534:65534", "--tmpfs=/work:rw,nosuid,nodev,size=16m,mode=1777",
                                     "--tmpfs=/tmp:rw,nosuid,nodev,size=16m,mode=1777"])
        canary_command = "python -I -S -c " + shlex.quote(
            "import os,json; print(json.dumps({'key_absent': 'DEEPSEEK_API_KEY' not in os.environ}))")
        canary = env.execute({"command": canary_command}, phase="credential_canary")
        canary_absent = canary["returncode"] == 0 and json.loads(canary["output"]).get("key_absent") is True
        event("credential_canary", absent_inside_container=canary_absent, fake_key_used=not args.live)
        if not canary_absent or "DEEPSEEK_API_KEY" in safe_process_env():
            raise RuntimeError("credential_isolation_check_failed")
        env.execute({"command": "cat > tags.py <<'PY'\n" + initial + "\nPY"}, phase="setup")
        baseline = env.execute({"command": "validate"}, phase="baseline_validation")
        if baseline["returncode"] == 0:
            raise RuntimeError("initial_fixture_unexpectedly_passed")
        agent = DefaultAgent(model, env, system_template=SYSTEM, instance_template="{{task}}",
                             step_limit=MAX_CALLS, cost_limit=0.0, wall_time_limit_seconds=180,
                             max_consecutive_format_errors=1, output_path=run_dir / "trajectory.json")
        exit_status = agent.run(task)["exit_status"]
        validation = env.execute({"command": "validate"}, phase="independent_final_validation")
        passed = validation["returncode"] == 0 and json.loads(validation["output"]).get("passed") is True
        event("validation", passed=passed, returncode=validation["returncode"])
        final_code = env.execute({"command": "cat tags.py"}, phase="artifact_capture")
        if final_code["returncode"] == 0:
            (run_dir / "final-tags.py").write_text(final_code["output"], encoding="utf-8")
            event("artifact_capture", code_sha256=hashlib.sha256(final_code["output"].encode()).hexdigest())
    except Exception as error:
        exit_status = type(error).__name__
        event("run_error", error_type=exit_status)
    finally:
        if not args.live:
            if previous_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = previous_key
        drain_start = time.perf_counter()
        try:
            if env:
                env.cleanup()
            cleanup_ok = not any(item["event"] == "startup_cleanup_unconfirmed" for item in events)
        except Exception as error:
            event("cleanup_error", error_type=type(error).__name__)
        event("run_end", passed=passed, exit_status=exit_status, calls=model.calls, cleanup_ok=cleanup_ok,
              total_seconds=time.perf_counter() - started, drain_seconds=time.perf_counter() - drain_start)
        agent_completed = exit_status == "Submitted"
        smoke_passed = passed and cleanup_ok and agent_completed
        summary = {"framework": "mini-swe-agent", "version": VERSION, "source_commit": COMMIT,
                   "mode": "live" if args.live else "fake", "passed": passed, "exit_status": exit_status,
                   "artifact_passed": passed, "agent_completed": agent_completed, "smoke_passed": smoke_passed,
                   "provenance": provenance,
                   "calls": model.calls, "cleanup_ok": cleanup_ok, "events": events,
                   "cost_basis": {"usd_per_million": RATES, "planning_cny_per_usd": CNY_PER_USD,
                                  "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                                  "input_reserve": INPUT_RESERVE, "reserved_cny": model.reserved,
                                  "known_cost_subtotal_cny": model.estimated if args.live else None,
                                  "estimated_total_cny": model.estimated if args.live and not model.unknown_calls else None,
                                  "unknown_charged_requests": model.unknown_calls,
                                  "unknown_reserved_cny": model.unknown_calls * CALL_RESERVE}}
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run": run_dir.name, "mode": summary["mode"], "passed": passed,
                          "agent_completed": agent_completed, "smoke_passed": smoke_passed,
                          "calls": model.calls, "cleanup_ok": cleanup_ok, "exit_status": exit_status}))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--http-worker"]:
        http_worker()
    else:
        raise SystemExit(main())
