"""AWS Bedrock — Claude, Llama, Cohere via Converse API + dummy auth + x-api-key hook."""
import asyncio
import base64
import json
from functools import partial
from typing import AsyncGenerator, List, Optional

from ..config import get_config


async def _aiter_blocking(gen_factory):
    """Bridge a blocking generator to async, yielding items as they arrive
    (real streaming) instead of buffering the whole thing first."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _worker():
        try:
            for item in gen_factory():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:  # surface errors to the consumer
            loop.call_soon_threadsafe(queue.put_nowait, ("__error__", exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    loop.run_in_executor(None, _worker)
    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "__error__":
            raise item[1]
        yield item

# Models that accept a system[] block in Converse API
_CLAUDE_MODELS_PREFIX = ("anthropic.", "us.anthropic.", "global.anthropic.")


def _is_claude(model: str) -> bool:
    return any(model.startswith(p) for p in _CLAUDE_MODELS_PREFIX)


def _make_client():
    import boto3
    cfg = get_config().bedrock
    if not cfg:
        raise RuntimeError("Bedrock not configured — add [bedrock] to config.ini")

    session = boto3.Session(
        aws_access_key_id="dummy",
        aws_secret_access_key="dummy",
    )
    client = session.client(
        "bedrock-runtime",
        endpoint_url=cfg.endpoint,
        region_name="dummy",
    )

    api_key = cfg.api_key

    def _inject(model, params, request_signer, **kwargs):
        params["headers"]["x-api-key"] = api_key

    client.meta.events.register("before-call.bedrock-runtime.Converse", _inject)
    client.meta.events.register("before-call.bedrock-runtime.ConverseStream", _inject)
    client.meta.events.register("before-call.bedrock-runtime.InvokeModel", _inject)
    return client


async def stream_bedrock(
    messages: List[dict],
    model: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    client = _make_client()

    bedrock_msgs = _convert_messages(messages)
    kwargs: dict = {
        "modelId": model,
        "messages": bedrock_msgs,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system_prompt and _is_claude(model):
        kwargs["system"] = [{"text": system_prompt}]

    def _call():
        return client.converse_stream(**kwargs)

    response = await loop.run_in_executor(None, _call)
    stream = response.get("stream")
    if not stream:
        return

    def _iter():
        for event in stream:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text = delta.get("text", "")
            if text:
                yield text

    async for token in _aiter_blocking(_iter):
        yield token


async def complete_bedrock(
    messages: List[dict],
    model: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    tools: Optional[List] = None,
) -> dict:
    loop = asyncio.get_event_loop()
    client = _make_client()

    bedrock_msgs = _convert_messages(messages)
    kwargs: dict = {
        "modelId": model,
        "messages": bedrock_msgs,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system_prompt and _is_claude(model):
        kwargs["system"] = [{"text": system_prompt}]
    if tools:
        kwargs["toolConfig"] = {"tools": _convert_tools(tools)}

    def _call():
        return client.converse(**kwargs)

    resp = await loop.run_in_executor(None, _call)
    msg = resp["output"]["message"]
    content_text = ""
    tool_calls = []
    for block in msg.get("content", []):
        if "text" in block:
            content_text += block["text"]
        elif "toolUse" in block:
            tool_calls.append(block["toolUse"])

    return {
        "content": content_text,
        "tool_calls": tool_calls or None,
        "finish_reason": resp.get("stopReason", "stop"),
    }


def _convert_messages(messages: List[dict]) -> List[dict]:
    """Convert OpenAI-style messages to Bedrock Converse format."""
    result = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue  # handled separately
        content = m.get("content", "")
        if isinstance(content, str):
            blocks = [{"text": content}] if content else []
        elif isinstance(content, list):
            blocks = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and part.get("text"):
                        blocks.append({"text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime, b64 = url.split(",", 1)
                            fmt = mime.split("/")[1].split(";")[0]
                            blocks.append({
                                "image": {
                                    "format": fmt,
                                    # Converse expects RAW bytes, not the base64 text.
                                    "source": {"bytes": base64.b64decode(b64)},
                                }
                            })
        else:
            blocks = [{"text": str(content)}]

        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                blocks.append({
                    "toolUse": {
                        "toolUseId": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    }
                })

        if role == "tool":
            result.append({
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": m.get("tool_call_id", ""),
                        "content": [{"text": content}],
                    }
                }]
            })
            continue

        result.append({"role": role, "content": blocks})
    return result


def _convert_tools(tools: List[dict]) -> List[dict]:
    """Convert OpenAI tool format to Bedrock toolSpec format."""
    result = []
    for t in tools:
        fn = t.get("function", {})
        result.append({
            "toolSpec": {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "inputSchema": {"json": fn.get("parameters", {})},
            }
        })
    return result
