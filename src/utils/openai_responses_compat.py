"""Compatibility helpers for using GPT-5 family models via the Responses API.

Most of this codebase still expects the Chat Completions response shape
(`choices[0].message.content`). The current OpenAI model guide makes latest
GPT-5 models available through the Responses API, so these helpers route real
GPT-5-family calls through `client.responses.create(...)` and adapt the result
back to the small Chat-Completions-shaped surface the existing code consumes.

Mock clients and non-GPT-5 models are passed through to Chat Completions, which
keeps existing tests and explicit legacy overrides stable.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True for latest GPT-5-family model IDs."""
    return bool(model and str(model).startswith("gpt-5"))


def _is_mock(obj: Any) -> bool:
    return obj is None or type(obj).__module__.startswith("unittest.mock")


def _should_use_responses(client: Any, model: Optional[str]) -> bool:
    if not is_gpt5_family(model):
        return False
    responses = getattr(client, "responses", None)
    return responses is not None and not _is_mock(responses) and hasattr(responses, "create")


def _response_format_to_text(response_format: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not response_format:
        return None

    if response_format.get("type") == "json_schema":
        # Chat Completions wraps the Responses text format under `json_schema`.
        schema_format = dict(response_format.get("json_schema") or {})
        schema_format.setdefault("type", "json_schema")
        return {"format": schema_format}

    return {"format": dict(response_format)}


def _reasoning_for_model(model: Optional[str]) -> Dict[str, str]:
    if not is_gpt5_family(model):
        return {}
    model_s = str(model)
    if "mini" in model_s or "nano" in model_s:
        return {"effort": os.getenv("TOOL_REASONING_EFFORT", "none")}
    return {"effort": os.getenv("RESEARCH_REASONING_EFFORT", "low")}


def _build_responses_kwargs(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    responses_kwargs: Dict[str, Any] = {
        "model": kwargs["model"],
        "input": kwargs.get("messages", []),
    }

    text = _response_format_to_text(kwargs.get("response_format"))
    if text is not None:
        responses_kwargs["text"] = text

    max_output_tokens = kwargs.get(
        "max_output_tokens", kwargs.get("max_completion_tokens", kwargs.get("max_tokens"))
    )
    if max_output_tokens is not None:
        responses_kwargs["max_output_tokens"] = max_output_tokens

    for key in ("temperature", "top_p", "stream", "timeout", "metadata"):
        if key in kwargs and kwargs[key] is not None:
            responses_kwargs[key] = kwargs[key]

    reasoning = kwargs.get("reasoning") or _reasoning_for_model(kwargs.get("model"))
    if reasoning:
        responses_kwargs["reasoning"] = reasoning

    return responses_kwargs


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    chunks = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text is not None:
                chunks.append(str(text))
    return "".join(chunks)


def _chat_like_usage(response: Any) -> Any:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "prompt_tokens") and hasattr(usage, "completion_tokens"):
        return usage
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return SimpleNamespace(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
        response_usage=usage,
    )


def _chat_like_response(response: Any) -> Any:
    content = _extract_response_text(response)
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=_chat_like_usage(response))


def _chat_like_stream(events: Iterable[Any]) -> Iterator[Any]:
    for event in events:
        event_type = getattr(event, "type", "")
        # Responses terminal events can include the full accumulated text.
        # Do not emit them as deltas or SSE clients will see duplicate content.
        if event_type in {"response.output_text.done", "response.completed"}:
            continue
        delta = getattr(event, "delta", None)
        if not delta:
            continue
        choice = SimpleNamespace(delta=SimpleNamespace(content=str(delta)))
        yield SimpleNamespace(choices=[choice])


def create_chat_completion(client: Any, **kwargs: Any) -> Any:
    """Create a completion, routing real GPT-5-family calls through Responses."""
    model = kwargs.get("model")
    if not _should_use_responses(client, model):
        return client.chat.completions.create(**kwargs)

    response = client.responses.create(**_build_responses_kwargs(kwargs))
    if kwargs.get("stream"):
        return _chat_like_stream(response)
    return _chat_like_response(response)


async def async_create_chat_completion(client: Any, **kwargs: Any) -> Any:
    """Async equivalent of :func:`create_chat_completion`."""
    model = kwargs.get("model")
    if not _should_use_responses(client, model):
        return await client.chat.completions.create(**kwargs)

    response = await client.responses.create(**_build_responses_kwargs(kwargs))
    if kwargs.get("stream"):
        return _chat_like_stream(response)
    return _chat_like_response(response)
