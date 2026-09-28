"""Runtime model capability and deployment registry.

This module describes what the current RDI integration can actually do.  The
frontend can display many marketplace models, but orchestration must be based on
runtime integration capabilities and configured providers rather than labels.
"""
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class ModelCapabilities:
    tools: bool = False
    vision: bool = False
    image_generation: bool = False
    image_edit: bool = False
    reasoning: bool = False
    code_specialist: bool = False


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    group: str
    tier: str
    provider: str


_MODEL_SPECS: List[ModelSpec] = [
    ModelSpec("gpt-4.1-global", "GPT-4.1 Global", "GPT-4.1 (Recommended)", "standard", "azure_chat"),
    ModelSpec("gpt-4.1-mini-global", "GPT-4.1 Mini", "GPT-4.1 (Recommended)", "budget", "azure_chat"),
    ModelSpec("gpt-4.1-nano-global", "GPT-4.1 Nano", "GPT-4.1 (Recommended)", "budget", "azure_chat"),
    ModelSpec("gpt-4o-global", "GPT-4o Global", "GPT-4o", "standard", "azure_chat"),
    ModelSpec("gpt-4o-mini-global", "GPT-4o Mini Global", "GPT-4o", "budget", "azure_chat"),
    ModelSpec("gpt-5-global", "GPT-5 Global", "GPT-5", "ultra", "azure_gpt5"),
    ModelSpec("gpt-5.5-global", "GPT-5.5 Global", "GPT-5", "ultra", "azure_gpt5"),
    ModelSpec("gpt-5-mini-global", "GPT-5 Mini Global", "GPT-5", "premium", "azure_gpt5"),
    ModelSpec("gpt-5.4-global", "GPT-5.4 Global", "GPT-5", "premium", "azure_gpt5"),
    ModelSpec("gpt-5.4-mini-global", "GPT-5.4 Mini", "GPT-5", "standard", "azure_gpt5"),
    ModelSpec("gpt-5.4-nano-global", "GPT-5.4 Nano", "GPT-5", "budget", "azure_gpt5"),
    ModelSpec("gpt-5-nano-global", "GPT-5 Nano Global", "GPT-5", "budget", "azure_gpt5"),
    ModelSpec("o4-mini-global", "o4-mini Global", "Reasoning (o-series)", "premium", "azure_chat"),
    ModelSpec("o3-global", "o3 Global", "Reasoning (o-series)", "ultra", "azure_chat"),
    ModelSpec("o3-mini-global", "o3-mini Global", "Reasoning (o-series)", "premium", "azure_chat"),
    ModelSpec("o3-pro-global", "o3-pro Global", "Reasoning (o-series)", "ultra", "azure_chat"),
    ModelSpec("gpt-5.3-codex-global", "GPT-5.3 Codex", "Codex (Deep Reasoning Code)", "premium", "azure_gpt5"),
    ModelSpec("gpt-5.1-codex-global", "GPT-5.1 Codex", "Codex (Deep Reasoning Code)", "premium", "azure_gpt5"),
    ModelSpec("gpt-5.1-codex-mini-global", "GPT-5.1 Codex Mini", "Codex (Deep Reasoning Code)", "standard", "azure_gpt5"),
    ModelSpec("gpt-5.2-codex-global", "GPT-5.2 Codex", "Codex (Deep Reasoning Code)", "premium", "azure_gpt5"),
    ModelSpec("gpt-image-2-global", "DALL-E (gpt-image-2)", "Image Generation", "premium", "azure_image"),
    ModelSpec("gpt-image-1.5-global", "DALL-E (gpt-image-1.5)", "Image Generation", "premium", "azure_image"),
    ModelSpec("gpt-image-1-global", "DALL-E (gpt-image-1)", "Image Generation", "standard", "azure_image"),
    ModelSpec("gpt-image-1-mini-global", "DALL-E Mini", "Image Generation", "budget", "azure_image"),
    ModelSpec("gemini-2.5-flash-image", "Imagen (Gemini)", "Image Generation", "standard", "vertex_image"),
    ModelSpec("us.anthropic.claude-sonnet-4-6", "Claude Sonnet 4.6", "Claude (Bedrock)", "standard", "bedrock"),
    ModelSpec("us.anthropic.claude-opus-4-8", "Claude Opus 4.8", "Claude (Bedrock)", "ultra", "bedrock"),
    ModelSpec("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5", "Claude (Bedrock)", "budget", "bedrock"),
    ModelSpec("global.anthropic.claude-opus-4-8", "Claude Opus 4.8 (G)", "Claude (Bedrock)", "ultra", "bedrock"),
    ModelSpec("global.anthropic.claude-sonnet-4-6", "Claude Sonnet 4.6 (G)", "Claude (Bedrock)", "standard", "bedrock"),
    ModelSpec("us.meta.llama3-3-70b-instruct-v1:0", "Llama 3.3 70B", "Llama (Bedrock)", "standard", "bedrock"),
    ModelSpec("us.meta.llama3-2-90b-instruct-v1:0", "Llama 3.2 90B", "Llama (Bedrock)", "budget", "bedrock"),
    ModelSpec("gemini-2.5-pro", "Gemini 2.5 Pro", "Gemini (Vertex)", "premium", "vertex"),
    ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", "Gemini (Vertex)", "budget", "vertex"),
    ModelSpec("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "Gemini (Vertex)", "budget", "vertex"),
]


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
    # - Codex is a Responses API code specialist, not the function-call planner.
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
    """Choose a tool-capable orchestrator while preserving specialist intent."""
    if model_supports_tools(requested_model):
        return requested_model
    return "gpt-5.4-global" if gpt5_configured else "gpt-4.1-global"


def code_specialist_for(requested_model: str) -> str:
    if capabilities_for(requested_model).code_specialist:
        return requested_model
    return "gpt-5.3-codex-global"


def model_specs() -> Iterable[ModelSpec]:
    return tuple(_MODEL_SPECS)


def runtime_catalog(config) -> List[Dict]:
    """Return frontend-safe model metadata + live provider availability.

    This is a runtime integration registry, not a provider-side deployment
    discovery API.  It prevents the UI from advertising a model whose provider
    is not configured and centralizes capability labels in the backend.
    """
    provider_available = {
        "azure_chat": bool(getattr(config, "azure_chat", None)),
        "azure_gpt5": bool(getattr(config, "azure_gpt5", None)),
        "azure_image": bool(getattr(config, "azure_image", None)),
        "bedrock": bool(getattr(config, "bedrock", None)),
        "vertex": bool(getattr(config, "vertex", None)),
        "vertex_image": bool(getattr(config, "vertex_image", None)),
    }
    result = []
    for spec in _MODEL_SPECS:
        caps = capabilities_for(spec.id)
        item = asdict(spec)
        item["capabilities"] = asdict(caps)
        item["available"] = provider_available.get(spec.provider, False)
        result.append(item)
    return result
