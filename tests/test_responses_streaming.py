"""Responses API streaming contract without network/API credentials."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from backend.providers.azure_gpt5 import stream_codex_responses_api


class ResponsesStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with_transport(self, content, content_type):
        seen = []
        def handler(request):
            self.assertTrue(json.loads(request.content)["stream"])
            self.assertTrue(str(request.url).endswith("/openai/v1/responses"))
            return httpx.Response(200, headers={"content-type": content_type}, content=content)
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        config = SimpleNamespace(azure_gpt5=SimpleNamespace(
            endpoint="https://example.test", api_key="test"))
        def client_factory(**kwargs):
            return real_client(transport=transport, **kwargs)
        with (
            patch("backend.providers.azure_gpt5.get_config", return_value=config),
            patch("backend.providers.azure_gpt5.httpx.AsyncClient", side_effect=client_factory),
        ):
            async for delta in stream_codex_responses_api("gpt-5.3-codex-global", "Explain"):
                seen.append(delta)
        return seen

    async def test_100_real_sse_deltas_not_posthoc_character_replay(self):
        lines = []
        for i in range(100):
            event = {"type": "response.output_text.delta", "delta": f"chunk-{i} "}
            lines.append("data: " + json.dumps(event) + "\n\n")
        lines.append("data: " + json.dumps({
            "type": "response.completed", "response": {"output": []}}) + "\n\n")
        result = await self._run_with_transport("".join(lines), "text/event-stream")
        self.assertEqual(result, [f"chunk-{i} " for i in range(100)])

    async def test_gateway_json_fallback_preserves_exact_answer(self):
        body = json.dumps({"output": [{"content": [
            {"type": "output_text", "text": "Full answer"},
        ]}]})
        result = await self._run_with_transport(body, "application/json")
        self.assertEqual(result, ["Full answer"])

    async def test_sse_error_surfaces_instead_of_silent_blank(self):
        payload = "data: " + json.dumps({
            "type": "response.failed",
            "response": {"error": {"message": "backend unavailable"}},
        }) + "\n\n"
        with self.assertRaisesRegex(RuntimeError, "backend unavailable"):
            await self._run_with_transport(payload, "text/event-stream")


if __name__ == "__main__":
    unittest.main()
