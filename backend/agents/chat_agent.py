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


def attachments_to_text(
    attachments: Optional[List[Dict]],
    per_file_chars: int = 20_000,
    total_chars: int = 60_000,
) -> str:
    """Flatten attachments for text-only/tool models without exploding context."""
    parts = []
    used = 0
    for att in attachments or []:
        name = att.get("name", "file")
        if _is_image_attachment(att):
            piece = f"[Attached image available in workspace: {name}]"
        else:
            content = str(att.get("content", "") or "")
            if len(content) > per_file_chars:
                raise ValueError(
                    f"Attachment {name!r} exceeds the {per_file_chars:,}-character model context limit. "
                    "The full file is retained; ask to analyze a specific section or split the request."
                )
            piece = f"--- Attached file: {name} ---\n{content}\n---"
        if used + len(piece) > total_chars:
            raise ValueError(
                f"Attachment context exceeds {total_chars:,} characters. "
                "No attachment was silently omitted. Select fewer files or a smaller section."
            )
        parts.append(piece)
        used += len(piece)
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
        # Keep prior attachment awareness without resending historical image
        # base64 or full documents on every turn. The original behavior caused
        # context to balloon dramatically after a few multimodal turns.
        hist_atts = m.get("attachments") if role == "user" else None
        if hist_atts:
            prior = attachments_to_text(hist_atts, per_file_chars=12_000, total_chars=30_000)
            joined = (content or "")
            if prior:
                joined = (joined + "\n\n" + prior).strip()
            messages.append({"role": role, "content": joined})
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


def trim_history(history: List[Dict], max_chars: int = 180_000) -> List[Dict]:
    """Validate model context without deleting earlier turns or uploaded content.

    This limit is intentionally bounded: model context is finite and unbounded
    concatenation would increase latency/cost and risk provider failures.
    """
    total = sum(
        len(str(m.get("content", ""))) +
        sum(len(str(att.get("content", ""))) for att in m.get("attachments") or [])
        for m in history
    )
    if total > max_chars:
        raise ValueError(
            f"Conversation context is {total:,} characters, above the safe "
            f"{max_chars:,}-character model input limit. Nothing was removed "
            "or sent partially. Start a new conversation or reduce the input."
        )
    return history
