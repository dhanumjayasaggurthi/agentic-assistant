"""Azure Embeddings — text-embedding-3-large/small/ada-002."""
from typing import List

from openai import AsyncAzureOpenAI

from ..config import get_config

_DEFAULT_MODEL = "text-embedding-3-large"


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_embedding
    if not cfg:
        raise RuntimeError("Azure Embedding not configured — add [azure_embedding] to config.ini")
    return AsyncAzureOpenAI(
        api_key=cfg.api_key,
        azure_endpoint=cfg.endpoint,
        api_version=cfg.api_version,
    )


async def embed(text: str, model: str = _DEFAULT_MODEL) -> List[float]:
    c = _client()
    resp = await c.embeddings.create(model=model, input=text)
    return resp.data[0].embedding


async def embed_batch(texts: List[str], model: str = _DEFAULT_MODEL) -> List[List[float]]:
    c = _client()
    resp = await c.embeddings.create(model=model, input=texts)
    resp.data.sort(key=lambda x: x.index)
    return [d.embedding for d in resp.data]
