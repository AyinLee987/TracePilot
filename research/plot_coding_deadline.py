"""Plot the prespecified R3 tables; never infer an unobserved crossover time."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


MODELS = ("deepseek-flash", "deepseek-v4-pro")
POLICIES = ("resample", "repair")
TASKS = (55, 32, 7, 56, 16, 99, 18, 31)
LABELS = {"deepseek-flash": "Flash", "deepseek-v4-pro": "Pro"}
COLORS = {"deepseek-flash": "#0072B2", "deepseek-v4-pro": "#D55E00"}
MARKERS = {"deepseek-flash": "o", "deepseek-v4-pro": "s"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def table(source: Path, summary: dict, name: str) -> list[dict]:
    ref = summary["tables"][name]
    path = (source.parent / ref["path"]).resolve()
    if not path.is_relative_to(source.parent.resolve()):
        raise ValueError("table path escapes summary directory")
    raw = path.read_bytes()
    if sha(raw) != ref["sha256"]:
        raise ValueError("table hash changed: " + name)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def numeric(row: dict, name: str) -> float:
    value = float(row[name])
    if not (-float("inf") < value < float("inf")):
        raise ValueError("nonfinite table value: " + name)
    return value


def observed(row: dict) -> bool:
    value = row["quality_fully_observed"].lower()
    if value not in {"true", "false", "0", "1"}:
        raise ValueError("invalid observation flag")
    return value in {"true", "1"}


def select(rows: list[dict], *, model: str, policy: str, delay: int,
           exclude: int = 0, task_id: str | None = None) -> list[dict]:
    return [row for row in rows if row["cohort"] == "native"
            and row["stratum"] == "all" and numeric(row, "exclude_he32") == exclude
            and row["model"] == model and row["policy"] == policy
            and numeric(row, "delay_s") == delay
            and (task_id is None or row["task_id"] == task_id)]


def one(rows: list[dict], deadline: float) -> dict:
    matching = [row for row in rows if numeric(row, "deadline_s") == deadline]
    if len(matching) != 1:
        raise ValueError("expected exactly one frozen condition per deadline")
    row = matching[0]
    n, passed = numeric(row, "n_trajectories"), numeric(row, "pass_rate")
    if n <= 0 or not 0 <= passed <= 1:
        raise ValueError("invalid planned denominator or pass rate")
    return row


def save(fig, output: Path, name: str) -> dict:
    images = {}
    for suffix in (".pdf", ".svg", ".png"):
        path = output / (name + suffix)
        fig.savefig(path, dpi=180, facecolor="white")
        images[path.name] = sha(path.read_bytes())
    plt.close(fig)
    return images


def quality_plot(rows: list[dict], deadlines: list[float]):
    fig, axes = plt.subplots(2, 2, figsize=(7.4, 6.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=.09, right=.985, bottom=.18, top=.84, wspace=.12, hspace=.21)
    for row_index, excluded in enumerate((0, 1)):
        for col_index, delay in enumerate((0, 1)):
            ax = axes[row_index, col_index]
            for model in MODELS:
                for policy in POLICIES:
                    group = select(rows, model=model, policy=policy, delay=delay, exclude=excluded)
                    points = [one(group, d) for d in deadlines]
                    values = [100 * numeric(p, "pass_rate") for p in points]
                    ax.plot(deadlines, values, color=COLORS[model], marker=MARKERS[model],
                            linestyle="-" if policy == "repair" else "--", linewidth=1.5,
                            markerfacecolor=COLORS[model] if policy == "repair" else "white",
                            markersize=5, label=f"{LABELS[model]} / {policy}")
                    for deadline, point, value in zip(deadlines, points, values):
                        if not observed(point):
                            ax.annotate("*", (deadline, value), xytext=(4, 4),
                                        textcoords="offset points", fontsize=10)
            ax.set_title(f"{'All 8 tasks' if not excluded else '7 tasks; /32 excluded'} | tool +{delay}s", fontsize=9)
            ax.set_ylim(-2, 103)
            ax.set_yticks((0, 25, 50, 75, 100))
            ax.set_xticks(deadlines)
            ax.set_xlim(deadlines[0] - 1, deadlines[-1] + 1)
            ax.grid(axis="y", color="#E5E7EB", linewidth=.6)
            ax.set_axisbelow(True)
            if row_index == 1:
                ax.set_xlabel("WSL monotonic cutoff (s)")
    fig.supylabel("Observed hidden passes / planned (%)", x=.015, y=.53, fontsize=9)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.53, .96), ncol=2,
               frameon=False, fontsize=9)
    fig.text(.09, .085, "Native-start development tasks; two repeats per task/condition. Missing answers remain in the denominator.", fontsize=8)
    fig.text(.09, .055, "Two WSL monotonic cutoffs only; external clock equivalence is unverified. No crossing time is estimated.", fontsize=8)
    fig.text(.09, .025, "* Incomplete grading: observed success fraction is a lower bound. No population confidence interval is implied.", fontsize=8)
    return fig


def work_plot(rows: list[dict]):
    fig, axes = plt.subplots(2, 2, figsize=(7.8, 6.8), sharey="row")
    fig.subplots_adjust(left=.12, right=.985, bottom=.25, top=.92, wspace=.28, hspace=.43)
    configurations = [(model, policy) for model in MODELS for policy in POLICIES]
    native = [row for row in rows if row["cohort"] == "native"]
    upper = {field: max(minimum, 1.08 * max(numeric(row, field) for row in native))
             for field, minimum in (("eligible_rounds", 1), ("known_cost_cny", .001))}
    for col, delay in enumerate((0, 1)):
        for line, (field, label) in enumerate((("eligible_rounds", "Eligible candidates (count)"),
                                              ("known_cost_cny", "Known cost (CNY)"))):
            ax = axes[line, col]
            for x, (model, policy) in enumerate(configurations, 1):
                group = [r for r in rows if r["cohort"] == "native" and r["model"] == model
                         and r["policy"] == policy and numeric(r, "delay_s") == delay]
                if len(group) != 16:
                    raise ValueError("work plot requires all sixteen planned native rows per condition")
                values = [numeric(r, field) for r in group]
                box_values = [value for record, value in zip(group, values)
                              if record["status"] != "not_started"
                              and (field != "known_cost_cny" or numeric(record, "unknown_requests") == 0)]
                if box_values:
                    ax.boxplot([box_values], positions=[x], widths=.48, whis=(0, 100), showfliers=False,
                               medianprops={"color": COLORS[model]},
                               boxprops={"color": COLORS[model]}, whiskerprops={"color": COLORS[model]},
                               capprops={"color": COLORS[model]})
                for i, (record, value) in enumerate(zip(group, values)):
                    position = x + ((i % 5) - 2) * .045
                    if record["status"] == "not_started":
                        ax.scatter([position], [value], color="#777777", marker="x", s=24, zorder=4)
                    elif field == "known_cost_cny" and numeric(record, "unknown_requests") > 0:
                        ax.scatter([position], [value], color="#222222", marker="X", s=26, zorder=4)
                    else:
                        ax.scatter([position], [value], color=COLORS[model], marker=MARKERS[model], s=15,
                                   facecolors=COLORS[model] if policy == "repair" else "none", alpha=.65, zorder=3)
            ax.set_title(f"Actual added tool delay: {delay}s", fontsize=9)
            ax.set_xticks(range(1, 5), [f"{LABELS[m]}\n{p}" for m, p in configurations], fontsize=8)
            ax.set_ylabel(label, fontsize=9)
            ax.set_ylim(0, upper[field])
            ax.grid(axis="y", color="#E5E7EB", linewidth=.6)
            ax.set_axisbelow(True)
            if field == "eligible_rounds":
                ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.text(.12, .145, "Each dot is one planned native trajectory; boxes show quartiles, median and observed range.", fontsize=8)
    fig.text(.12, .11, "Counts use the 15s WSL monotonic cutoff. Known cost includes late requests and drain settlement.", fontsize=8)
    fig.text(.12, .075, "Gray x: unstarted; black X: incomplete fees. Both are excluded from boxes; liabilities are tabulated.", fontsize=8)
    fig.text(.12, .04, "Costs are usage-based estimates, not invoices. The common-state cohort is reported separately.", fontsize=8)
    return fig


def task_plot(rows: list[dict], deadlines: list[float]):
    columns = [(policy, delay, d) for policy in POLICIES for delay in (0, 1) for d in deadlines]
    values = []
    for number in TASKS:
        current = []
        for policy, delay, d in columns:
            points = [one(select(rows, model=m, policy=policy, delay=delay,
                                 task_id=f"HumanEval/{number}"), d) for m in MODELS]
            current.append(100 * (numeric(points[0], "pass_rate") - numeric(points[1], "pass_rate"))
                           if all(observed(p) for p in points) else float("nan"))
        values.append(current)
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    fig.subplots_adjust(left=.15, right=.88, bottom=.25, top=.92)
    im = ax.imshow(values, vmin=-100, vmax=100, cmap="PuOr", aspect="auto")
    ax.set_yticks(range(len(TASKS)), [f"HumanEval/{n}" + (" *" if n == 32 else "") for n in TASKS])
    ax.set_xticks(range(len(columns)), [f"{p}\n+{delay}s / {d:g}s" for p, delay, d in columns], fontsize=8)
    ax.set_xlabel("Policy / tool delay / WSL monotonic cutoff", labelpad=8)
    for y, line in enumerate(values):
        for x, value in enumerate(line):
            label = "NA" if value != value else f"{value:+.0f}" if value else "0"
            ax.text(x, y, label, ha="center", va="center", fontsize=9,
                    color="white" if abs(value) >= 75 else "#111827")
    fig.colorbar(im, ax=ax, fraction=.045, pad=.025, label="Flash minus Pro (percentage points)")
    fig.text(.15, .1, "Each cell compares two repeats per model. Positive favors Flash; negative favors Pro.", fontsize=8)
    fig.text(.15, .065, "* /32 has a known numeric-oracle limitation. NA means incomplete hidden grading.", fontsize=8)
    fig.text(.15, .03, "Descriptive development outcomes, not a validated rule for choosing a model on a new task.", fontsize=8)
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    raw = source.read_bytes()
    summary = json.loads(raw)
    deadlines = summary["deadlines_s"]
    if deadlines != [5, 15]:
        raise ValueError("this development plot requires frozen 5/15-second cutoffs")
    conditions = table(source, summary, "conditions.csv")
    tasks = table(source, summary, "task_conditions.csv")
    trajectories = table(source, summary, "trajectories.csv")
    if len(trajectories) != 144:
        raise ValueError("full planned trajectory denominator required")
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(source.parent) or source.parent.is_relative_to(output):
        raise ValueError("a fresh figure directory separate from source is required")
    output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none", "pdf.fonttype": 42})
    images = {}
    synthetic = summary["fixture_scores"] or not summary["paid_input"]
    incomplete = (summary["score_status"] != "complete"
                  or any(not observed(row) for row in conditions)
                  or any(key != "complete" and count > 0 for key, count in summary["trajectory_status_counts"].items()))
    for name, fig in (("deadline-quality", quality_plot(conditions, deadlines)),
                      ("deadline-work", work_plot(trajectories)),
                      ("deadline-task-gaps", task_plot(tasks, deadlines))):
        if synthetic:
            fig.text(.5, .992, "Synthetic fixture; no model results", ha="center", va="top", color="#A32222", fontsize=9)
        elif incomplete:
            fig.text(.5, .992, "Incomplete grading/batch; retain missing outcomes", ha="center", va="top", color="#A32222", fontsize=9)
        images.update(save(fig, output, name))
    record = {"schema": 1, "source_sha256": sha(raw), "script_sha256": sha(Path(__file__).read_bytes()),
              "matplotlib": matplotlib.__version__, "provider_calls": 0, "images": images,
              "synthetic_input": synthetic,
              "incomplete_input": incomplete,
              "limits": ["Two correlated measured cutoffs; no interpolation-based crossover estimate.",
                         "WSL monotonic cutoffs; batch UTC duration differs and external clock equivalence is unverified.",
                         "Task variation and observed trajectory ranges, not population confidence intervals.",
                         "No held-out prediction or multiple task domains in these development plots."]}
    (output / "figures.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "figures": len(images), "provider_calls": 0}))


if __name__ == "__main__":
    main()
