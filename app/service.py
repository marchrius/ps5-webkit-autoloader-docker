"""Exit on child failure so Docker restarts DNS and web as one service."""
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from healthcheck import check
from settings import Settings


def main():
    settings = Settings.load()
    conf = Path("/run/dnsmasq.conf")
    conf.write_text(settings.dnsmasq_config())
    subprocess.run(["dnsmasq", "--test", f"--conf-file={conf}"], check=True)
    print(f"DNS {settings.mode}; redirect to {settings.host_ip}; "
          f"{len(settings.blocked)} blocked suffixes", flush=True)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    children = []
    result = 0
    try:
        children.append(subprocess.Popen(["dnsmasq", "--keep-in-foreground", f"--conf-file={conf}"]))
        children.append(subprocess.Popen([sys.executable, "/app/web.py"]))
        next_check = time.monotonic() + 15
        failures = 0
        while not stop.wait(1):
            if any(child.poll() is not None for child in children):
                print("A service exited; container restart required", flush=True)
                result = 1
                break
            if time.monotonic() >= next_check:
                try:
                    check()
                    failures = 0
                except Exception as exc:
                    failures += 1
                    print(f"Service healthcheck failed ({failures}/3): {exc}", flush=True)
                if failures >= 3:
                    result = 1
                    break
                next_check = time.monotonic() + 20
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return result


if __name__ == "__main__":
    sys.exit(main())
