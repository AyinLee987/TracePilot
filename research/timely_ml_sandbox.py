"""Docker execution boundary for the unchanged upstream ML evaluation loop.

One container per episode; /work is a bounded, persistent in-memory filesystem.
Only public data is mounted. The host accepts a bounded regular submission file.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json
from pathlib import Path
import time
import uuid

ACTIVE: ContextVar = ContextVar("timely_ml_sandbox")
LIMIT = 16 * 1024 * 1024


async def command(*args, stdin=None, timeout=30, limit=LIMIT):
    process = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def read(stream):
        kept = bytearray()
        overflow = False
        while chunk := await stream.read(65536):
            if len(kept) + len(chunk) > limit:
                overflow = True
            kept.extend(chunk[:max(0, limit - len(kept))])
        return bytes(kept), overflow

    async def write():
        if stdin is not None:
            try:
                process.stdin.write(stdin)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

    tasks = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr)),
             asyncio.create_task(write()), asyncio.create_task(process.wait())]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        return process.returncode, results[0][0], results[1][0], results[0][1] or results[1][1]
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Sandbox:
    def __init__(self, image: str, public: Path, directory: Path):
        self.image, self.public, self.directory = image, public.resolve(), directory.resolve()
        self.name = "tracepilot-ml-" + uuid.uuid4().hex
        self.live = False
        self.attempt = 0
        self.records = []
        self.directory.mkdir(parents=True, exist_ok=False)

    async def start(self):
        if self.live:
            return
        # Mark ownership before launch so cancellation also cleans a partially created container.
        self.live = True
        result = await command("docker", "run", "-d", "--name", self.name, "--rm",
            "--label", "tracepilot.experiment=timely-ml", "--shm-size", "256m",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "1000:1000", "--cpus", "2", "--memory", "4g", "--memory-swap", "4g",
            "--pids-limit", "128", "--ulimit", "nofile=256:256", "--ulimit", "fsize=134217728:134217728",
            "--tmpfs", "/work:rw,nosuid,nodev,size=2g,mode=1777", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
            "--mount", f"type=bind,src={self.public},dst=/work/data/public,readonly",
            "--env", "KAGGLE_DATA_DIR=/work/data", "--env", "HOME=/tmp", "--workdir", "/work",
            self.image, "python", "-c", "import time; time.sleep(1200)")
        if result[0] != 0:
            raise RuntimeError("ML container startup failed: " + result[2].decode(errors="replace")[:1000])

    async def close(self):
        if not self.live:
            return
        await command("docker", "rm", "-f", self.name)
        rc, output, _, _ = await command("docker", "ps", "-a", "--filter", f"name=^/{self.name}$", "--format", "{{.ID}}")
        if rc != 0 or output.strip():
            from timely_batch import ProcessCleanupError
            raise ProcessCleanupError("ML container cleanup unverified")
        self.live = False

    async def execute(self, code, *, timeout=180, **unused):
        from timely_eval.ml_sandbox import ExecutionResult
        self.attempt += 1
        index = self.attempt
        (self.directory / f"code-{index:02}.py").write_text(code, encoding="utf-8")
        started = time.perf_counter()
        await self.start()
        timed_out = False
        submission = None
        try:
            rc, out, err, overflow = await command("docker", "exec", "-i", self.name, "python", "-",
                stdin=code.encode(), timeout=timeout, limit=65536)
        except asyncio.TimeoutError:
            timed_out, rc, out, err = True, -1, b"", b"Code execution timed out."
            await self.close()
        if not timed_out:
            # stdout is diagnostic only. Truncation does not change the return code.
            if rc == 0:
                # Docker cp does not reliably read files on container tmpfs mounts.
                # Isolated Python ignores user-site imports; O_NOFOLLOW rejects links.
                exporter = ("import os,stat,sys; f=os.open('/work/submission.csv',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK); "
                    "s=os.fstat(f); assert stat.S_ISREG(s.st_mode) and s.st_size<=16777216; "
                    "data=os.read(f,16777217); assert len(data)<=16777216; sys.stdout.buffer.write(data)")
                copied, raw, copyerr, large = await command("docker", "exec", self.name, "python", "-I", "-c", exporter, limit=LIMIT)
                if copied == 0 and not large:
                    target = self.directory / f"submission-{index:02}.csv"
                    target.write_bytes(raw)
                    submission = str(target)
        result = ExecutionResult(rc, out.decode(errors="replace"), err.decode(errors="replace"),
                                 timed_out, str(self.directory), time.perf_counter() - started, submission)
        self.records.append({"attempt":index, "returncode":rc, "timeout":timed_out,
            "possible_resource_limit":rc in (125,126,137) or any(x in result.stderr for x in ("can't start new thread","Too many open files","Cannot allocate memory","No space left")),
            "execution_time_clock":"guest monotonic diagnostic; not deadline eligibility",
            "execution_time":result.execution_time, "submission_path":submission,
            "stdout":result.stdout, "stderr":result.stderr})
        (self.directory / "executions.json").write_text(json.dumps(self.records, indent=2), encoding="utf-8")
        return result


async def execute_in_context(code, **kwargs):
    return await ACTIVE.get().execute(code, **kwargs)
