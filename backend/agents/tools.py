"""Tool definitions and executors for the coding agent sandbox."""
import asyncio
import contextvars
import difflib
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List

from ..config import get_config

# ── Per-request workspace contextvar (set per user in ws_handler) ─────────────

_workspace_var: contextvars.ContextVar[Path] = contextvars.ContextVar('workspace')


def _active_workspace() -> Path:
    """Return the workspace for the current async context, or the global default."""
    try:
        return _workspace_var.get()
    except LookupError:
        return get_config().workspace_dir


# ── Sandbox guard ─────────────────────────────────────────────────────────────

def _safe_path(rel: str) -> Path:
    workspace = _active_workspace().resolve()
    target = (workspace / rel).resolve()
    # is_relative_to (py3.9+) is robust against ../ and sibling-prefix tricks.
    if target != workspace and not target.is_relative_to(workspace):
        raise ValueError(f"Path traversal blocked: {rel!r}")
    return target


# ── Tool definitions (OpenAI function-calling format) ─────────────────────────

TOOL_DEFINITIONS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within workspace/"},
                    "start_line": {"type": "integer", "description": "Optional 1-based start line"},
                    "end_line": {"type": "integer", "description": "Optional 1-based end line"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return", "default": 20000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file in the workspace. Shows a diff preview first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within workspace/"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file (fails if already exists).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in the workspace or a subdirectory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Subdirectory to list, or '' for root",
                        "default": "",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Execute a bash/shell command in the workspace directory. Captures stdout+stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (max 60)",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute Python code and return stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a text pattern across all workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text to search for"},
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob pattern for files (e.g. '*.py')",
                        "default": "*",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "Make a precise text replacement in an existing workspace file. Prefer this over rewriting an entire file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "occurrence": {"type": "integer", "description": "1-based occurrence when old_text appears multiple times", "default": 1}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_image",
            "description": "Inspect an image already in the workspace with a vision-capable premium model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative image path"},
                    "question": {"type": "string", "description": "What to analyze in the image", "default": "Describe the image accurately and identify details relevant to the current task."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_code",
            "description": "Ask the premium Codex code specialist for implementation or debugging help. Use for substantial coding tasks, then apply and verify the result with workspace tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Precise coding task or debugging question"},
                    "context": {"type": "string", "description": "Relevant code/context already gathered", "default": ""}
                },
                "required": ["task"]
            }
        }
    },
    # ── Document creation ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_pdf",
            "description": "Create a PDF document with title, sections, and text. Saves to workspace/ and returns path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Output filename e.g. 'report.pdf'"},
                    "title": {"type": "string", "description": "Document title shown at top"},
                    "content": {"type": "string", "description": "Document body in plain text or markdown (#/##/-) format"},
                },
                "required": ["filename", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pptx",
            "description": "Create a polished 16:9 PowerPoint (.pptx) with a branded design system: title slide, section dividers, metric/stat slides, quote slides, two-column and image layouts, speaker notes, and slide numbers. To embed an image, first generate it with generate_image, then pass its workspace-relative path as image_path (e.g. 'images/chart.png'). Saves to workspace/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "title": {"type": "string", "description": "Presentation title (goes on the title slide)"},
                    "subtitle": {"type": "string", "description": "Optional subtitle/tagline for the title slide", "default": ""},
                    "slides": {
                        "type": "array",
                        "description": "Array of slide objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "array", "items": {"type": "string"}, "description": "Bullet points. For layout='metrics', use 'VALUE|LABEL' items (e.g. '23%|Revenue growth'). For layout='quote', item 0 is the quote and item 1 the attribution."},
                                "image_path": {"type": "string", "description": "Optional: workspace-relative path to an image to embed (e.g. 'images/chart.png')"},
                                "notes": {"type": "string", "description": "Optional speaker notes for this slide"},
                                "layout": {"type": "string", "enum": ["text", "section", "metrics", "quote", "two_column", "image_right", "image_full"], "description": "text=bullets; section=divider; metrics=stat cards (VALUE|LABEL); quote=pull quote; two_column=split bullets; image_right=bullets+image; image_full=full-bleed image with caption", "default": "text"},
                            },
                            "required": ["title", "content"],
                        },
                    },
                },
                "required": ["filename", "title", "slides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_docx",
            "description": "Create a Word document (.docx) with headings and paragraphs. Saves to workspace/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Document body (markdown headings # ## ### and - bullets supported)"},
                },
                "required": ["filename", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_excel",
            "description": "Create an Excel spreadsheet (.xlsx) with one or more sheets of tabular data. Saves to workspace/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "sheets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Sheet tab name"},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "description": "2D array of cell values", "items": {"type": "array"}},
                            },
                            "required": ["name", "headers", "rows"],
                        },
                    },
                },
                "required": ["filename", "sheets"],
            },
        },
    },
    # ── Web tools ──────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "web_crawl",
            "description": "Fetch and extract readable text content from a public URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch (https://...)"},
                    "max_chars": {"type": "integer", "description": "Max chars to return (default 5000)", "default": 5000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return results with titles, snippets, and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "max_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    # ── Image generation ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an AI image from a text prompt and save it to workspace/images/. Returns the saved file path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed description of the image to generate"},
                    "filename": {"type": "string", "description": "Output filename e.g. 'diagram.png' (auto-named if blank)", "default": ""},
                    "size": {"type": "string", "description": "Image size: 1024x1024, 1792x1024, 1024x1792", "default": "1024x1024"},
                },
                "required": ["prompt"],
            },
        },
    },
]


