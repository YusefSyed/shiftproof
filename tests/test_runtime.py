import json

import pytest

from shiftproof import config
from shiftproof.config import RuntimeUnavailable
from shiftproof.worker import sanitized_environment_from_payload


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11435",
        "http://localhost:11435",
        "http://10.0.0.1:11435",
        "http://127.0.0.1:11435?token=fake",
        "http://fake:secret@127.0.0.1:11435",
    ],
)
def test_endpoint_policy_rejects_non_dedicated_urls(url):
    with pytest.raises(RuntimeUnavailable):
        config.validate_endpoint(url)


def test_sanitized_environment_drops_credentials_and_forces_local_policy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-aws")
    monkeypatch.setenv("HTTPS_PROXY", "http://fake-proxy")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://fake-telemetry")
    environment = config.sanitized_environment()
    assert not {
        "OPENAI_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "HTTPS_PROXY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    } & set(environment)
    assert environment["OLLAMA_NO_CLOUD"] == "1"
    assert environment["OLLAMA_HOST"] == "127.0.0.1:11435"
    assert environment["OTEL_SDK_DISABLED"] == "true"


def test_local_client_disables_environment_and_redirects():
    with config.local_client() as client:
        assert client._trust_env is False
        assert client.follow_redirects is False


@pytest.mark.parametrize(
    "model,details",
    [
        (
            {
                "name": config.MODEL_TAG,
                "size": 2_000_000_000,
                "digest": "a" * 64,
                "remote_host": "fake",
            },
            {"capabilities": ["tools"]},
        ),
        (
            {"name": config.MODEL_TAG, "size": 2_000_000_000, "digest": "a" * 64},
            {"capabilities": [], "remote_model": "fake"},
        ),
        ({"name": config.MODEL_TAG, "size": 1, "digest": "a" * 64}, {"capabilities": ["tools"]}),
        (
            {"name": config.MODEL_TAG, "size": 2_000_000_000, "digest": "bad"},
            {"capabilities": ["tools"]},
        ),
    ],
)
def test_inspect_local_model_rejects_unapproved_metadata(monkeypatch, model, details):
    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            pass

        def json(self):
            return self.value

    class Client:
        def get(self, _):
            return Response({"models": [model]})

        def post(self, _, json):
            return Response(details)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(config, "local_client", lambda: Client())
    with pytest.raises(RuntimeUnavailable):
        config.inspect_local_model()


def test_validate_runtime_rejects_lock_mismatch_without_network(monkeypatch, tmp_path):
    owner = tmp_path / "owner.json"
    lock = tmp_path / "runtime-model.json"
    owner.write_text(
        json.dumps({"cloud_disabled": True, "endpoint": config.OLLAMA_URL, "daemon_pid": 123})
    )
    lock.write_text(json.dumps({"model_id": config.MODEL_TAG, "digest": "a" * 64}))
    monkeypatch.setattr(config, "OWNER_FILE", owner)
    monkeypatch.setattr(config, "MODEL_LOCK", lock)
    monkeypatch.setattr(config.os, "kill", lambda *_: None)
    monkeypatch.setattr(
        config, "inspect_local_model", lambda: {"model_id": config.MODEL_TAG, "digest": "b" * 64}
    )
    with pytest.raises(RuntimeUnavailable):
        config.validate_runtime()


def test_worker_environment_filters_unapproved_keys():
    environment = sanitized_environment_from_payload(
        {"PATH": "/fake", "OPENAI_API_KEY": "fake", "HTTPS_PROXY": "fake", "OLLAMA_NO_CLOUD": "1"}
    )
    assert environment == {"PATH": "/fake", "OLLAMA_NO_CLOUD": "1"}
