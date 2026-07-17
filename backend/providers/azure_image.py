"""Azure Image Generation — gpt-image-1/1.5/2 via /images/generations."""
import base64
from typing import Literal, Optional

from openai import AsyncAzureOpenAI

from ..config import get_config

_DEFAULT_MODEL = "gpt-image-2-global"
_QUALITY_MODEL = "gpt-image-1-global"
ImageSize = Literal["1024x1024", "1792x1024", "1024x1792"]


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_image
    if not cfg:
        raise RuntimeError("Azure Image not configured — add [azure_image] to config.ini")
    return AsyncAzureOpenAI(
        api_key=cfg.api_key,
        azure_endpoint=cfg.endpoint,
        api_version=cfg.api_version,
    )


async def generate_image(
    prompt: str,
    model: str = _DEFAULT_MODEL,
    size: ImageSize = "1024x1024",
    n: int = 1,
) -> dict:
    """Returns {url, b64, prompt}. b64 is set if no URL returned."""
    c = _client()
    resp = await c.images.generate(model=model, prompt=prompt, n=n, size=size)
    item = resp.data[0]
    return {
        "prompt": prompt,
        "url": getattr(item, "url", None),
        "b64": getattr(item, "b64_json", None),
        "model": model,
        "size": size,
    }


async def edit_image(
    image_bytes: bytes,
    mask_bytes: Optional[bytes],
    prompt: str,
    model: str = _QUALITY_MODEL,
    size: ImageSize = "1024x1024",
) -> dict:
    """Image inpainting — requires model that supports edits."""
    import io
    c = _client()
    img_buf = io.BytesIO(image_bytes)
    img_buf.name = "image.png"
    kwargs = {
        "model": model,
        "image": img_buf,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    if mask_bytes:
        mask_buf = io.BytesIO(mask_bytes)
        mask_buf.name = "mask.png"
        kwargs["mask"] = mask_buf

    resp = await c.images.edit(**kwargs)
    item = resp.data[0]
    return {
        "prompt": prompt,
        "url": getattr(item, "url", None),
        "b64": getattr(item, "b64_json", None),
    }
