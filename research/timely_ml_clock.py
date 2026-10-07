"""Read-only host clock bridge: Windows monotonic time for WSL ML deadlines.

The service exposes timestamps only. It exits after 10 idle minutes.
No scaling factor is fitted and no historical timestamps are modified.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
INFO = ROOT / ".local/timely-ml-host-clock.json"
_settings = None
STATS = {"reads":0,"retries":0,"max_guest_round_trip_s":0.0}


def configure():
    global _settings
    _settings = json.loads(INFO.read_text())
    return _settings


def now():
    if _settings is None:
        raise RuntimeError("host clock not configured")
    for attempt in range(3):
        start = time.perf_counter()
        try:
            with socket.create_connection((_settings["host"], _settings["port"]), timeout=0.1) as connection:
                raw = b""
                while len(raw) < 48:
                    part = connection.recv(48-len(raw))
                    if not part:
                        raise OSError("host clock disconnected")
                    raw += part
            identity, monotonic, wall = struct.unpack("!32sdd", raw)
            if identity.decode() != _settings["identity"]:
                raise RuntimeError("host clock identity changed")
            elapsed=time.perf_counter()-start
            STATS["reads"] += 1
            STATS["max_guest_round_trip_s"] = max(STATS["max_guest_round_trip_s"],elapsed)
            if elapsed <= 0.1:
                return monotonic
        except OSError:
            pass
        STATS["retries"] += 1
    raise RuntimeError("host clock unavailable or too slow after three reads")


class HostTimer:
    def __init__(self, mode="eval"):
        if mode != "eval":
            raise ValueError("ML host clock supports real elapsed time only")
        self.started = None

    def start(self):
        self.started = now()

    def call(self, return_format="text"):
        duration = now()-self.started
        if duration < 0:
            raise RuntimeError("host clock reversed")
        return duration if return_format=="value" else f"{duration:.2f} seconds."


def serve(host):
    if os.name != "nt":
        raise RuntimeError("clock service must run on Windows")
    identity = uuid.uuid4().hex
    with socket.socket() as listener:
        listener.bind((host,0))
        listener.listen(32)
        listener.settimeout(600)
        info={"host":host,"port":listener.getsockname()[1],"identity":identity,"pid":os.getpid(),
              "clock":"Windows time.perf_counter", "started_wall":time.time()}
        INFO.write_text(json.dumps(info,indent=2))
        print(json.dumps(info),flush=True)
        while True:
            try:
                connection,_=listener.accept()
            except socket.timeout:
                return
            with connection:
                connection.settimeout(1)
                try:
                    connection.sendall(struct.pack("!32sdd",identity.encode(),time.perf_counter(),time.time()))
                except OSError:
                    pass


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-host",required=True)
    serve(parser.parse_args().serve_host)
