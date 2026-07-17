# RDI GenAI API Marketplace — Enterprise Knowledge Reference

> **Status:** All 96 models verified LIVE — 2026-06-22  
> **Purpose:** Single-source reference for building enterprise AI systems on RDI's internal GenAI gateway.  
> **Use as:** System prompt context · RAG document · MCP tool description · AI skill file

---

## Table of Contents

1. [Quick Decision Guide](#1-quick-decision-guide)
2. [Architecture Overview](#2-architecture-overview)
3. [Complete Model Catalog](#3-complete-model-catalog)
4. [Cost Framework](#4-cost-framework)
5. [API Call Patterns](#5-api-call-patterns)
6. [When to Use Which Model](#6-when-to-use-which-model)
7. [Production Integration Guide](#7-production-integration-guide)
8. [Tool Use & Agentic Patterns](#8-tool-use--agentic-patterns)
9. [MCP / Skill Integration](#9-mcp--skill-integration)
10. [Configuration Reference](#10-configuration-reference)

---

## 1. Quick Decision Guide

```
What's your task?
│
├── WRITE CODE / COMPLETE CODE ──────────────────► gpt-5.3-codex-global   [Responses API]
│                                                  gpt-5.1-codex-global   [Responses API]
│
├── REASON / MATH / LOGIC ──────────────────────► o4-mini-global          [fast + cheap]
│   Complex multi-step                             o3-global               [thorough]
│   Proof-level accuracy                           o3-pro-global           [best, slow]
│
├── GENERAL CHAT (enterprise, compliance) ──────► gpt-4o-global            [default]
│   Balanced quality + cost                        gpt-4.1-global           [latest GPT-4]
│                                                  gpt-4.1-mini-global      [cost-optimized]
│
├── HIGH-VOLUME / BATCH ─────────────────────────► gpt-4.1-nano-global     [cheapest Azure]
│   Cost-sensitive, speed-sensitive                gemini-2.5-flash-lite   [cheapest overall]
│                                                  gpt-4o-mini-global      [balanced]
│
├── LONG DOCS / DEEP ANALYSIS ───────────────────► gpt-5-global            [200K context]
│   Multi-document, research-grade                 gemini-2.5-pro          [1M context]
│   Unstructured data extraction                   claude-opus-4-8         [200K context]
│
├── AGENTIC WORKFLOWS (tool use) ────────────────► gpt-4o-global           [OpenAI tools]
│   File ops, bash, multi-step                     claude-sonnet-4-6       [Anthropic tools]
│                                                  gpt-4.1-global          [OpenAI tools]
│
├── DOCUMENT GENERATION / STRUCTURED OUTPUT ─────► gpt-4.1-global
│   JSON, reports, templates                       claude-sonnet-4-6       [instruction-following]
│
├── IMAGE GENERATION ────────────────────────────► gpt-image-2-global      [fast]
│                                                  gpt-image-1.5-global    [balanced]
│                                                  gpt-image-1-global      [highest quality]
│
├── TEXT-TO-SPEECH ──────────────────────────────► gpt-4o-mini-tts-global
│
├── SPEECH-TO-TEXT ──────────────────────────────► gpt-4o-transcribe-global      [most accurate]
│   With speaker diarization                       gpt-4o-transcribe-diarize-global
│
├── EMBEDDINGS / RAG ────────────────────────────► text-embedding-3-large  [best quality]
│   Semantic search, classification                text-embedding-3-small  [cost-optimized]
│                                                  cohere.embed-v4:0       [multilingual RAG]
│
└── MULTIMODAL (vision + text) ──────────────────► gpt-4o-global           [images + text]
                                                   gemini-2.5-pro          [best vision]
                                                   claude-opus-4-8         [vision + analysis]
```

---

## 2. Architecture Overview

RDI's GenAI API Marketplace routes traffic through **two separate gateway domains**, each requiring its own API key per capability card:

```
Developer / Application
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              RDI GenAI API Gateway (Internal)                   │
├───────────────────────┬────────────────────┬────────────────────┤
│  Azure OpenAI (NA)    │  AWS Bedrock (NA)  │  Google Vertex (NA)│
│  genaiapimna.jnj.com  │  genaiapigwna.jnj  │  genaiapigcpna.jnj │
└──────┬────────────────┴────────────────────┴────────────────────┘
       │
       ├── /openai-chat          → GPT-3.5, GPT-4, GPT-4o, GPT-4.1, o-series
       ├── /openai-gpt-5         → GPT-5 family + all Codex models
       ├── /openai-embeddings    → text-embedding-ada-002, 3-small, 3-large
       ├── /openai-image         → gpt-image-1/1.5/2 generation
       ├── /openai-audio         → TTS + Transcription models
       └── /openai-completion    → Legacy (gpt-35-turbo-instruct, deprecated)
```

### 9 Marketplace Cards = 9 Separate API Keys

| Card | Base URL | Auth Header | Models |
|------|----------|-------------|--------|
| Azure Chat Completion | `https://genaiapimna.jnj.com/openai-chat` | `api-key` | GPT-3.5, GPT-4*, o-series |
| Azure GPT-5 | `https://genaiapimna.jnj.com/openai-gpt-5` | `api-key` | GPT-5*, Codex* |
| Azure Embeddings | `https://genaiapimna.jnj.com/openai-embeddings` | `api-key` | text-embedding-* |
| Azure Image Gen | `https://genaiapimna.jnj.com/openai-image` | `api-key` | gpt-image-* |
| Azure Audio | `https://genaiapimna.jnj.com/openai-audio` | `api-key` | TTS + Transcription |
| Azure Completion (legacy) | `https://genaiapimna.jnj.com/openai-completion` | `api-key` | gpt-35-turbo-instruct |
| Amazon Bedrock | `https://genaiapigwna.jnj.com` | `x-api-key` | Claude, Llama, Cohere |
| Google Vertex AI | `https://genaiapigcpna.jnj.com` | `x-api-key` | Gemini chat/text |
| Google Vertex Image | `https://genaiapigcpna.jnj.com` | `x-api-key` | Gemini image gen |

### SDK / Protocol Mapping

| Provider | SDK | Auth Method | API Style |
|----------|-----|-------------|-----------|
| Azure OpenAI | `openai.AzureOpenAI` | `api-key` header | OpenAI REST |
| Amazon Bedrock | `boto3` + event hooks | `x-api-key` header | AWS Bedrock Converse API |
| Google Vertex | `google-genai` client | `x-api-key` header (HttpOptions) | Vertex REST |

---

## 3. Complete Model Catalog

### 3.1 Azure Chat Completion (`openai-chat`)

API Version: `2024-12-01-preview`  
Call pattern: `POST /openai/deployments/{model}/chat/completions`

#### GPT-3.5 / GPT-4 Legacy

| Model | Context | Best For | Speed | Cost Tier |
|-------|---------|----------|-------|-----------|
| `gpt-35-turbo` | 4K | Simple Q&A, legacy compat | Fast | Budget |
| `gpt-35-turbo-16k` | 16K | Longer legacy docs | Fast | Budget |
| `gpt-4` | 8K | Reliable GPT-4 baseline | Moderate | Standard |
| `gpt-4-32k` | 32K | Longer GPT-4 docs | Moderate | Standard+ |
| `gpt-4-turbo` | 128K | High quality, long context | Moderate | Standard+ |
| `gpt-4o` | 128K | Vision + text, balanced | Fast | Standard |
| `gpt-4o-global` | 128K | Same as 4o, global routing | Fast | Standard |
| `gpt-4o-mini` | 128K | Cost-efficient GPT-4o | Very Fast | Budget |
| `gpt-4o-mini-global` | 128K | Same, global routing | Very Fast | Budget |

#### GPT-4.1 Family (Latest Recommended)

| Model | Context | Best For | Speed | Cost Tier |
|-------|---------|----------|-------|-----------|
| `gpt-4.1` | 1M | High quality, 1M context | Fast | Standard |
| `gpt-4.1-global` | 1M | Same, global routing | Fast | Standard |
| `gpt-4.1-mini` | 1M | Balanced, fast | Very Fast | Budget |
| `gpt-4.1-mini-global` | 1M | Same, global routing | Very Fast | Budget |
| `gpt-4.1-nano` | 1M | Extreme speed/cost | Ultra Fast | Ultra Budget |
| `gpt-4.1-nano-global` | 1M | Same, global routing | Ultra Fast | Ultra Budget |

#### o-Series Reasoning (No system prompt; use `max_completion_tokens`)

| Model | Best For | Speed | Cost Tier | Notes |
|-------|----------|-------|-----------|-------|
| `o1-mini-global` | Fast reasoning | Fast | Standard | Older gen |
| `o1-global` | Deep reasoning | Slow | Premium | Older gen |
| `o1` | Deep reasoning | Slow | Premium | Older gen |
| `o3-mini` | Efficient reasoning | Moderate | Standard | |
| `o3-mini-global` | Efficient reasoning | Moderate | Standard | |
| `o3` | Strong reasoning | Slow | Premium | |
| `o3-global` | Strong reasoning | Slow | Premium | |
| `o4-mini` | Best value reasoning | Fast | Standard | **Recommended** |
| `o4-mini-global` | Best value reasoning | Fast | Standard | **Recommended** |

#### o3-pro (Responses API only)

| Model | Best For | Speed | Cost Tier |
|-------|----------|-------|-----------|
| `o3-pro-global` | Best reasoning, high-stakes | Very Slow | Ultra Premium |

> ⚠️ `o3-pro-global` uses RDI's v1 Responses API: `POST /openai/v1/responses` on the `openai-chat` endpoint.

---

### 3.2 Azure GPT-5 (`openai-gpt-5`)

API Version: `2024-10-21`  
Token param: **`max_completion_tokens`** (NOT `max_tokens`)  
Call pattern: `POST /openai/deployments/{model}/chat/completions`

#### GPT-5 Chat Models

| Model | Context | Best For | Speed | Cost Tier |
|-------|---------|----------|-------|-----------|
| `gpt-5` | 1M+ | Best overall capability | Moderate | Ultra Premium |
| `gpt-5-global` | 1M+ | Same, global routing | Moderate | Ultra Premium |
| `gpt-5-mini` | 1M+ | Efficient GPT-5 | Fast | Premium |
| `gpt-5-mini-global` | 1M+ | Same, global routing | Fast | Premium |
| `gpt-5-nano` | 1M+ | Fast GPT-5 variant | Very Fast | Standard |
| `gpt-5-nano-global` | 1M+ | Same, global routing | Very Fast | Standard |
| `gpt-5-chat-global` | 1M+ | Chat-optimized GPT-5 | Fast | Premium |
| `gpt-5.2` | 1M+ | GPT-5.2 base | Fast | Premium |
| `gpt-5.3-chat-global` | 1M+ | GPT-5.3 chat | Fast | Premium |
| `gpt-5.4` | 1M+ | GPT-5.4 | Fast | Premium |
| `gpt-5.4-global` | 1M+ | Same, global routing | Fast | Premium |
| `gpt-5.4-mini-global` | 1M+ | Efficient GPT-5.4 | Fast | Standard |
| `gpt-5.4-nano` | 1M+ | Fast GPT-5.4 | Very Fast | Standard |
| `gpt-5.4-nano-global` | 1M+ | Same, global routing | Very Fast | Standard |
| `gpt-5.5` | 1M+ | Latest GPT-5 | Moderate | Ultra Premium |
| `gpt-5.5-global` | 1M+ | Same, global routing | Moderate | Ultra Premium |

#### GPT-5 Codex (Responses API only)

All Codex models use: `POST /openai/v1/responses` on the `openai-gpt-5` endpoint  
Body: `{"model": "...", "input": "...", "max_output_tokens": N}`

| Model | Best For | Notes |
|-------|----------|-------|
| `gpt-5-pro-global` | Complex code generation | Responses API only |
| `gpt-5-codex-global` | Code completion | Responses API only |
| `gpt-5.1-codex-global` | Code generation v5.1 | Responses API only |
| `gpt-5.1-codex-mini-global` | Efficient code gen | Responses API only |
| `gpt-5.1-codex-max-global` | Max code quality | Responses API only |
| `gpt-5.2-codex-global` | Code generation v5.2 | Responses API only |
| `gpt-5.3-codex-global` | **Recommended codex** | Responses API only |

> 💡 Codex models are purpose-built for code completion, refactoring, and code explanation. They do NOT support standard chat/completions — only the Responses API.

---

### 3.3 Azure Embeddings (`openai-embeddings`)

API Version: `2022-12-01`  
Call pattern: `POST /openai/deployments/{model}/embeddings`

| Model | Dimensions | Best For | Cost Tier |
|-------|-----------|----------|-----------|
| `text-embedding-ada-002` | 1536 | Legacy compatibility | Budget |
| `text-embedding-3-small` | 1536 | Cost-optimized RAG | Budget |
| `text-embedding-3-large` | 3072 | Highest quality RAG | Standard |

---

### 3.4 Azure Image Generation (`openai-image`)

API Version: `2024-10-21`  
Call pattern: `POST /openai/deployments/{model}/images/generations`

| Model | Best For | Quality | Speed | Cost Tier |
|-------|----------|---------|-------|-----------|
| `gpt-image-2-global` | Fast generation | High | Fast | Standard |
| `gpt-image-1.5-global` | Balanced | Very High | Moderate | Standard+ |
| `gpt-image-1-mini-global` | Efficient | High | Moderate | Standard |
| `gpt-image-1-global` | Highest quality | Best | Slow | Premium |

---

### 3.5 Azure Audio (`openai-audio`)

API Version: `2025-03-01-preview`  
Base URL: `https://genaiapimna.jnj.com/openai-audio` (**separate endpoint from chat**)

#### Text-to-Speech

| Model | Best For | Notes |
|-------|----------|-------|
| `gpt-4o-mini-tts-global` | Voice synthesis | Voices: alloy, echo, fable, onyx, nova, shimmer |

#### Speech-to-Text (Transcription)

| Model | Best For | Notes |
|-------|----------|-------|
| `gpt-4o-transcribe-global` | Accurate transcription | |
| `gpt-4o-mini-transcribe-global` | Fast transcription | |
| `gpt-4o-transcribe-diarize-global` | Multi-speaker + diarization | Identifies speakers |

---

### 3.6 Amazon Bedrock (`genaiapigwna.jnj.com`)

Auth: `x-api-key` header injected via boto3 `before-call` event hook  
SDK: `boto3` Converse API (unified across all model families)

#### Claude (Anthropic) — Via Bedrock

| Model | Context | Best For | Speed | Cost Tier |
|-------|---------|----------|-------|-----------|
| `anthropic.claude-3-haiku-20240307-v1:0` | 200K | Legacy fast | Very Fast | Budget |
| `anthropic.claude-3-sonnet-20240229-v1:0` | 200K | Legacy balanced | Moderate | Standard |
| `us.anthropic.claude-sonnet-4-20250514-v1:0` | 200K | Sonnet 4 | Fast | Standard |
| `global.anthropic.claude-sonnet-4-20250514-v1:0` | 200K | Same, global | Fast | Standard |
| `us.anthropic.claude-opus-4-1-20250805-v1:0` | 200K | Opus 4.1 | Moderate | Premium |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | 200K | Sonnet 4.5 | Fast | Standard |
| `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | 200K | Same, global | Fast | Standard |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 200K | Haiku 4.5 — **fastest Claude** | Ultra Fast | Budget |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 200K | Same, global | Ultra Fast | Budget |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 200K | Opus 4.5 | Moderate | Premium |
| `global.anthropic.claude-opus-4-5-20251101-v1:0` | 200K | Same, global | Moderate | Premium |
| `us.anthropic.claude-opus-4-6-v1` | 200K | Opus 4.6 | Moderate | Premium |
| `global.anthropic.claude-opus-4-6-v1` | 200K | Same, global | Moderate | Premium |
| `us.anthropic.claude-sonnet-4-6` | 200K | **Recommended Sonnet** | Fast | Standard |
| `global.anthropic.claude-sonnet-4-6` | 200K | Same, global | Fast | Standard |
| `us.anthropic.claude-opus-4-7` | 200K | Opus 4.7 | Moderate | Premium |
| `global.anthropic.claude-opus-4-7` | 200K | Same, global | Moderate | Premium |
| `us.anthropic.claude-opus-4-8` | 200K | **Best Claude, most capable** | Moderate | Ultra Premium |
| `global.anthropic.claude-opus-4-8` | 200K | Same, global | Moderate | Ultra Premium |

#### Meta Llama — Via Bedrock

| Model | Best For | Speed | Cost Tier |
|-------|----------|-------|-----------|
| `us.meta.llama3-2-11b-instruct-v1:0` | Lightweight open-source | Very Fast | Budget |
| `us.meta.llama3-2-90b-instruct-v1:0` | Quality open-source | Fast | Standard |
| `us.meta.llama3-3-70b-instruct-v1:0` | **Best Llama** — open-source | Fast | Standard |

#### Cohere Command — Via Bedrock

| Model | Best For | Notes |
|-------|----------|-------|
| `cohere.command-r-v1:0` | RAG + retrieval-augmented chat | Grounding-optimized |
| `cohere.command-r-plus-v1:0` | **Best Cohere chat** | Better reasoning |

#### Amazon Titan + Cohere Embeddings — Via Bedrock

| Model | Dimensions | Best For | Cost Tier |
|-------|-----------|----------|-----------|
| `amazon.titan-embed-text-v1` | 1536 | General text | Budget |
| `amazon.titan-embed-text-v2:0` | 1024 | Updated Titan | Budget |
| `amazon.titan-embed-image-v1` | 1024 | Multimodal embed | Standard |
| `cohere.embed-english-v3` | 1024 | English RAG | Standard |
| `cohere.embed-multilingual-v3` | 1024 | Multilingual RAG | Standard |
| `us.cohere.embed-v4:0` | 1536 | **Best embed** (float/int8 output) | Standard |
| `global.cohere.embed-v4:0` | 1536 | Same, global routing | Standard |

> ⚠️ Cohere embed-v4 response format: `{"embeddings": {"float": [[...]]}}` — nested dict, not list. Parse with `data["embeddings"]["float"][0]`.

---

### 3.7 Google Vertex AI (`genaiapigcpna.jnj.com`)

Auth: `x-api-key` in `HttpOptions.headers`  
SDK: `google-genai` Client with `vertexai=True`, dummy credentials

#### Gemini Chat Models

| Model | Context | Best For | Speed | Cost Tier |
|-------|---------|----------|-------|-----------|
| `gemini-2.5-flash-lite` | 1M | Ultra-fast, cheapest | Ultra Fast | Ultra Budget |
| `gemini-2.5-flash` | 1M | Fast + capable | Very Fast | Budget |
| `gemini-2.5-pro` | 1M | **Best Gemini**, vision, analysis | Moderate | Premium |

#### Gemini Image Generation

| Model | Best For | Notes |
|-------|----------|-------|
| `gemini-2.5-flash-image` | Image generation via Vertex | Raw HTTP, separate key |

> ⚠️ Vertex Image uses raw HTTP: `POST {endpoint}/v1/projects/GenAI/locations/us-east1/publishers/google/models/{model}:generateContent`

---

## 4. Cost Framework

> **Note:** RDI negotiates enterprise rates. Prices below are public reference rates as of mid-2026. Internal cost allocation may differ — check with your RDI IT cost center.

### 4.1 Cost Tiers

| Tier | ~Input Price ($/1M tokens) | ~Output Price ($/1M tokens) | Representative Models |
|------|--------------------------|----------------------------|-----------------------|
| **Ultra Budget** | < $0.10 | < $0.40 | gpt-4.1-nano, gemini-2.5-flash-lite |
| **Budget** | $0.10 – $0.50 | $0.40 – $2.00 | gpt-4o-mini, gpt-4.1-mini, gemini-2.5-flash, claude-haiku-4-5 |
| **Standard** | $0.50 – $3.00 | $2.00 – $10.00 | gpt-4o, gpt-4.1, claude-sonnet-4-6, gemini-2.5-pro |
| **Premium** | $3.00 – $15.00 | $10.00 – $40.00 | o3-mini, o4-mini, gpt-5-mini, claude-opus-4-5 |
| **Ultra Premium** | $15.00+ | $40.00+ | o3, o3-pro, gpt-5, gpt-5.5, claude-opus-4-8 |

### 4.2 Model Cost Matrix

| Model | Input $/1M | Output $/1M | Context | Tier |
|-------|-----------|------------|---------|------|
| `gpt-4.1-nano-global` | $0.10 | $0.40 | 1M | Ultra Budget |
| `gpt-4.1-mini-global` | $0.40 | $1.60 | 1M | Budget |
| `gpt-4o-mini-global` | $0.15 | $0.60 | 128K | Budget |
| `gemini-2.5-flash-lite` | $0.075 | $0.30 | 1M | Ultra Budget |
| `gemini-2.5-flash` | $0.075 | $0.30 | 1M | Budget |
| `claude-haiku-4-5` | $0.80 | $4.00 | 200K | Budget |
| `gpt-4.1-global` | $2.00 | $8.00 | 1M | Standard |
| `gpt-4o-global` | $2.50 | $10.00 | 128K | Standard |
| `gemini-2.5-pro` | $1.25 | $5.00 | 1M | Standard |
| `claude-sonnet-4-6` | $3.00 | $15.00 | 200K | Standard |
| `o4-mini-global` | $1.10 | $4.40 | 128K | Premium |
| `o3-mini-global` | $1.10 | $4.40 | 128K | Premium |
| `gpt-5-mini-global` | ~$5.00 | ~$20.00 | 1M | Premium |
| `claude-opus-4-8` | $15.00 | $75.00 | 200K | Ultra Premium |
| `o3-global` | $10.00 | $40.00 | 128K | Ultra Premium |
| `o3-pro-global` | $20.00 | $80.00 | 128K | Ultra Premium |
| `gpt-5-global` | ~$20.00 | ~$80.00 | 1M+ | Ultra Premium |

### 4.3 Embedding Costs

| Model | Price $/1M tokens |
|-------|------------------|
| `text-embedding-3-small` | $0.02 |
| `text-embedding-3-large` | $0.13 |
| `text-embedding-ada-002` | $0.10 (legacy) |
| `cohere.embed-v4:0` | $0.06 |

### 4.4 Image Generation Costs

| Model | Per Image (~1024×1024) |
|-------|----------------------|
| `gpt-image-2-global` | ~$0.04 |
| `gpt-image-1.5-global` | ~$0.06 |
| `gpt-image-1-global` | ~$0.08 |

### 4.5 Audio Costs

| Capability | Price |
|------------|-------|
| TTS (gpt-4o-mini-tts-global) | ~$15/1M characters |
| Transcription | ~$0.006/minute |

### 4.6 Cost Optimization Rules

```
1. NEVER use o3/o3-pro/gpt-5 for simple chat → use gpt-4o-mini ($100x cheaper)
2. NEVER use Claude Opus for batch classification → use Claude Haiku (10x cheaper)
3. For RAG: embed once with text-embedding-3-large, query with gpt-4o-mini
4. For high-volume (>100K req/day): use nano/flash-lite, cache repetitive prompts
5. Reasoning models (o-series) charge for thinking tokens — cap with max_completion_tokens
6. Use global routing variants for better throughput at same price
7. GPT-5 Codex models → use for code only, not general chat
```

---

## 5. API Call Patterns

### 5.1 Azure Chat (Standard)

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key="YOUR_AZURE_CHAT_API_KEY",
    azure_endpoint="https://genaiapimna.jnj.com/openai-chat",
    api_version="2024-12-01-preview",
)

response = client.chat.completions.create(
    model="gpt-4o-global",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user",   "content": "Summarize this document: ..."},
    ],
    max_tokens=500,
)
text = response.choices[0].message.content
```

### 5.2 Azure GPT-5 Chat

```python
# IMPORTANT: use max_completion_tokens, NOT max_tokens
client_gpt5 = AzureOpenAI(
    api_key="YOUR_AZURE_GPT5_API_KEY",
    azure_endpoint="https://genaiapimna.jnj.com/openai-gpt-5",
    api_version="2024-10-21",
)

response = client_gpt5.chat.completions.create(
    model="gpt-5-global",
    messages=[{"role": "user", "content": "..."}],
    max_completion_tokens=1000,   # NOT max_tokens
)
```

### 5.3 Azure Reasoning (o-series)

```python
# o-series: no system prompt, use max_completion_tokens
response = client.chat.completions.create(
    model="o4-mini-global",
    messages=[{"role": "user", "content": "Solve: ..."}],
    max_completion_tokens=2000,
    # DO NOT pass: temperature, top_p, system message
)
```

### 5.4 Codex / o3-pro — Responses API

```python
import requests

def call_responses_api(api_key, endpoint_base, model, prompt):
    url  = f"{endpoint_base.rstrip('/')}/openai/v1/responses"
    body = {"model": model, "input": prompt, "max_output_tokens": 2000}
    r = requests.post(
        url,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    return "".join(
        part.get("text", "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )

# Codex → gpt-5 endpoint
code = call_responses_api(
    api_key=GPT5_KEY,
    endpoint_base="https://genaiapimna.jnj.com/openai-gpt-5",
    model="gpt-5.3-codex-global",
    prompt="Write a Python function to merge two sorted lists.",
)

# o3-pro → chat endpoint
answer = call_responses_api(
    api_key=CHAT_KEY,
    endpoint_base="https://genaiapimna.jnj.com/openai-chat",
    model="o3-pro-global",
    prompt="Prove that sqrt(2) is irrational.",
)
```

### 5.5 Azure Embeddings

```python
client_emb = AzureOpenAI(
    api_key="YOUR_EMBEDDING_API_KEY",
    azure_endpoint="https://genaiapimna.jnj.com/openai-embeddings",
    api_version="2022-12-01",
)

response = client_emb.embeddings.create(
    model="text-embedding-3-large",
    input="Patient reported adverse event: headache and nausea",
)
vector = response.data[0].embedding  # List[float], length 3072
```

### 5.6 Amazon Bedrock (all models)

```python
import boto3, json

session = boto3.Session(aws_access_key_id="dummy", aws_secret_access_key="dummy")
client  = session.client("bedrock-runtime",
                         endpoint_url="https://genaiapigwna.jnj.com",
                         region_name="dummy")

# Inject RDI API key for every call
BEDROCK_KEY = "YOUR_BEDROCK_API_KEY"
def _inject(model, params, request_signer, **kwargs):
    params["headers"]["x-api-key"] = BEDROCK_KEY

client.meta.events.register("before-call.bedrock-runtime.Converse",    _inject)
client.meta.events.register("before-call.bedrock-runtime.InvokeModel", _inject)

# Chat (Converse API — works for Claude, Llama, Cohere)
response = client.converse(
    modelId="us.anthropic.claude-opus-4-8",
    system=[{"text": "You are a clinical data analyst."}],
    messages=[{"role": "user", "content": [{"text": "Analyze this trial data..."}]}],
)
text   = response["output"]["message"]["content"][0]["text"]
tokens = response["usage"]["inputTokens"] + response["usage"]["outputTokens"]
```

### 5.7 Google Vertex AI (Gemini)

```python
from google import genai
from google.genai.types import HttpOptions
from google.auth.credentials import Credentials

class DummyCreds(Credentials):
    def refresh(self, req):
        self.token  = "dummy-token"
        self.expiry = None

client = genai.Client(
    vertexai=True, project="dummy", location="dummy",
    http_options=HttpOptions(
        api_version="v1",
        base_url="https://genaiapigcpna.jnj.com",
        headers={"x-api-key": "YOUR_VERTEX_API_KEY"},
    ),
    credentials=DummyCreds(),
)

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents="Explain this clinical trial protocol...",
)
text = response.text
```

### 5.8 Azure Audio — TTS

```python
client_audio = AzureOpenAI(
    api_key="YOUR_AZURE_AUDIO_API_KEY",
    azure_endpoint="https://genaiapimna.jnj.com/openai-audio",
    api_version="2025-03-01-preview",
)

audio = client_audio.audio.speech.create(
    model="gpt-4o-mini-tts-global",
    voice="nova",   # alloy | echo | fable | onyx | nova | shimmer
    input="Welcome to RDI's AI assistant. How can I help you today?",
)
audio.stream_to_file("output.mp3")
```

### 5.9 Azure Audio — Transcription

```python
with open("meeting.wav", "rb") as f:
    transcript = client_audio.audio.transcriptions.create(
        model="gpt-4o-transcribe-global",
        file=f,
    )
print(transcript.text)

# With speaker diarization:
transcript_diarized = client_audio.audio.transcriptions.create(
    model="gpt-4o-transcribe-diarize-global",
    file=f,
)
```

### 5.10 Bedrock Cohere Embeddings (v4 format)

```python
body = json.dumps({"texts": [text], "input_type": "search_query"})
resp = client.invoke_model(
    modelId="us.cohere.embed-v4:0",
    body=body,
    accept="application/json",
    contentType="application/json",
)
payload = json.loads(resp["body"].read())
# v4 response is DICT, not list:
embeddings = payload["embeddings"]["float"]   # [[...]]
vector = embeddings[0]                         # List[float]
```

---

## 6. When to Use Which Model

### 6.1 Task-to-Model Mapping

| Task Type | Top Pick | Backup | Notes |
|-----------|----------|--------|-------|
| **Simple Q&A, chat** | `gpt-4o-global` | `gpt-4.1-mini-global` | Default for most |
| **Document summarization** | `gpt-4.1-global` | `claude-sonnet-4-6` | 1M context |
| **Long-form content gen** | `gpt-5-global` | `claude-opus-4-8` | High quality |
| **Code generation** | `gpt-5.3-codex-global` | `gpt-5.1-codex-global` | Responses API |
| **Code review / explain** | `gpt-4o-global` | `claude-sonnet-4-6` | Tool use |
| **Math / logic / proofs** | `o4-mini-global` | `o3-global` | No system prompt |
| **Multi-step reasoning** | `o3-global` | `o4-mini-global` | |
| **Highest-stakes reasoning** | `o3-pro-global` | `o3-global` | Slow, 16s avg |
| **Data extraction / JSON** | `gpt-4.1-global` | `claude-sonnet-4-6` | Structured output |
| **Classification (high vol)** | `gpt-4.1-nano-global` | `gemini-2.5-flash-lite` | Cheapest |
| **Agentic tool use** | `gpt-4o-global` | `claude-sonnet-4-6` | Function calling |
| **Vision / image analysis** | `gpt-4o-global` | `gemini-2.5-pro` | Multimodal |
| **RAG retrieval** | `gpt-4o-mini-global` | `claude-haiku-4-5` | Fast + cheap |
| **Translation** | `gpt-4o-global` | `gemini-2.5-flash` | |
| **Sentiment / NLP** | `gpt-4.1-mini-global` | `gemini-2.5-flash` | |
| **Enterprise compliance** | `claude-opus-4-8` | `gpt-4o-global` | Policy-aware |
| **Medical / clinical** | `claude-opus-4-8` | `o3-global` | High accuracy |
| **Legal document review** | `o3-global` | `claude-opus-4-8` | Reasoning |
| **Image generation** | `gpt-image-2-global` | `gpt-image-1-global` | |
| **Voice/TTS** | `gpt-4o-mini-tts-global` | — | |
| **Transcription** | `gpt-4o-transcribe-global` | — | |
| **Multilingual embeddings** | `cohere.embed-v4:0` | `cohere.embed-multilingual-v3` | |

### 6.2 Quality vs Cost vs Speed Trade-off Matrix

```
QUALITY
   ▲
   │  o3-pro  gpt-5  claude-opus-4-8
   │    o3    gpt-5.5
   │   o4-mini  gpt-5-mini  claude-opus-4-5
   │  gpt-4.1  claude-sonnet-4-6  gemini-2.5-pro
   │  gpt-4o   gpt-4.1-mini
   │  gpt-4o-mini  gemini-2.5-flash  claude-haiku-4-5
   │  gpt-4.1-nano  gemini-2.5-flash-lite
   └──────────────────────────────────────────────► SPEED / LOW COST
```

### 6.3 Provider Strengths

| Provider | Excels At | Watch Out For |
|----------|-----------|---------------|
| **Azure OpenAI** | Standard enterprise chat, reasoning (o-series), coding (Codex), widest model selection | GPT-5 requires `max_completion_tokens`; o-series no system prompt |
| **AWS Bedrock** | Claude models (safety, instruction-following, tool use), open-source (Llama), unified Converse API | `x-api-key` not native AWS auth — requires event hook |
| **Google Vertex** | Longest context (1M), multimodal (vision), Gemini thinking mode, cheapest per-token | `x-api-key` auth via HttpOptions workaround; no tool use in RDI gateway currently |

---

## 7. Production Integration Guide

### 7.1 Error Handling

```python
import time
from openai import RateLimitError, APIStatusError, APITimeoutError

def call_with_retry(fn, max_retries=3, base_delay=2):
    for attempt in range(max_retries):
        try:
            return fn()
        except RateLimitError:
            wait = base_delay * (2 ** attempt)
            print(f"Rate limited. Waiting {wait}s...")
            time.sleep(wait)
        except APIStatusError as e:
            if e.status_code in (429, 503, 502):
                time.sleep(base_delay)
            else:
                raise   # 400, 401, 404 are not retryable
        except APITimeoutError:
            if attempt == max_retries - 1:
                raise
            time.sleep(base_delay)
    raise RuntimeError("Max retries exceeded")
```

### 7.2 Streaming Responses

```python
# Stream for real-time UX
with client.chat.completions.create(
    model="gpt-4o-global",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=1000,
    stream=True,
) as stream:
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
```

### 7.3 Timeout Guidelines

| Model Class | Recommended Timeout |
|-------------|-------------------|
| Chat (nano/mini) | 15s |
| Chat (standard) | 30s |
| Chat (GPT-5/Claude Opus) | 60s |
| Reasoning (o3-mini, o4-mini) | 60s |
| Reasoning (o3) | 120s |
| o3-pro | 300s |
| Codex (Responses API) | 120s |
| Image generation | 60s |
| Embeddings | 10s |
| Transcription | 30s |

### 7.4 Context Window Management

```python
# Sliding window for long conversations
def trim_history(history, max_tokens=100000, model="gpt-4o-global"):
    # Keep system + last N messages within token budget
    # Rule of thumb: 1 token ≈ 4 chars
    total = sum(len(m["content"]) // 4 for m in history)
    while total > max_tokens and len(history) > 2:
        history.pop(1)  # remove oldest non-system message
        total = sum(len(m["content"]) // 4 for m in history)
    return history
```

### 7.5 Rate Limits

RDI gateway enforces limits per API key per minute. As a safe default:

| Tier | RPM (Requests/min) | TPM (Tokens/min) |
|------|-------------------|-----------------|
| Chat (standard) | 60 | 100,000 |
| Reasoning | 20 | 50,000 |
| Embeddings | 100 | 500,000 |
| Image gen | 5 | — |
| Audio | 30 | — |

> Contact RDI IT / marketplace admin for increased limits.

### 7.6 Security Best Practices

```python
# NEVER hardcode API keys
import os
from configparser import ConfigParser

cfg = ConfigParser()
cfg.read("config.ini")

api_key = cfg.get("azure_chat", "api_key")
# OR from environment:
api_key = os.environ.get("JNJ_AZURE_CHAT_KEY")

# NEVER log full API keys
print(f"Using key: {api_key[:8]}...")  # show only prefix
```

---

## 8. Tool Use & Agentic Patterns

### 8.1 Azure OpenAI Tool Use

Supported on all chat models (NOT on o-series or Codex/Responses API models).

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search the RDI document store for relevant records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":  {"type": "string"},
                    "top_k":  {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    }
]

response = client.chat.completions.create(
    model="gpt-4o-global",
    messages=messages,
    tools=tools,
    tool_choice="auto",
    max_tokens=2000,
)

choice = response.choices[0]
if choice.finish_reason == "tool_calls":
    for tc in choice.message.tool_calls:
        fn_args = json.loads(tc.function.arguments)
        result  = your_tool_handler(tc.function.name, fn_args)
        messages.append(choice.message)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    # Loop: call model again with tool results
```

### 8.2 Bedrock Converse API Tool Use

Supported on Claude, Llama, and Cohere models via unified Converse API.

```python
tool_config = {
    "tools": [
        {
            "toolSpec": {
                "name": "search_documents",
                "description": "Search the RDI document store.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    }
                },
            }
        }
    ]
}

resp = client.converse(
    modelId="us.anthropic.claude-opus-4-8",
    messages=messages,
    toolConfig=tool_config,
)
msg = resp["output"]["message"]

if any("toolUse" in c for c in msg["content"]):
    for c in msg["content"]:
        if "toolUse" in c:
            result = your_tool_handler(c["toolUse"]["name"], c["toolUse"]["input"])
            messages.append(msg)
            messages.append({
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": c["toolUse"]["toolUseId"],
                        "content":   [{"text": result}],
                    }
                }],
            })
```

### 8.3 Agentic Loop Pattern

```python
def agent_loop(system_prompt, user_message, model="gpt-4o-global", max_turns=10):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]
    for turn in range(max_turns):
        response = client.chat.completions.create(
            model=model, messages=messages,
            tools=TOOL_DEFS, tool_choice="auto", max_tokens=2000,
        )
        choice = response.choices[0]
        if choice.finish_reason == "stop":
            return choice.message.content   # Final answer
        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                args   = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max turns reached."
```

---

## 9. MCP / Skill Integration

### 9.1 Using This Doc as a Knowledge Source

This document is designed to be loaded as context for any AI system. Use it as:

**System prompt prefix:**
```
You are a RDI enterprise AI assistant. Use the following marketplace knowledge to route tasks to the correct model and API endpoint:
[paste relevant sections from this doc]
```

**RAG embedding:**  
Embed individual sections (model catalog, decision guide, API patterns) with `text-embedding-3-large` for semantic retrieval.

**MCP Tool Description:**  
When building an MCP server that wraps the RDI marketplace, use this doc's decision framework to auto-route requests to the correct model.

### 9.2 MCP Server Skeleton (FastMCP)

```python
from mcp.server.fastmcp import FastMCP
from openai import AzureOpenAI

mcp = FastMCP("RDI-genai-marketplace")

@mcp.tool()
def chat(prompt: str, model: str = "gpt-4o-global", task_type: str = "general") -> str:
    """
    Call the RDI GenAI API Marketplace.
    task_type: general | code | reasoning | analysis | summary
    Automatically selects optimal model if not specified.
    """
    # Auto-route based on task type
    model_map = {
        "code":      "gpt-5.3-codex-global",
        "reasoning": "o4-mini-global",
        "analysis":  "claude-opus-4-8",
        "summary":   "gpt-4.1-global",
        "general":   "gpt-4o-global",
    }
    resolved_model = model if model != "gpt-4o-global" else model_map.get(task_type, "gpt-4o-global")
    # ... route to appropriate provider
    return response_text

@mcp.tool()
def embed(text: str, model: str = "text-embedding-3-large") -> list[float]:
    """Generate embeddings for RAG / semantic search."""
    # ... call embedding endpoint
    return vector
```

### 9.3 Skill File Frontmatter

For Claude Code skill files, add this as context:

```markdown
---
name: RDI-genai-marketplace
description: >
  Routes AI tasks to the correct RDI GenAI API Marketplace model.
  Covers 96 models: Azure OpenAI (GPT-4/5, o-series, Codex), 
  AWS Bedrock (Claude, Llama, Cohere), Google Vertex (Gemini).
  Includes cost optimization, API patterns, and decision framework.
triggers:
  - "which model should I use"
  - "call the RDI API"
  - "use gpt-5"
  - "use claude"
  - "use bedrock"
  - "use gemini"
---
```

### 9.4 Model Router Function (Drop-In)

```python
def route_model(task_type: str, budget: str = "standard",
                requires_tools: bool = False) -> dict:
    """
    Returns the optimal model config for the given task.
    
    task_type: chat|code|reasoning|embedding|image|audio|tts|summary|classification
    budget:    budget|standard|premium|ultra_premium
    """
    routes = {
        ("code",           "*"):            {"section": "azure_gpt5", "model": "gpt-5.3-codex-global", "api": "responses"},
        ("reasoning",      "ultra_premium"):{"section": "azure_chat", "model": "o3-pro-global", "api": "responses"},
        ("reasoning",      "premium"):      {"section": "azure_chat", "model": "o3-global",     "api": "chat"},
        ("reasoning",      "standard"):     {"section": "azure_chat", "model": "o4-mini-global","api": "chat"},
        ("chat",           "ultra_premium"):{"section": "azure_gpt5", "model": "gpt-5-global",  "api": "chat"},
        ("chat",           "premium"):      {"section": "bedrock",    "model": "us.anthropic.claude-opus-4-8", "api": "converse"},
        ("chat",           "standard"):     {"section": "azure_chat", "model": "gpt-4o-global", "api": "chat"},
        ("chat",           "budget"):       {"section": "azure_chat", "model": "gpt-4o-mini-global", "api": "chat"},
        ("classification", "budget"):       {"section": "azure_chat", "model": "gpt-4.1-nano-global", "api": "chat"},
        ("summary",        "standard"):     {"section": "azure_chat", "model": "gpt-4.1-global", "api": "chat"},
        ("embedding",      "*"):            {"section": "azure_embedding", "model": "text-embedding-3-large", "api": "embedding"},
        ("image",          "*"):            {"section": "azure_image", "model": "gpt-image-2-global", "api": "image"},
        ("tts",            "*"):            {"section": "azure_audio", "model": "gpt-4o-mini-tts-global", "api": "tts"},
        ("transcription",  "*"):            {"section": "azure_audio", "model": "gpt-4o-transcribe-global", "api": "transcription"},
    }
    key = (task_type, budget)
    return routes.get(key, routes.get((task_type, "*"),
                      {"section": "azure_chat", "model": "gpt-4o-global", "api": "chat"}))
```

---

## 10. Configuration Reference

### 10.1 `config.ini` Template

```ini
[azure_chat]
api_key     = <key-from-chat-completion-marketplace-card>
endpoint    = https://genaiapimna.jnj.com/openai-chat
api_version = 2024-12-01-preview

[azure_gpt5]
api_key     = <key-from-gpt5-marketplace-card>
endpoint    = https://genaiapimna.jnj.com/openai-gpt-5
api_version = 2024-10-21

[azure_embedding]
api_key     = <key-from-embedding-marketplace-card>
endpoint    = https://genaiapimna.jnj.com/openai-embeddings
api_version = 2022-12-01

[azure_image]
api_key     = <key-from-image-marketplace-card>
endpoint    = https://genaiapimna.jnj.com/openai-image
api_version = 2024-10-21

[azure_audio]
api_key     = <key-from-audio-marketplace-card>
endpoint    = https://genaiapimna.jnj.com/openai-audio
api_version = 2025-03-01-preview

[bedrock]
api_key     = <key-from-bedrock-marketplace-card>
endpoint    = https://genaiapigwna.jnj.com

[vertex]
api_key     = <key-from-vertex-marketplace-card>
endpoint    = https://genaiapigcpna.jnj.com

[vertex_image]
api_key     = <key-from-vertex-image-marketplace-card>
endpoint    = https://genaiapigcpna.jnj.com
```

### 10.2 Critical API Quirks (Avoid These Mistakes)

| Mistake | Correct Behavior |
|---------|-----------------|
| Using `max_tokens` for GPT-5 | Use `max_completion_tokens` |
| Adding system prompt to o-series | Remove system message for all o* models |
| Calling Codex via chat/completions | Use `/openai/v1/responses` Responses API |
| Using `openai-chat` endpoint for Codex | Use `openai-gpt-5` endpoint for all Codex |
| Using `openai-chat` for audio | Use `openai-audio` with `2025-03-01-preview` |
| Using native AWS credentials for Bedrock | Use dummy credentials + `x-api-key` header |
| Using deployment-path responses URL | Use `/openai/v1/responses`, NOT `/openai/deployments/{model}/responses` |
| Expecting Cohere embed-v4 as list | v4 returns `{"embeddings": {"float": [[...]]}}` — parse as dict |
| Setting Bedrock region to us-east-1 | Use `region_name="dummy"` with RDI gateway |

### 10.3 Required Python Packages

```txt
openai>=1.61.0
boto3>=1.34.0
google-genai>=0.5.0
requests>=2.31.0
```

### 10.4 Environment Setup

```bash
pip install openai boto3 google-genai requests

# Test all 96 models
python test_endpoints.py

# Launch interactive AI assistant
python jnj_agent.py

# One-shot query with specific model
python jnj_agent.py --model claude "Analyze this data..."
python jnj_agent.py --model codex  "Write a merge sort in Python"
python jnj_agent.py --model o3     "Prove P != NP... or try"
```

---

## Appendix: Model Alias Quick Reference

| Alias | Resolves To | Provider |
|-------|------------|---------|
| `gpt4o` | `gpt-4o-global` | Azure Chat |
| `gpt4` | `gpt-4.1-global` | Azure Chat |
| `gpt5` | `gpt-5-global` | Azure GPT-5 |
| `codex` | `gpt-5.3-codex-global` | Azure GPT-5 (Responses API) |
| `o3` | `o3-global` | Azure Chat (Reasoning) |
| `o4` | `o4-mini-global` | Azure Chat (Reasoning) |
| `claude` | `us.anthropic.claude-opus-4-8` | Bedrock |
| `sonnet` | `us.anthropic.claude-sonnet-4-6` | Bedrock |
| `haiku` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock |
| `llama` | `us.meta.llama3-3-70b-instruct-v1:0` | Bedrock |
| `gemini` | `gemini-2.5-pro` | Vertex |
| `flash` | `gemini-2.5-flash` | Vertex |

---

*Last verified: 2026-06-22 | 96/96 models LIVE | Generated by RDI GenAI Test Suite*
