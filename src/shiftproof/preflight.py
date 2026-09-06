"""Check the exact installed model and perform a genuine Strands tool round trip."""

from __future__ import annotations

import argparse
import json
import time
import uuid

from strands import Agent, tool
from strands.agent.conversation_manager import NullConversationManager
from strands.models.ollama import OllamaModel
from strands.tools.executors import SequentialToolExecutor

from shiftproof.config import (
    MODEL_LOCK,
    OLLAMA_URL,
    WORKSPACE,
    inspect_local_model,
    install_worker_network_guard,
    validate_runtime,
)


def make_model(lock: dict[str, str], *, max_tokens: int = 1536) -> OllamaModel:
    return OllamaModel(host=OLLAMA_URL, model_id=lock["model_id"], temperature=0,
                       max_tokens=max_tokens, options={"num_ctx": 8192, "seed": 7},
                       additional_args={"think": False},
                       ollama_client_args={"trust_env": False, "follow_redirects": False,
                                           "timeout": 60.0})


def smoke_test(lock: dict[str, str]) -> dict:
    nonce = uuid.uuid4().hex
    calls: list[str] = []

    @tool
    def inspect_case() -> dict:
        """Read the test case and its fresh verification nonce."""
        calls.append("inspect_case")
        return {"nonce": nonce, "required_slots": 8}

    agent = Agent(model=make_model(lock, max_tokens=256), tools=[inspect_case],
                  tool_executor=SequentialToolExecutor(), conversation_manager=NullConversationManager(),
                  system_prompt="Call inspect_case exactly once. Report its nonce verbatim. No other task.",
                  callback_handler=None)
    started = time.monotonic()
    result = str(agent("Inspect the test case and report its nonce."))
    if calls != ["inspect_case"] or nonce not in result:
        raise RuntimeError("The real local Strands tool-use round trip did not pass.")
    return {"passed": True, "tool_calls": calls, "nonce_returned": True,
            "elapsed_seconds": round(time.monotonic() - started, 3), "model": lock,
            "scope": "One real nonce-bearing tool round trip, not a full workflow evaluation."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pin", action="store_true", help="Pin the approved already-installed model.")
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    if args.pin:
        lock = inspect_local_model()
        if MODEL_LOCK.exists() and json.loads(MODEL_LOCK.read_text()) != lock:
            raise RuntimeError("Refusing to overwrite a different model lock.")
        MODEL_LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    lock = validate_runtime()
    if args.inventory_only:
        print(json.dumps({"ready": True, "model": lock}, indent=2))
        return
    install_worker_network_guard()
    result = smoke_test(lock)
    WORKSPACE.mkdir(exist_ok=True)
    (WORKSPACE / "preflight.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
