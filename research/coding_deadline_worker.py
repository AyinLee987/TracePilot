"""Trusted one-check supervisor entry. Candidate code only enters Docker."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import coding_tasks as coding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    outcome = {"finished": False}
    try:
        with args.input.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("public_worker_input_limit")
        packet = json.loads(raw)
        if set(packet) != {"task", "source", "source_sha256", "image_id"}:
            raise ValueError("public_worker_input_shape")
        if set(packet["task"]) != {"task_id", "entry_point", "prompt"}:
            raise ValueError("public_worker_task_must_be_visible_only")
        coding.check_source(packet["source"])
        if coding.sandbox.sha(packet["source"].encode()) != packet["source_sha256"]:
            raise ValueError("public_worker_source_changed")
        result = coding.public_check(packet["task"], packet["source"], packet["image_id"],
                                     args.output / "check", timeout=30)
        outcome.update(finished=True, result=result)
    except BaseException as exc:
        outcome["error_type"] = type(exc).__name__
    finally:
        coding.dump_result(args.output / "checker-exit.json", outcome)
    return 0 if outcome["finished"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