# ── PDF text safety (fpdf2 core fonts are Latin-1 only) ───────────────────────

_PDF_TRANSLIT = {
    "•": "-", "‣": "-", "◦": "-", "⁃": "-", "∙": "-",
    "–": "-", "—": "-", "‒": "-", "―": "-",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "…": "...", " ": " ", " ": " ", " ": " ", "​": "",
    "→": "->", "←": "<-", "↑": "^", "↓": "v",
    "™": "(TM)", "®": "(R)", "©": "(C)",
    "≠": "!=", "≤": "<=", "≥": ">=", "×": "x", "÷": "/",
}


def pdf_safe_text(s: str) -> str:
    """Make text safe for fpdf2's built-in Helvetica (Latin-1). Transliterates
    common Unicode punctuation and drops anything else, so PDFs never crash on
    bullets, em-dashes, smart quotes, or ellipses."""
    if not s:
        return s or ""
    for k, v in _PDF_TRANSLIT.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


# ── Diff preview helper ───────────────────────────────────────────────────────

def compute_diff(old_content: str, new_content: str, filename: str) -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "".join(diff) or "(no changes)"


# ── Tool build preview ────────────────────────────────────────────────────────

def build_preview(tool: str, args: Dict) -> str:
    if tool == "run_bash":
        return f"$ {args.get('command', '')}"
    if tool == "run_python":
        code = args.get("code", "")
        preview = code[:300] + ("…" if len(code) > 300 else "")
        return f"```python\n{preview}\n```"
    if tool in ("write_file", "create_file"):
        path = args.get("path", "")
        content = args.get("content", "")
        target = _safe_path(path)
        if tool == "write_file" and target.exists():
            old = target.read_text(encoding="utf-8", errors="replace")
            return compute_diff(old, content, path)
        preview = content[:500] + ("…" if len(content) > 500 else "")
        return f"Create {path}:\n{preview}"
    if tool == "patch_file":
        return f"Patch workspace/{args.get('path', '')}: replace {len(args.get('old_text', ''))} chars with {len(args.get('new_text', ''))} chars"
    if tool == "inspect_image":
        return f"Inspect image workspace/{args.get('path', '')}: {args.get('question', '')[:120]}"
    if tool == "delegate_code":
        return f"Delegate to code specialist: {args.get('task', '')[:160]}"
    if tool == "delete_file":
        return f"Delete workspace/{args.get('path', '')}"
    if tool == "list_files":
        return f"List workspace/{args.get('directory', '')}"
    if tool == "read_file":
        return f"Read workspace/{args.get('path', '')}"
    if tool == "search_files":
        return f"Search '{args.get('pattern', '')}' in {args.get('file_pattern', '*')}"
    if tool == "create_pdf":
        return f"Create PDF: {args.get('filename', '')} — {args.get('title', '')}"
    if tool == "create_pptx":
        n = len(args.get("slides", []))
        return f"Create PPTX: {args.get('filename', '')} — {n} slides"
    if tool == "create_docx":
        return f"Create DOCX: {args.get('filename', '')} — {args.get('title', '')}"
    if tool == "create_excel":
        sheets = [s.get("name", "Sheet") for s in args.get("sheets", [])]
        return f"Create Excel: {args.get('filename', '')} — sheets: {', '.join(sheets)}"
    if tool == "web_crawl":
        return f"Fetch URL: {args.get('url', '')}"
    if tool == "web_search":
        return f"Search: \"{args.get('query', '')}\""
    if tool == "generate_image":
        prompt = args.get("prompt", "")
        return f"Generate image: {prompt[:120]}{'…' if len(prompt)>120 else ''}"
    return str(args)[:200]


# ── Tool executors ────────────────────────────────────────────────────────────

async def execute_tool(tool: str, args: Dict, image_fn=None) -> str:
    try:
        if tool == "read_file":       return await _read_file(args)
        if tool == "write_file":      return await _write_file(args)
        if tool == "create_file":     return await _create_file(args)
        if tool == "delete_file":     return await _delete_file(args)
        if tool == "list_files":      return await _list_files(args)
        if tool == "run_bash":        return await _run_bash(args)
        if tool == "run_python":      return await _run_python(args)
        if tool == "search_files":    return await _search_files(args)
        if tool == "patch_file":      return await _patch_file(args)
        if tool == "inspect_image":   return await _inspect_image(args)
        if tool == "delegate_code":   return await _delegate_code(args)
        if tool == "create_pdf":      return await _create_pdf(args)
        if tool == "create_pptx":     return await _create_pptx(args)
        if tool == "create_docx":     return await _create_docx(args)
        if tool == "create_excel":    return await _create_excel(args)
        if tool == "web_crawl":       return await _web_crawl(args)
        if tool == "web_search":      return await _web_search(args)
        if tool == "generate_image":  return await _generate_image(args, image_fn=image_fn)
        return f"Unknown tool: {tool}"
    except Exception as exc:
        return f"Error: {exc}"


