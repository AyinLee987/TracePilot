"""Run one pinned Timely/Jericho episode with bounded, observable model calls.

The official evaluator loop, virtual latency, scoring, and clock noise are
preserved. Prompts are official by default; single-json variants are disclosed
format instructions, not output repair. This is an API-model protocol replication, not the paper's
unreleased cold-start checkpoints. Fake mode still requires a real game ROM.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
import math
from pathlib import Path
import platform
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "e13af2b8c98d799857ace789ebcfdfd4ea6c2985"
HTTP_OPERATION_TIMEOUT_S = 60
TOOL_FORMATS = ("official", "single-json-v1", "single-json-v2")
SINGLE_JSON_TOOL_NOTE = """Tool-call format for this condition (single-json-v1):
For each non-conclusion reply, emit exactly one <tool_call>{"name":"<function-name>","arguments":{}}</tool_call> block containing a JSON object. Use the function signatures above for argument names and values.
Call only one tool per reply, and wait for its observation before calling another tool. Do not use DSML or native tool-call syntax.
For a terminal conclusion, keep the existing <conclusion> format."""
SINGLE_JSON_V2_TOOL_NOTE = """Tool-call format for this condition (single-json-v2):
Every non-conclusion reply must contain exactly one complete tool-call block on one physical line. Both the opening <tool_call> and closing </tool_call> tags are required. A JSON object without the closing tag will not execute.
Complete syntax examples (choose the actual function and arguments for the current state):
<tool_call>{"name":"step","arguments":{"action":"look"}}</tool_call>
<tool_call>{"name":"get_available_actions","arguments":{}}</tool_call>
Use the function signatures above. Call only one tool per reply and wait for its observation. Do not use DSML or native tool-call syntax, and do not insert a newline inside the tool-call block. If you include reasoning, place it before the tool-call line. End every non-conclusion reply with the literal closing tag </tool_call>.
For a terminal conclusion, keep the existing <conclusion> format."""


def tool_format_metadata(system_prompt: str, base_tool_prompt: str, tool_format: str) -> dict:
    """Describe the exact prompt condition without changing module state."""
    if tool_format not in TOOL_FORMATS:
        raise ValueError("Unknown tool format")
    note = {"official": "", "single-json-v1": SINGLE_JSON_TOOL_NOTE,
            "single-json-v2": SINGLE_JSON_V2_TOOL_NOTE}[tool_format]
    actual = base_tool_prompt + ("\n\n" + note if note else "")
    prompts = {"base_tool_prompt": base_tool_prompt, "actual_tool_prompt": actual,
               "base_system_message": system_prompt + "\n\n" + base_tool_prompt,
               "actual_system_message": system_prompt + "\n\n" + actual}
    return {"tool_format": tool_format, "prompt_condition_id": f"timely-interactive:{tool_format}",
            "tool_format_note": note,
            "prompt_sha256": {name: hashlib.sha256(value.encode("utf-8")).hexdigest()
                              for name, value in prompts.items()}}


@contextmanager
def tool_prompt_condition(official, tool_format: str):
    """Single-episode, process-local prompt scope; never edit the pinned source."""
    original = official.INTERACTIVE_TOOL_PROMPT
    metadata = tool_format_metadata(official.INTERACTIVE_SYSTEM, original, tool_format)
    try:
        if metadata["tool_format_note"]:
            official.INTERACTIVE_TOOL_PROMPT = original + "\n\n" + metadata["tool_format_note"]
        yield metadata
    finally:
        official.INTERACTIVE_TOOL_PROMPT = original


def dump(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify_source(source: Path) -> dict[str, str]:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE)

    if git("rev-parse", "HEAD").decode().strip() != COMMIT:
        raise ValueError("Unexpected upstream commit")
    package = source / "src/timely_eval"
    actual = {p.relative_to(source).as_posix() for p in package.rglob("*.py")}
    tracked = {p for p in git("ls-tree", "-r", "--name-only", COMMIT, "src/timely_eval").decode().splitlines() if p.endswith(".py")}
    if actual != tracked:
        raise ValueError("Unexpected or missing upstream Python source")
    hashes = {}
    for name in sorted(tracked):
        blob = git("show", f"{COMMIT}:{name}")
        if (source / name).read_text(encoding="utf-8") != blob.decode().replace("\r\n", "\n"):
            raise ValueError(f"Modified upstream source: {name}")
        hashes[name] = hashlib.sha256(blob).hexdigest()
    return hashes


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=["deepseek-flash", "deepseek-v4-pro"], default="deepseek-flash")
    parser.add_argument("--mode", choices=["speed", "timed"], default="speed")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--average-duration-per-step", type=float)
    parser.add_argument("--tool-delay", type=float, help="Uniform virtual seconds per tool; absent preserves upstream defaults")
    parser.add_argument("--tool-format", choices=TOOL_FORMATS, default="official")
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--budget-cny", default="5")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--fake-case", choices=["valid", "no-tool", "missing-close", "conclusion", "conclusion-after-tool",
                                               "length", "invalid-finish-reason", "action-discovery", "tool-error",
                                               "http-error", "missing-usage"], default="valid")
    args = parser.parse_args()
    if not 1 <= args.steps <= 500 or not 1 <= args.max_tokens <= 2048:
        parser.error("steps must be 1..500 and max_tokens 1..2048")
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        parser.error("temperature must be finite and within 0..2")
    if args.tool_delay is not None and not 0 <= args.tool_delay <= 50:
        parser.error("tool-delay must be 0..50")
    if args.mode == "timed" and (args.average_duration_per_step is None or not 0 < args.average_duration_per_step <= 600):
        parser.error("timed mode requires a finite, positive calibration duration <=600")
    if args.execute_paid and args.env_file is None:
        parser.error("paid mode requires an env-file; no credentials in command arguments")
    if args.execute_paid and args.fake_case != "valid":
        parser.error("fake-case is only available without execute-paid")
    return args


async def run(args: argparse.Namespace) -> dict:
    import httpx
    from openai import AsyncOpenAI
    from timely_transport import (BudgetedTimelyTransport, run_context, MAX_MESSAGE_BYTES,
                                  MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, MAX_OUTPUT_TOKENS,
                                  MESSAGE_OVERHEAD_TOKENS)
    from timely_evidence import inspect_evidence, observe_environment

    source = args.source.resolve(strict=True)
    game = args.game.resolve(strict=True)
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".local"):
        raise ValueError("Output must be a fresh directory below this checkout's .local")
    hashes = verify_source(source)
    if importlib.metadata.version("jericho") != "3.2.1":
        raise ValueError("This protocol requires jericho==3.2.1")
    sys.path.insert(0, str(source / "src"))
    import timely_eval.interactive as official
    from timely_eval.agents import ChatModelConfig

    if Path(official.__file__).resolve() != source / "src/timely_eval/interactive.py":
        raise ValueError("Imported evaluator is not the verified checkout")
    key = "offline-no-credential"
    if args.execute_paid:
        from dotenv import dotenv_values
        key = dotenv_values(args.env_file).get("DEEPSEEK_API_KEY") or ""
        if not key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
    # Preflight performs no model call, including with --execute-paid.
    from jericho import FrotzEnv
    env = FrotzEnv(str(game))
    try:
        observation, info = env.reset()
        preflight = {"observation_nonempty": bool(observation), "score": env.get_score(), "max_score": env.get_max_score()}
        if not observation or preflight["max_score"] <= 0:
            raise ValueError("Game preflight did not produce a supported scored task")
    finally:
        env.close()

    output.mkdir(parents=True, exist_ok=False)
    run_id = output.name
    durations = dict(official.DEFAULT_TOOL_DURATIONS)
    if args.tool_delay is not None:
        durations = {name: args.tool_delay for name in durations}
    manifest = {
        "schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "paid": args.execute_paid, "evidence": "api_model_protocol_replication" if args.execute_paid else "fake_model_real_environment",
        "upstream_commit": COMMIT, "upstream_sha256": hashes,
        "game": game.name, "game_sha256": hashlib.sha256(game.read_bytes()).hexdigest(),
        "model": args.model, "mode": args.mode, "steps": args.steps,
        **tool_format_metadata(official.INTERACTIVE_SYSTEM, official.INTERACTIVE_TOOL_PROMPT, args.tool_format),
        "average_duration_per_step": args.average_duration_per_step,
        "time_limit": args.steps * args.average_duration_per_step if args.mode == "timed" else None,
        "tool_durations": durations, "tool_delay_semantics": "upstream_virtual_accounting_no_sleep",
        "timer": "upstream_static_0.99_1.01_noise", "python_random_seed": args.seed,
        "jericho_seed": "3.2.1 implicit walkthrough default; not a new randomized game seed",
        "batch_size": 1, "workers": 1, "official_agent_attempts": 1, "sdk_max_retries": 0,
        "http_operation_timeout_s": HTTP_OPERATION_TIMEOUT_S,
        "http_timeout_semantics": "per_operation_not_absolute_task_deadline",
        "transport_limits": {"max_message_bytes": MAX_MESSAGE_BYTES,
                             "max_request_bytes": MAX_REQUEST_BYTES,
                             "max_response_bytes_each_wire_decoded": MAX_RESPONSE_BYTES,
                             "max_output_tokens": MAX_OUTPUT_TOKENS,
                             "message_overhead_tokens_each": MESSAGE_OVERHEAD_TOKENS},
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "max_calls": args.max_calls, "budget_cny": args.budget_cny,
        "max_tokens": args.max_tokens, "temperature": args.temperature, "thinking": "disabled",
        "fake_case": None if args.execute_paid else args.fake_case,
        "preflight": preflight,
        "versions": {name: importlib.metadata.version(name) for name in ["openai", "httpx", "jericho", "spacy"]},
        "runner_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                          for name in ["timely_reproduce.py", "timely_transport.py", "timely_evidence.py"]},
        "differences_from_paper": ["unreleased cold-start checkpoints unavailable", "API model substitution", "one serial episode", "bounded output and retries", "public-release prompts and evaluator", "explicit Python noise seed", "in-memory environment observer adds small included runtime overhead"]
                                 + ([f"{args.tool_format} tool-format-only prompt clarification"] if args.tool_format != "official" else []),
    }
    dump(output / "manifest.json", manifest)
    calls = 0

    async def fake(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        action = ["look", "inventory", "look"][min(calls - 1, 2)]
        content = '<tool_call>' + json.dumps({"name": "step", "arguments": {"action": action}}) + '</tool_call>'
        if args.fake_case == "http-error":
            return httpx.Response(500, text="fake upstream error", request=request)
        if args.fake_case == "no-tool":
            content = "I will think without using any tool."
        elif args.fake_case == "missing-close":
            content = content.removesuffix("</tool_call>")
        elif args.fake_case == "conclusion" or (args.fake_case == "conclusion-after-tool" and calls > 1):
            content = "<conclusion>I declare success.</conclusion>"
        elif args.fake_case == "tool-error":
            content = '<tool_call>{"name":"step","arguments":[]}</tool_call>'
        elif args.fake_case == "action-discovery":
            content = '<tool_call>{"name":"get_available_actions","arguments":{}}</tool_call>'
        response = {
            "id": f"fake-{calls}", "object": "chat.completion", "created": 0, "model": args.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 200},
        }
        if args.fake_case == "missing-usage":
            del response["usage"]
        elif args.fake_case == "length":
            response["choices"][0]["finish_reason"] = "length"
        elif args.fake_case == "invalid-finish-reason":
            response["choices"][0]["finish_reason"] = []
        return httpx.Response(200, json=response, request=request)

    transport = None
    observer = None
    measured_wall_s = None
    failure = None
    result = None
    try:
        async with AsyncExitStack() as resources:
            resources.enter_context(tool_prompt_condition(official, args.tool_format))
            transport = BudgetedTimelyTransport(
                log_path=output / "requests.jsonl", batch_budget_cny=args.budget_cny,
                max_calls=args.max_calls, inner=None if args.execute_paid else httpx.MockTransport(fake),
            )
            resources.push_async_callback(transport.aclose)
            config = official.InteractiveEvalConfig(
                game_path=game, output_dir=output / "official", batch_size=1, workers=1,
                max_test_steps=args.steps, eval_max_steps=[args.steps], tool_durations=durations,
                solver=ChatModelConfig(
                    model=args.model, api_base="https://api.deepseek.com", api_key=key,
                    max_tokens=args.max_tokens, temperature=args.temperature,
                    extra_params={"stream": False, "extra_body": {"thinking": {"type": "disabled"}}},
                ),
            )
            evaluator = official.InteractiveEvaluator(config)
            # The upstream constructor creates an unused client. Close it even if later setup fails.
            resources.push_async_callback(evaluator.solver_agent.client.close)
            await evaluator.solver_agent.client.close()
            http_client = httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=HTTP_OPERATION_TIMEOUT_S)
            resources.push_async_callback(http_client.aclose)
            client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com", max_retries=0,
                                 timeout=HTTP_OPERATION_TIMEOUT_S, http_client=http_client)
            resources.push_async_callback(client.close)
            evaluator.solver_agent.client = client
            evaluator.solver_agent.retries = 1
            random.seed(args.seed)
            started = time.perf_counter()
            try:
                with observe_environment(official) as observer:
                    with run_context(run_id=run_id, task_id=game.name, phase=args.mode):
                        if args.mode == "speed":
                            result = await evaluator.run_speed_eval()
                        else:
                            result = await evaluator.run_full_eval(args.average_duration_per_step)
            finally:
                measured_wall_s = time.perf_counter() - started
    except BaseException as exc:
        failure = type(exc).__name__  # No exception body: provider errors may contain private data.
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    finally:
        accounting = transport.snapshot() if transport is not None else {}
        environment = observer.snapshot() if observer is not None else {}
        dump(output / "environment.json", environment)
        try:
            evidence = inspect_evidence(output, result, mode=args.mode, expected_steps=args.steps,
                                        accounting=accounting, failure_type=failure, environment=environment)
        except Exception as exc:
            # Derived diagnostics must not hide the raw result or billing state.
            evidence = {"schema": 1, "technical_ok": False, "protocol_ok": False,
                        "calibration_usable": False, "errors": ["evidence_inspection_failed"],
                        "inspection_error_type": type(exc).__name__}
        payload = {
            "run_id": run_id, "paid": args.execute_paid, "official_result": result,
            "measured_evaluator_wall_s": measured_wall_s, "failure_type": failure,
            "accounting": accounting, "evidence": evidence,
            "cost_interpretation": "peak-price estimate" if args.execute_paid else "synthetic accounting; zero API spend",
            "paper_result_reproduced": False,
        }
        dump(output / "result.json", payload)
    return {**payload, "output": str(output)}


def main() -> int:
    logging.disable(logging.CRITICAL)  # Avoid upstream exception-body logging.
    args = arguments()
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"status": "setup_failed", "type": type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["evidence"]["technical_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
