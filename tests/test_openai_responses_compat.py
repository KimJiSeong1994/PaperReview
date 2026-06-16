"""Compatibility tests for GPT-5-family Responses routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.utils.openai_responses_compat import create_chat_completion


def test_gpt5_family_routes_real_like_client_to_responses_api():
    class _Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text='{"ok": true}', usage={"total_tokens": 3})

    client = SimpleNamespace(responses=_Responses(), chat=MagicMock())

    response = create_chat_completion(
        client,
        model="gpt-5.5",
        messages=[{"role": "user", "content": "Return JSON"}],
        response_format={"type": "json_object"},
        max_tokens=20,
        temperature=0.2,
    )

    assert client.responses.kwargs["model"] == "gpt-5.5"
    assert client.responses.kwargs["input"] == [{"role": "user", "content": "Return JSON"}]
    assert client.responses.kwargs["text"] == {"format": {"type": "json_object"}}
    assert client.responses.kwargs["max_output_tokens"] == 20
    assert client.responses.kwargs["reasoning"] == {"effort": "low"}
    assert response.choices[0].message.content == '{"ok": true}'
    assert not client.chat.completions.create.called


def test_gpt5_mini_uses_minimal_reasoning_for_speed():
    class _Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text="{}")

    client = SimpleNamespace(responses=_Responses(), chat=MagicMock())

    create_chat_completion(
        client,
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Classify"}],
    )

    assert client.responses.kwargs["reasoning"] == {"effort": "none"}


def test_mock_or_non_gpt5_clients_stay_on_chat_completions():
    client = MagicMock()
    client.chat.completions.create.return_value = "chat-response"

    assert create_chat_completion(client, model="gpt-5.5", messages=[]) == "chat-response"
    client.chat.completions.create.assert_called_once_with(model="gpt-5.5", messages=[])


def test_responses_adapter_maps_max_completion_tokens():
    class _Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text="{}")

    client = SimpleNamespace(responses=_Responses(), chat=MagicMock())

    create_chat_completion(
        client,
        model="gpt-5.4",
        messages=[{"role": "user", "content": "Build curriculum"}],
        max_completion_tokens=4096,
    )

    assert client.responses.kwargs["max_output_tokens"] == 4096


def test_streaming_adapter_skips_terminal_full_text_events():
    class _Responses:
        def create(self, **_kwargs):
            return iter([
                SimpleNamespace(type="response.output_text.delta", delta="Hel"),
                SimpleNamespace(type="response.output_text.delta", delta="lo"),
                SimpleNamespace(type="response.output_text.done", text="Hello"),
                SimpleNamespace(type="response.completed"),
            ])

    client = SimpleNamespace(responses=_Responses(), chat=MagicMock())

    chunks = list(
        create_chat_completion(
            client,
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
    )

    assert [chunk.choices[0].delta.content for chunk in chunks] == ["Hel", "lo"]
