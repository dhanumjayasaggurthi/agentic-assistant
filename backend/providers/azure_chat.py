"""Azure OpenAI Chat — GPT-3.5/4/4o/4.1 + o-series + o3-pro (Responses API)."""
import asyncio
from functools import partial
from typing import AsyncGenerator, List, Optional

import requests
from openai import AsyncAzureOpenAI

from ..config import get_config

# o-series: no system prompt, use max_completion_tokens
_O_SERIES = {
    "o1", "o1-mini-global", "o1-global",
    "o3", "o3-global", "o3-mini", "o3-mini-global", "o3-pro-global",
    "o4-mini", "o4-mini-global",
}

# Uses Responses API (not chat/completions)
_RESPONSES_MODELS = {"o3-pro-global"}


def _is_o_series(model: str) -> bool:
    return model in _O_SERIES or any(
        model.startswith(p) for p in ("o1", "o3", "o4")
    )


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_chat
    if not cfg:
        raise RuntimeError("Azure Chat not configured — add [azure_chat] to config.ini")
    return AsyncAzureOpenAI(
        api_key=cfg.api_key,
        azure_endpoint=cfg.endpoint,
        api_version=cfg.api_version,
    )


async def stream_chat(
    messages: List[dict],
    model: str,
    max_tokens: int = 8192,
    temperature: Optional[float] = None,
) -> AsyncGenerator[str, None]:
    if model in _RESPONSES_MODELS:
        text = await responses_api(model, _messages_to_text(messages))
        for ch in text:
            yield ch
        return

    c = _client()
    if _is_o_series(model):
        filtered = [m for m in messages if m.get("role") != "system"]
        kw = {"model": model, "messages": filtered,
              "max_completion_tokens": max_tokens, "stream": True}
    else:
        kw = {"model": model, "messages": messages,
              "max_tokens": max_tokens, "stream": True}
        if temperature is not None:
            kw["temperature"] = temperature

    async with await c.chat.completions.create(**kw) as stream:
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


async def complete_with_tools(
    messages: List[dict],
    model: str,
    tools: List[dict],
    max_tokens: int = 8192,
) -> dict:
    """Non-streaming call with tool use support."""
    c = _client()
    kw: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if not _is_o_series(model):
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    else:
        kw.pop("max_tokens")
        kw["max_completion_tokens"] = max_tokens
        kw["messages"] = [m for m in messages if m.get("role") != "system"]

    resp = await c.chat.completions.create(**kw)
    choice = resp.choices[0]
    return {
        "content": choice.message.content or "",
        "tool_calls": choice.message.tool_calls,
        "finish_reason": choice.finish_reason,
    }


async def responses_api(model: str, prompt: str, max_output_tokens: int = 8192) -> str:
    """Responses API for o3-pro-global — POST /openai/v1/responses."""
    cfg = get_config().azure_chat
    if not cfg:
        raise RuntimeError("Azure Chat not configured")
    url = f"{cfg.endpoint.rstrip('/')}/openai/v1/responses"
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(
            url,
            headers={"api-key": cfg.api_key, "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "max_output_tokens": max_output_tokens},
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        return "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )

    return await loop.run_in_executor(None, _call)


def _messages_to_text(messages: List[dict]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        if role != "system":
            parts.append(f"{role}: {content}")
    return "\n".join(parts)