# ── File tools ────────────────────────────────────────────────────────────────

async def _read_file(args: Dict) -> str:
    path = _safe_path(args["path"])
    if not path.exists():
        return f"File not found: {args['path']}"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(1, int(args.get("start_line") or 1))
    end = int(args.get("end_line") or len(lines))
    end = max(start, min(end, len(lines)))
    selected = "\n".join(lines[start - 1:end])
    max_chars = max(1000, min(int(args.get("max_chars") or 20000), 100000))
    if len(selected) > max_chars:
        selected = selected[:max_chars] + "\n...[truncated; request a narrower line range]"
    return selected


async def _write_file(args: Dict) -> str:
    path = _safe_path(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"Written {len(args['content'])} chars to {args['path']}"


async def _create_file(args: Dict) -> str:
    path = _safe_path(args["path"])
    if path.exists():
        return f"File already exists: {args['path']} — use write_file to overwrite"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"Created {args['path']}"


async def _patch_file(args: Dict) -> str:
    path = _safe_path(args["path"])
    if not path.exists():
        return f"File not found: {args['path']}"
    old = args.get("old_text", "")
    new = args.get("new_text", "")
    if not old:
        return "Error: old_text must not be empty"
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = []
    start = 0
    while True:
        idx = text.find(old, start)
        if idx < 0:
            break
        matches.append(idx)
        start = idx + max(1, len(old))
    if not matches:
        return "Error: exact old_text was not found; read the relevant range and retry with exact text"
    occurrence = int(args.get("occurrence") or 1)
    if occurrence < 1 or occurrence > len(matches):
        return f"Error: occurrence must be between 1 and {len(matches)}"
    idx = matches[occurrence - 1]
    updated = text[:idx] + new + text[idx + len(old):]
    path.write_text(updated, encoding="utf-8")
    return (
        f"Patched {args['path']} occurrence {occurrence}/{len(matches)} "
        f"({len(old)} chars -> {len(new)} chars)"
    )


async def _inspect_image(args: Dict) -> str:
    import base64 as _b64
    import mimetypes
    path = _safe_path(args["path"])
    if not path.exists():
        return f"File not found: {args['path']}"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime.startswith("image/"):
        return f"Error: {args['path']} is not an image"
    b64 = _b64.b64encode(path.read_bytes()).decode()
    question = args.get("question") or "Describe the image accurately."
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }]
    cfg = get_config()
    chunks = []
    if cfg.azure_chat:
        from ..providers.azure_chat import stream_chat
        async for token in stream_chat(messages, "gpt-4.1-global", max_tokens=4000):
            chunks.append(token)
    elif cfg.azure_gpt5:
        from ..providers.azure_gpt5 import stream_gpt5
        async for token in stream_gpt5(messages, "gpt-5-global", max_tokens=4000):
            chunks.append(token)
    else:
        return "Error: no vision-capable Azure chat/GPT-5 gateway is configured"
    return "".join(chunks)


async def _delegate_code(args: Dict) -> str:
    from ..config import get_config
    cfg = get_config()
    if not cfg.azure_gpt5:
        return "Error: GPT-5/Codex gateway is not configured"
    task = args.get("task", "").strip()
    context = args.get("context", "")
    prompt = (
        "You are a code specialist working inside a larger agent. "
        "Return implementation-ready guidance or code. Be explicit about assumptions, "
        "edge cases, and validation. Do not claim files were changed.\n\n"
        f"TASK:\n{task}\n\n"
    )
    if context:
        prompt += f"CONTEXT:\n{context[:60000]}"
    from ..providers.azure_gpt5 import codex_responses_api
    return await codex_responses_api("gpt-5.3-codex-global", prompt, max_output_tokens=8000)


async def _delete_file(args: Dict) -> str:
    path = _safe_path(args["path"])
    if not path.exists():
        return f"File not found: {args['path']}"
    path.unlink()
    return f"Deleted {args['path']}"


async def _list_files(args: Dict) -> str:
    directory = args.get("directory", "")
    workspace = _active_workspace()
    base = _safe_path(directory) if directory else workspace
    if not base.exists():
        return "Directory not found"
    files = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rel = p.relative_to(workspace)
            files.append(str(rel))
    return "\n".join(files) if files else "(empty workspace)"


