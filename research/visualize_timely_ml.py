"""Render offline ML analysis: PNG/SVG/PDF figures and a local stage explorer."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics as stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analyze_timely_ml import INTENTS, MODELS, ROOT, TASKS, read, require

TASK_LABELS = ("Leaf classification", "Spaceship Titanic", "Random Acts of Pizza", "Detecting insults")
COLORS = ("#0072B2", "#D55E00")
STYLES = (("o","-"),("s","--"))


def render(data, preview):
    summary, runs, steps, segments = (read(data/name) for name in
        ("summary.json","runs.json","iterations.json","segments.json"))
    figures = ROOT / "research/figures/timely-ml"
    figures.mkdir(parents=True,exist_ok=True)
    preview.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"svg.fonttype":"none",
                         "axes.spines.top":False,"axes.spines.right":False})
    manifest = {"matplotlib":matplotlib.__version__, "data_sha256":{}, "figures":{},
                "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name in ("summary.json","runs.json","iterations.json","segments.json"):
        manifest["data_sha256"][name] = hashlib.sha256((data/name).read_bytes()).hexdigest()

    def save(fig, name):
        for ext in ("png","svg","pdf"):
            path = figures / (name+"."+ext)
            fig.savefig(path,dpi=175)
            manifest["figures"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        plt.close(fig)

    def setup(ax, title, xlabel, ylabel):
        ax.set_title(title,loc="left",fontsize=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y",alpha=.16)
        ax.set_ylim(0,1.03)

    fig, axes = plt.subplots(2,2,figsize=(10.5,7.5),layout="constrained")
    for ax, task, title in zip(axes.flat,TASKS,TASK_LABELS):
        for model,color,(marker,line) in zip(MODELS,COLORS,STYLES):
            groups = [g for g in summary["groups"] if g["task"]==task and g["model"]==model and g["multiplier"]]
            x=[g["multiplier"] for g in groups]; y=[g["mean_score"] for g in groups]
            low=[v-g["score_ci95"][0] for v,g in zip(y,groups)]
            high=[g["score_ci95"][1]-v for v,g in zip(y,groups)]
            ax.errorbar(x,y,yerr=[low,high],marker=marker,linestyle=line,color=color,capsize=3,
                        label=model.removeprefix("deepseek-").replace("v4-","").title())
        setup(ax,title,"Multiplier of each model's calibration time","Mean accepted accuracy")
        ax.set_xticks([1,2,3,4,5])
        ax.legend(frameon=False,loc="lower right")
    fig.suptitle("Additional nominal time does not consistently improve the selected score",fontsize=14)
    fig.supxlabel("n=8 per point; invalid=0; bootstrap 95% intervals. Different model-specific deadlines; private-test feedback.",fontsize=9)
    save(fig,"quality-budget")

    fig, axes = plt.subplots(2,2,figsize=(10.5,7.5),layout="constrained")
    for ax, task, title in zip(axes.flat,TASKS,TASK_LABELS):
        for model,color,(marker,_) in zip(MODELS,COLORS,STYLES):
            groups=[g for g in summary["groups"] if g["task"]==task and g["model"]==model and g["multiplier"]]
            ax.scatter([g["mean_duration_s"] for g in groups],[g["mean_score"] for g in groups],
                       marker=marker,s=48,c=color,label=model.removeprefix("deepseek-").replace("v4-","").title())
        setup(ax,title,"Mean measured episode time (host seconds)","Mean accepted accuracy")
        ax.set_xlim(left=0)
        ax.legend(frameon=False,loc="lower right")
    fig.suptitle("Observed quality and total episode time depend on the task",fontsize=14)
    fig.supxlabel("Each mark averages 8 episodes at one budget multiplier. Descriptive points, not matched-deadline comparisons.",fontsize=9)
    save(fig,"quality-time")

    fig, axes = plt.subplots(2,2,figsize=(10.5,7.5),layout="constrained")
    for ax, task, title in zip(axes.flat,TASKS,TASK_LABELS):
        for model,color,(marker,line) in zip(MODELS,COLORS,STYLES):
            cell=[r for r in runs if r["phase"]=="timed" and r["task"]==task and r["model"]==model]
            y=[]
            for turn in (1,2,3):
                y.append(stats.mean(max((x["best_eligible_so_far"] for x in steps
                    if x["run_id"]==r["run_id"] and x["iteration"]<=turn),default=0) for r in cell))
            ax.plot([1,2,3],y,marker=marker,linestyle=line,color=color,
                    label=model.removeprefix("deepseek-").replace("v4-","").title())
        setup(ax,title,"Model response index (not code execution count)","Mean best eligible accuracy")
        ax.set_xticks([1,2,3]); ax.legend(frameon=False,loc="lower right")
    fig.suptitle("Later replies sometimes repair failures or improve the selected candidate",fontsize=14)
    fig.supxlabel("40 timed episodes per model/task, pooling 5 budgets. Carry earlier best forward after stopping; selection is monotone by construction.",fontsize=9)
    save(fig,"iteration-gain")

    timed=[r for r in steps if r["phase"]=="timed"]
    fig, axes=plt.subplots(2,1,figsize=(10.5,8),layout="constrained")
    keys=[(m,i) for m in MODELS for i in (1,2,3)]
    palette=["#0072B2","#009E73","#E69F00","#CC79A7","#56B4E9","#666666"]
    outcome_map={"scored":"Scored","no_code":"No executable code","execution_error":"Execution error",
                 "execution_timeout":"Timeout","no_submission":"No submission","scoring_error":"Scoring error"}
    intent_map={"initial_solution":"Initial solution","report_result":"Report result",
                "repair_attempt":"Repair / format","format_repair":"Repair / format",
                "improve_quality":"Change / improve","reduce_runtime":"Change / improve",
                "change_model":"Change / improve","rerun_unchanged":"Same-code rerun","unknown":"Unknown"}
    for ax,field,mapping,title in ((axes[0],"outcome",outcome_map,"What each response actually produced"),
                                   (axes[1],"possible_intent",intent_map,"Possible response intent (rule-based hypotheses)")):
        categories=list(dict.fromkeys(mapping.values()))
        bottom=[0]*6
        for index,category in enumerate(categories):
            values=[sum(r["model"]==m and r["iteration"]==i and mapping[r[field]]==category for r in timed) for m,i in keys]
            ax.bar(range(6),values,bottom=bottom,label=category,color=palette[index],edgecolor="white",linewidth=.4,
                   hatch=("", "//", "..", "\\\\", "xx", "--")[index])
            bottom=[a+b for a,b in zip(bottom,values)]
        ax.set_xticks(range(6),["Flash 1","Flash 2","Flash 3","Pro 1","Pro 2","Pro 3"])
        ax.set_ylabel("Recorded model responses")
        ax.set_ylim(0,180); ax.set_title(title,loc="left",fontsize=12)
        for i,n in enumerate(bottom): ax.text(i,n+2,str(n),ha="center",fontsize=9)
        ax.legend(frameon=False,ncol=3,loc="upper center",bbox_to_anchor=(.5,-.11),fontsize=9)
    fig.suptitle("Many follow-up replies are reports rather than executable revisions",fontsize=14)
    fig.supxlabel("320 timed episodes; stopped runs contribute no later response. Intent labels are tentative; unknown is not forced into another class.",fontsize=9)
    save(fig,"response-intents")
    fig, axes=plt.subplots(2,2,figsize=(10.5,6.7))
    fig.subplots_adjust(left=.07,right=.99,top=.89,bottom=.17,hspace=.5,wspace=.25)
    for ax,task,title in zip(axes.flat,TASKS,TASK_LABELS):
        cell=[r for r in summary["task_models"] if r["task"]==task]
        for i,r in enumerate(cell):
            ax.barh(i,r["mean_model_s"],color="#0072B2",label="Model request time" if i==0 else None)
            ax.barh(i,r["mean_other_s"],left=r["mean_model_s"],color="#c5cbd3",hatch="//",
                    label="Execution + other time" if i==0 else None)
            ax.text(r["mean_duration_s"]+.7,i,
                    f'{r["mean_duration_s"]:.1f}s / CNY {r["mean_cost_cny"]:.3f}',va="center",fontsize=9)
        ax.set_yticks([0,1],["Flash","Pro"]);ax.invert_yaxis()
        ax.set_xlim(0,max(r["mean_duration_s"] for r in cell)*1.65)
        ax.set_title(title,loc="left",fontsize=12);ax.set_xlabel("Mean host-clock seconds per episode")
        ax.set_ylim(1.6,-.6);ax.grid(axis="x",alpha=.15)
    handles,labels=axes.flat[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="lower center",bbox_to_anchor=(.5,.055),ncol=2,frameon=False)
    fig.suptitle("Faster model requests do not always produce faster end-to-end episodes",fontsize=14)
    fig.text(.5,.018,"40 timed episodes per model/task; different budgets. Other time includes execution, I/O and scheduling/contention.",ha="center",fontsize=9)
    save(fig,"time-components")
    packed={"summary":{k:summary[k] for k in ("episodes","responses","executions","segments","multi_response_segments")},
            "runs":runs,"steps":steps,"segments":segments,"labels":INTENTS}
    template=(ROOT/"research/templates/timely-ml.html").read_text(encoding="utf-8")
    html=template.replace("__DATA__",json.dumps(packed,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c"))
    require("__DATA__" not in html,"unfilled template")
    (preview/"explorer.html").write_text(html,encoding="utf-8")
    manifest["template_sha256"]=hashlib.sha256(template.encode()).hexdigest()
    manifest["explorer_sha256"]=hashlib.sha256(html.encode()).hexdigest()
    (figures/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"figures":len(manifest["figures"]),"explorer":str(preview/"explorer.html"),
                      "segments":len(segments),"provider_calls":0}))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=Path,default=ROOT/"research/results/timely-ml-analysis")
    p.add_argument("--preview",type=Path,default=ROOT/".local/timely-ml-analysis-preview")
    a=p.parse_args()
    render(a.data,a.preview)
