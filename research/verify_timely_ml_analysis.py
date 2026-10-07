"""Offline end-to-end verification against the frozen real ML batch (no replay)."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    data = ROOT / "research/results/timely-ml-analysis"
    source = ROOT / ".local/timely-ml-corrected-paid-20261007"
    figures = ROOT / "research/figures/timely-ml"
    paths = [source / n for n in ("plan.json", "result.json", "requests.jsonl")]
    before = {p.name: sha(p) for p in paths}
    completed_hashes = read(ROOT / "research/results/timely-ml-corrected-completion.json")["raw_sha256"]
    check(all(before[p.name] == completed_hashes[p.relative_to(ROOT).as_posix()] for p in paths),
          "source differs from frozen completion")
    runs, steps, segments, summary = [read(data / n) for n in
        ("runs.json", "iterations.json", "segments.json", "summary.json")]
    row_fields = {"model", "multiplier", "phase", "repeat", "run_id", "task"}
    plan = read(source / "plan.json")["rows"]
    check(all(set(r) == row_fields for r in plan), "unexpected plan row fields")
    planned_by_id = {r["run_id"]: r for r in plan}
    check(len(plan) == len(planned_by_id) == len(runs) == 384, "episode denominator changed")
    check(len({r["run_id"] for r in runs}) == 384 and
          all({k: r[k] for k in row_fields} == planned_by_id.get(r["run_id"]) for r in runs),
          "planned and analyzed identities differ")
    expected_groups = {(r["task"], r["model"], r["multiplier"]) for r in plan}
    check(len(summary["groups"]) == len(expected_groups) == 48 and
          {(g["task"], g["model"], g["multiplier"]) for g in summary["groups"]} == expected_groups,
          "group coverage changed")
    with (source / "requests.jsonl").open(encoding="utf-8") as stream:
        completions = sum(json.loads(line)["event"] == "request_complete" for line in stream)
    check(len(steps) == completions == 1034, "response denominator changed")
    covered = Counter((s["run_id"], i) for s in segments
                      for i in range(s["start_iteration"], s["end_iteration"] + 1))
    check(covered == Counter((s["run_id"], s["iteration"]) for s in steps)
          and all(v == 1 for v in covered.values()), "stage coverage not exact once")
    for g in summary["groups"]:
        raw = [read(source / r["run_id"] / "result.json") for r in plan
               if all(r[k] == g[k] for k in ("task", "model", "multiplier"))]
        check(len(raw) == 8, "wrong denominator")
        check(abs(statistics.mean(r["score"] for r in raw) - g["mean_score"]) < 1e-12,
              "raw score mean mismatch")
        check(sum(r["valid"] for r in raw) == g["valid"], "raw validity mismatch")
    check(all(isinstance(r["cost_cny"], str) for r in runs), "cost must retain decimal strings")
    check(sum(Decimal(r["cost_cny"]) for r in runs) == Decimal(read(source / "result.json")["batch_cost_cny"]),
          "cost mismatch")
    names = ("summary.json", "runs.json", "iterations.json", "iterations.csv", "segments.json",
             "failures.json", "provenance.json")
    with tempfile.TemporaryDirectory(prefix="timely-ml-verify-", dir=ROOT / ".local") as directory:
        recheck = Path(directory).resolve()
        check(recheck.parent == (ROOT / ".local").resolve(), "temporary cleanup path outside workspace")
        subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "research/analyze_timely_ml.py"),
                        "--output", str(recheck)], check=True, stdout=subprocess.DEVNULL)
        check(all(sha(data / n) == sha(recheck / n) for n in names), "nondeterministic tables")
    check(before == {p.name: sha(p) for p in paths}, "frozen source modified")
    manifest = read(figures / "manifest.json")
    for n, h in manifest["figures"].items():
        check(sha(figures / n) == h, "figure hash mismatch")
    for n, h in manifest["data_sha256"].items():
        check(sha(data / n) == h, "figure source data mismatch")
    check(sha(ROOT / "research/visualize_timely_ml.py") == manifest["source_sha256"], "plot source changed")
    template = (ROOT / "research/templates/timely-ml.html").read_text(encoding="utf-8")
    check(hashlib.sha256(template.encode()).hexdigest() == manifest["template_sha256"], "template changed")
    record = {"source": "corrected real ML traces", "provider_calls": 0, "replay": False,
              "verification_script_sha256": sha(Path(__file__)),
              "aligned_responses": len(steps), "reconstructed_episode_scores": len(runs),
              "independently_checked_cells": len(summary["groups"]), "episodes_per_cell": 8,
              "segment_coverage_exact_once": True, "segments": len(segments),
              "deterministic_table_rebuild": True, "cost_reconciled": True,
              "plan_row_fields_checked": sorted(row_fields), "frozen_inputs_unchanged": before,
              "figure_hashes_verified": len(manifest["figures"]),
              "annotation_accuracy": "not measured; rule-based hypotheses"}
    (data / "validation.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
