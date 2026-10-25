"""Azure GPT-5 — chat models (max_completion_tokens) + Codex (Responses API)."""
import asyncio
import json
from typing import AsyncGenerator, List

import httpx
import requests
from openai import AsyncAzureOpenAI

from ..config import get_config

# All Codex models use Responses API, NOT chat/completions
_CODEX_MODELS = {
    "gpt-5-pro-global",
    "gpt-5-codex-global",
    "gpt-5.1-codex-global",
    "gpt-5.1-codex-mini-global",
    "gpt-5.1-codex-max-global",
    "gpt-5.2-codex-global",
    "gpt-5.3-codex-global",
}


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_gpt5
    if not cfg:
        raise RuntimeError("Azure GPT-5 not configured — add [azure_gpt5] to config.ini")
    return AsyncAzureOpenAI(
        api_key=cfg.api_key,
        azure_endpoint=cfg.endpoint,
        api_version=cfg.api_version,
    )


async def stream_gpt5(
    messages: List[dict],
    model: str,
    max_tokens: int = 8192,
) -> AsyncGenerator[str, None]:
    if model in _CODEX_MODELS:
        prompt = _messages_to_prompt(messages)
        async for delta in stream_codex_responses_api(model, prompt, max_tokens):
            yield delta
        return

    c = _client()
    # All GPT-5 chat models require max_completion_tokens
    resp = await c.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_tokens,
        stream=True,
    )
    async with resp as stream:
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta.content:
                yield choice.delta.content
            if choice.finish_reason == "length":
                yield "\n\n**Model output limit reached. Reply 'continue' for the remainder.**"


def _responses_output_text(data: dict) -> str:
    return "".join(
        part.get("text", "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


async def stream_codex_responses_api(
    model: str, prompt: str, max_output_tokens: int = 8192
) -> AsyncGenerator[str, None]:
    """Stream real Responses API SSE deltas; do not replay a completed answer."""
    cfg = get_config().azure_gpt5
    if not cfg:
        raise RuntimeError("Azure GPT-5 not configured")
    url = f"{cfg.endpoint.rstrip('/')}/openai/v1/responses"
    payload = {"model": model, "input": prompt,
               "max_output_tokens": max_output_tokens, "stream": True}
    headers = {"api-key": cfg.api_key, "Accept": "text/event-stream"}
    timeout = httpx.Timeout(300.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            if "text/event-stream" not in resp.headers.get("content-type", ""):
                # Some gateways return only the final JSON even with stream=True.
                # Expose the genuine limitation rather than fake token-by-token UI.
                data = json.loads((await resp.aread()).decode("utf-8"))
                text = _responses_output_text(data)
                if text:
                    yield text
                return

            received_delta = False
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload_text = line[5:].strip()
                if not payload_text or payload_text == "[DONE]":
                    continue
                event = json.loads(payload_text)
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        received_delta = True
                        yield delta
                elif kind == "response.completed":
                    if not received_delta:
                        text = _responses_output_text(event.get("response") or {})
                        if text:
                            yield text
                elif kind == "response.incomplete":
                    yield "\n\n**Model output limit reached. Reply 'continue' for the remainder.**"
                elif kind in ("response.failed", "error"):
                    error = event.get("error") or (event.get("response") or {}).get("error") or {}
                    raise RuntimeError(f"Responses API failed: {error.get('message', str(error))}")


async def codex_responses_api(model: str, prompt: str, max_output_tokens: int = 8192) -> str:
    """Codex: POST {gpt5_endpoint}/openai/v1/responses."""
    cfg = get_config().azure_gpt5
    if not cfg:
        raise RuntimeError("Azure GPT-5 not configured")
    url = f"{cfg.endpoint.rstrip('/')}/openai/v1/responses"
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(
            url,
            headers={"api-key": cfg.api_key, "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "max_output_tokens": max_output_tokens},
            timeout=120,
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


def is_codex(model: str) -> bool:
    return model in _CODEX_MODELS


def _messages_to_prompt(messages: List[dict]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        parts.append(f"{role}: {content}")
    return "\n".join(parts)
