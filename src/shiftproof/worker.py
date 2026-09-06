"""A cancellable local child process has tools, but no parent approval capability."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
import uuid

from shiftproof.config import WORKER_DEADLINE, sanitized_environment
from shiftproof.models import Assignment, Case


def execute(send, payload: dict) -> None:
    os.environ.clear()
    os.environ.update(sanitized_environment_from_payload(payload["environment"]))
    try:
        from shiftproof.agent import run_agent
        from shiftproof.config import install_worker_network_guard, validate_runtime
        from shiftproof.tools import ToolContext

        install_worker_network_guard()
        lock = validate_runtime()
        case = Case.model_validate(payload["case"])
        baseline = tuple(Assignment.model_validate(a) for a in payload["baseline"])

        def emit(event: dict) -> None:
            send.send(json.dumps({"kind": "event", "event": event}))

        context = ToolContext(case, baseline, emit, payload.get("prior"))
        result = run_agent(context, payload["request"], lock)
        send.send(json.dumps({"kind": "complete", "payload": result}))
    except Exception as exc:
        # Do not transmit exception strings which may contain user input or local paths.
        send.send(json.dumps({"kind": "complete", "payload": {
            "results": [], "proposals": [], "review_result_id": None,
            "error": f"Local run stopped ({type(exc).__name__}). No cloud fallback was used."}}))
    finally:
        send.close()


def sanitized_environment_from_payload(environment: dict) -> dict[str, str]:
    allowed = {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME", "SYSTEMROOT",
               "OLLAMA_NO_CLOUD", "OLLAMA_HOST", "OTEL_SDK_DISABLED", "AWS_EC2_METADATA_DISABLED",
               "PYTHONUNBUFFERED"}
    return {k: v for k, v in environment.items() if k in allowed and isinstance(v, str)}


class Job:
    def __init__(self, case: Case, baseline: tuple[Assignment, ...], request: str, prior: dict):
        self.run_id = "RUN_" + uuid.uuid4().hex[:16]
        self.case_hash = case.case_hash
        self.baseline = baseline
        self.started = time.monotonic()
        self.done = False
        context = mp.get_context("spawn")
        self.receive, send = context.Pipe(duplex=False)
        payload = {"case": case.model_dump(mode="json"),
                   "baseline": [a.model_dump() for a in baseline], "request": request,
                   "prior": prior, "environment": sanitized_environment()}
        self.process = context.Process(target=execute, args=(send, payload), daemon=True)
        self.process.start()
        send.close()

    def poll(self) -> list[dict]:
        messages = []
        try:
            while self.receive.poll():
                value = self.receive.recv()
                if not isinstance(value, str) or len(value) > 2_000_000:
                    raise ValueError("Invalid worker envelope.")
                messages.append(json.loads(value))
                if messages[-1].get("kind") == "complete":
                    self.done = True
        except EOFError:
            pass
        if not self.done and time.monotonic() - self.started > WORKER_DEADLINE:
            self.cancel()
            messages.append({"kind": "complete", "payload": {"results": [], "proposals": [],
                "review_result_id": None, "error": "Local worker deadline reached. Result undetermined."}})
        elif not self.done and not self.process.is_alive():
            self.done = True
            messages.append({"kind": "complete", "payload": {"results": [], "proposals": [],
                "review_result_id": None, "error": "Local worker stopped without a verified result."}})
        return messages

    def cancel(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
        self.done = True

    def close(self) -> None:
        self.process.join(timeout=0.2)
        if self.process.is_alive():
            self.cancel()
        self.receive.close()
