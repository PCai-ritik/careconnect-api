"""
CareConnect — Transcription Service

Vendor-agnostic adapter for Speech-to-Text.

Supported vendors:
  • sarvam  (primary)  — Sarvam AI Saaras v3, optimised for Indian languages
  • deepgram (future)  — Deepgram Nova-2, Hindi (awaiting API key)

Interface:
  async def generate_transcript(audio_data: bytes, vendor: str = "sarvam") -> str
"""

import time
import logging

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# SARVAM AI — Primary Vendor
# ═══════════════════════════════════════════════════════════════════════

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_MODEL = "saaras:v3"


async def _transcribe_sarvam(audio_data: bytes) -> str:
    """
    Transcribe audio using Sarvam AI's Saaras v3 model.

    Uses the speech-to-text endpoint with multipart/form-data.
    Mode is set to 'transcribe' for original-language output
    (preserving Hindi, Marathi, etc. as spoken by the patient).
    """
    if not settings.SARVAM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SARVAM_API_KEY is not configured.",
        )

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
    }

    # Determine content type from audio — OGG is what our Egress produces
    files = {
        "file": ("recording.ogg", audio_data, "audio/ogg"),
    }

    data = {
        "model": SARVAM_MODEL,
        "language_code": "unknown",  # Auto-detect — supports all Indian languages
        "mode": "transcribe",
    }

    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                SARVAM_STT_URL,
                headers=headers,
                files=files,
                data=data,
            )
    except httpx.TimeoutException:
        logger.error("Sarvam AI STT request timed out")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription service timed out.",
        )
    except Exception as e:
        logger.error("Sarvam AI STT request failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription service error: {e}",
        )

    elapsed = time.perf_counter() - start

    if response.status_code != 200:
        logger.error(
            "Sarvam AI STT returned %d: %s (took %.2fs)",
            response.status_code, response.text, elapsed,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sarvam AI returned HTTP {response.status_code}: {response.text}",
        )

    result = response.json()
    transcript = result.get("transcript", "")

    logger.info(
        "Sarvam AI transcription completed in %.2fs — %d chars",
        elapsed, len(transcript),
    )

    return transcript


# ═══════════════════════════════════════════════════════════════════════
# DEEPGRAM — Future Vendor (awaiting API key)
# ═══════════════════════════════════════════════════════════════════════


async def _transcribe_deepgram(audio_data: bytes) -> str:
    """
    Transcribe audio using Deepgram's Nova-2 model.

    Uses the deepgram-sdk for prerecorded transcription with
    Hindi language detection and smart formatting.

    Currently stubbed — will be activated once DEEPGRAM_API_KEY is obtained.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DEEPGRAM_API_KEY is not configured. "
                   "Deepgram transcription is not yet available.",
        )

    from deepgram import DeepgramClient, PrerecordedOptions

    start = time.perf_counter()

    try:
        client = DeepgramClient(settings.DEEPGRAM_API_KEY)

        source = {"buffer": audio_data, "mimetype": "audio/ogg"}
        options = PrerecordedOptions(
            model="nova-2",
            language="hi",
            smart_format=True,
        )

        response = await client.listen.asyncrest.v("1").transcribe_file(
            source, options
        )

        transcript = (
            response.results.channels[0].alternatives[0].transcript
        )

    except Exception as e:
        logger.error("Deepgram STT request failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deepgram transcription error: {e}",
        )

    elapsed = time.perf_counter() - start

    logger.info(
        "Deepgram transcription completed in %.2fs — %d chars",
        elapsed, len(transcript),
    )

    return transcript


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ═══════════════════════════════════════════════════════════════════════

# Vendor dispatch table
_VENDORS = {
    "sarvam": _transcribe_sarvam,
    "deepgram": _transcribe_deepgram,
}


async def generate_transcript(
    audio_data: bytes,
    vendor: str = "sarvam",
) -> str:
    """
    Generate a text transcript from audio data.

    Args:
        audio_data: Raw audio bytes (e.g. OGG from LiveKit Egress).
        vendor:     STT vendor to use. One of 'sarvam' (default) or 'deepgram'.

    Returns:
        The transcribed text as a string.

    Raises:
        HTTPException(500) if the STT vendor fails or is not configured.
        HTTPException(400) if an unknown vendor is requested.
    """
    if not audio_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No audio data provided for transcription.",
        )

    handler = _VENDORS.get(vendor)
    if not handler:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown transcription vendor: '{vendor}'. "
                   f"Supported: {list(_VENDORS.keys())}",
        )

    logger.info("Starting transcription with vendor '%s' (%d bytes)", vendor, len(audio_data))
    return await handler(audio_data)
