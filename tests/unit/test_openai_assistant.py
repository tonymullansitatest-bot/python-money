import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest
from openai import APIConnectionError, OpenAI

from finance_manager.infrastructure.openai_assistant import (
    MAX_PROMPT_LENGTH,
    AssistantError,
    OpenAIAssistant,
)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    client = MagicMock()
    constructor = MagicMock()
    constructor.return_value.__enter__.return_value = client
    monkeypatch.setattr(
        "finance_manager.infrastructure.openai_assistant.OpenAI", constructor
    )
    return constructor, client


def test_request_sends_only_manual_text_and_disables_response_storage(api):
    constructor, client = api
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text="  Explanation  "
    )
    assert OpenAIAssistant().ask("  Explain interest  ") == "Explanation"
    constructor.assert_called_once_with(
        base_url="https://api.openai.com/v1", timeout=45.0, max_retries=0
    )
    request = client.responses.create.call_args.kwargs
    assert request["input"] == "Explain interest"
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert "tools" not in request


def test_validation_prevents_requests_and_handles_missing_key(api, monkeypatch):
    constructor, _ = api
    with pytest.raises(AssistantError, match="Enter"):
        OpenAIAssistant().ask(" ")
    with pytest.raises(AssistantError, match="at most"):
        OpenAIAssistant().ask("x" * (MAX_PROMPT_LENGTH + 1))
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(AssistantError, match="OPENAI_API_KEY"):
        OpenAIAssistant().ask("Explain interest")
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output_text="partial"),
        SimpleNamespace(status="completed", output_text=""),
    ],
)
def test_unusable_response_is_reported(api, response):
    _, client = api
    client.responses.create.return_value = response
    with pytest.raises(AssistantError):
        OpenAIAssistant().ask("Explain interest")


def test_connection_error_does_not_expose_exception_details(api):
    _, client = api
    client.responses.create.side_effect = APIConnectionError(request=MagicMock())
    with pytest.raises(AssistantError, match="Could not connect"):
        OpenAIAssistant().ask("Explain interest")


def test_sdk_request_uses_mock_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "test-response",
                "object": "response",
                "created_at": 0,
                "model": "test-model",
                "status": "completed",
                "output": [{
                    "id": "message",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{
                        "type": "output_text", "text": "Test answer", "annotations": []
                    }],
                }],
            },
        )

    def client_factory(**kwargs):
        return OpenAI(
            http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
            **kwargs,
        )

    monkeypatch.setattr(
        "finance_manager.infrastructure.openai_assistant.OpenAI", client_factory
    )
    assert OpenAIAssistant().ask("Explain interest") == "Test answer"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.openai.com/v1/responses"
    body = json.loads(requests[0].content)
    assert body["input"] == "Explain interest"
    assert body["store"] is False
