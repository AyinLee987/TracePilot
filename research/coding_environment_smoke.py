"""Zero-model preparation of one isolated HumanEval+ coding task.

Run in Linux/WSL with permission to access Docker. Only tracepilot-coding-*
images and UUID-owned containers are created. No model credentials are read.
This validates preset candidates and external judging, not an R3/R4 experiment,
the complete EvalPlus evaluator, or a complete judge for arbitrary model code.
Candidate code never executes in the parent.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local" / "coding-research-env"
COMMIT = "e5d0ed0bab96280b60b637ec7f15b5e4841b0cb2"
BASE = "python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
IMAGE = "tracepilot-coding-smoke:py312-593bd06efe90"
TASK = "HumanEval/0"
DOWNLOADS = {
    "evalplus-source.zip": (
        f"https://codeload.github.com/evalplus/evalplus/zip/{COMMIT}",
        "0d1cfc8651d11dd46b85ad3b66f70856d8dcb55d49aa017e217edda1b95d82cf"),
    "evalplus-release-tag.json": (
        "https://api.github.com/repos/evalplus/evalplus/git/ref/tags/v0.3.1",
        "c05f1468166c799669d094ac3e3f2476d7830d90dfa17f015a9fbbcb741c7199"),
    "HumanEvalPlus-v0.1.10.jsonl.gz": (
        "https://github.com/evalplus/humanevalplus_release/releases/download/v0.1.10/HumanEvalPlus.jsonl.gz",
        "272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101"),
    "HumanEvalPlus-LICENSE.txt": (
        "https://raw.githubusercontent.com/evalplus/humanevalplus_release/68cd26d53a0dec69f85eafe1f82a2a74155a2bd6/LICENSE",
        "b0b08821a8c2b49e0f296b0b498c17d6e19b0439d1e4dd9cdb5f37712993c8a7"),
    "HumanEval-MIT-LICENSE.txt": (
        "https://raw.githubusercontent.com/openai/human-eval/6d43fb980f9fee3c892a914eda09951f772ad10d/LICENSE",
        "bcba3de214851cce46ed5af42d6698044616eeace887c3231bc7a20474ab639e"),
}
# Independently record the expanded source and data, as well as download bytes.
# These pins preserve the verified 2026-10-06 acquisition; they are not a claim
# of publisher-signed checksums. A changed codeload serialization fails closed.
SOURCE_FILES_SHA = "ce44b0dfa7ffce1501eebdd1d9437bf3ce93cde98c6df8a96eb7f84bab81f012"
DATASET_SHA = "42526ec0e7d5f3ee0b06d6ced98f8c8bae3d76519151bfb3d36f79010645bd7f"
PREPARATION_BOUNDARIES = {
    "candidate_scope": "only the five preset candidates on HumanEval/0; not arbitrary model code",
    "hidden_input_boundary": "worker can read test inputs; raw worker output is local evidence only, never model feedback",
    "r3_feedback_requirement": "separate visible tests and return only parent-generated hidden-judge summaries",
    "failure_taxonomy": "preset smoke errors are diagnostic; general candidate versus infrastructure classification is not implemented",
    "timeout_semantics": "one wall timeout for the whole input batch, not EvalPlus per-input canonical-relative limits",
    "autoremove_boundary": "--rm acts when started PID 1 exits; unstarted containers still require exact-name cleanup",
}

# This worker receives candidate source and inputs, never expected answers,
# the dataset, canonical reference, or judge code. The parent enforces byte caps
# even when candidate code bypasses Python redirection with os.write(1/2, ...).
WORKER = r'''
import contextlib, json, os, sys
header = json.loads(sys.stdin.readline())
source = header.pop("source")
entry_point = header.pop("entry_point")
if header:
    raise ValueError("unexpected worker header")
with open("/work/candidate.py", "x") as stream:
    stream.write(source)
namespace = {"__name__": "candidate"}
with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
    exec(compile(source, "/work/candidate.py", "exec"), namespace)
function = namespace[entry_point]
for line in sys.stdin:
    case = json.loads(line)
    try:
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            value = function(*case["arguments"])
        if type(value) is not bool:
            raise TypeError("this smoke task requires a bool result")
        answer = {"index": case["index"], "value": value}
    except Exception as exc:
        answer = {"index": case["index"], "error_type": type(exc).__name__}
    print(json.dumps(answer), flush=True)
'''

LIMIT_PROBE = r'''
import errno, json, os
from pathlib import Path
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
mounts = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()]
root_options = next(row[5].split(",") for row in mounts if row[4] == "/")
types = {row[4]: row[row.index("-") + 1] for row in mounts}
with open("/work/write-probe", "x") as stream:
    stream.write("private tmpfs")
os.unlink("/work/write-probe")
root_write_errno = None
try:
    with open("/root-write-probe", "x") as stream:
        stream.write("unexpected")
except OSError as exc:
    root_write_errno = exc.errno
record = {"uid": os.getuid(), "gid": os.getgid(),
          "cap_eff": status["CapEff"].strip(), "no_new_privs": status["NoNewPrivs"].strip(),
          "seccomp": status["Seccomp"].strip(), "root_read_only": "ro" in root_options,
          "root_write_errno": root_write_errno, "work_tmpfs": types.get("/work") == "tmpfs",
          "tmp_tmpfs": types.get("/tmp") == "tmpfs",
          "interfaces": sorted(os.listdir("/sys/class/net")),
          "memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
          "memory_swap_max": Path("/sys/fs/cgroup/memory.swap.max").read_text().strip(),
          "pids_max": Path("/sys/fs/cgroup/pids.max").read_text().strip(),
          "cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
          "docker_socket_visible": Path("/var/run/docker.sock").exists(),
          "credential_names_present": any(name in os.environ for name in
              ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")),
          "dataset_visible": any(Path(path).exists() for path in
              ("/dataset", "/checks", "/app", "/evalplus", "/work/HumanEvalPlus.jsonl")),
          "work_entries": sorted(os.listdir("/work"))}
print(json.dumps(record))
'''


def dump(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def process_env() -> dict[str, str]:
    # No inherited Docker authentication config, proxies, model keys, or home.
    config = LOCAL / "docker-client"
    config.mkdir(parents=True, exist_ok=True)
    return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8", "HOME": str(config), "DOCKER_CONFIG": str(config),
            "DOCKER_HOST": "unix:///var/run/docker.sock"}


def command(args: list[str], timeout: float = 30, *, check: bool = True) -> subprocess.CompletedProcess:
    reply = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=process_env(), check=False)
    if check and reply.returncode:
        raise RuntimeError(f"command failed ({reply.returncode}): {' '.join(args[:3])}: {reply.stderr[:500]}")
    return reply


def verify_daemon(output: Path, summary: dict) -> None:
    """Refuse Desktop/remote Docker before any image or container mutation."""
    identity = {"accepted": False, "endpoint": "unix:///var/run/docker.sock"}
    summary["docker_daemon"] = identity
    try:
        host = os.uname()
        identity.update({"host_kernel": host.release, "host_name": host.nodename,
                         "socket_resolved": str(Path("/var/run/docker.sock").resolve())})
        template = '{"name":{{json .Name}},"operating_system":{{json .OperatingSystem}},"os_type":{{json .OSType}},"kernel":{{json .KernelVersion}},"version":{{json .ServerVersion}},"root_dir":{{json .DockerRootDir}},"id":{{json .ID}}}'
        identity["server"] = json.loads(command(["docker", "info", "--format", template]).stdout)
        server = identity["server"]
        if any(token in json.dumps(server).lower() for token in ("docker desktop", "docker-desktop", "linuxkit")):
            raise RuntimeError("Docker Desktop daemon refused; native Ubuntu WSL Docker is required")
        pid = int(command(["systemctl", "show", "docker", "--property=MainPID", "--value"]).stdout.strip())
        executable = str(Path(f"/proc/{pid}/exe").resolve(strict=True)) if pid > 0 else ""
        identity.update({"local_dockerd_pid": pid, "local_dockerd_executable": executable})
        if (host.sysname != "Linux" or "microsoft" not in host.release.lower()
                or not Path("/var/run/docker.sock").is_socket()
                or identity["socket_resolved"] != "/run/docker.sock"
                or not server["operating_system"].startswith("Ubuntu 24.04")
                or server["os_type"] != "linux" or server["kernel"] != host.release
                or server["name"] != host.nodename or executable != "/usr/bin/dockerd"):
            raise RuntimeError("Docker endpoint does not match the required native Ubuntu 24.04 WSL daemon")
        identity["accepted"] = True
    except Exception as exc:
        identity["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        dump(output / "daemon.json", identity)


@contextmanager
def cleanup_without_sigint():
    """Finish bounded, exact-owner cleanup even if Ctrl-C is pressed again."""
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def prepare_assets(output: Path) -> dict:
    assets = LOCAL / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    inventory = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, (url, pinned_sha) in DOWNLOADS.items():
        path = assets / name
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "TracePilot-zero-model-environment-check"})
            # Preserve incomplete acquisitions as evidence; never load them as assets.
            partial = assets / (name + ".partial-" + uuid.uuid4().hex)
            with opener.open(request, timeout=60) as response, partial.open("xb") as stream:
                total = 0
                while chunk := response.read(1_048_576):
                    total += len(chunk)
                    if total > 128_000_000:
                        raise ValueError("asset download exceeded offline preparation limit")
                    stream.write(chunk)
            if sha(partial.read_bytes()) != pinned_sha:
                raise ValueError(f"download does not match fixed SHA256: {name}; partial retained")
            partial.rename(path)
        if sha(path.read_bytes()) != pinned_sha:
            raise ValueError(f"cached asset does not match fixed SHA256: {name}")
        inventory.append({"file": name, "url": url, "bytes": path.stat().st_size,
                          "sha256": sha(path.read_bytes())})
    lock_path = assets / "acquisition-lock.json"
    # Keep the original acquisition record unchanged; fixed script constants,
    # not this historical record, now determine acceptance on every machine.
    if not lock_path.exists():
        dump(lock_path, {"downloads": inventory, "verification": "fixed SHA256 constants in script"})
    release_tag = json.loads((assets / "evalplus-release-tag.json").read_text())
    if release_tag["ref"] != "refs/tags/v0.3.1" or release_tag["object"] != {
            "sha": COMMIT, "type": "commit",
            "url": f"https://api.github.com/repos/evalplus/evalplus/git/commits/{COMMIT}"}:
        raise ValueError("fixed release tag does not identify the pinned evaluator commit")
    version = release_tag["ref"].removeprefix("refs/tags/v")
    prefix = f"evalplus-{COMMIT}/"
    with zipfile.ZipFile(assets / "evalplus-source.zip") as archive:
        if not all(name.startswith(prefix) for name in archive.namelist()):
            raise ValueError("source archive root differs from the pinned commit")
        source_hashes = {name[len(prefix):]: sha(archive.read(name)) for name in archive.namelist()
                         if not name.endswith("/")}
        source_license = archive.read(prefix + "LICENSE")
        loader = archive.read(prefix + "evalplus/data/humaneval.py").decode()
        version_config = archive.read(prefix + "pyproject.toml").decode()
    if sha(json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()) != SOURCE_FILES_SHA:
        raise ValueError("expanded source file manifest differs from fixed SHA256")
    if '[tool.setuptools_scm]' not in version_config or 'write_to = "evalplus/_version.py"' not in version_config:
        raise ValueError("archive version configuration differs from expected SCM-derived release")
    if 'HUMANEVAL_PLUS_VERSION = "v0.1.10"' not in loader:
        raise ValueError("pinned evaluator dataset version differs")
    license_path = assets / "EvalPlus-LICENSE.txt"
    if not license_path.exists():
        license_path.write_bytes(source_license)
    if license_path.read_bytes() != source_license:
        raise ValueError("saved source license differs from archive")
    dataset_raw = gzip.decompress((assets / "HumanEvalPlus-v0.1.10.jsonl.gz").read_bytes())
    if sha(dataset_raw) != DATASET_SHA:
        raise ValueError("decompressed dataset differs from fixed SHA256")
    rows = [json.loads(line) for line in dataset_raw.splitlines() if line.strip()]
    if len(rows) != 164 or len({row["task_id"] for row in rows}) != 164:
        raise ValueError("expected 164 unique HumanEval+ tasks")
    task = next(row for row in rows if row["task_id"] == TASK)
    if task["entry_point"] != "has_close_elements":
        raise ValueError("unexpected fixed smoke task")
    # The only model-visible object is made by field allowlist, not by deleting
    # a few hidden fields from a complete dataset record.
    visible = {key: task[key] for key in ("task_id", "prompt", "entry_point")}
    if set(visible) & {"canonical_solution", "base_input", "plus_input", "contract", "atol"}:
        raise ValueError("hidden dataset fields leaked into the visible prompt")
    dump(output / "visible-task.json", visible)
    dump(output / "provenance.json", {
        "evalplus_version": version, "source_commit": COMMIT, "source_files_sha256": source_hashes,
        "source_file_manifest_sha256": SOURCE_FILES_SHA,
        "version_source": "fixed-hash official tag record; archive uses setuptools_scm and omits generated _version.py",
        "asset_verification": "fixed SHA256 for every download and expanded source/data; not publisher-signed checksums",
        "dataset_version": "HumanEval+ v0.1.10", "dataset_rows": len(rows),
        "dataset_decompressed_sha256": sha(dataset_raw), "downloads": inventory,
        "licenses": {"EvalPlus": "Apache-2.0; HumanEval-derived portions additionally MIT",
                     "HumanEvalPlus": "Apache-2.0 and underlying HumanEval MIT",
                     "source_license_sha256": sha(source_license)},
        "visible_fields": list(visible), "hidden_fields_excluded": True,
        "scope": "one fixed environment-check task; R3 sample and train/test split not selected",
    })
    return task


def prepare_image(output: Path) -> str:
    build = output / "image-build"
    build.mkdir()
    dockerfile = f"FROM {BASE}\nLABEL org.tracepilot.purpose=zero-model-coding-environment\n"
    (build / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    build_command = ["docker", "build", "--network=none", "--tag", IMAGE, str(build)]
    dump(build / "command.json", build_command)
    with (build / "stdout.txt").open("x") as stdout, (build / "stderr.txt").open("x") as stderr:
        result = subprocess.run(build_command, stdout=stdout, stderr=stderr, timeout=300,
                                env=process_env(), check=False)
    if result.returncode:
        raise RuntimeError("fixed-base Docker build failed; see image-build logs")
    image = json.loads(command(["docker", "image", "inspect", IMAGE]).stdout)[0]
    metadata = {key: image.get(key) for key in ("Id", "RepoDigests", "Architecture", "Os", "Created")}
    metadata.update({"tag": IMAGE, "base_digest": BASE, "dockerfile_sha256": sha(dockerfile.encode()),
                     "runtime_packages_installed": False, "evalplus_imported_or_executed": False})
    if metadata["Architecture"] != "amd64" or metadata["Os"] != "linux":
        raise ValueError("unexpected image architecture")
    dump(output / "image.json", metadata)
    return image["Id"]


def oracle(arguments: list) -> bool:
    """Independent, literal specification oracle for HumanEval/0 only."""
    numbers, threshold = arguments
    if (not isinstance(numbers, list) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or any(not math.isfinite(number) for number in numbers)):
        raise ValueError("fixed-task input outside supported finite-number contract")
    return any(abs(numbers[i] - numbers[j]) < threshold for i in range(len(numbers)) for j in range(i))


def run_worker(name: str, payload: bytes, timeout: float, case_dir: Path, record: dict,
               *, worker_code: str = WORKER) -> bytes:
    """Bound all three pipes of this preset-candidate smoke subprocess."""
    caps = {"stdout": 256 * 1024, "stderr": 64 * 1024}
    captured = {stream: bytearray() for stream in caps}
    observed = {stream: 0 for stream in caps}
    selector = selectors.DefaultSelector()
    process = None
    offset = 0
    started = time.monotonic()
    record.update({"timed_out": False, "output_limit_exceeded": False,
                   "output_limits_bytes": caps, "worker_cli_reaped": False})
    try:
        process = subprocess.Popen(
            ["docker", "exec", "-i", name, "python", "-I", "-S", "-c", worker_code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, env=process_env())
        record["worker_cli_pid"] = process.pid
        for stream in ("stdin", "stdout", "stderr"):
            pipe = getattr(process, stream)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_WRITE if stream == "stdin" else selectors.EVENT_READ, stream)
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                record["timed_out"] = True
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                pipe, stream = key.fileobj, key.data
                if stream == "stdin":
                    try:
                        count = os.write(pipe.fileno(), memoryview(payload)[offset:offset + 16_384])
                        offset += count
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        offset = len(payload)
                    if offset == len(payload):
                        selector.unregister(pipe)
                        pipe.close()
                else:
                    # Read at most one byte beyond the cap, never an unbounded
                    # chunk and never an unbounded host output file.
                    space = caps[stream] - len(captured[stream])
                    try:
                        chunk = os.read(pipe.fileno(), min(65_536, space + 1))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(pipe)
                        pipe.close()
                        continue
                    observed[stream] += len(chunk)
                    captured[stream].extend(chunk[:space])
                    if len(chunk) > space:
                        record["output_limit_exceeded"] = True
                        record["output_limit_stream"] = stream
                        break
            if record["output_limit_exceeded"]:
                break
        if not record["timed_out"] and not record["output_limit_exceeded"]:
            try:
                process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
    except BaseException as exc:
        record["worker_io_error_type"] = type(exc).__name__
        raise
    finally:
        # Do not use Popen's context manager: its implicit wait can hang after
        # KeyboardInterrupt or a pipe/JSON error. Kill and reap this exact CLI;
        # run_case's outer finally then removes the exact owned container.
        with cleanup_without_sigint():
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                    record["worker_cli_exit_code"] = process.returncode
                    record["worker_cli_reaped"] = process.returncode is not None
            finally:
                selector.close()
                if process is not None:
                    for stream in ("stdin", "stdout", "stderr"):
                        getattr(process, stream).close()
                record["worker_wall_s"] = time.monotonic() - started
                record["output_bytes_observed"] = observed
                record["output_bytes_retained"] = {stream: len(data) for stream, data in captured.items()}
                for stream, data in captured.items():
                    (case_dir / f"worker-{stream}.txt").write_bytes(data)
    return bytes(captured["stdout"])


def execute_isolated(label: str, source: str, entry_point: str, arguments: list,
                     image_id: str, output: Path, timeout: float, *,
                     worker_code: str = WORKER) -> tuple[dict, bytes]:
    """Run one fresh candidate container; no correctness or smoke verdict here.

    worker_code is trusted harness code supplied by callers, never a candidate
    option. The caller owns correctness; this function owns Docker and cleanup.
    """
    if not label or len(label) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in label):
        raise ValueError("invalid evidence label")
    if not math.isfinite(timeout) or not 0 < timeout <= 90:
        raise ValueError("worker timeout must be finite and in (0, 90]")
    stdout = b""
    case_dir = output / label
    case_dir.mkdir()
    name = "tracepilot-coding-" + uuid.uuid4().hex
    record = {"name": label, "container": name, "source_sha256": sha(source.encode()), "execution_ok": False, "candidate_started": False}
    cleanup = {"attempted": False, "removed": False}
    try:
        args = ["docker", "create", "--rm", "--name", name, "--network=none", "--read-only",
                "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=64",
                "--tmpfs=/work:rw,nosuid,nodev,noexec,size=16m,mode=1777",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777", "--workdir=/work",
                image_id, "python", "-I", "-S", "-c", "import time; time.sleep(120)"]
        dump(case_dir / "create-command.json", args)
        command(args)
        command(["docker", "start", name])
        inspected = json.loads(command(["docker", "inspect", name]).stdout)[0]
        host = inspected["HostConfig"]
        configuration = {key: host.get(key) for key in
                         ("NetworkMode", "ReadonlyRootfs", "CapDrop", "SecurityOpt", "Memory",
                          "MemorySwap", "NanoCpus", "PidsLimit", "Binds", "Tmpfs", "AutoRemove")}
        configuration.update({"User": inspected["Config"]["User"], "Mounts": inspected["Mounts"]})
        dump(case_dir / "container-limits.json", configuration)
        if (configuration["NetworkMode"] != "none" or not configuration["ReadonlyRootfs"]
                or configuration["CapDrop"] != ["ALL"] or "no-new-privileges" not in configuration["SecurityOpt"]
                or configuration["Memory"] != 536_870_912 or configuration["MemorySwap"] != 536_870_912
                or configuration["NanoCpus"] != 1_000_000_000 or configuration["PidsLimit"] != 64
                or configuration["AutoRemove"] is not True
                or configuration["User"] != "65534:65534" or configuration["Binds"]
                or any(mount["Type"] == "bind" for mount in configuration["Mounts"])):
            raise ValueError("Docker resource or mount isolation differs from the required configuration")
        probe = json.loads(command(["docker", "exec", name, "python", "-I", "-S", "-c", LIMIT_PROBE]).stdout)
        dump(case_dir / "actual-limits.json", probe)
        quota, period = map(int, probe["cpu_max"].split())
        if (probe["uid"] != 65534 or probe["gid"] != 65534 or int(probe["cap_eff"], 16)
                or probe["no_new_privs"] != "1" or probe["seccomp"] != "2"
                or not probe["root_read_only"] or not probe["work_tmpfs"] or not probe["tmp_tmpfs"]
                or probe["root_write_errno"] not in (errno.EROFS, errno.EACCES)
                or probe["interfaces"] != ["lo"] or probe["memory_max"] != "536870912"
                or probe["memory_swap_max"] != "0" or probe["pids_max"] != "64" or quota != period
                or probe["docker_socket_visible"] or probe["credential_names_present"]
                or probe["dataset_visible"] or probe["work_entries"]):
            raise ValueError("in-container controls or hidden-data boundary failed before candidate execution")
        payload = json.dumps({"source": source, "entry_point": entry_point}) + "\n"
        payload += "".join(json.dumps({"index": index, "arguments": item}) + "\n" for index, item in enumerate(arguments))
        record.update({"input_count": len(arguments), "expected_results_sent_to_worker": False,
                       "worker_header_fields": ["source", "entry_point"],
                       "worker_case_fields": ["index", "arguments"], "worker_sha256": sha(worker_code.encode()),
                       "limits_verified_before_code": True, "timeout_s": timeout,
                       "candidate_started": True})
        stdout = run_worker(name, payload.encode(), timeout, case_dir, record, worker_code=worker_code)
        record["execution_ok"] = record["worker_cli_reaped"]
    except KeyboardInterrupt:
        record["error"] = "KeyboardInterrupt"
        raise
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        # --rm is a daemon fallback only after PID 1 exits (including its 120s
        # watchdog). It does not replace this cleanup, particularly if create
        # succeeded but start never ran. Names are always generated here.
        with cleanup_without_sigint():
            cleanup.update({"attempted": True, "auto_remove_fallback": True,
                            "interrupt_policy": "ignore SIGINT during bounded exact-owner cleanup"})
            try:
                removed = command(["docker", "rm", "--force", name], check=False)
                cleanup["remove_exit_code"] = removed.returncode
                remaining = command(["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"], check=False)
                cleanup["removed"] = remaining.returncode == 0 and not remaining.stdout.strip()
            except Exception as exc:
                cleanup["error_type"] = type(exc).__name__
            if not cleanup["removed"]:
                record["execution_ok"] = False
            record["cleanup"] = cleanup
            dump(case_dir / "execution.json", record)
    return record, stdout



def run_case(label: str, source: str, task: dict, image_id: str, output: Path, timeout: float) -> dict:
    """Keep the original HumanEval/0 preset smoke verdict separate from execution."""
    arguments = task["base_input"] + task["plus_input"]
    expected = [oracle(item) for item in arguments]
    try:
        record, stdout = execute_isolated(label, source, task["entry_point"], arguments,
                                         image_id, output, timeout)
    except KeyboardInterrupt:
        # Preserve the smoke's original interruption artifact in addition to
        # the reusable execution evidence written after exact-owner cleanup.
        record = json.loads((output / label / "execution.json").read_text())
        record["passed"] = False
        dump(output / label / "check.json", record)
        raise
    record.update({"passed": False, "base_inputs": len(task["base_input"]),
                   "plus_inputs": len(task["plus_input"])})
    try:
        if not record["execution_ok"]:
            return record
        if record["output_limit_exceeded"]:
            record["passed"] = label == f"{record['output_limit_stream']}-flood"
            record["judge_result"] = "output_limit"
        elif record["timed_out"]:
            record["passed"] = label == "infinite-loop"
            record["judge_result"] = "timeout"
        else:
            rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            if len(rows) != len(expected) or any(row.get("index") != index for index, row in enumerate(rows)):
                raise ValueError("worker returned incomplete or forged result sequence")
            correct = [row.get("value") is value and "error_type" not in row for row, value in zip(rows, expected)]
            record["correct_inputs"] = sum(correct)
            record["judge_result"] = "pass" if all(correct) else "fail"
            record["passed"] = (label == "canonical" and all(correct)) or (label == "known-wrong" and not all(correct))
            if record["worker_cli_exit_code"] != 0:
                record["passed"] = False
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        dump(output / label / "check.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true")
    args = parser.parse_args()
    output = LOCAL / "runs" / uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    summary = {"scope": "zero-model environment and external-judge smoke only", "output": str(output),
               "created_at": datetime.now(timezone.utc).isoformat(), "model_calls": 0, "api_spend_cny": "0",
               "r3_r4_experiment_completed": False, "script_sha256": sha(Path(__file__).read_bytes()),
               "preparation_boundaries": PREPARATION_BOUNDARIES,
               "cases": [], "passed": False}
    try:
        task = prepare_assets(output)
        if args.assets_only:
            summary["passed"] = True
            summary["assets_only"] = True
        else:
            verify_daemon(output, summary)
            summary["docker_server_version"] = summary["docker_daemon"]["server"]["version"]
            image_id = prepare_image(output)
            canonical = task["prompt"] + task["canonical_solution"]
            wrong = 'def has_close_elements(numbers, threshold):\n    print("{\\\"passed\\\": true}")\n    return False\n'
            infinite = "def has_close_elements(numbers, threshold):\n    while True:\n        pass\n"
            flood = "def has_close_elements(numbers, threshold):\n    import os\n    while True:\n        os.write({fd}, b'x' * 16384)\n"
            for label, source, timeout in (("canonical", canonical, 30), ("known-wrong", wrong, 30),
                                            ("infinite-loop", infinite, 2),
                                            ("stdout-flood", flood.format(fd=1), 10),
                                            ("stderr-flood", flood.format(fd=2), 10)):
                result = run_case(label, source, task, image_id, output, timeout)
                summary["cases"].append(result)
                print(json.dumps({"case": label, "passed": result["passed"], "output": str(output)}, ensure_ascii=False), flush=True)
                if not result["cleanup"]["removed"]:
                    break
            summary["passed"] = len(summary["cases"]) == 5 and all(case["passed"] for case in summary["cases"])
    except KeyboardInterrupt:
        summary["error"] = "KeyboardInterrupt"
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        dump(output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
