"""Multi-turn chat agent — routes to correct provider based on model ID."""
import base64
import io
from typing import AsyncGenerator, Dict, List, Optional

# GPT-5 model prefixes
_GPT5_PREFIXES = ("gpt-5", "gpt-5.", "gpt-5-")
# Bedrock model prefixes
_BEDROCK_PREFIXES = (
    "anthropic.", "us.anthropic.", "global.anthropic.",
    "us.meta.", "global.meta.",
    "cohere.command", "cohere.embed",
    "us.cohere.", "global.cohere.",
    "amazon.titan",
    "meta.llama",
)
# Vertex model IDs
_VERTEX_MODELS = {"gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"}


def _route(model: str) -> str:
    if any(model.startswith(p) for p in _BEDROCK_PREFIXES):
        return "bedrock"
    if model in _VERTEX_MODELS:
        return "vertex"
    if any(model.startswith(p) for p in _GPT5_PREFIXES):
        return "gpt5"
    return "azure_chat"


_DEFAULT_SYSTEM = (
    "You are RDI AI, an advanced enterprise AI assistant. "
    "Be helpful, accurate, and concise. Format responses in Markdown."
)


def _is_image_attachment(att: Dict) -> bool:
    t = att.get("type", "")
    return t.startswith("image/") or t == "image"


def _user_content(text: str, attachments: Optional[List[Dict]]):
    """Return either a plain string (no attachments) or an OpenAI multimodal
    parts list. Images become image_url parts; docs are inlined as text."""
    if not attachments:
        return text
    parts: List[Dict] = [{"type": "text", "text": text}]
    for att in attachments:
        content = att.get("content", "")
        name = att.get("name", "file")
        if _is_image_attachment(att):
            mime = att.get("type", "")
            if not mime.startswith("image/"):
                mime = "image/png"
            url = content if content.startswith("data:") else f"data:{mime};base64,{content}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        elif content:
            parts.append({"type": "text", "text": f"\n--- {name} ---\n{content}\n---"})
    return parts


def attachments_to_text(attachments: Optional[List[Dict]]) -> str:
    """Flatten attachments to a plain-text block (for text-only / tool-calling models)."""
    parts = []
    for att in attachments or []:
        name = att.get("name", "file")
        if _is_image_attachment(att):
            parts.append(f"[Attached image: {name}]")
        else:
            content = att.get("content", "")
            parts.append(f"--- Attached file: {name} ---\n{content}\n---")
    return "\n\n".join(parts)


def build_messages(
    history: List[Dict],
    user_message: str,
    attachments: Optional[List[Dict]] = None,
    system_prompt: str = _DEFAULT_SYSTEM,
    system_prefix: str = "",
) -> List[Dict]:
    full_system = f"{system_prefix}\n\n{system_prompt}" if system_prefix else system_prompt
    messages = [{"role": "system", "content": full_system}]

    for m in history:
        role = m.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content", "")
        # Re-attach prior-turn files so follow-up questions keep their context.
        hist_atts = m.get("attachments") if role == "user" else None
        if hist_atts:
            messages.append({"role": role, "content": _user_content(content, hist_atts)})
        else:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": _user_content(user_message, attachments)})
    return messages


async def stream_response(
    messages: List[Dict],
    model: str,
) -> AsyncGenerator[str, None]:
    provider = _route(model)

    if provider == "azure_chat":
        from ..providers.azure_chat import stream_chat
        async for token in stream_chat(messages, model):
            yield token

    elif provider == "gpt5":
        from ..providers.azure_gpt5 import stream_gpt5
        async for token in stream_gpt5(messages, model):
            yield token

    elif provider == "bedrock":
        from ..providers.bedrock import stream_bedrock
        # Extract system prompt
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        user_msgs = [m for m in messages if m.get("role") != "system"]
        async for token in stream_bedrock(user_msgs, model, system_prompt=sys_msg):
            yield token

    elif provider == "vertex":
        from ..providers.vertex import stream_vertex
        async for token in stream_vertex(messages, model):
            yield token

    else:
        yield f"Unknown provider for model: {model}"


def trim_history(history: List[Dict], max_chars: int = 400_000) -> List[Dict]:
    """Sliding window: drop the OLDEST messages first, keeping newest within budget.

    history holds only user/assistant turns (no system message), so we pop from
    index 0. Attachment content counts toward the budget too."""
    def _size(m: Dict) -> int:
        n = len(str(m.get("content", "")))
        for att in m.get("attachments") or []:
            n += len(str(att.get("content", "")))
        return n

    total = sum(_size(m) for m in history)
    while total > max_chars and len(history) > 1:
        removed = history.pop(0)
        total -= _size(removed)
    return history
