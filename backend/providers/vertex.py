"""Google Vertex AI — Gemini chat + image generation via RDI gateway."""
import asyncio
import base64
from typing import AsyncGenerator, List, Optional

import requests

from ..config import get_config


async def _aiter_blocking(gen_factory):
    """Bridge a blocking generator to async, yielding items as they arrive."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _worker():
        try:
            for item in gen_factory():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:
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


def _make_vertex_client():
    from google import genai
    from google.auth.credentials import Credentials
    from google.genai.types import HttpOptions

    class _Creds(Credentials):
        def refresh(self, request):
            self.token = "dummy-token"
            self.expiry = None

    cfg = get_config().vertex
    if not cfg:
        raise RuntimeError("Vertex AI not configured — add [vertex] to config.ini")

    return genai.Client(
        vertexai=True,
        project="dummy",
        location="dummy",
        http_options=HttpOptions(
            api_version="v1",
            base_url=cfg.endpoint,
            headers={"x-api-key": cfg.api_key},
        ),
        credentials=_Creds(),
    )


async def stream_vertex(
    messages: List[dict],
    model: str,
) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    client = _make_vertex_client()
    contents = _convert_messages(messages)

    def _iter():
        for chunk in client.models.generate_content_stream(
            model=model, contents=contents
        ):
            if chunk.text:
                yield chunk.text

    async for t in _aiter_blocking(_iter):
        yield t


async def complete_vertex(messages: List[dict], model: str) -> dict:
    loop = asyncio.get_event_loop()
    client = _make_vertex_client()
    contents = _convert_messages(messages)

    def _call():
        return client.models.generate_content(model=model, contents=contents)

    resp = await loop.run_in_executor(None, _call)
    return {"content": resp.text or "", "tool_calls": None, "finish_reason": "stop"}


async def generate_vertex_image(prompt: str, model: str = "gemini-2.5-flash-image") -> dict:
    """Vertex image via raw HTTP — POST /v1/projects/GenAI/.../models/{model}:generateContent."""
    cfg = get_config().vertex_image
    if not cfg:
        raise RuntimeError("Vertex Image not configured — add [vertex_image] to config.ini")

    url = (
        f"{cfg.endpoint.rstrip('/')}/v1/projects/GenAI"
        f"/locations/us-east1/publishers/google/models/{model}:generateContent"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "x-api-key": cfg.api_key,
    }
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()

    data = await loop.run_in_executor(None, _call)
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    result: dict = {"prompt": prompt, "b64": None, "text": ""}
    for p in parts:
        if "inlineData" in p:
            result["b64"] = p["inlineData"].get("data", "")
        elif "text" in p:
            result["text"] += p["text"]
    return result


def _convert_messages(messages: List[dict]) -> List[dict]:
    """Convert OpenAI-style messages to Vertex contents list."""
    contents = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            # Prepend as first user turn for Vertex
            contents.insert(0, {"role": "user", "parts": [{"text": m.get("content", "")}]})
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            parts = [{"text": content}]
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append({"text": block["text"]})
                    elif block.get("type") == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime, b64 = url.split(",", 1)
                            fmt = mime.split("/")[1].split(";")[0]
                            parts.append({
                                "inline_data": {"mime_type": f"image/{fmt}", "data": b64}
                            })
        else:
            parts = [{"text": str(content)}]

        vertex_role = "model" if role == "assistant" else "user"
        contents.append({"role": vertex_role, "parts": parts})
    return contents
