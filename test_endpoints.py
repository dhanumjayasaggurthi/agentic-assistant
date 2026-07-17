"""
GenAI API Marketplace — Full Model Test Suite
==============================================
Tests all 110 models across 8 separate marketplace cards / endpoints.

Setup:
    pip install openai boto3 google-genai
    Fill every section in config.ini with endpoint + API key from each card, then:
    python test_endpoints.py

Outputs (written to current directory):
    test_run_<ts>.log          Full debug trace
    test_report_<ts>.txt       Human-readable summary table
    test_report_<ts>.json      Machine-readable results
"""

import configparser, dataclasses, io, json, logging, math, struct, sys, time, wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ── Logging ────────────────────────────────────────────────────────────────────
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(f"test_run_{_TS}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("genai_test")

# ── Test prompts ───────────────────────────────────────────────────────────────
CHAT_PROMPT   = "In one sentence, what makes Python popular for AI development?"
CODE_PROMPT   = "Write a Python one-liner to flatten [[1,2],[3,4]] into [1,2,3,4]."
REASON_PROMPT = "If x=5 and y=x*2+1, what is y? Show reasoning in one line."
EMBED_INPUT   = "def count_lines(path): return sum(1 for l in open(path) if l.strip())"
IMAGE_PROMPT  = "A simple blue circle logo on a white background, flat minimal design"
TTS_TEXT      = "Hello, this is a connectivity test for the text to speech system."


# ── Model registry ─────────────────────────────────────────────────────────────
#
# Each entry: (capability, model_id)
# Capabilities:
#   chat          → Chat Completion (system + user messages, max_tokens)
#   codex         → Same API as chat but CODE_PROMPT
#   reasoning     → No system msg, max_completion_tokens (o-series)
#   embedding     → client.embeddings.create
#   image_gen     → client.images.generate
#   tts           → client.audio.speech.create
#   transcription → client.audio.transcriptions.create
#   bedrock_chat  → Bedrock Converse API
#   bedrock_embed_titan  → Bedrock InvokeModel (Titan format)
#   bedrock_embed_cohere → Bedrock InvokeModel (Cohere format)
#   vertex_chat   → Gemini generate_content (text)
#   vertex_image  → Gemini generate_content (IMAGE modality)

AZURE_CHAT_MODELS = [
    ("chat", "gpt-35-turbo"),
    ("chat", "gpt-35-turbo-16k"),
    ("chat", "gpt-35-turbo-0301"),
    ("chat", "gpt-4"),
    ("chat", "gpt-4-32k"),
    ("chat", "gpt-4-turbo-preview"),
    ("chat", "gpt-4-turbo"),
    ("chat", "gpt-4o"),
    ("chat", "gpt-4o-global"),
    ("chat", "gpt-4o-mini"),
    ("chat", "gpt-4o-mini-global"),
    ("chat", "gpt-4.1"),
    ("chat", "gpt-4.1-global"),
    ("chat", "gpt-4.1-mini"),
    ("chat", "gpt-4.1-mini-global"),
    ("chat", "gpt-4.1-nano"),
    ("chat", "gpt-4.1-nano-global"),
    ("reasoning", "o1-mini-global"),
    ("reasoning", "o1-global"),
    ("reasoning", "o1"),
    ("reasoning", "o3-mini"),
    ("reasoning", "o3-mini-global"),
    ("reasoning", "o3"),           # moved from azure_gpt5 — wrong endpoint there
    ("reasoning", "o3-global"),
    ("responses", "o3-pro-global"),   # Responses API via /openai/v1/responses
    # gpt-5.3-codex-global → moved to azure_gpt5 (/openai/v1/responses only on gpt-5 endpoint)
    ("reasoning", "o4-mini"),
    ("reasoning", "o4-mini-global"),
]

AZURE_EMBEDDING_MODELS = [
    ("embedding", "text-embedding-ada-002"),
    ("embedding", "text-embedding-3-small"),
    ("embedding", "text-embedding-3-large"),
]

AZURE_IMAGE_MODELS = [
    ("image_gen", "gpt-image-1-global"),
    ("image_gen", "gpt-image-1-mini-global"),
    ("image_gen", "gpt-image-1.5-global"),
    ("image_gen", "gpt-image-2-global"),
]

AZURE_AUDIO_MODELS = [
    ("tts",           "gpt-4o-mini-tts-global"),
    ("transcription", "gpt-4o-transcribe-global"),
    ("transcription", "gpt-4o-mini-transcribe-global"),
    ("transcription", "gpt-4o-transcribe-diarize-global"),
]

# Legacy text-completion API — gpt-35-turbo-instruct returned 410 ModelDeprecated.
# Leaving list empty; update if a replacement is deployed.
AZURE_COMPLETION_MODELS = []

AZURE_GPT5_MODELS = [
    # All GPT-5 models require max_completion_tokens (see main — token_param override)
    ("chat",  "gpt-5"),
    ("chat",  "gpt-5-global"),
    ("chat",  "gpt-5-mini"),
    ("chat",  "gpt-5-mini-global"),
    ("chat",  "gpt-5-nano"),
    ("chat",  "gpt-5-nano-global"),
    ("chat",  "gpt-5-chat-global"),
    ("codex", "gpt-5-pro-global"),   # needs Responses API via /openai/v1/responses
    ("chat",  "gpt-5.2"),
    # gpt-5.2-chat        → 404 not found (not yet deployed)
    ("chat",  "gpt-5.3-chat-global"),
    ("chat",  "gpt-5.4"),
    ("chat",  "gpt-5.4-global"),
    # gpt-5.4-pro-global  → skipped (untested; verify from marketplace card)
    ("chat",  "gpt-5.4-mini-global"),
    ("chat",  "gpt-5.4-nano"),
    ("chat",  "gpt-5.4-nano-global"),
    ("chat",  "gpt-5.5"),
    ("chat",  "gpt-5.5-global"),
    # Codex models — use /openai/v1/responses (v1 format, not Azure deployment path)
    ("codex", "gpt-5-codex-global"),
    ("codex", "gpt-5.1-codex-global"),
    ("codex", "gpt-5.1-codex-mini-global"),
    ("codex", "gpt-5.1-codex-max-global"),
    ("codex", "gpt-5.2-codex-global"),
    ("codex", "gpt-5.3-codex-global"),  # listed under Chat Completion card but needs gpt-5 endpoint
    # o3/o3-global/o3-pro-global → moved to azure_chat (correct endpoint)
]

BEDROCK_MODELS = [
    # Claude — Converse API
    # v3 EOL removed: claude-3-5-sonnet-v1, 3-5-sonnet-v2, 3-5-haiku, 3-7-sonnet, 3-opus, v2, instant
    ("bedrock_chat", "anthropic.claude-3-haiku-20240307-v1:0"),
    ("bedrock_chat", "anthropic.claude-3-sonnet-20240229-v1:0"),
    ("bedrock_chat", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
    ("bedrock_chat", "global.anthropic.claude-sonnet-4-20250514-v1:0"),
    # claude-opus-4-20250514 EOL removed
    ("bedrock_chat", "us.anthropic.claude-opus-4-1-20250805-v1:0"),
    ("bedrock_chat", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("bedrock_chat", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("bedrock_chat", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("bedrock_chat", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("bedrock_chat", "us.anthropic.claude-opus-4-5-20251101-v1:0"),
    ("bedrock_chat", "global.anthropic.claude-opus-4-5-20251101-v1:0"),
    ("bedrock_chat", "us.anthropic.claude-opus-4-6-v1"),
    ("bedrock_chat", "global.anthropic.claude-opus-4-6-v1"),
    ("bedrock_chat", "us.anthropic.claude-sonnet-4-6"),
    ("bedrock_chat", "global.anthropic.claude-sonnet-4-6"),
    ("bedrock_chat", "us.anthropic.claude-opus-4-7"),
    ("bedrock_chat", "global.anthropic.claude-opus-4-7"),
    ("bedrock_chat", "us.anthropic.claude-opus-4-8"),
    ("bedrock_chat", "global.anthropic.claude-opus-4-8"),
    # Meta Llama — Converse API (1b/3b removed — legacy, access denied)
    ("bedrock_chat", "us.meta.llama3-2-11b-instruct-v1:0"),
    ("bedrock_chat", "us.meta.llama3-2-90b-instruct-v1:0"),
    ("bedrock_chat", "us.meta.llama3-3-70b-instruct-v1:0"),
    # Amazon Titan Text — EOL removed (express-v1, lite-v1)
    # Cohere Command — Converse API
    ("bedrock_chat", "cohere.command-r-v1:0"),
    ("bedrock_chat", "cohere.command-r-plus-v1:0"),
    # Amazon Titan Embeddings — InvokeModel
    ("bedrock_embed_titan", "amazon.titan-embed-text-v1"),
    ("bedrock_embed_titan", "amazon.titan-embed-text-v2:0"),
    ("bedrock_embed_titan", "amazon.titan-embed-image-v1"),
    # Cohere Embeddings — InvokeModel (v4 uses different response shape — handled below)
    ("bedrock_embed_cohere", "cohere.embed-english-v3"),
    ("bedrock_embed_cohere", "cohere.embed-multilingual-v3"),
    ("bedrock_embed_cohere", "us.cohere.embed-v4:0"),
    ("bedrock_embed_cohere", "global.cohere.embed-v4:0"),
]

VERTEX_CHAT_MODELS = [
    ("vertex_chat", "gemini-2.5-flash-lite"),
    ("vertex_chat", "gemini-2.5-flash"),
    ("vertex_chat", "gemini-2.5-pro"),
]

VERTEX_IMAGE_MODELS = [
    ("vertex_image", "gemini-2.5-flash-image"),
]


# ── Result dataclass ───────────────────────────────────────────────────────────
@dataclass
class Result:
    provider:   str
    capability: str
    model:      str
    status:     str    # PASS | FAIL | SKIP
    latency_s:  float = 0.0
    tokens:     int   = 0
    preview:    str   = ""
    error:      str   = ""


# ── Helpers ────────────────────────────────────────────────────────────────────
def _pass(provider, cap, model, t0, text, tokens=0) -> Result:
    lat = round(time.time() - t0, 2)
    log.info(f"  PASS  {provider} / {model}  {lat}s  {tokens}tok")
    return Result(provider, cap, model, "PASS", lat, tokens,
                  str(text)[:200].replace("\n", " "))


def _fail(provider, cap, model, t0, exc) -> Result:
    lat = round(time.time() - t0, 2)
    msg = str(exc)[:300]
    log.error(f"  FAIL  {provider} / {model}  {lat}s  {msg}")
    return Result(provider, cap, model, "FAIL", lat, error=msg)


def _skips(provider, model_list, reason="API key / endpoint not configured") -> list[Result]:
    log.warning(f"  SKIP  [{provider}]  {reason}")
    return [Result(provider, cap, m, "SKIP", error=reason) for cap, m in model_list]


def _placeholder(val: str) -> bool:
    return not val or val.upper().startswith("YOUR_")


def _get(cfg, section, key, fallback=""):
    return cfg.get(section, key, fallback=fallback) if cfg.has_section(section) else fallback


# ── Minimal WAV for transcription tests ───────────────────────────────────────
def _make_wav() -> io.BytesIO:
    sr, freq, secs = 16000, 440, 1
    samples = [int(32767 * math.sin(2 * math.pi * freq * i / sr))
               for i in range(sr * secs)]
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    buf.seek(0)
    buf.name = "test.wav"
    return buf


# ══════════════════════════════════════════════════════════════════════════════
#  AZURE — shared AzureOpenAI client factory
# ══════════════════════════════════════════════════════════════════════════════
def _az_client(api_key, endpoint, api_version):
    from openai import AzureOpenAI
    return AzureOpenAI(api_key=api_key, azure_endpoint=endpoint,
                       api_version=api_version)


def _az_chat_call(client, model, prompt, token_param="max_tokens"):
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user",   "content": prompt},
        ],
        **{token_param: 150},
    )
    return resp.choices[0].message.content or "", \
           (resp.usage.total_tokens if resp.usage else 0)


def _az_reasoning_call(client, model):
    # o-series: no system prompt, use max_completion_tokens
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": REASON_PROMPT}],
        max_completion_tokens=150,
    )
    return resp.choices[0].message.content or "", \
           (resp.usage.total_tokens if resp.usage else 0)


def _az_responses_call(api_key, endpoint, model, prompt):
    # RDI gateway exposes Responses API at /openai/v1/responses (v1 format),
    # NOT the Azure deployment-specific /openai/deployments/{model}/responses path.
    import requests as _req
    url  = f"{endpoint.rstrip('/')}/openai/v1/responses"
    hdrs = {"api-key": api_key, "Content-Type": "application/json"}
    body = {"model": model, "input": prompt, "max_output_tokens": 500}
    r = _req.post(url, headers=hdrs, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    text = ""
    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                text += part.get("text", "")
    return text or f"status={data.get('status', 'ok')}", 0


def _az_embed_call(client, model):
    resp = client.embeddings.create(model=model, input=EMBED_INPUT)
    dims = len(resp.data[0].embedding)
    return f"dims={dims}", 0


def _az_image_call(client, model):
    resp = client.images.generate(
        model=model, prompt=IMAGE_PROMPT, n=1, size="1024x1024",
    )
    item = resp.data[0]
    if getattr(item, "url", None):
        return f"url_len={len(item.url)}", 0
    if getattr(item, "b64_json", None):
        return f"b64={len(item.b64_json)//1024}KB", 0
    return "image_received", 0


def _az_completion_call(client, model):
    # Legacy completions endpoint — different API from chat.completions
    resp = client.completions.create(
        model=model,
        prompt=CHAT_PROMPT,
        max_tokens=100,
    )
    text   = resp.choices[0].text or ""
    tokens = resp.usage.total_tokens if resp.usage else 0
    return text, tokens


def _az_tts_call(client, model):
    resp = client.audio.speech.create(
        model=model, voice="alloy", input=TTS_TEXT,
    )
    return f"audio={len(resp.content)}B", 0


def _az_transcription_call(client, model):
    wav = _make_wav()
    resp = client.audio.transcriptions.create(
        model=model,
        file=("test.wav", wav, "audio/wav"),
    )
    return resp.text or "transcription_ok", 0


# ── Generic Azure runner ───────────────────────────────────────────────────────
def test_azure_section(cfg, section: str, label: str,
                       model_list: list,
                       token_param: str = "max_tokens") -> list[Result]:
    """
    Run every (capability, model) in model_list using the given config section.
    """
    if not cfg.has_section(section):
        log.warning(f"[{label}] Section '{section}' missing in config.ini — skipping")
        return _skips(label, model_list, f"Section [{section}] missing")

    api_key     = cfg[section].get("api_key",  "")
    endpoint    = cfg[section].get("endpoint", "")
    api_version = cfg[section].get("api_version", "2024-10-21")

    if _placeholder(api_key) or _placeholder(endpoint):
        return _skips(label, model_list,
                      f"API key or endpoint not set in [{section}]")

    try:
        from openai import AzureOpenAI  # noqa: ensure import works before loop
    except ImportError:
        log.error("openai not installed — pip install openai")
        return _skips(label, model_list, "openai package not installed")

    client = _az_client(api_key, endpoint, api_version)
    log.info(f"[{label}] endpoint={endpoint}  models={len(model_list)}")

    results = []
    for cap, model in model_list:
        log.info(f"[{label}] {cap} / {model} ...")
        t0 = time.time()
        try:
            if cap == "chat":
                text, tok = _az_chat_call(client, model, CHAT_PROMPT, token_param)
            elif cap == "codex":
                text, tok = _az_responses_call(api_key, endpoint, model, CODE_PROMPT)
            elif cap == "responses":
                text, tok = _az_responses_call(api_key, endpoint, model, REASON_PROMPT)
            elif cap == "reasoning":
                text, tok = _az_reasoning_call(client, model)
            elif cap == "embedding":
                text, tok = _az_embed_call(client, model)
            elif cap == "image_gen":
                text, tok = _az_image_call(client, model)
            elif cap == "tts":
                text, tok = _az_tts_call(client, model)
            elif cap == "transcription":
                text, tok = _az_transcription_call(client, model)
            elif cap == "completion":
                text, tok = _az_completion_call(client, model)
            else:
                text, tok = _az_chat_call(client, model, CHAT_PROMPT)

            results.append(_pass(label, cap, model, t0, text, tok))
        except Exception as e:
            results.append(_fail(label, cap, model, t0, e))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  AMAZON BEDROCK
# ══════════════════════════════════════════════════════════════════════════════
def test_bedrock(cfg) -> list[Result]:
    section = "bedrock"
    label   = "Bedrock"

    if not cfg.has_section(section):
        log.warning("[Bedrock] Section missing — skipping all Bedrock models")
        return _skips(label, BEDROCK_MODELS, "Section [bedrock] missing")

    api_key  = cfg[section].get("api_key",  "")
    endpoint = cfg[section].get("endpoint", "")

    if _placeholder(api_key) or _placeholder(endpoint):
        return _skips(label, BEDROCK_MODELS, "API key or endpoint not set in [bedrock]")

    try:
        import boto3
    except ImportError:
        log.error("boto3 not installed — pip install boto3")
        return _skips(label, BEDROCK_MODELS, "boto3 not installed")

    session = boto3.Session(aws_access_key_id="dummy", aws_secret_access_key="dummy")
    client  = session.client("bedrock-runtime", endpoint_url=endpoint, region_name="dummy")

    # Inject the marketplace API key for both Converse and InvokeModel calls
    def _inject(model, params, request_signer, **kwargs):
        params["headers"]["x-api-key"] = api_key

    client.meta.events.register("before-call.bedrock-runtime.Converse",    _inject)
    client.meta.events.register("before-call.bedrock-runtime.InvokeModel", _inject)
    log.info(f"[Bedrock] endpoint={endpoint}  models={len(BEDROCK_MODELS)}")

    results = []
    for cap, model in BEDROCK_MODELS:
        log.info(f"[Bedrock] {cap} / {model} ...")
        t0 = time.time()
        try:
            if cap == "bedrock_chat":
                resp = client.converse(
                    modelId=model,
                    messages=[{"role": "user",
                               "content": [{"text": CHAT_PROMPT}]}],
                )
                text   = resp["output"]["message"]["content"][0]["text"]
                usage  = resp.get("usage", {})
                tokens = usage.get("inputTokens", 0) + usage.get("outputTokens", 0)
                results.append(_pass(label, cap, model, t0, text, tokens))

            elif cap == "bedrock_embed_titan":
                body = json.dumps({"inputText": EMBED_INPUT})
                resp = client.invoke_model(
                    modelId=model, body=body,
                    accept="application/json",
                    contentType="application/json",
                )
                payload = json.loads(resp["body"].read())
                dims = len(payload.get("embedding", []))
                results.append(_pass(label, cap, model, t0, f"dims={dims}"))

            elif cap == "bedrock_embed_cohere":
                body = json.dumps({
                    "texts": [EMBED_INPUT],
                    "input_type": "search_query",
                })
                resp = client.invoke_model(
                    modelId=model, body=body,
                    accept="application/json",
                    contentType="application/json",
                )
                payload = json.loads(resp["body"].read())
                embs_raw = payload.get("embeddings", [])
                if isinstance(embs_raw, dict):
                    # Cohere embed v4 response: {"float": [[...]], "int8": [[...]]}
                    inner = embs_raw.get("float") or embs_raw.get("int8") or [[]]
                    dims = len(inner[0]) if inner else 0
                else:
                    # Cohere embed v3 response: [[...]]
                    dims = len(embs_raw[0]) if embs_raw else 0
                results.append(_pass(label, cap, model, t0, f"dims={dims}"))

        except Exception as e:
            results.append(_fail(label, cap, model, t0, e))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  GOOGLE VERTEX AI — Chat
# ══════════════════════════════════════════════════════════════════════════════
def _vertex_client(api_key, endpoint):
    from google import genai
    from google.auth.credentials import Credentials
    from google.genai.types import HttpOptions

    class _Creds(Credentials):
        def refresh(self, request):
            self.token  = "dummy-token"
            self.expiry = None

    return genai.Client(
        vertexai=True, project="dummy", location="dummy",
        http_options=HttpOptions(
            api_version="v1",
            base_url=endpoint,
            headers={"x-api-key": api_key},
        ),
        credentials=_Creds(),
    )


def test_vertex_chat(cfg) -> list[Result]:
    section = "vertex"
    label   = "Vertex AI"

    if not cfg.has_section(section):
        log.warning("[Vertex AI] Section missing — skipping")
        return _skips(label, VERTEX_CHAT_MODELS, "Section [vertex] missing")

    api_key  = cfg[section].get("api_key",  "")
    endpoint = cfg[section].get("endpoint", "")

    if _placeholder(api_key) or _placeholder(endpoint):
        return _skips(label, VERTEX_CHAT_MODELS,
                      "API key or endpoint not set in [vertex]")

    try:
        from google import genai  # noqa
    except ImportError:
        log.error("google-genai not installed — pip install google-genai")
        return _skips(label, VERTEX_CHAT_MODELS, "google-genai not installed")

    client = _vertex_client(api_key, endpoint)
    log.info(f"[Vertex AI] endpoint={endpoint}  models={len(VERTEX_CHAT_MODELS)}")

    results = []
    for cap, model in VERTEX_CHAT_MODELS:
        log.info(f"[Vertex AI] {cap} / {model} ...")
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=model, contents=CHAT_PROMPT)
            results.append(_pass(label, cap, model, t0, resp.text or ""))
        except Exception as e:
            results.append(_fail(label, cap, model, t0, e))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  GOOGLE VERTEX AI — Image  (separate card, separate key)
#  Uses raw HTTP exactly as shown in the marketplace sample code:
#  POST {endpoint}/v1/projects/GenAI/locations/us-east1/publishers/google/models/{model}:generateContent
# ══════════════════════════════════════════════════════════════════════════════
def test_vertex_image(cfg) -> list[Result]:
    section = "vertex_image"
    label   = "Vertex Image"

    if not cfg.has_section(section):
        log.warning("[Vertex Image] Section missing — skipping")
        return _skips(label, VERTEX_IMAGE_MODELS, "Section [vertex_image] missing")

    api_key  = cfg[section].get("api_key",  "")
    endpoint = cfg[section].get("endpoint", "").rstrip("/")

    if _placeholder(api_key) or _placeholder(endpoint):
        return _skips(label, VERTEX_IMAGE_MODELS,
                      "API key or endpoint not set in [vertex_image]")

    try:
        import requests as _req
    except ImportError:
        log.error("requests not installed — pip install requests")
        return _skips(label, VERTEX_IMAGE_MODELS, "requests package not installed")

    headers = {
        "content-type": "application/json",
        "accept":        "application/json",
        "x-api-key":     api_key,
    }
    log.info(f"[Vertex Image] endpoint={endpoint}  models={len(VERTEX_IMAGE_MODELS)}")

    results = []
    for cap, model in VERTEX_IMAGE_MODELS:
        log.info(f"[Vertex Image] {cap} / {model} ...")
        t0  = time.time()
        url = (f"{endpoint}/v1/projects/GenAI/locations/us-east1"
               f"/publishers/google/models/{model}:generateContent")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": IMAGE_PROMPT}],
                }
            ],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }
        try:
            resp = _req.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data      = resp.json()
            parts     = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            has_img   = any("inlineData" in p for p in parts)
            has_text  = any("text" in p for p in parts)
            preview   = f"image={has_img}  text={has_text}  parts={len(parts)}"
            results.append(_pass(label, cap, model, t0, preview))
        except Exception as e:
            results.append(_fail(label, cap, model, t0, e))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT
