"""Coding agent — agentic loop with permission pause/resume via asyncio.Event."""
import asyncio
import json
import uuid
from typing import AsyncGenerator, Callable, Dict, List, Optional

from .tools import TOOL_DEFINITIONS, build_preview, execute_tool

# Coding agent uses GPT-5 Codex or falls back to gpt-4o
_DEFAULT_CODE_MODEL = "gpt-5.3-codex-global"
_FALLBACK_MODEL = "gpt-4o-global"

_CODING_SYSTEM = """You are RDI AI Agent — a powerful multi-capability assistant with access to a \
sandboxed workspace. You can write and execute code, create documents, search the web, and generate images.

## Available tools
- **read_file / write_file / create_file / delete_file / list_files** — manage workspace files
- **run_bash** — execute shell commands in the workspace directory
- **run_python** — run Python code and see output
- **search_files** — grep across workspace files
- **create_pdf** — generate a PDF document (fpdf2)
- **create_pptx** — generate a PowerPoint presentation (python-pptx)
- **create_docx** — generate a Word document (python-docx)
- **create_excel** — generate an Excel spreadsheet (openpyxl)
- **web_crawl** — fetch and read text content from a URL
- **web_search** — search DuckDuckGo and return results
- **generate_image** — generate an image from a text prompt (saved to workspace/images/); returns the saved path

## Rules
1. Always explain what you are about to do before calling a tool.
2. Read existing files before modifying them.
3. Show code with syntax highlighting in Markdown fences.
4. When a task is complete, summarize what was done and list created files.
5. Never access paths outside the workspace/ directory.
6. For document creation tasks, use the dedicated create_pdf / create_pptx / create_docx / create_excel tools.
7. For information you don't know, use web_search first, then web_crawl to get full content.

## Creating PowerPoint presentations with images (MANDATORY WORKFLOW)

When asked to create a PPTX — especially one that should include visuals, diagrams, charts, or any imagery:

**Step 1 — Plan all slides first.**
Decide slide titles, bullet points, and which slides need a visual.

**Step 2 — Generate images BEFORE calling create_pptx.**
For each slide that needs an image, call generate_image. The response will be in the format:
`Image saved. image_path = images/filename.png`
Copy the value after `image_path = ` EXACTLY and use it in Step 3. Do not rename, guess, or reconstruct the path — use only what generate_image returned.

**Step 3 — Call create_pptx ONCE with all slides, setting image_path on each slide that has an image.**
- `layout: "image_full"` — hero/title/impact slides where the image fills the whole slide with a caption
- `layout: "image_right"` — content slides: bullets on the left, image on the right
- `layout: "text"` — slides with only text/bullets and no image

Example create_pptx call using the full design system:
```json
{
  "filename": "q4_review.pptx",
  "title": "Q4 Business Review",
  "subtitle": "Performance, insights, and the road ahead",
  "slides": [
    { "title": "Agenda", "content": ["Results", "Key drivers", "Outlook"], "layout": "two_column" },
    { "title": "Results", "layout": "section", "content": ["The numbers that defined the quarter"] },
    { "title": "By the numbers", "layout": "metrics", "content": ["23%|Revenue growth", "1.4M|New users", "18%|Margin", "4.8/5|CSAT"], "notes": "Revenue beat plan by 6 points." },
    { "title": "Record Growth", "content": ["Revenue up 23% YoY", "Two new markets opened", "Retention at all-time high"], "image_path": "images/revenue_chart.png", "layout": "image_right" },
    { "title": "What customers told us", "layout": "quote", "content": ["This is the most capable platform we have deployed.", "VP Engineering, Fortune 100 client"] },
    { "title": "Looking Ahead", "content": ["Expand to EMEA"], "image_path": "images/future_vision.png", "layout": "image_full" }
  ]
}
```

## Presentation quality standards — make decks that look designed, not generic
- **Structure:** cover → agenda → section dividers between topics → content → a metrics slide → a quote if relevant → closing. Aim for 7–12 slides.
- **Use the varied layouts deliberately.** Don't make every slide a bullet list:
  - `section` to open each major topic (divider slide)
  - `metrics` for KPIs/numbers — pass `"VALUE|LABEL"` items (e.g. `"23%|Revenue growth"`)
  - `quote` for a customer/expert voice or a key takeaway
  - `two_column` for agendas or comparisons
  - `image_right` for data/analysis, `image_full` for impact/opening/closing
- **Content:** 3–5 tight bullets per slide, phrases not paragraphs. Add `notes` (speaker notes) with the detail that would otherwise clutter the slide.
- **Visuals:** generate specific, high-quality images (`generate_image`) with an explicit style ("clean white background, flat vector infographic, professional"). For real data, produce an actual chart with run_python (matplotlib) saved to images/, then reference that path.
- **NEVER** ship a deck that is only text slides when visuals or metrics would add value.
"""

MAX_TURNS = 20


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
    # Build message list for the coding agent
    from .chat_agent import attachments_to_text
    messages = [{"role": "system", "content": _CODING_SYSTEM}]
    for m in history[-20:]:  # last 20 turns for context
        if m.get("role") in ("user", "assistant"):
            content = m["content"]
            # Re-inject prior-turn attachment text so follow-ups keep file context.
            atts = m.get("attachments") if m["role"] == "user" else None
            if atts:
                content = attachments_to_text(atts) + "\n\n" + (content or "")
            messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": user_message})

    # Route model to correct provider
    from .chat_agent import _route
    provider = _route(model)

    # Codex models don't support tool calling — switch to the fallback chat model
    from ..providers.azure_gpt5 import is_codex
    if is_codex(model):
        model = _FALLBACK_MODEL
        provider = _route(model)

    # Standard agentic loop
    final_answer = ""
    for turn in range(MAX_TURNS):
        resp = await _complete_with_tools(messages, model, provider)
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls") or []
        finish = resp.get("finish_reason", "stop")

        # Stream any text content — in small chunks, not per-character (the
        # underlying completion is non-streaming, so per-char just floods WS frames).
        if content:
            _chunk = 48
            for i in range(0, len(content), _chunk):
                await token_callback(content[i:i + _chunk])
                await asyncio.sleep(0)  # yield event loop
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

            messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": result,
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


async def _complete_with_tools(messages: List[Dict], model: str, provider: str) -> dict:
    if provider == "azure_chat":
        from ..providers.azure_chat import complete_with_tools
        return await complete_with_tools(messages, model, TOOL_DEFINITIONS)
    elif provider == "gpt5":
        # GPT-5 chat models support tool calling
        from openai import AsyncAzureOpenAI
        from ..config import get_config
        cfg = get_config().azure_gpt5
        if not cfg:
            raise RuntimeError("Azure GPT-5 not configured")
        c = AsyncAzureOpenAI(
            api_key=cfg.api_key,
            azure_endpoint=cfg.endpoint,
            api_version=cfg.api_version,
        )
        resp = await c.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_completion_tokens=4096,
        )
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
        return await complete_bedrock(user_msgs, model, system_prompt=sys_msg,
                                      tools=TOOL_DEFINITIONS)
    else:
        # Vertex doesn't support tool calling on RDI gateway — fallback to plain completion
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
