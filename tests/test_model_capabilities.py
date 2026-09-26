import unittest

from backend.model_capabilities import (
    capabilities_for,
    model_supports_tools,
    preferred_agent_orchestrator,
)


class ModelCapabilityTests(unittest.TestCase):
    def test_gpt41_can_orchestrate_tools(self):
        caps = capabilities_for("gpt-4.1-global")
        self.assertTrue(caps.tools)
        self.assertTrue(caps.vision)
        self.assertFalse(caps.code_specialist)

    def test_codex_is_specialist_not_orchestrator(self):
        caps = capabilities_for("gpt-5.3-codex-global")
        self.assertTrue(caps.code_specialist)
        self.assertFalse(caps.tools)

    def test_reasoning_model_uses_agent_orchestrator(self):
        self.assertFalse(model_supports_tools("o3-pro-global"))
        self.assertEqual(
            preferred_agent_orchestrator("o3-pro-global", gpt5_configured=True),
            "gpt-5.4-global",
        )

    def test_vertex_chat_uses_agent_orchestrator(self):
        self.assertFalse(model_supports_tools("gemini-2.5-pro"))
        self.assertEqual(
            preferred_agent_orchestrator("gemini-2.5-pro", gpt5_configured=False),
            "gpt-4.1-global",
        )

    def test_image_models_are_not_tool_orchestrators(self):
        caps = capabilities_for("gpt-image-2-global")
        self.assertTrue(caps.image_generation)
        self.assertFalse(caps.tools)

    def test_tool_capable_model_is_preserved(self):
        self.assertEqual(
            preferred_agent_orchestrator("gpt-5.4-global", gpt5_configured=True),
            "gpt-5.4-global",
        )


if __name__ == "__main__":
    unittest.main()
