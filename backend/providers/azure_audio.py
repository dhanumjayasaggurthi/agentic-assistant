"""Azure Audio — TTS (gpt-4o-mini-tts-global) + Transcription + Diarization."""
import asyncio
import base64
import io
from typing import Optional

from openai import AsyncAzureOpenAI

from ..config import get_config

_TTS_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
_TTS_MODEL = "gpt-4o-mini-tts-global"
_STT_MODEL = "gpt-4o-transcribe-global"
_STT_DIARIZE = "gpt-4o-transcribe-diarize-global"


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_audio
    if not cfg:
        raise RuntimeError("Azure Audio not configured — add [azure_audio] to config.ini")
    return AsyncAzureOpenAI(
        api_key=cfg.api_key,
        azure_endpoint=cfg.endpoint,
        api_version=cfg.api_version,
    )


async def text_to_speech(text: str, voice: str = "nova", model: str = _TTS_MODEL) -> bytes:
    """Return MP3 audio bytes."""
    if voice not in _TTS_VOICES:
        voice = "nova"
    c = _client()
    resp = await c.audio.speech.create(model=model, voice=voice, input=text)
    return resp.content


async def text_to_speech_b64(text: str, voice: str = "nova") -> str:
    """Return base64-encoded MP3 for WebSocket delivery."""
    audio = await text_to_speech(text, voice)
    return base64.b64encode(audio).decode()


import mimetypes as _mimetypes


async def transcribe(audio_bytes: bytes, filename: str = "audio.webm",
                     diarize: bool = False) -> str:
    """Transcribe audio bytes, optionally with speaker diarization.

    The MIME type is derived from the filename extension so browser-recorded
    webm isn't mislabeled as wav (which the API can reject or mis-decode)."""
    model = _STT_DIARIZE if diarize else _STT_MODEL
    c = _client()
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    mime = _mimetypes.guess_type(filename)[0] or "audio/webm"
    resp = await c.audio.transcriptions.create(
        model=model,
        file=(filename, buf, mime),
    )
    return resp.text or ""
