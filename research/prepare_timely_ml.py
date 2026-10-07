"""Prepare the four published Timely ML tasks from pinned public mirrors.

No provider calls. Splits follow MLE-bench 507f92e (not an authenticated copy
of the unpublished Timely data). Raw data and private labels stay in .local.
"""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/timely-ml-data-20261007"
SOURCE = ROOT / ".local/timely-machine-audit"
MLE_COMMIT = "507f92e1138bb6e40dac5c6ee7a6758e6424bf97"
HF_COMMIT = "2bfbf40c45d90bfe05f50e872526a2964608a132"
TASKS = {
    "leaf-classification": {"prompt": "leaf_classification.txt", "id": "id", "label": None},
    "spaceship-titanic": {"prompt": "spaceship-titanic.txt", "id": "PassengerId", "label": "Transported"},
    "random-acts-of-pizza": {"prompt": "random-acts-of-pizza.txt", "id": "request_id", "label": "requester_received_pizza"},
    "detecting-insults-in-social-commentary": {"prompt": "detecting-insults-in-social-commentary.txt", "id": None, "label": "Insult"},
}
URLS = {
    "leaf.csv": "https://raw.githubusercontent.com/BhuvaneshwaranK/Leaf-Classification/ac242cea0536b18fefb9f35218cb7710ddbbb949/train.csv",
    "leaf-images.zip": "https://codeload.github.com/abhmul/LeafClassification/zip/22c248d6e1a0ec47bb7a86007030dd9bd3fad601",
    "spaceship.csv": "https://raw.githubusercontent.com/You-sha/Spaceship-Titanic/40e756d0ca71f3f993c845b41ac5bcc09ccb5b6f/train.csv",
    "pizza-train.json": "https://raw.githubusercontent.com/marycboardman/Random-Acts-of-Pizza/a1ff9de6dc49583d7ffefaeacf5ec7582eb19a66/train.json",
    "pizza-test.json": "https://raw.githubusercontent.com/marycboardman/Random-Acts-of-Pizza/a1ff9de6dc49583d7ffefaeacf5ec7582eb19a66/test.json",
}
for rel in ("public/train.csv", "public/test.csv", "private/test.csv"):
    URLS["insult-" + rel.replace("/", "-")] = (
        f"https://huggingface.co/datasets/TIGER-Lab/mle-bench/resolve/{HF_COMMIT}/"
        f"data/detecting-insults-in-social-commentary/prepared/{rel}")
for task in TASKS:
    URLS[task + "-prepare.py"] = f"https://raw.githubusercontent.com/openai/mle-bench/{MLE_COMMIT}/mlebench/competitions/{task}/prepare.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(item):
    name, url = item
    path = LOCAL / "raw" / name
    if path.exists():
        return {"file": name, "url": url, "sha256": sha(path), "bytes": path.stat().st_size}
    temporary = path.with_suffix(path.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 100_000_000:
                raise ValueError("download size limit")
            output.write(chunk)
    temporary.rename(path)
    return {"file": name, "url": url, "sha256": sha(path), "bytes": path.stat().st_size}


def main():
    import pandas as pd
    from sklearn.model_selection import train_test_split
    LOCAL.mkdir(exist_ok=True)
    (LOCAL / "raw").mkdir(exist_ok=True)
    if (LOCAL / "manifest.json").exists():
        raise ValueError("prepared data already exists; do not overwrite")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        downloads = list(pool.map(download, URLS.items()))
    summaries = []
    for task, info in TASKS.items():
        directory = LOCAL / task
        public, private = directory / "public", directory / "private"
        public.mkdir(parents=True, exist_ok=False)
        private.mkdir()
        if task in ("leaf-classification", "spaceship-titanic"):
            frame = pd.read_csv(LOCAL / "raw" / ("leaf.csv" if task.startswith("leaf") else "spaceship.csv"))
            expected = (990, 194) if task.startswith("leaf") else (8693, 14)
            if frame.shape != expected:
                raise ValueError(f"unexpected source dimensions: {task}: {frame.shape}")
            label = "species" if task.startswith("leaf") else "Transported"
            train, test = train_test_split(frame, test_size=0.1, random_state=0)
            train.to_csv(public / "train.csv", index=False)
            test.drop(columns=[label]).to_csv(public / "test.csv", index=False)
            if task.startswith("leaf"):
                classes = sorted(frame.species.unique())
                if len(classes) != 99:
                    raise ValueError("leaf requires 99 classes")
                answers = pd.get_dummies(test.set_index("id").species).reindex(columns=classes, fill_value=0).astype(int)
                answers.to_csv(private / "test.csv", index=True)
                (public / "images").mkdir()
                with zipfile.ZipFile(LOCAL / "raw/leaf-images.zip") as archive:
                    for entry in archive.infolist():
                        parts = Path(entry.filename).parts
                        if len(parts) == 3 and parts[1] == "images" and parts[2].endswith(".jpg") and Path(parts[2]).stem.isdecimal():
                            (public / "images" / parts[2]).write_bytes(archive.read(entry))
                if not all((public / "images" / f"{i}.jpg").exists() for i in frame.id):
                    raise ValueError("missing leaf images")
            else:
                test.to_csv(private / "test.csv", index=False)
        elif task == "random-acts-of-pizza":
            old_train = json.loads((LOCAL / "raw/pizza-train.json").read_text())
            old_test = json.loads((LOCAL / "raw/pizza-test.json").read_text())
            if (len(old_train), len(old_test)) != (4040, 1631):
                raise ValueError("unexpected pizza source size")
            train, test = train_test_split(old_train, test_size=len(old_test)/(len(old_train)+len(old_test)), random_state=0)
            fields = set(old_test[0])
            (public / "train.json").write_text(json.dumps(train), encoding="utf-8")
            (public / "test.json").write_text(json.dumps([{k:v for k,v in row.items() if k in fields} for row in test]), encoding="utf-8")
            pd.DataFrame([{k:row[k] for k in ("request_id", "requester_received_pizza")} for row in test]).to_csv(private / "test.csv", index=False)
        else:
            for rel in ("public/train.csv", "public/test.csv", "private/test.csv"):
                shutil.copyfile(LOCAL / "raw" / ("insult-" + rel.replace("/", "-")), directory / rel)
            train, test = pd.read_csv(public / "train.csv"), pd.read_csv(public / "test.csv")
            if (len(train), len(test)) != (3947, 2647):
                raise ValueError("unexpected insult size")
        prompt = SOURCE / "rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/ML_source/prompt_templates" / info["prompt"]
        shutil.copyfile(prompt, directory / "prompt.txt")
        files = {p.relative_to(directory).as_posix():sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
        summaries.append({"task":task, **info, "train_rows":len(train), "test_rows":len(test), "files":files})
    manifest = {"schema":1, "source_scope":"public mirrors + MLE-bench preparation; Timely split identity unverified", "mle_commit":MLE_COMMIT, "downloads":downloads, "tasks":summaries}
    (LOCAL / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_sha256":sha(LOCAL / "manifest.json"), "tasks":[{k:t[k] for k in ("task","train_rows","test_rows")} for t in summaries]}))


if __name__ == "__main__":
    main()
