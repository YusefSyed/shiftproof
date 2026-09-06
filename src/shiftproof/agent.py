"""Bounded real Strands agent; no scripted solver fallback or hosted provider."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
)
from strands.tools.executors import SequentialToolExecutor

from shiftproof.config import MAX_MODEL_ROUNDS, MAX_TOOL_CALLS
from shiftproof.preflight import make_model
from shiftproof.tools import TOOL_NAMES, ToolContext, make_tools


class BudgetHooks(HookProvider):
    def __init__(self, context: ToolContext):
        self.context = context
        self.rounds = 0
        self.attempts = 0
        self.invalid = 0
        self.round_started = 0.0

    def register_hooks(self, registry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_model(self, event) -> None:
        self.rounds += 1
        self.round_started = time.monotonic()
        # Conservative byte ceiling with separately reserved tool/system/template space.
        # Runtime context is 32768; this bound prevents silent history reduction.
        history_bytes = len(json.dumps(event.agent.messages, ensure_ascii=True).encode())
        if self.rounds > MAX_MODEL_ROUNDS or history_bytes > 20000 or self.context.abort_reason:
            self.context.abort_reason = self.context.abort_reason or "Local context/action budget reached."
            event.cancel = self.context.abort_reason
        self.context.emit({"type": "model_round", "status": "running", "detail": f"Model round {self.rounds}"})

    def after_model(self, event) -> None:
        self.context.emit({"type": "model_end", "status": "failed" if event.exception else "complete",
                           "duration": round(time.monotonic() - self.round_started, 3),
                           "detail": f"Model round {self.rounds}"})

    def before_tool(self, event) -> None:
        self.attempts += 1
        name = event.tool_use.get("name")
        if self.attempts > MAX_TOOL_CALLS or name not in TOOL_NAMES or self.context.abort_reason:
            event.cancel_tool = "Tool is not permitted or the local action budget was reached."

    def after_tool(self, event) -> None:
        if event.result.get("status") == "error":
            self.invalid += 1
            if self.invalid > 1:
                self.context.abort_reason = "The model made repeated invalid tool requests."


def run_agent(context: ToolContext, request: str, lock: dict[str, str]) -> dict:
    prompt = (Path(__file__).parent / "prompts" / "coordinator.txt").read_text()
    model = make_model(lock)
    model.config["options"] = {"num_ctx": 32768, "seed": 7}
    agent = Agent(model=model, tools=make_tools(context), tool_executor=SequentialToolExecutor(),
                  system_prompt=prompt, conversation_manager=NullConversationManager(),
                  hooks=[BudgetHooks(context)], callback_handler=None,
                  plugins=[], load_tools_from_directory=False)
    agent(request)
    payload = context.payload()
    if not payload["results"] and not payload["proposals"]:
        payload["error"] = "NO_VERIFIED_RESULT: no computed result or typed proposal was produced."
    return payload
