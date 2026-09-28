"""Coding agent — agentic loop with permission pause/resume via asyncio.Event."""
import asyncio
import json
import uuid
from typing import Callable, Dict, List, Optional

from .tools import TOOL_DEFINITIONS, build_preview, execute_tool


_CODING_SYSTEM = """You are RDI AI Agent, an enterprise-grade action assistant operating in a sandboxed per-conversation workspace.

Your job is to complete the user's task, not merely describe how it could be done.

## Operating model
- Use tools when the task requires files, code execution, current web information, image inspection/generation, or artifact creation.
- For substantial coding/debugging, inspect the relevant files first, then use delegate_code when a specialist second opinion materially improves quality. Apply changes yourself with patch_file/write_file and verify them.
- Prefer patch_file for precise edits. Do not rewrite large files unless necessary.
- Use inspect_image when an attached/workspace image must be understood before editing or using it.
- After changing code, run the narrowest meaningful validation (syntax check, unit test, targeted command) before declaring success.
- Tool errors are evidence, not success. Diagnose and retry with a corrected approach.
- Keep progress updates short and factual. Do not expose private chain-of-thought.
- Never claim a file was created or changed unless a tool result confirms it.
- Never access paths outside the active workspace.

## Artifact creation
Use dedicated PDF/PPTX/DOCX/XLSX tools when they fit. For presentations, plan the deck, generate any needed images/charts first, then create the PPTX once with the final assets.

## Web research
For time-sensitive or unknown facts, search first and crawl authoritative results as needed. Distinguish sourced facts from your own synthesis.

## Completion
Finish with a concise summary of what changed, validations run, and the exact files/artifacts produced.
"""

MAX_TURNS = 30


async def run_coding_agent(
    user_message: str,
    history: List[Dict],
    model: str,
    permission_fn: Callable[[str, str, Dict, str], asyncio.Future],
    token_callback: Callable[[str], asyncio.Future],
    tool_result_callback: Callable[[str, str, str, bool], asyncio.Future],
    image_fn: Optional[Callable] = None,
    pre_tool_callback: Optional[Callable] = None,
) -> str:
    """
    Agentic loop. For each tool call:
      1. Call permission_fn(request_id, tool, args, preview) → awaits user Allow/Deny
      2. If allowed, execute_tool(tool, args)
      3. Feed result back to model
    Streams tokens via token_callback as they arrive.
    Returns final assistant text.
    """
    # Build a bounded message list for the agent. Re-injecting entire files from
    # every prior turn made long conversations balloon until even premium models
    # behaved inconsistently. Keep the newest useful context within a hard budget.
    from .chat_agent import attachments_to_text, _route
    messages = [{"role": "system", "content": _CODING_SYSTEM}]
    budget = 120_000
    selected = []
    used = 0
    for m in reversed(history):
        if m.get("role") not in ("user", "assistant"):
            continue
        content = m.get("content", "") or ""
        atts = m.get("attachments") if m.get("role") == "user" else None
        if atts:
            content = attachments_to_text(atts) + "\n\n" + content
        if len(content) > 40_000:
            content = content[:40_000] + "\n...[older attachment/context truncated]"
        cost = len(content)
        if selected and used + cost > budget:
            break
        selected.append({"role": m["role"], "content": content})
        used += cost
    messages.extend(reversed(selected))
    messages.append({"role": "user", "content": user_message})

    provider = _route(model)

    # Standard agentic loop
    final_answer = ""
    for turn in range(MAX_TURNS):
        resp = await _complete_with_tools(
            messages, model, provider, token_callback=token_callback
        )
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls") or []
        finish = resp.get("finish_reason", "stop")

        # Azure planning/final turns stream directly. Other providers still
        # return complete text, which we emit in bounded chunks.
        if content:
            if not resp.get("streamed"):
                _chunk = 48
                for i in range(0, len(content), _chunk):
                    await token_callback(content[i:i + _chunk])
                    await asyncio.sleep(0)
            final_answer = content

        if finish == "stop" or not tool_calls:
            break

        # Normalize tool calls from any provider (OpenAI objects OR Bedrock dicts)
        # into a canonical OpenAI-style shape both providers can consume downstream.
        norm = [_normalize_tool_call(tc) for tc in tool_calls]
        messages.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {"id": tid, "type": "function",
                 "function": {"name": name, "arguments": args_json}}
                for (tid, name, _args, args_json) in norm
            ],
        })

        for tid, tool_name, tool_args, _args_json in norm:
            preview = build_preview(tool_name, tool_args)
            request_id = str(uuid.uuid4())

            # Fire pre-tool activity notification
            if pre_tool_callback:
                await pre_tool_callback(tool_name, tool_args)

            # Request user permission — awaits asyncio.Event
            allowed = await permission_fn(request_id, tool_name, tool_args, preview)

            if allowed:
                result = await execute_tool(tool_name, tool_args, image_fn=image_fn)
            else:
                result = f"Tool '{tool_name}' was denied by user."

            await tool_result_callback(request_id, tool_name, result, allowed)

            # Keep the full result in the UI, but bound what is fed back to the
            # model. Huge command/file outputs were a major source of context blow-ups.
            model_result = result
            if len(model_result) > 20_000:
                model_result = (
                    model_result[:16_000]
                    + "\n...[tool output truncated for model context]...\n"
                    + model_result[-3_000:]
                )
            messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": model_result,
            })

    return final_answer


