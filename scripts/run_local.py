"""Own a cloud-disabled local daemon and web app. Never attach to or kill another service."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shiftproof.config import (  # noqa: E402
    APP_PORT,
    MODEL_LOCK,
    OLLAMA_URL,
    OWNER_FILE,
    WORKSPACE,
    inspect_local_model,
    sanitized_environment,
    validate_runtime,
)


def free_port(port: int) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def stop_owned(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    free_port(11435)
    free_port(APP_PORT)
    ollama = shutil.which("ollama")
    if not ollama:
        raise SystemExit("Ollama is not installed. No hosted fallback is available.")
    WORKSPACE.mkdir(exist_ok=True)
    env = sanitized_environment()
    sandbox = Path("/usr/bin/sandbox-exec")
    prefix = [str(sandbox), "-f", str(ROOT / "scripts" / "local-only.sb")] if sandbox.is_file() else []
    daemon = None
    server = None
    try:
        with (WORKSPACE / "ollama.log").open("w") as log:
            daemon = subprocess.Popen(prefix + [ollama, "serve"], env=env, cwd=ROOT,
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            ready = False
            for _ in range(100):
                if daemon.poll() is not None:
                    raise RuntimeError("Owned Ollama did not start. Inspect workspace/ollama.log locally.")
                try:
                    inspect_local_model()
                    if "Ollama cloud disabled: true" in (WORKSPACE / "ollama.log").read_text():
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            if not ready:
                raise RuntimeError("Could not verify the owned cloud-disabled model server.")
            OWNER_FILE.write_text(json.dumps({"daemon_pid": daemon.pid, "endpoint": OLLAMA_URL,
                "cloud_disabled": True, "process_egress_restricted": bool(prefix)}, indent=2) + "\n")
            if not MODEL_LOCK.exists():
                MODEL_LOCK.write_text(json.dumps(inspect_local_model(), indent=2) + "\n")
            validate_runtime()
            server = subprocess.Popen(prefix + [sys.executable, "-m", "uvicorn", "shiftproof.server:app",
                                       "--host", "127.0.0.1", "--port", str(APP_PORT)],
                                      env=env, cwd=ROOT, stdin=subprocess.DEVNULL)
            print(f"ShiftProof: http://127.0.0.1:{APP_PORT}", flush=True)
            print("Local inference only. Cloud disabled. Ctrl-C stops only these owned processes.", flush=True)
            while server.poll() is None and daemon.poll() is None:
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop_owned(server)
        stop_owned(daemon)
        if OWNER_FILE.exists():
            OWNER_FILE.unlink()


if __name__ == "__main__":
    main()
