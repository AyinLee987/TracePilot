"""Zero-provider E2E: four real tasks, original grading, isolated Docker, fake HTTP."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx
from openai import AsyncOpenAI

import timely_ml as runner
from timely_ml_sandbox import Sandbox, command
from timely_transport import BudgetedTimelyTransport

CODE = '''import os
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
root="data/public/"
if os.path.exists(root+"train.json"):
    train=pd.read_json(root+"train.json"); test=pd.read_json(root+"test.json")
    x=train.request_text_edit_aware.fillna(""); z=test.request_text_edit_aware.fillna("")
    y=train.requester_received_pizza.astype(int); label="requester_received_pizza"; ident="request_id"
    model=make_pipeline(TfidfVectorizer(max_features=10000),LogisticRegression(max_iter=200))
else:
    train=pd.read_csv(root+"train.csv"); test=pd.read_csv(root+"test.csv")
    if "species" in train:
        x=train.drop(columns=["id","species"]); z=test.drop(columns="id"); y=train.species
        label=None; ident="id"
        model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500))
    elif "Transported" in train:
        cols=train.select_dtypes("number").columns
        x=train[cols]; z=test[cols]; y=train.Transported.astype(int)
        label="Transported"; ident="PassengerId"
        model=make_pipeline(SimpleImputer(),StandardScaler(),LogisticRegression(max_iter=200))
    else:
        x=train.Comment.fillna(""); z=test.Comment.fillna(""); y=train.Insult
        label="Insult"; ident=None
        model=make_pipeline(TfidfVectorizer(max_features=10000),LogisticRegression(max_iter=200))
model.fit(x,y)
p=model.predict_proba(z)
out=pd.DataFrame(p,columns=model.classes_) if label is None else pd.DataFrame({label:p[:,1]})
if ident: out.insert(0,ident,test[ident].values)
out.to_csv("submission.csv",index=False)
'''


async def main(image_name="tracepilot-timely-ml:20261007"):
    runner.upstream()
    root = runner.ROOT / (".local/timely-ml-e2e-" + uuid.uuid4().hex[:10])
    root.mkdir()
    image = subprocess.check_output(["docker","image","inspect",image_name,"--format","{{.Id}}"],text=True).strip()
    counts = {}
    async def fake(request):
        body = json.loads(request.content)
        # Separate episode identities are carried by the transport, not shared model state.
        text = body["messages"][1]["content"]
        timed = "Please finish the task within" in text
        prior = len(body["messages"])
        content = "No code here" if timed and prior == 2 else "```python\n" + CODE + "\n```"
        return httpx.Response(200,json={"id":"offline", "object":"chat.completion", "created":0,"model":body["model"],
            "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":100,"completion_tokens":500,"total_tokens":600,
                     "prompt_cache_hit_tokens":0,"prompt_cache_miss_tokens":100}})
    transport = BudgetedTimelyTransport(log_path=root / "requests.jsonl", batch_budget_cny="5",max_calls=12, inner=httpx.MockTransport(fake))
    client=AsyncOpenAI(api_key="offline",base_url="https://api.deepseek.com",max_retries=0,
                      http_client=httpx.AsyncClient(transport=transport))
    plan={"image":image}
    results=[]
    started_wall, started_mono=time.time(),time.perf_counter()
    try:
        tasks=list(runner.TASKS)
        for offset in (0,2):
            results.extend(await asyncio.gather(*(runner.episode(root,plan,
                {"run_id":f"task-{i}","phase":"speed","task":tasks[i],"model":runner.batch.MODELS[i%2],"repeat":1,"multiplier":0},
                client,"offline") for i in range(offset,offset+2))))
        assert all(r["valid"] and 0 < r["score"] < 1 for r in results), results
        timed=await runner.episode(root,plan,{"run_id":"timed","phase":"timed","task":tasks[1],
            "model":runner.batch.MODELS[0],"repeat":1,"multiplier":5},client,"offline",tau=10)
        assert timed["requests"]==3 and timed["executions"]==2 and timed["valid"],timed
    finally:
        await client.close()
    sandbox=Sandbox(image,runner.DATA / tasks[0] / "public",root / "boundary")
    independent_imports=[]
    try:
        for module in ("lightgbm","xgboost","torch","torchvision","sklearn","statsmodels","bayes_opt","timm","torch_geometric"):
            check=await sandbox.execute(f"import {module}; print('fresh process import passed')")
            assert check.returncode==0,(module,check.stderr)
            independent_imports.append(module)
        check=await sandbox.execute('''import lightgbm as lgb
import pandas as pd
df=pd.read_csv("data/public/train.csv")
model=lgb.LGBMClassifier(n_estimators=5,n_jobs=2,verbosity=-1)
model.fit(df.drop(columns=["id","species"]),df.species)
test=pd.read_csv("data/public/test.csv")
p=model.predict_proba(test.drop(columns="id"))
assert p.shape==(99,99)
''')
        assert check.returncode==0,check.stderr
        check=await sandbox.execute('''import os, socket
assert not os.path.exists("data/private")
assert not any("API_KEY" in k for k in os.environ)
try:
 socket.create_connection(("1.1.1.1",443),timeout=1)
 raise AssertionError("network reachable")
except OSError: pass
try:
 open("data/public/forbidden","w").write("bad")
 raise AssertionError("data writable")
except OSError: pass
print("isolation verified")
''')
        assert check.returncode==0,check.stderr
        symlink=await sandbox.execute('import os; os.symlink("/etc/passwd","submission.csv")')
        assert symlink.submission_path is None
        timeout=await sandbox.execute('import time; time.sleep(30)',timeout=1)
        assert timeout.timeout and not sandbox.live
        operation=asyncio.create_task(sandbox.execute('import time; time.sleep(30)'))
        await asyncio.sleep(2)
        operation.cancel()
        await asyncio.gather(operation,return_exceptions=True)
    finally:
        await sandbox.close()
    rc,names,_,_=await command("docker","ps","-a","--filter","name=tracepilot-ml-","--format","{{.Names}}")
    assert rc==0 and not names.strip(),names
    evidence={"paid":False,"provider_calls":0,"image":image,
        "independent_process_imports":independent_imports,"lightgbm_real_leaf_training":True,
        "real_task_results":[{k:r[k] for k in ("task","valid","score","duration")} for r in results],
        "timed_missing_code_feedback":True,"isolation_imports_timeout_cancel":True,"no_remaining_containers":True,
        "wall_s":time.time()-started_wall,"monotonic_s":time.perf_counter()-started_mono,
        "synthetic_accounting":transport.snapshot()}
    # Exercise the actual scheduler and terminal report with no paid requests.
    stopped=root / "scheduler-failure"
    stopped.mkdir()
    async def unknown(request):
        return httpx.Response(200,json={"choices":[{"message":{"content":"unused"}}]})
    mini={"image":image,"rows":runner.rows()[:2],"study_opening":{"known_cny":"31.874239712","liabilities":[]}}
    failed=await runner.execute(mini,"offline",root=stopped,inner=httpx.MockTransport(unknown))
    assert failed["completed"]==0 and failed["terminal_rows"]==2 and not failed["complete"] and float(failed["held_cny"])>0,failed
    assert failed["accounting"]["calls_dispatched"]<=2,failed
    evidence["scheduler_unknown_usage_terminal_report"]=True
    (root / "evidence.json").write_text(json.dumps(evidence,indent=2))
    print(json.dumps({"path":str(root),**evidence},indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image",default="tracepilot-timely-ml:20261007")
    asyncio.run(main(parser.parse_args().image))
