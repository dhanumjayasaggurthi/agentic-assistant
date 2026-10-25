import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.execution import docker_command
from backend.model_capabilities import runtime_catalog
from backend.ws_handler import _normalize_attachments


class RuntimeCatalogTests(unittest.TestCase):
    def test_catalog_marks_provider_availability(self):
        cfg = types.SimpleNamespace(
            azure_chat=object(),
            azure_gpt5=None,
            azure_image=object(),
            bedrock=None,
            vertex=None,
            vertex_image=None,
        )
        catalog = {m["id"]: m for m in runtime_catalog(cfg)}
        self.assertTrue(catalog["gpt-4.1-global"]["available"])
        self.assertFalse(catalog["gpt-5.4-global"]["available"])
        self.assertTrue(catalog["gpt-image-1-global"]["capabilities"]["image_edit"])

    def test_codex_is_available_only_when_gpt5_provider_is_configured(self):
        cfg = types.SimpleNamespace(
            azure_chat=None,
            azure_gpt5=object(),
            azure_image=None,
            bedrock=None,
            vertex=None,
            vertex_image=None,
        )
        catalog = {m["id"]: m for m in runtime_catalog(cfg)}
        self.assertTrue(catalog["gpt-5.3-codex-global"]["available"])
        self.assertTrue(catalog["gpt-5.3-codex-global"]["capabilities"]["code_specialist"])
        self.assertFalse(catalog["gpt-5.3-codex-global"]["capabilities"]["tools"])


class AttachmentHandleTests(unittest.TestCase):
    def test_normalizer_preserves_handle_without_inline_content(self):
        items = _normalize_attachments([{
            "attachment_id": "att-123",
            "name": "sample.pdf",
            "content_type": "application/pdf",
            "size": 42,
        }])
        self.assertEqual(items[0]["attachment_id"], "att-123")
        self.assertEqual(items[0]["id"], "att-123")
        self.assertNotIn("content", items[0])
        self.assertEqual(items[0]["content_type"], "application/pdf")


class ExecutionIsolationTests(unittest.TestCase):
    def test_docker_runner_is_network_off_and_constrained(self):
        execution_cfg = types.SimpleNamespace(
            docker_image="python:3.12-slim",
            network_enabled=False,
            memory_mb=768,
            cpus=0.75,
            pids_limit=96,
            timeout_seconds=60,
            mode="docker",
        )
        cfg = types.SimpleNamespace(execution=execution_cfg)
        with patch("backend.execution.get_config", return_value=cfg):
            cmd = docker_command(Path("/tmp/workspace"), "python -V")
        joined = " ".join(cmd)
        self.assertIn("--network none", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("no-new-privileges", joined)
        self.assertIn("--memory 768m", joined)
        self.assertIn("--pids-limit 96", joined)
        self.assertIn("python:3.12-slim", joined)


if __name__ == "__main__":
    unittest.main()
