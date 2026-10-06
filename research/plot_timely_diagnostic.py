"""Render a single observed trace; never compare models or estimate causality."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "research/results/timely-trajectory-diagnostic.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "research/figures/timely-v2-diagnostic")
    args = parser.parse_args()
    source = args.source.read_bytes()
    data = json.loads(source)
    run = next(item for item in data["runs"] if item["alias"] == "r2_pro_v2")
    steps = run["steps"]
    if ([row["response_index"] for row in steps] != list(range(1, 33))
            or run["summary"]["tools_executed"] != 31
            or sum(row["executed_tools"] for row in steps) != 31
            or run["summary"]["max_score"] != 350
            or run["summary"]["no_tool_response_indices"] != [24]
            or steps[24]["error_feedback_received"] is not True
            or steps[24]["score_before"] != 15 or steps[24]["score_after"] != 15
            or steps[24]["score_delta"] != 0
            or run["summary"]["final_score"] != 40):
        raise ValueError("This annotated diagnostic requires the recorded v2 trajectory")
    observed = [row for row in steps if row["score_after"] is not None]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    blue, orange, teal = "#245DA8", "#C95D20", "#167B78"
    fig, (score_ax, time_ax) = plt.subplots(2, 1, figsize=(11, 6.7), sharex=True,
                                           gridspec_kw={"height_ratios": [1.6, 1]})
    fig.subplots_adjust(left=0.085, right=0.965, top=0.82, bottom=0.20, hspace=0.16)
    fig.suptitle("A tool call recovered; its immediate score did not improve",
                 x=0.085, y=0.96, ha="left", fontsize=16, fontweight="bold")
    fig.text(0.085, 0.902,
             "One Zork1 run | DeepSeek-V4-Pro | single-json-v2 | 31 tool executions / 32 responses",
             color="#4B5563", fontsize=10)
    for ax in (score_ax, time_ax):
        ax.set_xlim(0.5, 32.9)
        ax.axvspan(23.55, 24.45, color=orange, alpha=0.12)
        ax.axvspan(24.55, 25.45, color=teal, alpha=0.12)
        ax.grid(axis="y", color="#E4E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
    score_ax.step([row["response_index"] for row in observed],
                  [row["score_after"] for row in observed], where="post", color=blue, linewidth=2)
    score_ax.scatter([row["response_index"] for row in observed],
                     [row["score_after"] for row in observed], color=blue, s=14, zorder=3)
    score_ax.set_ylabel("Observed game score (max 350)")
    score_ax.set_ylim(-2, 52)
    score_ax.set_yticks([0, 10, 20, 30, 40])
    for row in observed:
        if row["score_delta"] > 0:
            score_ax.annotate(f"+{row['score_delta']}",
                              (row["response_index"], row["score_after"]),
                              xytext=(-2, 8), textcoords="offset points",
                              color=blue, ha="center", fontsize=9)
    score_ax.annotate("24: invalid JSON; no tool",
                      xy=(24, 16), xytext=(12.4, 44), color=orange,
                      arrowprops={"arrowstyle": "-", "color": orange}, fontsize=9)
    score_ax.annotate("25: valid call after error feedback\nScore stays at 15",
                      xy=(25, 15), xytext=(18.0, 31), color=teal,
                      arrowprops={"arrowstyle": "-", "color": teal}, fontsize=9)
    colors = [orange if row["response_index"] == 24 else
              teal if row["response_index"] == 25 else blue for row in steps]
    time_ax.bar([row["response_index"] for row in steps],
                [row["http_duration_s"] for row in steps], width=0.68, color=colors, alpha=0.85)
    time_ax.set_ylabel("HTTP request duration (s)")
    time_ax.set_xlabel("Response index (1-based; not elapsed time)")
    time_ax.set_xticks([1, 4, 8, 12, 16, 20, 24, 28, 32])
    fig.text(0.085, 0.035,
             "Descriptive trace only. This run failed the predeclared calibration gate.\n"
             "No model ranking, prompt effect, or causal benefit of feedback is identified.",
             fontsize=9, color="#4B5563", linespacing=1.6)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".svg"):
        fig.savefig(args.output.with_suffix(suffix), dpi=180, facecolor="white")
    plt.close(fig)
    record = {"schema": 1, "source_sha256": hashlib.sha256(source).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "matplotlib": matplotlib.__version__, "trajectory": run["alias"],
              "response_count": len(steps), "observed_score_points": len(observed),
              "http_duration_sum_s": sum(row["http_duration_s"] for row in steps),
              "score_timing": "observed after each executed tool; no score sample invented for response 24",
              "x_axis": "response index, not wall clock", "api_calls": 0,
              "images": {suffix: hashlib.sha256(args.output.with_suffix(suffix).read_bytes()).hexdigest()
                         for suffix in (".png", ".svg")}}
    args.output.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
