"""Runtime model capability registry.

This describes what the current RDI integration can actually do, not what a
provider may support in theory. Keep orchestration decisions here so the UI,
WebSocket layer, and agent do not silently disagree about model behavior.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    tools: bool = False
    vision: bool = False
    image_generation: bool = False
    image_edit: bool = False
    reasoning: bool = False
    code_specialist: bool = False


def capabilities_for(model: str) -> ModelCapabilities:
    m = (model or "").lower()

    is_image = (
        "gpt-image" in m
        or "dall" in m
        or "imagen" in m
        or m == "gemini-2.5-flash-image"
    )
    is_codex = "codex" in m
    is_reasoning = m.startswith(("o1", "o3", "o4"))
    is_vertex_chat = m.startswith("gemini-") and not is_image

    # Current integration constraints:
    # - Codex is used through Responses API as a code specialist, not an
    #   orchestrator with function calls.
    # - o-series integration intentionally does not attach function tools.
    # - Vertex gateway integration currently exposes plain generation only.
    tools = not (is_image or is_codex or is_reasoning or is_vertex_chat)

    vision = (
        m.startswith(("gpt-4o", "gpt-4.1", "gpt-5"))
        or "anthropic.claude" in m
        or is_vertex_chat
    ) and not is_codex

    return ModelCapabilities(
        tools=tools,
        vision=vision,
        image_generation=is_image,
        image_edit="gpt-image" in m,
        reasoning=is_reasoning,
        code_specialist=is_codex,
    )


def model_supports_tools(model: str) -> bool:
    return capabilities_for(model).tools


def preferred_agent_orchestrator(requested_model: str, gpt5_configured: bool = True) -> str:
    """Return a tool-capable orchestrator while preserving premium quality.

    A specialist model (Codex, image, o-series, Vertex chat) should not be
    silently used as if it had tool-calling support. Prefer GPT-5.4 when the
    GPT-5 gateway is configured, otherwise use GPT-4.1.
    """
    if model_supports_tools(requested_model):
        return requested_model
    return "gpt-5.4-global" if gpt5_configured else "gpt-4.1-global"


def code_specialist_for(requested_model: str) -> str:
    if capabilities_for(requested_model).code_specialist:
        return requested_model
    return "gpt-5.3-codex-global"