async def _run_bash(args: Dict) -> str:
    cmd = args["command"]
    timeout = min(int(args.get("timeout", 30)), 60)
    workspace = _active_workspace()
    loop = asyncio.get_event_loop()

    def _run():
        result = subprocess.run(
            cmd, shell=True, cwd=str(workspace),
            capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout + result.stderr
        return out[:4000] + ("…[truncated]" if len(out) > 4000 else "")

    try:
        return await loop.run_in_executor(None, _run)
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"


async def _run_python(args: Dict) -> str:
    code = args["code"]
    timeout = min(int(args.get("timeout", 30)), 60)
    workspace = str(_active_workspace())
    loop = asyncio.get_event_loop()

    def _run():
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workspace, capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout + result.stderr
        return out[:4000] + ("…[truncated]" if len(out) > 4000 else "")

    try:
        return await loop.run_in_executor(None, _run)
    except subprocess.TimeoutExpired:
        return f"Python execution timed out after {timeout}s"


async def _search_files(args: Dict) -> str:
    pattern = args["pattern"]
    file_glob = args.get("file_pattern", "*")
    workspace = _active_workspace()
    results = []
    for path in workspace.rglob(file_glob):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.lower() in line.lower():
                        rel = path.relative_to(workspace)
                        results.append(f"{rel}:{i}: {line.rstrip()}")
            except Exception:
                pass
    if not results:
        return f"No matches for '{pattern}'"
    out = "\n".join(results[:100])
    if len(results) > 100:
        out += f"\n… ({len(results) - 100} more matches)"
    return out


# ── Document creation tools ───────────────────────────────────────────────────

async def _create_pdf(args: Dict) -> str:
    filename = args["filename"]
    if not filename.endswith(".pdf"):
        filename += ".pdf"
    title = args["title"]
    content = args["content"]
    path = _safe_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    def _make():
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_margins(20, 20, 20)
        pdf.set_auto_page_break(auto=True, margin=20)

        # Title
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, pdf_safe_text(title), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(4)

        pdf.set_font("Helvetica", size=11)
        for raw_line in content.split("\n"):
            line = pdf_safe_text(raw_line.rstrip())
            if line.startswith("### "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.cell(0, 9, line[4:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=11)
            elif line.startswith("## "):
                pdf.set_font("Helvetica", "B", 15)
                pdf.cell(0, 10, line[3:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=11)
            elif line.startswith("# "):
                pdf.set_font("Helvetica", "B", 17)
                pdf.cell(0, 11, line[2:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=11)
            elif line.startswith("- ") or line.startswith("* "):
                # new_x=LMARGIN resets the cursor — multi_cell otherwise leaves x at
                # the right edge, starving the next multi_cell of horizontal space.
                pdf.multi_cell(0, 7, "   -  " + line[2:], new_x="LMARGIN", new_y="NEXT")
            elif line == "":
                pdf.ln(3)
            else:
                pdf.multi_cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")

        pdf.output(str(path))

    await loop.run_in_executor(None, _make)
    size = path.stat().st_size
    return f"PDF created: workspace/{filename} ({size:,} bytes)"


async def _create_pptx(args: Dict) -> str:
    filename = args["filename"]
    if not filename.endswith(".pptx"):
        filename += ".pptx"
    title = args["title"]
    subtitle = args.get("subtitle", "")
    slides_data = args["slides"]
    path = _safe_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    def _make():
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
        from pptx.enum.shapes import MSO_SHAPE

        # ── Brand palette ────────────────────────────────────────────────────
        RED    = RGBColor(0xCC, 0x00, 0x00)
        DARK   = RGBColor(0x14, 0x14, 0x28)
        SLATE  = RGBColor(0x33, 0x37, 0x4D)
        WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
        MUTED  = RGBColor(0x6B, 0x70, 0x86)
        FAINT  = RGBColor(0xBB, 0xBE, 0xCC)
        CARD   = RGBColor(0xF3, 0xF4, 0xF8)
        FONT_H = "Calibri"
        FONT_B = "Calibri"

        def _add_text(para, text, size_pt, bold=False, color=None, italic=False,
                      align=None, font=FONT_B):
            """Crash-safe run insertion (never touches paragraph.runs[0])."""
            run = para.add_run()
            run.text = "" if text is None else str(text)
            run.font.size = Pt(size_pt)
            run.font.bold = bold
            run.font.italic = italic
            run.font.name = font
            if color:
                run.font.color.rgb = color
            if align is not None:
                para.alignment = align

        def _rect(slide, x, y, w, h, color, shape=MSO_SHAPE.RECTANGLE):
            sp = slide.shapes.add_shape(shape, x, y, w, h)
            sp.fill.solid()
            sp.fill.fore_color.rgb = color
            sp.line.fill.background()
            sp.shadow.inherit = False
            return sp

        def _bg(slide, color):
            _rect(slide, 0, 0, W, H, color)

        def _translucent(shape, alpha_val):
            """Best-effort alpha on a shape's solid fill (pptx has no direct API)."""
            try:
                from lxml import etree
                ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
                spPr = shape.fill._xPr
                solid = spPr.find(f".//{{{ns}}}solidFill")
                if solid is not None:
                    srgb = solid.find(f"{{{ns}}}srgbClr")
                    if srgb is not None:
                        el = etree.SubElement(srgb, f"{{{ns}}}alpha")
                        el.set("val", str(alpha_val))
            except Exception:
                pass

        def _notes(slide, s):
            note = s.get("notes")
            if note:
                slide.notes_slide.notes_text_frame.text = str(note)

        def _blank():
            return prs.slides.add_slide(prs.slide_layouts[6])

        def _page_chrome(slide, title_text, number):
            """Top accent bar, title, red divider, footer with slide number."""
            _rect(slide, 0, 0, W, Inches(0.10), RED)
            tb_t = slide.shapes.add_textbox(Inches(0.5), Inches(0.30), W - Inches(1.0), Inches(0.75))
            tb_t.text_frame.word_wrap = True
            _add_text(tb_t.text_frame.paragraphs[0], title_text, 26, bold=True,
                      color=DARK, font=FONT_H)
            _rect(slide, Inches(0.5), Inches(1.02), Inches(1.1), Inches(0.045), RED)
            # Footer
            fb = slide.shapes.add_textbox(Inches(0.5), H - Inches(0.42), W - Inches(1.5), Inches(0.3))
            _add_text(fb.text_frame.paragraphs[0], "RDI AI  |  Johnson & Johnson", 9, color=MUTED)
            if number is not None:
                nb = slide.shapes.add_textbox(W - Inches(1.1), H - Inches(0.42), Inches(0.6), Inches(0.3))
                _add_text(nb.text_frame.paragraphs[0], str(number), 9, color=MUTED,
                          align=PP_ALIGN.RIGHT)

        prs = Presentation()
        prs.slide_width = Inches(13.333)   # 16:9 widescreen
        prs.slide_height = Inches(7.5)
        W = prs.slide_width
        H = prs.slide_height

        # ── Title slide ──────────────────────────────────────────────────────
        ts = _blank()
        _bg(ts, DARK)
        _rect(ts, 0, 0, Inches(0.28), H, RED)                       # left spine
        _rect(ts, Inches(0.9), Inches(2.55), Inches(2.2), Inches(0.09), RED)  # accent
        tb_title = ts.shapes.add_textbox(Inches(0.9), Inches(2.75), W - Inches(1.8), Inches(2.0))
        tb_title.text_frame.word_wrap = True
        _add_text(tb_title.text_frame.paragraphs[0], title, 44, bold=True, color=WHITE, font=FONT_H)
        if subtitle:
            tb_ss = ts.shapes.add_textbox(Inches(0.92), Inches(4.6), W - Inches(1.8), Inches(0.8))
            tb_ss.text_frame.word_wrap = True
            _add_text(tb_ss.text_frame.paragraphs[0], subtitle, 20, color=FAINT)
        tb_sub = ts.shapes.add_textbox(Inches(0.92), H - Inches(1.0), W - Inches(1.8), Inches(0.5))
        _add_text(tb_sub.text_frame.paragraphs[0],
                  "Generated by RDI AI  •  Johnson & Johnson", 13, color=FAINT)

        # ── Content slides ───────────────────────────────────────────────────
        page = 1
        for s in slides_data:
            layout = (s.get("layout") or "text").strip()
            slide_title = s.get("title", "")
            bullets = [str(b) for b in s.get("content", []) if str(b).strip()]

            img_rel = (s.get("image_path") or "").strip()
            img_path = None
            if img_rel:
                # Strip common prefixes the model sometimes adds
                for _pfx in ("workspace/", "./workspace/", "./"):
                    if img_rel.startswith(_pfx):
                        img_rel = img_rel[len(_pfx):]
                        break
                # Try the given path, then fall back to just the filename under images/
                _ws = _active_workspace()
                for _candidate in [_ws / img_rel, _ws / "images" / Path(img_rel).name]:
                    if _candidate.exists():
                        img_path = _candidate
                        break
                if not img_path:
                    print(f"[pptx] WARNING: image_path '{img_rel}' not found — slide will be text-only")

            # ── Section divider ──────────────────────────────────────────────
            if layout == "section":
                slide = _blank()
                _bg(slide, SLATE)
                _rect(slide, Inches(0.9), Inches(3.05), Inches(1.8), Inches(0.09), RED)
                tb = slide.shapes.add_textbox(Inches(0.9), Inches(3.25), W - Inches(1.8), Inches(1.6))
                tb.text_frame.word_wrap = True
                _add_text(tb.text_frame.paragraphs[0], slide_title, 40, bold=True,
                          color=WHITE, font=FONT_H)
                if bullets:
                    tb2 = slide.shapes.add_textbox(Inches(0.92), Inches(4.7), W - Inches(1.8), Inches(1.0))
                    tb2.text_frame.word_wrap = True
                    _add_text(tb2.text_frame.paragraphs[0], bullets[0], 18, color=FAINT)
                _notes(slide, s)
                page += 1
                continue

            # ── Quote slide ──────────────────────────────────────────────────
            if layout == "quote":
                slide = _blank()
                _bg(slide, CARD)
                _rect(slide, 0, 0, Inches(0.10), H, RED)
                mark = slide.shapes.add_textbox(Inches(0.7), Inches(0.7), Inches(3), Inches(2))
                _add_text(mark.text_frame.paragraphs[0], "“", 120, bold=True, color=RED, font=FONT_H)
                quote = bullets[0] if bullets else slide_title
                attrib = bullets[1] if len(bullets) > 1 else ""
                tb = slide.shapes.add_textbox(Inches(1.4), Inches(2.4), W - Inches(2.8), Inches(2.6))
                tb.text_frame.word_wrap = True
                _add_text(tb.text_frame.paragraphs[0], quote, 30, italic=True, color=DARK, font=FONT_H)
                if attrib:
                    ab = slide.shapes.add_textbox(Inches(1.42), Inches(5.1), W - Inches(2.8), Inches(0.6))
                    _add_text(ab.text_frame.paragraphs[0], f"— {attrib}", 18, bold=True, color=RED)
                _notes(slide, s)
                page += 1
                continue

            # ── Metrics / stat cards ─────────────────────────────────────────
            if layout == "metrics":
                slide = _blank()
                _bg(slide, WHITE)
                _page_chrome(slide, slide_title, page)
                stats = []
                for item in bullets[:4]:
                    if "|" in item:
                        val, lbl = item.split("|", 1)
                    else:
                        val, lbl = item, ""
                    stats.append((val.strip(), lbl.strip()))
                n = max(1, len(stats))
                margin = Inches(0.5)
                gap = Inches(0.35)
                total_gap = gap * (n - 1)
                card_w = (W - margin * 2 - total_gap) / n
                card_h = Inches(2.9)
                top = Inches(2.3)
                for i, (val, lbl) in enumerate(stats):
                    x = margin + i * (card_w + gap)
                    _rect(slide, x, top, card_w, card_h, CARD, MSO_SHAPE.ROUNDED_RECTANGLE)
                    _rect(slide, x, top, card_w, Inches(0.10), RED)
                    vtb = slide.shapes.add_textbox(x, top + Inches(0.55), card_w, Inches(1.3))
                    vtb.text_frame.word_wrap = True
                    _add_text(vtb.text_frame.paragraphs[0], val, 46, bold=True, color=RED,
                              align=PP_ALIGN.CENTER, font=FONT_H)
                    ltb = slide.shapes.add_textbox(x + Inches(0.15), top + Inches(1.95),
                                                   card_w - Inches(0.3), Inches(0.8))
                    ltb.text_frame.word_wrap = True
                    _add_text(ltb.text_frame.paragraphs[0], lbl, 15, color=SLATE,
                              align=PP_ALIGN.CENTER)
                _notes(slide, s)
                page += 1
                continue

            # ── Image full ───────────────────────────────────────────────────
            if img_path and layout == "image_full":
                slide = _blank()
                slide.shapes.add_picture(str(img_path), 0, 0, W, H)
                cap_h = Inches(1.5)
                cap = _rect(slide, 0, H - cap_h, W, cap_h, DARK)
                _translucent(cap, 68000)
                _rect(slide, 0, H - cap_h, W, Inches(0.08), RED)
                tb = slide.shapes.add_textbox(Inches(0.6), H - cap_h + Inches(0.32),
                                              W - Inches(1.2), cap_h - Inches(0.5))
                tb.text_frame.word_wrap = True
                _add_text(tb.text_frame.paragraphs[0], slide_title, 30, bold=True,
                          color=WHITE, font=FONT_H)
                if bullets:
                    _add_text(tb.text_frame.add_paragraph(), bullets[0], 16, color=FAINT)
                _notes(slide, s)
                page += 1
                continue

            # ── Image full bleed ─────────────────────────────────────────────
            if layout == "image_full":
                slide = _blank()
                _bg(slide, DARK)
                if img_path:
                    slide.shapes.add_picture(str(img_path), 0, 0, W, H)
                # Dark caption bar at bottom
                cap_h = Inches(1.5)
                overlay = _rect(slide, 0, H - cap_h, W, cap_h, DARK)
                try:
                    from lxml import etree as _et
                    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
                    solid = overlay.fill._xPr.find(f".//{{{ns}}}solidFill")
                    if solid is not None:
                        srgb = solid.find(f"{{{ns}}}srgbClr")
                        if srgb is not None:
                            a = _et.SubElement(srgb, f"{{{ns}}}alpha")
                            a.set("val", "75000")  # ~75% opacity
                except Exception:
                    pass
                tb = slide.shapes.add_textbox(Inches(0.7), H - cap_h + Inches(0.15),
                                              W - Inches(1.4), cap_h - Inches(0.2))
                tb.text_frame.word_wrap = True
                _add_text(tb.text_frame.paragraphs[0], slide_title, 30, bold=True,
                          color=WHITE, font=FONT_H)
                if bullets:
                    _add_text(tb.text_frame.add_paragraph(), bullets[0], 15, color=FAINT)
                _notes(slide, s)
                page += 1
                continue

            # ── Image right ──────────────────────────────────────────────────
            if img_path and layout == "image_right":
                slide = _blank()
                _bg(slide, WHITE)
                _page_chrome(slide, slide_title, page)
                col_w = int(W * 0.46)
                tb_b = slide.shapes.add_textbox(Inches(0.5), Inches(1.35),
                                                col_w - Inches(0.5), H - Inches(2.0))
                tf_b = tb_b.text_frame
                tf_b.word_wrap = True
                for i, point in enumerate(bullets):
                    para = tf_b.paragraphs[0] if i == 0 else tf_b.add_paragraph()
                    _add_text(para, f"›  {point}", 16, color=SLATE)
                    para.space_after = Pt(10)
                slide.shapes.add_picture(str(img_path), col_w, Inches(1.35),
                                         W - col_w - Inches(0.5), H - Inches(2.0))
                _notes(slide, s)
                page += 1
                continue

            # ── Image + bullets (default when an image is present) ───────────
            if img_path:
                slide = _blank()
                _bg(slide, WHITE)
                _page_chrome(slide, slide_title, page)
                text_rows = min(len(bullets), 3)
                tb_b = slide.shapes.add_textbox(Inches(0.5), Inches(1.35),
                                                W - Inches(1.0), Inches(1.7))
                tf_b = tb_b.text_frame
                tf_b.word_wrap = True
                for i, point in enumerate(bullets[:text_rows]):
                    para = tf_b.paragraphs[0] if i == 0 else tf_b.add_paragraph()
                    _add_text(para, f"›  {point}", 15, color=SLATE)
                img_top = Inches(3.2)
                slide.shapes.add_picture(str(img_path), Inches(1.5), img_top,
                                         W - Inches(3.0), H - img_top - Inches(0.6))
                _notes(slide, s)
                page += 1
                continue

            # ── Two-column text ──────────────────────────────────────────────
            if layout == "two_column":
                slide = _blank()
                _bg(slide, WHITE)
                _page_chrome(slide, slide_title, page)
                mid = (len(bullets) + 1) // 2
                cols = [bullets[:mid], bullets[mid:]]
                col_w = (W - Inches(1.3)) / 2
                for c, col in enumerate(cols):
                    x = Inches(0.5) + c * (col_w + Inches(0.3))
                    tb = slide.shapes.add_textbox(x, Inches(1.35), col_w, H - Inches(2.0))
                    tf = tb.text_frame
                    tf.word_wrap = True
                    for i, point in enumerate(col):
                        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                        _add_text(para, f"›  {point}", 16, color=SLATE)
                        para.space_after = Pt(10)
                _notes(slide, s)
                page += 1
                continue

            # ── Text-only (default) ──────────────────────────────────────────
            slide = _blank()
            _bg(slide, WHITE)
            _page_chrome(slide, slide_title, page)
            tb_b = slide.shapes.add_textbox(Inches(0.5), Inches(1.4),
                                            W - Inches(1.0), H - Inches(2.1))
            tf_b = tb_b.text_frame
            tf_b.word_wrap = True
            for i, point in enumerate(bullets):
                para = tf_b.paragraphs[0] if i == 0 else tf_b.add_paragraph()
                _add_text(para, f"›  {point}", 18, color=SLATE)
                para.space_after = Pt(12)
            _notes(slide, s)
            page += 1

        prs.save(str(path))

    await loop.run_in_executor(None, _make)
    return f"PowerPoint created: workspace/{filename} ({path.stat().st_size:,} bytes)"


async def _create_docx(args: Dict) -> str:
    filename = args["filename"]
    if not filename.endswith(".docx"):
        filename += ".docx"
    title = args["title"]
    content = args["content"]
    path = _safe_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    def _make():
        from docx import Document
        doc = Document()
        doc.add_heading(title, 0)

        for line in content.split("\n"):
            line = line.rstrip()
            if line.startswith("### "):
                doc.add_heading(line[4:], level=3)
            elif line.startswith("## "):
                doc.add_heading(line[3:], level=2)
            elif line.startswith("# "):
                doc.add_heading(line[2:], level=1)
            elif line.startswith("- ") or line.startswith("* "):
                doc.add_paragraph(line[2:], style="List Bullet")
            elif line == "":
                pass
            else:
                doc.add_paragraph(line)

        doc.save(str(path))

    await loop.run_in_executor(None, _make)
    return f"Word document created: workspace/{filename} ({path.stat().st_size:,} bytes)"


async def _create_excel(args: Dict) -> str:
    filename = args["filename"]
    if not filename.endswith(".xlsx"):
        filename += ".xlsx"
    sheets = args["sheets"]
    path = _safe_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    def _make():
        import openpyxl
        from openpyxl.styles import Font, PatternFill

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        for sheet_data in sheets:
            ws = wb.create_sheet(title=sheet_data.get("name", "Sheet"))
            headers = sheet_data.get("headers", [])
            rows = sheet_data.get("rows", [])

            # Header row with styling
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="4B5563")

            # Data rows
            for row_idx, row in enumerate(rows, 2):
                for col_idx, val in enumerate(row, 1):
                    ws.cell(row=row_idx, column=col_idx, value=val)

            # Auto-fit columns
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

        wb.save(str(path))

    await loop.run_in_executor(None, _make)
    return f"Excel file created: workspace/{filename} ({path.stat().st_size:,} bytes)"


# ── Web tools ─────────────────────────────────────────────────────────────────

async def _web_crawl(args: Dict) -> str:
    url = args["url"]
    max_chars = int(args.get("max_chars", 5000))

    # Try Playwright (renders JS) if installed, fall back to urllib
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=20000)
                html = await page.content()
            finally:
                # Always close the browser, even if navigation fails, to avoid leaks.
                await browser.close()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        text = text[:max_chars] + ("…[truncated]" if len(text) > max_chars else "")
        return f"Content from {url} (JS-rendered):\n\n{text}"
    except ImportError:
        pass  # Playwright not installed — use urllib fallback
    except Exception:
        pass  # Playwright failed (e.g. no browser) — use urllib fallback

    loop = asyncio.get_event_loop()

    def _fetch():
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:max_chars] + ("…[truncated]" if len(text) > max_chars else "")

    try:
        result = await loop.run_in_executor(None, _fetch)
        return f"Content from {url}:\n\n{result}"
    except Exception as exc:
        return f"Failed to crawl {url}: {exc}"


async def _web_search(args: Dict) -> str:
    query = args["query"]
    max_results = int(args.get("max_results", 5))
    loop = asyncio.get_event_loop()

    def _search():
        from bs4 import BeautifulSoup
        q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={q}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.select(".result"):
            title_el = item.select_one(".result__a")
            snippet_el = item.select_one(".result__snippet")
            url_el = item.select_one(".result__url")
            if title_el:
                results.append({
                    "title": title_el.get_text(strip=True),
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    "url": url_el.get_text(strip=True) if url_el else title_el.get("href", ""),
                })
            if len(results) >= max_results:
                break
        return results

    try:
        results = await loop.run_in_executor(None, _search)
        if not results:
            return f"No search results found for: {query}"
        lines = [f"Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '')}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            if r.get("url"):
                lines.append(f"   {r['url']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"Search failed: {exc}"


# ── Image generation ──────────────────────────────────────────────────────────

async def _generate_image(args: Dict, image_fn=None) -> str:
    import base64 as _b64
    import time

    prompt = args["prompt"]
    filename = (args.get("filename") or "").strip()
    if not filename:
        filename = f"image_{int(time.time())}.png"
    if not filename.endswith(".png"):
        filename += ".png"
    size = args.get("size", "1024x1024")

    path = _safe_path(f"images/{filename}")
    path.parent.mkdir(parents=True, exist_ok=True)

    cfg = get_config()
    loop = asyncio.get_event_loop()

    async def _emit_image(img_bytes: bytes):
        """Fire image_fn callback with the b64-encoded image so it shows inline in chat."""
        if image_fn:
            b64_str = _b64.b64encode(img_bytes).decode()
            await image_fn(b64_str, filename)

    def _success_msg(fname: str) -> str:
        # Single clean line the agent can copy verbatim into create_pptx image_path
        return f"Image saved. image_path = images/{fname}"

    # Try Azure DALL-E
    if hasattr(cfg, "azure_image") and cfg.azure_image:
        from ..providers.azure_image import generate_image as _az_gen
        result = await _az_gen(prompt, size=size)
        if result.get("b64"):
            img_bytes = _b64.b64decode(result["b64"])
            path.write_bytes(img_bytes)
            await _emit_image(img_bytes)
            return _success_msg(filename)
        if result.get("url"):
            def _dl():
                with urllib.request.urlopen(result["url"]) as r:
                    return r.read()
            img_bytes = await loop.run_in_executor(None, _dl)
            path.write_bytes(img_bytes)
            await _emit_image(img_bytes)
            return _success_msg(filename)
        if result.get("error"):
            return f"Image generation error: {result['error']}"

    # Try Vertex Imagen
    if hasattr(cfg, "vertex_image") and cfg.vertex_image:
        from ..providers.vertex import generate_vertex_image
        result = await generate_vertex_image(prompt)
        if result.get("b64"):
            img_bytes = _b64.b64decode(result["b64"])
            path.write_bytes(img_bytes)
            await _emit_image(img_bytes)
            return _success_msg(filename)

    return (
        "Image generation is not configured. "
        "Add [azure_image] or [vertex_image] section to config.ini."
    )


# ── Workspace file tree (for UI sidebar) ─────────────────────────────────────

def get_file_tree() -> List[Dict]:
    workspace = _active_workspace()
    tree = []
    if not workspace.exists():
        return tree
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and ".gitkeep" not in p.name:
            rel = p.relative_to(workspace)
            tree.append({
                "path": str(rel).replace("\\", "/"),
                "name": p.name,
                "size": p.stat().st_size,
            })
    return tree
