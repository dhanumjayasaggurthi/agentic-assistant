"""Chat transport regression tests. No database or external model required."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.ws_handler import StreamState, WSSession, _STREAMS, get_stream


class FakeWebSocket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(dict(event))


class ChatLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        _STREAMS.clear()

    async def test_stream_scoping_and_sequence_replay_across_100_conversations(self):
        for i in range(100):
            ws = FakeWebSocket()
            st = StreamState(f"user:conversation-{i}")
            st.session = type("SocketOwner", (), {"ws": ws})()
            for j in range(10):
                await st.emit({"type": "token", "text": str(j)})
            self.assertEqual([e["seq"] for e in ws.events], list(range(1, 11)))
            self.assertTrue(all(e["conversation_id"] == f"conversation-{i}" for e in ws.events))
            self.assertEqual(len(st.replay_after(5)), 5)
            self.assertEqual(st.replay_after(10), [])

    async def test_new_chat_uses_explicit_null_not_old_session(self):
        ws = FakeWebSocket()
        session = WSSession(ws, {"id": "user", "username": "tester"})
        session.conversation_id = "old-chat"
        new_conv = {"id": "brand-new", "title": "New Conversation", "model": "gpt-4.1-global"}
        with (
            patch("backend.ws_handler.create_conversation", new_callable=AsyncMock, return_value=new_conv) as create,
            patch("backend.ws_handler.get_messages", new_callable=AsyncMock, return_value=[]),
            patch("backend.ws_handler.get_conversation", new_callable=AsyncMock,
                  return_value={"id": "brand-new", "cross_chat_reference": False}),
            patch("backend.ws_handler.add_message", new_callable=AsyncMock),
            patch("backend.ws_handler.auto_title", new_callable=AsyncMock),
            patch("backend.ws_handler.bind_attachments_to_conversation", new_callable=AsyncMock),
            patch("backend.ws_handler.record_usage", new_callable=AsyncMock),
            patch.object(session, "_stream_with_retry", new_callable=AsyncMock, return_value="Answer"),
        ):
            await session._handle_chat({
                "type": "chat", "message": "New topic", "model": "gpt-4.1-global",
                "conversation_id": None, "request_id": "new-request", "auto_agent": False
            })
        create.assert_awaited_once()
        created = next(e for e in ws.events if e["type"] == "conversation_created")
        self.assertEqual(created["request_id"], "new-request")
        self.assertEqual(created["id"], "brand-new")
        self.assertEqual(session.conversation_id, "brand-new")
        self.assertTrue(all(e["conversation_id"] == "brand-new" for e in ws.events if "seq" in e))

    async def test_stop_pending_request_without_known_conversation(self):
        ws = FakeWebSocket()
        session = WSSession(ws, {"id": "user"})
        session.conversation_id = "old-chat"
        task = asyncio.create_task(asyncio.sleep(30))
        session._pending_tasks["incoming"] = task
        await session._handle_stop({"type": "stop", "conversation_id": None, "request_id": "incoming"})
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled())
        self.assertFalse(any(e.get("type") == "cancelled" for e in ws.events))

    async def test_reopen_running_chat_restores_partial_stream_and_activity(self):
        ws = FakeWebSocket()
        session = WSSession(ws, {"id": "user"})
        st = get_stream("user", "conversation-live")
        st.running = True
        st.session = session
        await st.emit({"type": "token", "text": "Part "})
        await st.emit({"type": "activity", "action": "Reading document", "icon": "📄"})
        await st.emit({"type": "token", "text": "two"})
        conv = {"id": "conversation-live", "model": "gpt-4.1-global"}
        with (
            patch("backend.ws_handler.get_conversation", new_callable=AsyncMock, return_value=conv),
            patch("backend.ws_handler.get_messages", new_callable=AsyncMock, return_value=[]),
            patch("backend.ws_handler.get_latest_run", new_callable=AsyncMock, return_value=None),
        ):
            await session._handle_load_conversation({"conversation_id": "conversation-live"})
        loaded = ws.events[-1]
        self.assertEqual(loaded["type"], "conversation_loaded")
        self.assertEqual(loaded["partial_text"], "Part two")
        self.assertEqual(loaded["activity_log"][0]["action"], "Reading document")
        self.assertTrue(loaded["running"])


if __name__ == "__main__":
    unittest.main()