# ══════════════════════════════════════════════════════════════════════════════
_CAP_LABEL = {
    "chat":               "Chat",
    "codex":              "Codex (Resp API)",
    "responses":          "Responses API",
    "reasoning":          "Reasoning",
    "embedding":          "Embedding",
    "image_gen":          "Image Gen",
    "completion":         "Completion (legacy)",
    "tts":                "TTS",
    "transcription":      "Transcription",
    "bedrock_chat":       "Chat",
    "bedrock_embed_titan": "Embedding",
    "bedrock_embed_cohere":"Embedding",
    "vertex_chat":        "Chat",
    "vertex_image":       "Image Gen",
}

_W  = 105
_DIV = "=" * _W
_SEP = "-" * _W
_HDR = (f"  {'Provider':<16} {'Capability':<14} "
        f"{'Model':<46} {'Status':<6} {'Latency':>8}  {'Tokens':>7}")


def write_report(results: list[Result]) -> None:
    passed  = [r for r in results if r.status == "PASS"]
    failed  = [r for r in results if r.status == "FAIL"]
    skipped = [r for r in results if r.status == "SKIP"]

    # Group by provider
    by_provider: dict[str, list[Result]] = {}
    for r in results:
        by_provider.setdefault(r.provider, []).append(r)

    lines = [
        "",
        _DIV,
        "  GENAI API MARKETPLACE — FULL MODEL TEST REPORT",
        f"  Timestamp  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Total      : {len(results)}   "
        f"PASS: {len(passed)}   FAIL: {len(failed)}   SKIP: {len(skipped)}",
        _DIV,
        "",
        "  PROVIDER SUMMARY",
        _SEP,
        f"  {'Provider':<22} {'Total':>6} {'PASS':>6} {'FAIL':>6} {'SKIP':>6}",
        _SEP,
    ]
    for prov, rs in by_provider.items():
        p = sum(1 for r in rs if r.status == "PASS")
        f = sum(1 for r in rs if r.status == "FAIL")
        s = sum(1 for r in rs if r.status == "SKIP")
        lines.append(f"  {prov:<22} {len(rs):>6} {p:>6} {f:>6} {s:>6}")
    lines += [_SEP, "", "  FULL RESULTS TABLE", _HDR, _SEP]

    for prov, rs in by_provider.items():
        for r in rs:
            cap = _CAP_LABEL.get(r.capability, r.capability)
            lat = f"{r.latency_s:.2f}s" if r.latency_s else "—"
            tok = str(r.tokens) if r.tokens else "—"
            lines.append(
                f"  {r.provider:<16} {cap:<14} {r.model:<46} "
                f"{r.status:<6} {lat:>8}  {tok:>7}"
            )
        lines.append(_SEP)

    if failed:
        lines += ["", "  FAILURE DETAILS", _SEP]
        for r in failed:
            lines.append(f"  [{r.provider}] {r.model}")
            lines.append(f"    {r.error}")
        lines.append(_SEP)

    if passed:
        lines += ["", "  RESPONSE PREVIEWS (PASS only)", _SEP]
        for r in passed:
            cap = _CAP_LABEL.get(r.capability, r.capability)
            lines.append(f"  [{r.provider}] {cap} / {r.model}")
            lines.append(f"    {r.preview}")
        lines.append(_SEP)

    lines.append("")
    report = "\n".join(lines)
    log.info(report)

    txt_path  = f"test_report_{_TS}.txt"
    json_path = f"test_report_{_TS}.json"
    Path(txt_path).write_text(report, encoding="utf-8")
    Path(json_path).write_text(
        json.dumps({
            "timestamp": _TS,
            "summary": {
                "total":   len(results),
                "passed":  len(passed),
                "failed":  len(failed),
                "skipped": len(skipped),
            },
            "results": [dataclasses.asdict(r) for r in results],
        }, indent=2),
        encoding="utf-8",
    )
    log.info(f"Text report → {txt_path}")
    log.info(f"JSON report → {json_path}")
    log.info(f"Debug log   → test_run_{_TS}.log")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info(_DIV)
    log.info("GenAI API Marketplace — Full Test Suite")
    total = (len(AZURE_CHAT_MODELS) + len(AZURE_COMPLETION_MODELS) +
             len(AZURE_EMBEDDING_MODELS) + len(AZURE_IMAGE_MODELS) +
             len(AZURE_AUDIO_MODELS) + len(AZURE_GPT5_MODELS) +
             len(BEDROCK_MODELS) + len(VERTEX_CHAT_MODELS) +
             len(VERTEX_IMAGE_MODELS))
    log.info(f"Total models to test: {total}")
    log.info(f"  Azure Chat:          {len(AZURE_CHAT_MODELS)}")
    log.info(f"  Azure Completion:    {len(AZURE_COMPLETION_MODELS)}  (legacy)")
    log.info(f"  Azure Embedding:     {len(AZURE_EMBEDDING_MODELS)}")
    log.info(f"  Azure Image Gen:     {len(AZURE_IMAGE_MODELS)}")
    log.info(f"  Azure Audio:         {len(AZURE_AUDIO_MODELS)}")
    log.info(f"  Azure GPT-5/Codex:   {len(AZURE_GPT5_MODELS)}")
    log.info(f"  Bedrock:             {len(BEDROCK_MODELS)}")
    log.info(f"  Vertex Chat:         {len(VERTEX_CHAT_MODELS)}")
    log.info(f"  Vertex Image:        {len(VERTEX_IMAGE_MODELS)}")
    log.info(_DIV)

    cfg = configparser.ConfigParser()
    cfg.read("config.ini")
    if not cfg.sections():
        log.error("config.ini not found or empty — aborting.")
        sys.exit(1)

    all_results: list[Result] = []

    # Azure Chat (gpt-35/4/4o/4.1 + o1/o3-mini/o4)  →  [azure_chat]
    all_results += test_azure_section(
        cfg, "azure_chat", "Azure Chat", AZURE_CHAT_MODELS)

    # Azure Completion legacy (gpt-35-turbo-instruct)  →  [azure_completion]
    all_results += test_azure_section(
        cfg, "azure_completion", "Azure Completion", AZURE_COMPLETION_MODELS)

    # Azure Embedding (text-embedding-*)  →  [azure_embedding]  api_version=2022-12-01
    all_results += test_azure_section(
        cfg, "azure_embedding", "Azure Embedding", AZURE_EMBEDDING_MODELS)

    # Azure Image Generation (gpt-image-*)  →  [azure_image]
    all_results += test_azure_section(
        cfg, "azure_image", "Azure Image", AZURE_IMAGE_MODELS)

    # Azure Audio TTS + Transcription  →  [azure_audio]  (same base as openai-chat, diff key)
    all_results += test_azure_section(
        cfg, "azure_audio", "Azure Audio", AZURE_AUDIO_MODELS)

    # Azure GPT-5  →  [azure_gpt5]  (max_completion_tokens required for all GPT-5 models)
    all_results += test_azure_section(
        cfg, "azure_gpt5", "Azure GPT-5", AZURE_GPT5_MODELS,
        token_param="max_completion_tokens")

    # Amazon Bedrock (all models share one endpoint)  →  [bedrock] section
    all_results += test_bedrock(cfg)

    # Google Vertex AI chat  →  [vertex] section
    all_results += test_vertex_chat(cfg)

    # Google Vertex AI image  →  [vertex_image] section  (separate card!)
    all_results += test_vertex_image(cfg)

    write_report(all_results)
