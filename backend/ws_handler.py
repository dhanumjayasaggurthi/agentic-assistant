"""WebSocket session handler — bidirectional streaming + permission pause/resume.

Robustness layer (2026-07-12 redesign — "never break mid-run"):

  • Seq-numbered stream + resume buffer. Every event emitted during a chat/run
    carries a monotonically increasing `seq`, buffered per conversation. If the
    socket drops, the run KEEPS GOING server-side; on reconnect the client sends
    {type:"resume", conversation_id, last_seq} and receives every missed event
    (`resume_ok` + replay). Nothing is lost.
  • Checkpointed runs. Agent runs persist a step timeline to the `runs` table
    after every state change (see database.create_run/checkpoint_run/finish_run),
    so a killed process still shows an accurate, resumable timeline.
  • Permission decisions survive reconnects: they are keyed on the stream state,
    not the socket. Auto-approve for read-only tools is supported
    ({type:"set_auto_allow", enabled:true}).
  • Model fallback. Tool-less models (Codex / image models) selected in Agent
    mode never error the run: it falls back to a tool-capable model and emits
    {type:"model_fallback", requested, fallback} for the UI banner.
  • Model-stream retries with backoff (only before first token, so output is
    never duplicated).
  • Artifact registry. Every file a run produces is registered (database.
    register_artifact) so later steps/chats can reuse it ("build a PPT with
    those images").
"""
import asyncio
import base64
import json
import logging
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .agents.chat_agent import build_messages, stream_response, trim_history
from .agents.coding_agent import run_coding_agent
from .agents.tools import _workspace_var, get_file_tree
from .config import get_config
from .model_capabilities import model_supports_tools, preferred_agent_orchestrator
from .database import (
    add_message, auto_title, checkpoint_run, create_conversation, create_run,
    bind_attachments_to_conversation, delete_conversation, finish_run,
    get_attachment, get_conversation, get_latest_run, get_messages,
    get_other_conversation_summaries, get_user_by_id, list_artifacts,
    list_conversations, record_usage, register_artifact, set_user_workspace,
    update_conversation_meta,
)
from .providers.azure_audio import text_to_speech_b64, transcribe
from .providers.azure_image import edit_image, generate_image
from .providers.vertex import generate_vertex_image
from .telemetry import emit as telemetry_emit

# Activity icons per tool
_TOOL_ICONS: Dict[str, str] = {
    "read_file": "📄", "file_overview": "📊", "write_file": "✏️", "create_file": "📝",
    "patch_file": "🩹", "inspect_image": "👁️", "delegate_code": "🧠",
    "delete_file": "🗑️", "list_files": "📁", "run_bash": "⚡",
    "run_python": "🐍", "search_files": "🔍", "create_pdf": "📑",
    "create_pptx": "📊", "create_docx": "📃", "create_excel": "📈",
    "web_crawl": "🌐", "web_search": "🔎", "generate_image": "🖼️",
}

# Tools that never mutate anything — eligible for auto-approval.
READONLY_TOOLS = {"read_file", "file_overview", "list_files", "search_files", "web_search", "web_crawl", "inspect_image"}

# Tools that produce files — their outputs get registered as artifacts.
FILE_TOOLS = {"write_file", "create_file", "patch_file", "create_pdf", "create_pptx",
              "create_docx", "create_excel", "generate_image"}

# ── Stream state: survives socket drops, owns seq numbering ──────────────────

_BUFFER_SIZE = 2000  # events kept for replay per conversation


class StreamState:
    """Per-(user, conversation) stream buffer + live socket pointer.

    The agent/chat task writes through emit(); whichever WSSession is currently
    attached receives the events. If none is attached the events just buffer.
    """

    def __init__(self, key: str):
        self.key = key
        self.seq = 0
        self.buffer: deque = deque(maxlen=_BUFFER_SIZE)
        self.partial_text = ""  # full active turn, not the bounded replay buffer
        self.session: Optional["WSSession"] = None
        self.running = False
        self.run_id: Optional[str] = None
        self.perm_events: Dict[str, asyncio.Event] = {}
        self.perm_decisions: Dict[str, str] = {}
        self.auto_allow_readonly = False
        self.auto_allow_tools: set[str] = set()
        self.task: Optional[asyncio.Task] = None
        self._emit_lock = asyncio.Lock()

    async def emit(self, data: dict) -> None:
        # Serialize live sends with reconnect replay so tokens never arrive
        # out of order or overtake an older replayed chunk.
        async with self._emit_lock:
            data = {**data, "conversation_id": self.key.split(":", 1)[1]}
            self.seq += 1
            data["seq"] = self.seq
            self.buffer.append(data)
            if data.get("type") == "token":
                self.partial_text += data.get("text", "")
            sess = self.session
            if sess is not None:
                try:
                    await sess.ws.send_json(data)
                except Exception:
                    if self.session is sess:
                        self.session = None

    def replay_after(self, last_seq: int) -> List[dict]:
        return [e for e in self.buffer if e.get("seq", 0) > last_seq]


_STREAMS: Dict[str, StreamState] = {}
_PERM_INDEX: Dict[str, str] = {}  # request_id -> stream key
_PERM_TOOL_INDEX: Dict[str, str] = {}  # tool name for approved permission prompt
_PERMISSION_TIMEOUT_SECONDS = 30 * 60
_logger = logging.getLogger(__name__)


def _stream_key(user_id: str, conv_id: str) -> str:
    return f"{user_id}:{conv_id}"


def get_stream(user_id: str, conv_id: str) -> StreamState:
    key = _stream_key(user_id, conv_id)
    st = _STREAMS.get(key)
    if st is None:
        st = StreamState(key)
        _STREAMS[key] = st
    return st