def _normalize_tool_call(tc):
    """Return (id, name, args_dict, args_json) from an OpenAI tool-call object
    or a Bedrock Converse toolUse dict."""
    if isinstance(tc, dict):
        tid = tc.get("toolUseId") or tc.get("id") or str(uuid.uuid4())
        name = tc.get("name", "")
        args = tc.get("input", {}) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return tid, name, args, json.dumps(args)
    # OpenAI SDK object
    tid = getattr(tc, "id", None) or str(uuid.uuid4())
    fn = tc.function
    raw = fn.arguments or "{}"
    try:
        args = json.loads(raw)
    except Exception:
        args = {}
    return tid, fn.name, args, raw


async def _stream_openai_with_tools(client, kwargs: Dict,
                                    token_callback: Callable[[str], asyncio.Future]) -> dict:
    """Stream assistant text while accumulating function-call deltas."""
    kwargs = dict(kwargs)
    kwargs["stream"] = True
    stream = await client.chat.completions.create(**kwargs)
    content_parts: List[str] = []
    tool_parts: Dict[int, Dict] = {}
    finish_reason = "stop"

    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content:
            content_parts.append(delta.content)
            await token_callback(delta.content)
        for tc in (getattr(delta, "tool_calls", None) or []):
            idx = getattr(tc, "index", 0) or 0
            entry = tool_parts.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if getattr(tc, "id", None):
                entry["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    entry["name"] += fn.name
                if getattr(fn, "arguments", None):
                    entry["arguments"] += fn.arguments
        if choice.finish_reason:
            finish_reason = choice.finish_reason

    tool_calls = []
    for idx in sorted(tool_parts):
        part = tool_parts[idx]
        try:
            args = json.loads(part["arguments"] or "{}")
        except Exception:
            args = {}
        tool_calls.append({
            "id": part["id"] or str(uuid.uuid4()),
            "name": part["name"],
            "input": args,
        })

    return {
        "content": "".join(content_parts),
        "tool_calls": tool_calls or None,
        "finish_reason": finish_reason,
        "streamed": True,
    }


async def _complete_with_tools(messages: List[Dict], model: str, provider: str,
                               token_callback=None) -> dict:
    if provider == "azure_chat":
        from ..providers.azure_chat import _client
        client = _client()
        kwargs = {
            "model": model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "max_tokens": 8192,
        }
        if token_callback:
            return await _stream_openai_with_tools(client, kwargs, token_callback)
        from ..providers.azure_chat import complete_with_tools
        return await complete_with_tools(messages, model, TOOL_DEFINITIONS, max_tokens=8192)

    elif provider == "gpt5":
        from openai import AsyncAzureOpenAI
        from ..config import get_config
        cfg = get_config().azure_gpt5
        if not cfg:
            raise RuntimeError("Azure GPT-5 not configured")
        client = AsyncAzureOpenAI(
            api_key=cfg.api_key,
            azure_endpoint=cfg.endpoint,
            api_version=cfg.api_version,
        )
        kwargs = {
            "model": model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "max_completion_tokens": 8192,
        }
        if token_callback:
            return await _stream_openai_with_tools(client, kwargs, token_callback)
        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": choice.message.tool_calls,
            "finish_reason": choice.finish_reason,
        }

    elif provider == "bedrock":
        from ..providers.bedrock import complete_bedrock
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        user_msgs = [m for m in messages if m.get("role") != "system"]
        return await complete_bedrock(
            user_msgs, model, system_prompt=sys_msg, tools=TOOL_DEFINITIONS
        )

    else:
        from ..providers.vertex import complete_vertex
        return await complete_vertex(messages, model)


def _messages_to_prompt(messages: List[Dict]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        parts.append(f"{role}: {content}")
    return "\n".join(parts)
