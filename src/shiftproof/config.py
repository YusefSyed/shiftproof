"""Fixed local runtime policy. User data cannot select an endpoint or provider."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
MODEL_LOCK = ROOT / "runtime-model.json"
OWNER_FILE = WORKSPACE / "runtime-owner.json"
MODEL_TAG = "qwen3.5:9b-q4_K_M"
OLLAMA_URL = "http://127.0.0.1:11435"
APP_HOST = "127.0.0.1"
APP_PORT = 8000
MAX_MODEL_ROUNDS = 8
MAX_TOOL_CALLS = 12
MAX_SOLVES = 3
WORKER_DEADLINE = 180.0


class RuntimeUnavailable(RuntimeError):
    pass


def validate_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != ("http", "127.0.0.1:11435"):
        raise RuntimeUnavailable("Only the dedicated localhost Ollama endpoint is permitted.")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RuntimeUnavailable("Endpoint parameters and credentials are not permitted.")


def local_client() -> httpx.Client:
    validate_endpoint(OLLAMA_URL)
    return httpx.Client(base_url=OLLAMA_URL, trust_env=False, follow_redirects=False, timeout=5)


def sanitized_environment() -> dict[str, str]:
    allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME", "SYSTEMROOT")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result.update({"OLLAMA_NO_CLOUD": "1", "OLLAMA_HOST": "127.0.0.1:11435",
                   "OTEL_SDK_DISABLED": "true", "AWS_EC2_METADATA_DISABLED": "true",
                   "PYTHONUNBUFFERED": "1"})
    return result


def inspect_local_model() -> dict[str, str]:
    with local_client() as client:
        response = client.get("/api/tags")
        response.raise_for_status()
        matches = [m for m in response.json().get("models", []) if m.get("name") == MODEL_TAG]
        if len(matches) != 1:
            raise RuntimeUnavailable("The approved local Qwen model is missing. No fallback is used.")
        model = matches[0]
        if model.get("size", 0) < 1_000_000_000 or "cloud" in MODEL_TAG.lower():
            raise RuntimeUnavailable("A full local model is required.")
        response = client.post("/api/show", json={"model": MODEL_TAG})
        response.raise_for_status()
        details = response.json()
    for source in (model, details, model.get("details", {}), details.get("details", {})):
        if source.get("remote_host") or source.get("remote_model"):
            raise RuntimeUnavailable("Remote model metadata is prohibited.")
    if "tools" not in details.get("capabilities", []):
        raise RuntimeUnavailable("The local model does not report tool capability.")
    digest = model.get("digest", "")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeUnavailable("The model digest could not be verified.")
    return {"model_id": MODEL_TAG, "digest": digest,
            "quantization": model.get("details", {}).get("quantization_level", ""),
            "parameter_size": model.get("details", {}).get("parameter_size", ""),
            "endpoint": OLLAMA_URL}


def validate_runtime(*, require_owner: bool = True) -> dict[str, str]:
    if require_owner:
        try:
            owner = json.loads(OWNER_FILE.read_text())
            if owner.get("cloud_disabled") is not True or owner.get("endpoint") != OLLAMA_URL:
                raise ValueError
            pid = owner["daemon_pid"]
            if type(pid) is not int or pid <= 1:
                raise ValueError
            os.kill(pid, 0)
        except (OSError, ValueError, KeyError):
            raise RuntimeUnavailable("Start the owned local runtime with scripts/run_local.py.") from None
    try:
        expected = json.loads(MODEL_LOCK.read_text())
    except (OSError, ValueError):
        raise RuntimeUnavailable("The local model lock is missing or invalid.") from None
    try:
        actual = inspect_local_model()
    except httpx.HTTPError:
        raise RuntimeUnavailable("The local model server is unavailable. No cloud fallback is used.") from None
    if actual != expected:
        raise RuntimeUnavailable("Local model metadata differs from the reviewed runtime lock.")
    return actual


def runtime_status() -> dict[str, Any]:
    try:
        lock = validate_runtime()
        return {"ready": True, "tag": lock["model_id"], "detail": "Local model verified; cloud disabled."}
    except (RuntimeUnavailable, OSError) as exc:
        return {"ready": False, "tag": MODEL_TAG, "detail": str(exc)}


def install_worker_network_guard() -> None:
    """Deny non-model TCP destinations inside a dedicated worker process."""
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    sendto = socket.socket.sendto

    def check(address: Any) -> None:
        if isinstance(address, tuple) and address[:2] not in (("127.0.0.1", 11435), ("::1", 11435)):
            raise RuntimeUnavailable("Outbound destination denied by the local-only policy.")

    def guarded_connect(sock, address):
        check(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    def guarded_sendto(sock, data, *args):
        if args:
            check(args[-1])
        return sendto(sock, data, *args)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.socket.sendto = guarded_sendto  # type: ignore[method-assign]
