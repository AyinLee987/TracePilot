"""Generate fixed-batch plots/explorers in this repository. No API calls.

Data/source inputs are configurable; figure and private preview destinations
are fixed. Run only one writer at a time. Raw feedback stays in .local.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import hashlib
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"no_tool": "No valid call", "argument_error": "Argument error", "query": "Information query",
          "score_gain": "Score gain", "score_loss": "Score loss", "repeated_observation": "Repeated text",
          "other_action": "Other action", "conclusion": "Conclusion", "end_game": "End game"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "research/results/timely-iterations")
    parser.add_argument("--source", type=Path, default=ROOT / ".local/timely-official-paid-20261006")
    parser.add_argument("--inline", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.data / "summary.json").read_text(encoding="utf-8"))
    provenance = json.loads((args.data / "provenance.json").read_text(encoding="utf-8"))
    runs = json.loads((args.data / "runs.json").read_text(encoding="utf-8"))
    rows = defaultdict(list)
    for line in (args.data / "iterations.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        rows[row["run_id"]].append(row)
    figure_dir = ROOT / "research/figures/timely-iterations"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "font.family": "DejaVu Sans", "svg.fonttype": "none",
                         "axes.spines.top": False, "axes.spines.right": False})
    models = ["deepseek-flash", "deepseek-v4-pro"]
    colors = ["#0072B2", "#D55E00"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), layout="constrained")
    for i, model in enumerate(models):
        d = summary["timed"][model]
        axes[0].bar(i, 100*d["categories"].get("no_tool", 0)/d["recorded_steps"], color=colors[i])
        axes[1].bar(i, 100*d["no_tool_http_s"]/d["http_s"], color=colors[i])
    for ax, title in zip(axes, ["Recorded steps without a valid call", "HTTP time spent on those responses"]):
        ax.set_title(title, loc="left"); ax.set_ylabel("Percent (%)");ax.set_xticks([0, 1], ["Flash", "Pro"])
        ax.set_ylim(0, 50)
        for bar in ax.patches:
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1, f"{bar.get_height():.1f}%", ha="center")
    fig.suptitle("Protocol failure consumes requests and elapsed model time", x=.015, ha="left", fontsize=14)
    fig.supxlabel("320 timed episodes; descriptive. HTTP time is not recoverable savings.", fontsize=10)
    for ext in ("png", "svg", "pdf"):
        fig.savefig(figure_dir / f"protocol-cost.{ext}", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), layout="constrained")
    for ax, game in zip(axes.flat, ["zork1.z5", "advent.z5", "enchanter.z3", "detective.z5"]):
        for model, color in zip(models, colors):
            groups = sorted([g for g in summary["groups"] if g["game"] == game and g["model"] == model], key=lambda x:x["budget"])
            x=[g["budget"] for g in groups];y=[g["mean_net_gain"] for g in groups];sd=[g["net_gain_sd"] for g in groups]
            ax.errorbar(x,y,yerr=sd,marker="o",capsize=3,color=color,label=model.replace("deepseek-", ""))
        ax.set_title(game); ax.set_xlabel("Max steps (also scales logical time limit)"); ax.set_ylabel("Score change from initial state")
        ax.axhline(0,color="0.65",linewidth=.7); ax.legend(frameon=False); ax.set_xticks([10,30,50,100])
    fig.suptitle("Net progress, excluding the score already present at reset", fontsize=14)
    fig.supxlabel("Mean ± sample SD; n=8 per cell. Different model-specific time limits and mixed scheduling.",fontsize=9)
    for ext in ("png", "svg", "pdf"):
        fig.savefig(figure_dir / f"net-progress.{ext}", dpi=160)
    plt.close(fig)
    template=(ROOT / "research/templates/timely-iterations.html").read_text(encoding="utf-8")
    cases={c["run_id"] for c in summary["cases"]}
    all_data, inline_data=[], []
    for run in runs:
        trajectory_path=args.source/run["run_id"]/f"official/trajectories_max_steps_{run['steps']}.jsonl"
        if hashlib.sha256(trajectory_path.read_bytes()).hexdigest() != provenance["inputs"][run["run_id"]]["trajectory"]:
            raise ValueError(f"Source trajectory changed: {run['run_id']}")
        trace=json.loads(trajectory_path.read_text(encoding="utf-8").strip())
        feedback={s["step"]+1:"\n".join(t["result"] for t in s["tool_results"]) for s in trace["steps"]}
        public={"id":run["run_id"],"game":run["game"],"model":run["model"],"mode":run["mode"],"budget":run["steps"],
                "initial":run["initial_score"],"final":run["final_score"],"max":run["max_score"],"wall":run["wall_s"],"phase":run["scheduler"]}
        public["points"]=[[r["category"],r["score_before"],r["score_after"],r["action"] or r["tool"] or "",
            round(r["http_s"],3),r["parsed_calls"],r["executed_calls"],r["feedback_summary"]] for r in rows[run["run_id"]]]
        if run["run_id"] in cases:
            inline_data.append(public)
        private={**public,"points":[p[:7]+[feedback.get(r["recorded_step"],"No tool feedback; see local raw response if needed.")[:2000]] for p,r in zip(public["points"],rows[run["run_id"]])]}
        all_data.append(private)
    def fragment(data):
        return template.replace("__DATA__",json.dumps(data,ensure_ascii=False,separators=(",", ":")).replace("<", "\\u003c"))
    args.inline.parent.mkdir(parents=True,exist_ok=True)
    args.inline.write_text(fragment(inline_data),encoding="utf-8")
    if args.inline.stat().st_size >= 1_000_000:
        raise ValueError("Inline visualization exceeds 1 MB")
    wrapper='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TracePilot iteration explorer</title><style>
    :root{--foreground:#172438;--border:#cad2dd;--viz-series-1:#0072b2;--viz-series-2:#d55e00;--viz-series-3:#009e73;color-scheme:light}body{font:16px system-ui,sans-serif;max-width:1060px;margin:24px auto;padding:0 18px;background:#fff;color:var(--foreground)}h2{font-size:24px;font-weight:500}.form-select{max-width:100%;padding:7px;font:inherit}.form-label{display:inline-block}.viz-row{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.form-range{max-width:260px;vertical-align:middle}.btn{padding:7px 12px;font:inherit}.text-small{font-size:13px}pre{font-size:13px}summary{cursor:pointer}
    </style><body>'''
    local=ROOT/".local/timely-iteration-analysis-20261007"
    local.mkdir(parents=True,exist_ok=True)
    (local/"trace-explorer.html").write_text(wrapper+fragment(all_data)+"</body></html>",encoding="utf-8")
    (local/"inline-preview.html").write_text(wrapper+fragment(inline_data)+"</body></html>",encoding="utf-8")
    print(json.dumps({"all_runs":len(all_data),"inline_cases":len(inline_data),"inline_bytes":args.inline.stat().st_size,"api_calls":0}))


if __name__ == "__main__":
    main()