class WSSession:
    """One WebSocket session per connected client."""

    def __init__(self, ws: WebSocket, user: dict):
        self.ws = ws
        self.user = user
        self.conversation_id: Optional[str] = None
        self.cross_chat_reference: bool = False
        self.model: str = "gpt-4o-global"
        self.history: List[Dict] = []
        self.auto_allow_readonly: bool = False
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        # Workspace settings cache (loaded lazily from DB)
        self._workspace_mode: Optional[str] = None
        self._workspace_custom_path: Optional[str] = None

    # ── Workspace helpers ─────────────────────────────────────────────────────

    async def _load_ws_settings(self) -> None:
        if self._workspace_mode is not None:
            return
        full_user = await get_user_by_id(self.user["id"])
        self._workspace_mode = (full_user or {}).get("workspace_mode", "cloud") or "cloud"
        self._workspace_custom_path = (full_user or {}).get("workspace_custom_path") or ""

    def _ws_base(self) -> Path:
        if self._workspace_mode == "local" and self._workspace_custom_path:
            base = Path(self._workspace_custom_path).expanduser() / str(self.user["id"])
        else:
            base = get_config().workspace_dir / str(self.user["id"])
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _conv_workspace(self, conv_id: Optional[str] = None) -> Path:
        cid = conv_id or self.conversation_id
        ws = (self._ws_base() / cid) if cid else self._ws_base()
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def _hydrate_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Resolve lightweight attachment handles into model-ready content.

        The client carries only attachment IDs/metadata. Ownership is enforced
        in the database lookup; raw image bytes and extracted document text are
        loaded server-side only when needed by a model turn.
        """
        hydrated: List[Dict] = []
        for ref in attachments or []:
            if not isinstance(ref, dict):
                continue
            aid = ref.get("attachment_id") or ref.get("id")
            if not aid:
                # Backward compatibility with historical inline attachments.
                hydrated.append(ref)
                continue
            row = await get_attachment(aid, self.user["id"])
            if not row:
                continue
            content_type = row.get("content_type") or ref.get("content_type") or "text/plain"
            item = {
                "id": aid,
                "attachment_id": aid,
                "name": row.get("filename") or ref.get("name") or "file",
                "type": content_type,
                "content_type": content_type,
                "size": row.get("size_bytes") or ref.get("size") or 0,
                "storage_path": row.get("storage_path"),
            }
            storage_path = row.get("storage_path")
            base = self._ws_base().resolve()
            original = (base / storage_path).resolve() if storage_path else None
            authorized = original is not None and original.is_file() and original.is_relative_to(base)
            if content_type.startswith("image/"):
                if authorized:
                    item["content"] = base64.b64encode(original.read_bytes()).decode()
            else:
                # Most legacy attachments kept text in the DB. Modern uploads
                # have full extracted UTF-8 sidecars, with original bytes intact.
                sidecar = original.parent / "extracted.txt" if authorized else None
                manifest = original.parent / "manifest.json" if authorized else None
                if manifest and manifest.is_file():
                    try:
                        item["extraction"] = json.loads(manifest.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        item["extraction"] = {"complete": False, "note": "Extraction metadata unavailable"}
                if sidecar and sidecar.is_file():
                    item["extracted_path"] = str(sidecar)
                    if sidecar.stat().st_size <= 12_000:
                        item["content"] = sidecar.read_text(encoding="utf-8")
                    else:
                        item["content"] = ""
                else:
                    item["content"] = row.get("content") or ""
            hydrated.append(item)
        return hydrated

    async def _hydrate_history(self, history: List[Dict], max_messages: int = 10) -> List[Dict]:
        result: List[Dict] = []
        start = max(0, len(history) - max_messages)
        for i, msg in enumerate(history):
            copy = dict(msg)
            if i >= start and copy.get("role") == "user" and copy.get("attachments"):
                copy["attachments"] = await self._hydrate_attachments(copy["attachments"])
            result.append(copy)
        return result

    # ── Send helpers ──────────────────────────────────────────────────────────

    async def send(self, data: dict) -> None:
        await self.ws.send_json(data)

    async def send_error(self, msg: str) -> None:
        try:
            await self.send({"type": "error", "message": msg})
        except Exception:
            pass

    def _attach_stream(self, cid: str) -> StreamState:
        st = get_stream(self.user["id"], cid)
        st.session = self
        st.auto_allow_readonly = self.auto_allow_readonly
        return st

    # ── Message router ────────────────────────────────────────────────────────

    async def _run_request(self, handler, data: dict) -> None:
        current = asyncio.current_task()
        try:
            await handler(data)
        except asyncio.CancelledError:
            pass  # Stop has already acknowledged cancellation.
        except Exception:
            _logger.exception("Chat request failed")
            active = [st for st in _STREAMS.values() if st.task is current]
            if active:
                for st in active:
                    await st.emit({"type": "error", "message": "Request failed. Check server logs."})
            else:
                await self.send({"type": "error", "request_id": data.get("request_id"),
                                 "message": "Request failed. Check server logs."})
        finally:
            for st in _STREAMS.values():
                if st.task is current:
                    st.running = False
                    st.task = None
                    await st.emit({"type": "activity_done"})

    async def handle(self, data: dict) -> None:
        t = data.get("type", "")
        if t in ("chat", "generate_image", "edit_image"):
            handler = {"chat": self._handle_chat, "generate_image": self._handle_image,
                       "edit_image": self._handle_edit_image}[t]
            task = asyncio.create_task(self._run_request(handler, data))
            request_id = data.get("request_id")
            if request_id:
                self._pending_tasks[request_id] = task
                task.add_done_callback(
                    lambda finished, rid=request_id: self._pending_tasks.pop(rid, None)
                    if self._pending_tasks.get(rid) is finished else None
                )
        elif t == "stop":
            await self._handle_stop(data)
        elif t == "permission":
            await self._handle_permission(data)
        elif t == "resume":
            await self._handle_resume(data)
        elif t == "set_auto_allow":
            self.auto_allow_readonly = bool(data.get("enabled", False))
            if self.conversation_id:
                st = _STREAMS.get(_stream_key(self.user["id"], self.conversation_id))
                if st:
                    st.auto_allow_readonly = self.auto_allow_readonly
            await self.send({"type": "auto_allow_set", "enabled": self.auto_allow_readonly})
        elif t == "ping":
            await self.send({"type": "pong", "ts": data.get("ts")})
        elif t == "new_conversation":
            await self._handle_new_conversation(data)
        elif t == "load_conversation":
            await self._handle_load_conversation(data)
        elif t == "list_conversations":
            await self._handle_list_conversations()
        elif t == "set_model":
            self.model = data.get("model", self.model)
        elif t == "tts":
            asyncio.create_task(self._handle_tts(data))
        elif t == "transcribe":
            asyncio.create_task(self._handle_transcribe(data))
        elif t == "delete_conversation":
            await self._handle_delete_conversation(data)
        elif t == "rename_conversation":
            await self._handle_rename_conversation(data)
        elif t == "set_cross_chat_reference":
            await self._handle_cross_chat_reference(data)
        elif t == "set_workspace_settings":
            await self._handle_workspace_settings(data)
        elif t == "get_artifacts":
            cid = data.get("conversation_id") or self.conversation_id
            arts = await list_artifacts(cid) if cid else []
            await self.send({"type": "artifacts", "conv_id": cid, "artifacts": arts})
        elif t == "get_workspace":
            await self._load_ws_settings()
            tok = _workspace_var.set(self._conv_workspace())
            try:
                await self.send({
                    "type": "workspace",
                    "files": get_file_tree(),
                    "conv_id": self.conversation_id,
                    "workspace_mode": self._workspace_mode,
                })
            finally:
                _workspace_var.reset(tok)
        else:
            await self.send_error(f"Unknown message type: {t}")

    # ── Resume after reconnect ────────────────────────────────────────────────

    async def _handle_resume(self, data: dict) -> None:
        cid = data.get("conversation_id")
        last_seq = int(data.get("last_seq", 0) or 0)
        if not cid:
            await self.send({"type": "resume_ok", "running": False, "replayed": 0})
            return
        self.conversation_id = cid
        st = _STREAMS.get(_stream_key(self.user["id"], cid))
        if st is None:
            # No live buffer (server restarted?) — surface last checkpointed run
            run = await get_latest_run(cid)
            await self.send({
                "type": "resume_ok", "running": False, "replayed": 0,
                "current_seq": 0, "last_run": run,
            })
            return
        async with st._emit_lock:
            st.session = self
            # A bounded event replay may have rolled over: never silently
            # present only the last N tokens as though they were the full answer.
            gap = bool(st.buffer and last_seq < st.buffer[0].get("seq", 1) - 1)
            replay = [] if gap else st.replay_after(last_seq)
            await self.send({
                "type": "resume_ok", "conversation_id": cid,
                "running": st.running,
                "replayed": len(replay),
                "current_seq": st.seq,
                "snapshot": st.partial_text if gap and st.running else None,
                "reload_required": bool(gap and not st.running),
            })
            for ev in replay:
                try:
                    await self.ws.send_json(ev)
                except Exception:
                    st.session = None
                    return

    async def _handle_stop(self, data: dict) -> None:
        request_id = data.get("request_id")
        pending = self._pending_tasks.get(request_id) if request_id else None
        if pending and not pending.done():
            pending.cancel()
        # Explicit null means a not-yet-created conversation: never stop a
        # different chat held in session.conversation_id.
        cid = data.get("conversation_id") if "conversation_id" in data else self.conversation_id
        if not cid:
            return
        st = _STREAMS.get(_stream_key(self.user["id"], cid))
        if not st:
            return
        task = st.task
        st.running = False
        if task and not task.done():
            task.cancel()
        st.task = None
        for permission_id, event in list(st.perm_events.items()):
            _PERM_INDEX.pop(permission_id, None)
            _PERM_TOOL_INDEX.pop(permission_id, None)
            st.perm_events.pop(permission_id, None)
            event.set()
        st.perm_decisions.clear()
        await st.emit({"type": "cancelled", "message": "Run stopped by user."})
        await st.emit({"type": "activity_done"})

    # ── New conversation ──────────────────────────────────────────────────────

    async def _handle_new_conversation(self, data: dict) -> None:
        model = data.get("model", self.model)
        self.model = model
        self.history = []
        self.cross_chat_reference = False
        conv = await create_conversation(self.user["id"], model)
        self.conversation_id = conv["id"]
        await self._load_ws_settings()
        self._conv_workspace()
        await self.send({"type": "conversation_created", "id": conv["id"], "conversation": conv})

    # ── Load conversation ─────────────────────────────────────────────────────

    async def _handle_load_conversation(self, data: dict) -> None:
        cid = data.get("conversation_id")
        conv = await get_conversation(cid, self.user["id"])
        if not conv:
            await self.send_error("Conversation not found")
            return
        self.conversation_id = cid
        self.model = conv["model"]
        self.cross_chat_reference = bool(conv.get("cross_chat_reference", False))
        msgs = await get_messages(cid)
        self.history = [
            {"role": m["role"], "content": m["content"],
             "attachments": m.get("attachments") or []}
            for m in msgs
        ]
        # Re-attach to a live stream if this conversation has one (running agent).
        st = _STREAMS.get(_stream_key(self.user["id"], cid))
        if st is not None:
            st.session = self
        run = await get_latest_run(cid)
        partial_text = st.partial_text if st and st.running else ""
        activity_log = [
            {"action": ev.get("action", "Working…"), "icon": ev.get("icon", "·")}
            for ev in st.buffer if ev.get("type") == "activity"
        ][-16:] if st and st.running else []
        await self.send({
            "type": "conversation_loaded",
            "conversation": conv,
            "messages": msgs,
            "cross_chat_reference": self.cross_chat_reference,
            "running": bool(st.running) if st else False,
            "current_seq": st.seq if st else 0,
            "partial_text": partial_text,
            "activity_log": activity_log,
            "last_run": run,
        })

    # ── List conversations ────────────────────────────────────────────────────

    async def _handle_list_conversations(self) -> None:
        convs = await list_conversations(self.user["id"])
        await self.send({"type": "conversations", "conversations": convs})

    # ── Delete conversation ───────────────────────────────────────────────────

    async def _handle_delete_conversation(self, data: dict) -> None:
        cid = data.get("conversation_id")
        if not await get_conversation(cid, self.user["id"]):
            await self.send_error("Conversation not found")
            return
        st = _STREAMS.get(_stream_key(self.user["id"], cid))
        if st and st.running:
            task = st.task
            await self._handle_stop({"conversation_id": cid})
            if task and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=3)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    await self.send_error("Run is still stopping; retry deletion after it exits.")
                    return
        deleted = await delete_conversation(cid, self.user["id"])
        if not deleted:
            await self.send_error("Conversation not found")
            return
        _STREAMS.pop(_stream_key(self.user["id"], cid), None)
        try:
            import shutil
            await self._load_ws_settings()
            ws_dir = self._ws_base() / cid
            if ws_dir.exists():
                shutil.rmtree(ws_dir, ignore_errors=True)
        except Exception:
            pass
        if self.conversation_id == cid:
            self.conversation_id = None
            self.history = []
        await self.send({"type": "conversation_deleted", "id": cid})

    # ── Rename conversation ───────────────────────────────────────────────────

    async def _handle_rename_conversation(self, data: dict) -> None:
        cid = data.get("conversation_id")
        title = data.get("title", "")
        owned = await get_conversation(cid, self.user["id"])
        if not owned:
            await self.send_error("Conversation not found")
            return
        await update_conversation_meta(cid, title=title)
        await self.send({"type": "conversation_renamed", "id": cid, "title": title})

    # ── Cross-chat reference toggle ───────────────────────────────────────────

    async def _handle_cross_chat_reference(self, data: dict) -> None:
        enabled = bool(data.get("enabled", False))
        self.cross_chat_reference = enabled
        if self.conversation_id:
            await update_conversation_meta(
                self.conversation_id, cross_chat_reference=enabled
            )
        await self.send({
            "type": "cross_chat_reference_set",
            "enabled": enabled,
            "conv_id": self.conversation_id,
        })

    # ── Workspace settings ────────────────────────────────────────────────────

    async def _handle_workspace_settings(self, data: dict) -> None:
        mode = data.get("mode", "cloud")
        custom_path = data.get("custom_path", "")
        if mode not in ("cloud", "local"):
            await self.send_error("workspace mode must be 'cloud' or 'local'")
            return
        if mode == "local" and custom_path:
            p = Path(custom_path).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                await self.send_error(f"Cannot create local workspace: {exc}")
                return
        await set_user_workspace(self.user["id"], mode, custom_path or None)
        self._workspace_mode = mode
        self._workspace_custom_path = custom_path
        await self.send({
            "type": "workspace_settings_updated",
            "mode": mode,
            "custom_path": custom_path,
        })

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def _handle_chat(self, data: dict) -> None:
        user_msg = data.get("message", "").strip()
        model = data.get("model", self.model)
        cid = data.get("conversation_id") if "conversation_id" in data else self.conversation_id
        attachments = data.get("attachments", [])

        if not user_msg and not attachments:
            await self.send_error("Empty message")
            return

        self.model = model

        if not cid:
            conv = await create_conversation(self.user["id"], model)
            cid = conv["id"]
            self.conversation_id = cid
            await self.send({"type": "conversation_created", "id": cid, "conversation": conv,
                             "request_id": data.get("request_id")})
        else:
            owned = await get_conversation(cid, self.user["id"])
            if not owned:
                await self.send_error("Conversation not found")
                return
            await update_conversation_meta(cid, model=model)

        st = self._attach_stream(cid)
        if st.running and st.task is not asyncio.current_task():
            await self.send({"type": "request_rejected",
                             "message": "This conversation already has an active response."})
            return
        st.task = asyncio.current_task()
        st.running = True
        st.partial_text = ""

        # History belongs to this conversation, never to a mutable WebSocket session.
        previous = await get_messages(cid)
        history = trim_history([
            {"role": m["role"], "content": m["content"],
             "attachments": m.get("attachments") or []}
            for m in previous
        ])

        norm_atts = _normalize_attachments(attachments)
        attachment_ids = [
            a.get("attachment_id") or a.get("id")
            for a in norm_atts
            if a.get("attachment_id") or a.get("id")
        ]
        await bind_attachments_to_conversation(attachment_ids, cid, self.user["id"])
        model_atts = await self._hydrate_attachments(norm_atts)

        # Persist only handles/metadata; never persist another duplicate copy in
        # the message JSON when the attachment service already owns the content.
        await add_message(cid, "user", user_msg, attachments=norm_atts or None)
        if not previous:
            await auto_title(cid, user_msg)

        agent_mode = bool(data.get("agent_mode", False))
        auto_agent = bool(data.get("auto_agent", True))
        # Reading substantial documents requires file tools regardless of the
        # UI's Chat/Agent selection. Keep the selected model when tool-capable;
        # report any necessary orchestrator fallback to the user.
        has_documents = any(not (a.get("type") or "").startswith("image/")
                            for a in model_atts)
        long_context = sum(len(str(m.get("content", ""))) for m in history) > 100_000
        if not agent_mode and (has_documents or long_context or
                               (auto_agent and _should_auto_agent(user_msg, model_atts))):
            agent_mode = True
            await st.emit({
                "type": "auto_agent_started",
                "reason": "Analyzing complete attachments using paginated tools; originals are retained.",
            })
        if agent_mode:
            await self._run_coding_agent(user_msg, model, cid, st,
                                         attachments=model_atts, history=history)
            return

        # ── Plain chat ────────────────────────────────────────────────────────
        t0 = time.time()
        st.running = True
        await st.emit({"type": "activity", "action": "Connecting to model…", "icon": "🔗"})

        sys_prefix = await self._cross_chat_prefix(cid)
        hydrated_history = await self._hydrate_history(history)
        messages = build_messages(hydrated_history, user_msg, model_atts or None,
                                  system_prefix=sys_prefix)
        full_response = ""
        try:
            await st.emit({"type": "activity", "action": "Streaming response…", "icon": "💬"})
            full_response = await self._stream_with_retry(st, messages, model)
        except asyncio.CancelledError:
            # Keep actually generated partial text when a user presses Stop.
            partial = st.partial_text
            if partial:
                await add_message(cid, "assistant", partial)
            st.running = False
            st.task = None
            return
        except Exception as exc:
            st.running = False
            st.task = None
            await st.emit({"type": "error", "message": f"Model error: {exc}"})
            await st.emit({"type": "activity_done"})
            return

        latency = int((time.time() - t0) * 1000)
        await add_message(cid, "assistant", full_response)
        st.running = False
        st.task = None
        await st.emit({"type": "done", "latency_ms": latency})
        await st.emit({"type": "activity_done"})

        input_chars = sum(len(str(m.get("content", ""))) for m in messages)
        await record_usage(
            user_id=self.user["id"], conv_id=cid, model=model,
            input_tokens=max(1, input_chars // 4),
            output_tokens=max(1, len(full_response) // 4),
        )

    async def _stream_with_retry(self, st: StreamState, messages, model: str,
                                 retries: int = 2) -> str:
        """Stream tokens; retry with backoff ONLY if nothing has streamed yet,
        so output is never duplicated."""
        full = ""
        attempt = 0
        while True:
            try:
                async for token in stream_response(messages, model):
                    full += token
                    await st.emit({"type": "token", "text": token})
                return full
            except Exception:
                if full or attempt >= retries:
                    raise
                attempt += 1
                await st.emit({
                    "type": "activity",
                    "action": f"Model hiccup — retrying ({attempt}/{retries})…",
                    "icon": "🔁",
                })
                await asyncio.sleep(attempt * 1.5)

    # ── Cross-chat context builder ────────────────────────────────────────────

    async def _cross_chat_prefix(self, cid: str) -> str:
        # Never use session-wide state: a newer conversation may already be active.
        conv = await get_conversation(cid, self.user["id"])
        if not conv or not conv.get("cross_chat_reference", False):
            return ""
        others = await get_other_conversation_summaries(self.user["id"], cid)
        if not others:
            return ""
        lines = ["[Context from other conversations — for reference only]"]
        for o in others:
            title = o.get("title") or "Untitled"
            last = (o.get("last_response") or "")[:300]
            if last:
                lines.append(f"— {title}: …{last}…")
        return "\n".join(lines)

    # ── Coding agent (checkpointed run) ───────────────────────────────────────

    async def _run_coding_agent(self, user_msg: str, model: str, cid: str,
                                st: StreamState, attachments: list = None,
                                history: list = None) -> None:
        t0 = time.time()
        full_response = ""
        generated_images: List[Dict] = []
        await self._load_ws_settings()
        _tok = _workspace_var.set(self._conv_workspace(cid))

        # Use the selected model when the current integration exposes function
        # calling. Otherwise choose a premium orchestrator and keep specialist
        # models (for example Codex) available through delegate_code.
        requested_model = model
        run_model = preferred_agent_orchestrator(
            requested_model,
            gpt5_configured=bool(get_config().azure_gpt5),
        )
        telemetry_emit(
            "agent_model_route",
            conversation_id=cid,
            user_id=self.user["id"],
            requested_model=requested_model,
            orchestrator_model=run_model,
            delegated=(run_model != requested_model),
        )
        if run_model != requested_model:
            await st.emit({
                "type": "model_fallback",
                "requested": requested_model,
                "fallback": run_model,
                "reason": "selected model is a specialist or lacks tool calling in this integration; using a tool-capable orchestrator",
            })

        st.running = True
        st.task = asyncio.current_task()
        run_id = await create_run(cid, self.user["id"], requested_model,
                                  fallback_model=run_model if run_model != requested_model else None)
        st.run_id = run_id
        steps: List[Dict] = []

        async def _ckpt(status: str = "running"):
            try:
                await checkpoint_run(run_id, steps, status)
            except Exception:
                pass

        await st.emit({"type": "activity", "action": "Initializing agent…", "icon": "🤖"})
        await st.emit({"type": "run_started", "run_id": run_id,
                       "model": run_model, "requested_model": requested_model})

        # Materialize both original and extracted text; never paste entire file
        # contents into a single model request or silently omit large sections.
        import shutil
        workspace = self._conv_workspace(cid)
        enriched_msg = user_msg
        # Already ownership-validated by _hydrate_attachments. Do not run the
        # client-handle normalizer again (it strips trusted storage_path).
        atts = [dict(a) for a in (attachments or []) if isinstance(a, dict)]
        references = []
        for att in atts:
            name = Path(att.get("name", "file")).name
            aid = str(att.get("attachment_id") or att.get("id") or "legacy")
            content_type = att.get("type") or ""
            if content_type.startswith("image/") or content_type == "image":
                img_path = workspace / "images" / name
                img_path.parent.mkdir(parents=True, exist_ok=True)
                content = att.get("content") or ""
                if content:
                    raw = content.split(",", 1)[1] if content.startswith("data:") else content
                    await asyncio.to_thread(img_path.write_bytes, base64.b64decode(raw))
                references.append(f"- Image: images/{name} (inspect_image tool)")
                continue

            rel = att.get("storage_path")
            extracted_path = att.get("extracted_path")
            destination = None
            if rel:
                base = self._ws_base().resolve()
                source = (base / rel).resolve()
                if source.is_file() and source.is_relative_to(base):
                    safe_filename = f"{aid[:12]}_{name}"
                    original_target = workspace / "uploads" / safe_filename
                    original_target.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(shutil.copy2, source, original_target)
                    destination = original_target.relative_to(workspace).as_posix()
                    sidecar = source.parent / "extracted.txt"
                    if sidecar.is_file():
                        text_target = workspace / "uploads" / (safe_filename + ".extracted.txt")
                        await asyncio.to_thread(shutil.copy2, sidecar, text_target)
                        extracted_path = text_target.relative_to(workspace).as_posix()
            if not destination and att.get("content"):
                # Handle historical inline-text uploads without disk originals.
                text_target = workspace / "uploads" / f"{aid[:12]}_{name}.extracted.txt"
                text_target.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(
                    text_target.write_text, att["content"], encoding="utf-8"
                )
                extracted_path = text_target.relative_to(workspace).as_posix()
            status = att.get("extraction") or {}
            note = status.get("note") or ""
            references.append(
                f"- {name}: original={destination or 'not available'}; "
                f"extracted_text={extracted_path or 'not available'}; "
                f"extraction_complete={status.get('complete', 'unknown')}; "
                f"notes={note or 'none'}"
            )
        if references:
            enriched_msg = (
                "Attached sources are workspace files, NOT inline model context. "
                "Use file_overview, read_file with successive line ranges, "
                "search_files, or inspect_image as appropriate. For an entire-file "
                "request, inspect all relevant sections before concluding, "
                "and explicitly report what was not inspected. Cite file paths, "
                "sheet names, rows or page labels. Never invent data.\n"
                + "\n".join(references) + "\n\nUSER REQUEST:\n" + user_msg
            )

        # Keep complete older messages retrievable even when the LLM's active
        # context window only includes recent turns.
        history_target = workspace / "uploads" / "_conversation_history.txt"
        full_history = "\n\n".join(
            f"[{m.get('role','unknown').upper()}]\n{m.get('content','')}"
            for m in (history or [])
        )
        if full_history:
            await asyncio.to_thread(history_target.write_text, full_history, encoding="utf-8")
            enriched_msg += (
                "\n\nPrevious conversation text is accessible in "
                "uploads/_conversation_history.txt via read_file ranges."
            )

        sys_prefix = await self._cross_chat_prefix(cid)
        if sys_prefix:
            enriched_msg = f"{sys_prefix}\n\n---\n\n{enriched_msg}"

        async def _token_cb(text: str):
            nonlocal full_response
            full_response += text
            await st.emit({"type": "token", "text": text})

        def _find_step(rid: str) -> Optional[Dict]:
            for s in steps:
                if s.get("rid") == rid:
                    return s
            return None

        async def _perm_fn(rid: str, tool: str, args: dict, preview: str) -> bool:
            icon = _TOOL_ICONS.get(tool, "🔧")
            # Auto-approve read-only tools when the user opted in.
            if (st.auto_allow_readonly and tool in READONLY_TOOLS) or tool in st.auto_allow_tools:
                step = _find_step(rid) or {"rid": rid, "tool": tool}
                step["permission"] = "auto_allowed"
                await st.emit({
                    "type": "permission_auto", "request_id": rid, "tool": tool,
                })
                await _ckpt()
                return True

            event = asyncio.Event()
            st.perm_events[rid] = event
            _PERM_INDEX[rid] = st.key
            _PERM_TOOL_INDEX[rid] = tool
            step = _find_step(rid)
            if step is None:
                step = {"rid": rid, "tool": tool, "label": _tool_label(tool, args),
                        "status": "waiting_permission", "t0": time.time()}
                steps.append(step)
            else:
                step["status"] = "waiting_permission"
            await st.emit({"type": "activity",
                           "action": f"Waiting for permission: {tool}", "icon": icon})
            await st.emit({
                "type": "permission",
                "request_id": rid,
                "tool": tool,
                "args": args,
                "preview": preview,
            })
            await st.emit({"type": "run_step", "run_id": run_id, "steps": _public_steps(steps)})
            await _ckpt("waiting_permission")
            timed_out = False
            try:
                if rid not in st.perm_decisions:
                    try:
                        await asyncio.wait_for(event.wait(), timeout=_PERMISSION_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        timed_out = True
            finally:
                st.perm_events.pop(rid, None)
                _PERM_INDEX.pop(rid, None)
                _PERM_TOOL_INDEX.pop(rid, None)
            decision = st.perm_decisions.pop(rid, "deny")
            if timed_out:
                decision = "timeout"
                await st.emit({"type": "permission_timeout", "request_id": rid,
                               "message": "Permission timed out. Tool not executed; ask to continue."})
            step["permission"] = decision
            step["status"] = "running" if decision == "allow" else "denied"
            await st.emit({"type": "run_step", "run_id": run_id, "steps": _public_steps(steps)})
            await _ckpt()
            return decision == "allow"

        async def _pre_tool_cb(tool: str, args: dict):
            icon = _TOOL_ICONS.get(tool, "🔧")
            label = _tool_label(tool, args)
            steps.append({"rid": f"step-{len(steps)}-{uuid.uuid4().hex[:6]}",
                          "tool": tool, "label": label,
                          "status": "running", "t0": time.time(),
                          "args_preview": _args_preview(tool, args)})
            await st.emit({"type": "activity", "action": label, "icon": icon})
            await st.emit({"type": "run_step", "run_id": run_id, "steps": _public_steps(steps)})
            await _ckpt()

        async def _result_cb(rid: str, tool: str, result: str, allowed: bool):
            icon = _TOOL_ICONS.get(tool, "🔧")
            status = "Done" if allowed else "Skipped"
            duration_ms = None
            # Close the latest running step for this tool
            for step in reversed(steps):
                if step["tool"] == tool and step.get("status") in ("running", "waiting_permission"):
                    step["status"] = "done" if allowed else "denied"
                    duration_ms = int((time.time() - step.get("t0", time.time())) * 1000)
                    step["duration_ms"] = duration_ms
                    step["result_preview"] = (result or "")[:200]
                    break
            telemetry_emit(
                "agent_tool_result",
                conversation_id=cid,
                run_id=run_id,
                tool=tool,
                allowed=allowed,
                success=bool(allowed and not str(result).startswith("Error:")),
                duration_ms=duration_ms,
            )
            await st.emit({"type": "activity", "action": f"{status}: {tool}", "icon": icon})
            await st.emit({
                "type": "tool_result",
                "request_id": rid,
                "tool": tool,
                "result": result[:2000],
                "allowed": allowed,
            })
            await st.emit({"type": "run_step", "run_id": run_id, "steps": _public_steps(steps)})
            await _ckpt()
            if tool in FILE_TOOLS and allowed:
                # Register produced file(s) as artifacts for cross-step reuse.
                fname = None
                try:
                    import re as _re
                    m = _re.search(r"[\w\-./ ]+\.(png|jpg|jpeg|webp|gif|pdf|pptx|docx|xlsx|csv|py|txt|md|html|json)",
                                   str(result))
                    fname = m.group(0).strip() if m else None
                except Exception:
                    pass
                try:
                    ws_dir = self._conv_workspace(cid)
                    if fname and (ws_dir / fname).exists():
                        size = (ws_dir / fname).stat().st_size
                        await register_artifact(cid, Path(fname).name, fname,
                                                run_id=run_id, size_bytes=size)
                except Exception:
                    pass
                await st.emit({"type": "workspace", "files": get_file_tree()})

        async def _image_fn(b64: str, filename: str):
            # The image tool writes under workspace/images/, not workspace/.
            safe_name = Path(filename).name
            relative = f"images/{safe_name}"
            try:
                fpath = self._conv_workspace(cid) / relative
                if fpath.is_file():
                    await register_artifact(
                        cid, safe_name, relative, run_id=run_id,
                        kind="image", size_bytes=fpath.stat().st_size
                    )
                    # Persist a lightweight reference, never a duplicate base64
                    # payload in the message database.
                    generated_images.append({
                        "name": safe_name, "type": "image/png", "path": relative
                    })
            except Exception:
                _logger.exception("Failed to register generated image artifact")
            await st.emit({
                "type": "image_result",
                "base64": b64,
                "filename": safe_name,
                "from_agent": True,
            })

        agent_failed = False
        cancelled = False
        err_text = None
        try:
            hydrated_history = await self._hydrate_history((history or []))
            await run_coding_agent(
                enriched_msg, hydrated_history, run_model,
                permission_fn=_perm_fn,
                token_callback=_token_cb,
                tool_result_callback=_result_cb,
                pre_tool_callback=_pre_tool_cb,
                image_fn=_image_fn,
            )
        except asyncio.CancelledError:
            cancelled = True
            err_text = "cancelled by user"
        except Exception as exc:
            agent_failed = True
            err_text = str(exc)
        finally:
            _workspace_var.reset(_tok)

        st.running = False
        st.task = None
        latency = int((time.time() - t0) * 1000)

        input_chars = sum(len(str(m.get("content", ""))) for m in (history or []))
        in_toks = max(1, input_chars // 4)
        out_toks = max(1, len(full_response) // 4)

        if cancelled:
            if full_response or generated_images:
                await add_message(cid, "assistant", full_response,
                                  attachments=generated_images or None)

            await finish_run(run_id, "cancelled", in_toks, out_toks, 0.0, error=err_text)
            await st.emit({"type": "run_step", "run_id": run_id,
                           "steps": _public_steps(steps), "final": "cancelled"})
            return

        if agent_failed:
            if full_response or generated_images:
                await add_message(cid, "assistant", full_response,
                                  attachments=generated_images or None)

            await finish_run(run_id, "error", in_toks, out_toks, 0.0, error=err_text)
            await st.emit({"type": "run_step", "run_id": run_id,
                           "steps": _public_steps(steps), "final": "error"})
            await st.emit({"type": "error", "message": f"Coding agent error: {err_text}"})
            await st.emit({"type": "activity_done"})
            return

        await add_message(cid, "assistant", full_response,
                          attachments=generated_images or None)

        telemetry_emit(
            "agent_run_completed",
            conversation_id=cid,
            run_id=run_id,
            model=run_model,
            latency_ms=latency,
            steps=len(steps),
            output_chars=len(full_response),
        )
        await record_usage(user_id=self.user["id"], conv_id=cid, model=run_model,
                           input_tokens=in_toks, output_tokens=out_toks)
        await finish_run(run_id, "done", in_toks, out_toks, 0.0)
        await st.emit({"type": "run_step", "run_id": run_id,
                       "steps": _public_steps(steps), "final": "done"})
        await st.emit({"type": "done", "latency_ms": latency})
        await st.emit({"type": "activity_done"})

    # ── Permission response ───────────────────────────────────────────────────

    async def _handle_permission(self, data: dict) -> None:
        rid = data.get("request_id", "")
        decision = data.get("decision", "deny")
        always = bool(data.get("always"))
        # Route via the stream index so a decision after reconnect still lands.
        key = _PERM_INDEX.get(rid)
        st = _STREAMS.get(key) if key else None
        if st is None and self.conversation_id:
            st = _STREAMS.get(_stream_key(self.user["id"], self.conversation_id))
        if st is not None:
            if always and decision == "allow":
                tool = _PERM_TOOL_INDEX.get(rid)
                if tool:
                    st.auto_allow_tools.add(tool)
            st.perm_decisions[rid] = decision
            event = st.perm_events.pop(rid, None)
            if event:
                event.set()

    # ── Image generation ──────────────────────────────────────────────────────

    async def _handle_image(self, data: dict) -> None:
        prompt = data.get("prompt", "").strip()
        model = data.get("model", "gpt-image-2-global")
        size = data.get("size", "1024x1024")
        count = max(1, min(int(data.get("count", 1) or 1), 4))
        atts = _normalize_attachments(data.get("attachments", []))
        if not prompt:
            await self.send_error("Image prompt required")
            return

        hydrated_atts = await self._hydrate_attachments(atts)
        gen_prompt = prompt
        doc_context = _attachments_context(hydrated_atts, limit=3000)
        if doc_context:
            gen_prompt = f"{prompt}\n\nReference context:\n{doc_context}"

        cid = data.get("conversation_id") if "conversation_id" in data else self.conversation_id
        if not cid:
            conv = await create_conversation(self.user["id"], model)
            cid = conv["id"]
            self.conversation_id = cid
            await self.send({"type": "conversation_created", "id": cid, "conversation": conv,
                             "request_id": data.get("request_id")})
        first_msg = len(await get_messages(cid)) == 0

        st = self._attach_stream(cid)
        st.task = asyncio.current_task()
        st.running = True
        await st.emit({"type": "activity", "action": f"Generating {count} image{'s' if count > 1 else ''}…", "icon": "🖼️"})

        results = []
        try:
            reference_image = next(
                (a for a in hydrated_atts if (a.get("type") or "").startswith("image/") and a.get("content")),
                None,
            )
            for i in range(count):
                if reference_image and model.startswith("gpt-image"):
                    result = await edit_image(
                        base64.b64decode(reference_image["content"]),
                        None,
                        gen_prompt,
                        model=model,
                        size=size,
                    )
                    b64 = result.get("b64")
                    url = result.get("url")
                elif model == "gemini-2.5-flash-image":
                    result = await generate_vertex_image(gen_prompt, model)
                    b64 = result.get("b64")
                    url = None
                else:
                    result = await generate_image(gen_prompt, model, size)
                    b64 = result.get("b64")
                    url = result.get("url")
                if not b64 and url:
                    b64 = await _download_image_b64(url)
                results.append((b64, url))
                await st.emit({
                    "type": "image_result",
                    "url": url,
                    "base64": b64,
                    "prompt": prompt,
                    "model": model,
                    "variation_index": i,
                    "variation_count": count,
                })
        except asyncio.CancelledError:
            st.running = False
            raise
        except Exception as exc:
            st.running = False
            await st.emit({"type": "error", "message": f"Image generation error: {exc}"})
            await st.emit({"type": "activity_done"})
            return

        st.running = False
        st.task = None
        await st.emit({"type": "activity_done"})

        try:
            await add_message(cid, "user", prompt, attachments=atts or None)
            if first_msg:
                await auto_title(cid, prompt)
            for idx, (b64, url) in enumerate(results):
                if b64:
                    fname = f"generated_{int(time.time())}_{idx + 1}.png"
                    try:
                        await self._load_ws_settings()
                        ws_dir = self._conv_workspace(cid)
                        img_dir = ws_dir / "images"
                        img_dir.mkdir(parents=True, exist_ok=True)
                        (img_dir / fname).write_bytes(base64.b64decode(b64))
                        await register_artifact(
                            cid, fname, f"images/{fname}", kind="image",
                            size_bytes=(img_dir / fname).stat().st_size,
                            meta={"prompt": prompt, "model": model},
                        )
                    except Exception:
                        pass
                    await add_message(
                        cid, "assistant", f"[Generated image: {prompt}]",
                        attachments=[{"name": fname, "type": "image/png", "content": b64}],
                    )
                elif url:
                    await add_message(cid, "assistant", f"[Generated image: {prompt}]\n{url}")
            await record_usage(
                user_id=self.user["id"], conv_id=cid, model=model,
                input_tokens=max(1, len(gen_prompt) // 4), output_tokens=0,
            )
        except Exception:
            pass

    async def _handle_edit_image(self, data: dict) -> None:
        prompt = data.get("prompt", "").strip()
        image_b64 = data.get("image_base64", "")
        mask_b64 = data.get("mask_base64")
        size = data.get("size", "1024x1024")
        model = data.get("model", "gpt-image-1-global")
        source_name = data.get("source_name", "image.png")
        count = max(1, min(int(data.get("count", 1) or 1), 4))
        cid = data.get("conversation_id") or self.conversation_id

        if not prompt or not image_b64:
            await self.send_error("Image edit requires prompt and source image")
            return
        if not cid:
            conv = await create_conversation(self.user["id"], model)
            cid = conv["id"]
            self.conversation_id = cid
            await self.send({"type": "conversation_created", "id": cid, "conversation": conv})

        st = self._attach_stream(cid)
        st.task = asyncio.current_task()
        st.running = True
        await add_message(cid, "user", f"Edit {source_name}: {prompt}")
        await st.emit({"type": "activity", "action": "Editing image…", "icon": "🖼️"})
        try:
            raw = image_b64.split(",", 1)[1] if image_b64.startswith("data:") else image_b64
            mask_raw = None
            if mask_b64:
                mask_raw = mask_b64.split(",", 1)[1] if mask_b64.startswith("data:") else mask_b64
            for idx in range(count):
                result = await edit_image(
                    base64.b64decode(raw),
                    base64.b64decode(mask_raw) if mask_raw else None,
                    prompt,
                    model=model,
                    size=size,
                )
                b64 = result.get("b64")
                url = result.get("url")
                if not b64 and url:
                    b64 = await _download_image_b64(url)
                await st.emit({
                    "type": "image_result",
                    "url": url,
                    "base64": b64,
                    "prompt": f"Edited {source_name}: {prompt}",
                    "model": model,
                    "edited_from": source_name,
                    "variation_index": idx,
                    "variation_count": count,
                })
                if b64:
                    await self._load_ws_settings()
                    fname = f"edited_{int(time.time())}_{idx + 1}.png"
                    img_dir = self._conv_workspace(cid) / "images"
                    img_dir.mkdir(parents=True, exist_ok=True)
                    (img_dir / fname).write_bytes(base64.b64decode(b64))
                    await register_artifact(
                        cid, fname, f"images/{fname}", kind="image",
                        size_bytes=(img_dir / fname).stat().st_size,
                        meta={"edit_prompt": prompt, "source": source_name, "model": model},
                    )
                    await add_message(
                        cid, "assistant", f"[Edited image: {source_name}]",
                        attachments=[{"name": fname, "type": "image/png", "content": b64}],
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await st.emit({"type": "error", "message": f"Image edit error: {exc}"})
        finally:
            st.running = False
            st.task = None
            await st.emit({"type": "activity_done"})

    # ── Text-to-speech ────────────────────────────────────────────────────────

    async def _handle_tts(self, data: dict) -> None:
        text = data.get("text", "")
        voice = data.get("voice", "nova")
        if not text:
            await self.send_error("TTS text required")
            return
        try:
            b64 = await text_to_speech_b64(text, voice)
            await self.send({"type": "audio_result", "base64": b64, "voice": voice})
        except Exception as exc:
            await self.send_error(f"TTS error: {exc}")

    # ── Transcription ─────────────────────────────────────────────────────────

    async def _handle_transcribe(self, data: dict) -> None:
        b64 = data.get("audio_base64", "")
        diarize = data.get("diarize", False)
        fmt = data.get("audio_format", "webm")
        if not b64:
            await self.send_error("Audio data required")
            return
        try:
            audio_bytes = base64.b64decode(b64)
            text = await transcribe(audio_bytes, filename=f"audio.{fmt}", diarize=diarize)
            await self.send({"type": "transcription", "text": text})
        except Exception as exc:
            await self.send_error(f"Transcription error: {exc}")


async def _download_image_b64(url: str) -> str:
    """Normalize temporary provider URLs into durable base64 results."""
    if not url:
        return ""
    loop = asyncio.get_running_loop()

    def _download() -> bytes:
        import requests
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    raw = await loop.run_in_executor(None, _download)
    return base64.b64encode(raw).decode()


def _should_auto_agent(message: str, attachments: List[Dict]) -> bool:
    """Conservative tool-intent detector for ChatGPT-like automatic tool use.

    We intentionally avoid sending every normal question through the agent. The
    promotion only happens for explicit action verbs or file/workspace tasks.
    """
    text = (message or "").lower()
    phrases = (
        "create a file", "create file", "edit the file", "modify the file",
        "update the file", "fix the file", "make changes", "implement this",
        "fix this code", "fix the codebase", "update this repo", "update the repo",
        "run the code", "run tests", "execute the code", "debug this",
        "create a powerpoint", "build a powerpoint", "create ppt", "create a pdf",
        "create pdf", "create docx", "create a word", "create excel", "create xlsx",
        "search the web", "browse the web", "look up the latest", "research the latest",
        "use the workspace", "in the workspace", "inspect the attached",
        "analyze the attached", "edit this image", "modify this image",
    )
    if any(p in text for p in phrases):
        return True
    if attachments:
        action_words = ("analyze", "edit", "fix", "modify", "update", "implement", "run", "build")
        if any(w in text for w in action_words):
            return True
    return False


# ── Attachment normalization ──────────────────────────────────────────────────

def _normalize_attachments(attachments) -> List[Dict]:
    out: List[Dict] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        name = att.get("name") or att.get("filename") or "file"
        typ = att.get("content_type") or att.get("type") or "text"
        item = {
            "name": name,
            "type": typ,
            "content_type": typ,
        }
        aid = att.get("attachment_id") or att.get("id")
        if aid:
            item["id"] = aid
            item["attachment_id"] = aid
        if att.get("size") is not None:
            item["size"] = att.get("size")
        # Legacy clients may still send inline content; keep compatibility.
        if att.get("content"):
            item["content"] = att.get("content")
        out.append(item)
    return out


def _attachments_context(attachments, limit: int = 1500) -> str:
    parts = []
    for att in attachments or []:
        typ = att.get("type", "")
        if typ.startswith("image/") or typ == "image":
            continue
        content = att.get("content", "")
        if content:
            parts.append(f"{att.get('name', 'file')}: {content}")
    return "\n".join(parts)[:limit]


# ── Step / label helpers ──────────────────────────────────────────────────────

def _public_steps(steps: List[Dict]) -> List[Dict]:
    """Strip internal fields before sending steps to the client."""
    out = []
    for s in steps:
        out.append({
            "tool": s.get("tool"),
            "label": s.get("label"),
            "status": s.get("status"),
            "duration_ms": s.get("duration_ms"),
            "args_preview": s.get("args_preview"),
            "permission": s.get("permission"),
            "rid": s.get("rid"),
        })
    return out


def _args_preview(tool: str, args: dict) -> str:
    try:
        s = json.dumps(args)
        return s[:160]
    except Exception:
        return ""


def _tool_label(tool: str, args: dict) -> str:
    if tool == "read_file":    return f"Reading {args.get('path', '')}"
    if tool == "write_file":   return f"Writing {args.get('path', '')}"
    if tool == "create_file":  return f"Creating {args.get('path', '')}"
    if tool == "delete_file":  return f"Deleting {args.get('path', '')}"
    if tool == "list_files":   return "Listing files"
    if tool == "run_bash":     return f"Running: {args.get('command', '')[:60]}"
    if tool == "run_python":   return "Running Python code"
    if tool == "search_files": return f"Searching for '{args.get('pattern', '')}'"
    if tool == "patch_file":   return f"Patching {args.get('path', '')}"
    if tool == "inspect_image": return f"Inspecting {args.get('path', '')}"
    if tool == "delegate_code": return "Consulting code specialist"
    if tool == "create_pdf":   return f"Creating PDF: {args.get('filename', '')}"
    if tool == "create_pptx":  return f"Creating PowerPoint: {args.get('filename', '')}"
    if tool == "create_docx":  return f"Creating Word doc: {args.get('filename', '')}"
    if tool == "create_excel": return f"Creating Excel: {args.get('filename', '')}"
    if tool == "web_crawl":    return f"Fetching {args.get('url', '')[:60]}"
    if tool == "web_search":   return f"Searching: {args.get('query', '')[:60]}"
    if tool == "generate_image": return f"Generating image: {args.get('prompt', '')[:50]}…"
    return tool


# ── WebSocket runner ──────────────────────────────────────────────────────────

async def run_session(ws: WebSocket, user: dict) -> None:
    session = WSSession(ws, user)
    convs = await list_conversations(user["id"])
    await session._load_ws_settings()
    await session.send({"type": "init", "user": {
        "id": user["id"],
        "display_name": user.get("display_name", user["username"]),
        "auth_method": user.get("auth_method", "password"),
        "is_admin": bool(user.get("is_admin", 0)),
        "workspace_mode": session._workspace_mode,
        "workspace_custom_path": session._workspace_custom_path or "",
    }, "conversations": convs})

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            await session.handle(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # Detach (do NOT stop) any running streams owned by this session — the
        # run continues in the background and the client can resume.
        for st in _STREAMS.values():
            if st.session is session:
                st.session = None
