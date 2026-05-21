"""
CareConnect — LiveKit Video Service

Thin wrapper over the `livekit-api` Python SDK.
Provides synchronous helpers for room creation and join-token generation
to match the existing sync FastAPI codebase.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from livekit import api
from livekit.protocol import egress as egress_pb

from app.config import settings

logger = logging.getLogger(__name__)

# Default token validity: 40 minutes (covers -10min early join + 30min call)
DEFAULT_TOKEN_TTL = timedelta(minutes=40)


# ═══════════════════════════════════════════════════════════════════════
# ROOM MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


def create_room(room_name: str) -> None:
    """
    Create a LiveKit room with sensible defaults.

    LiveKit auto-creates rooms on first join, but calling this explicitly
    lets us set empty_timeout and max_participants up front.
    """

    async def _create():
        async with api.LiveKitAPI(
            url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        ) as lk:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=600,      # 10 min grace if everyone drops
                    max_participants=4,     # Doctor + Patient + Caregiver + buffer
                )
            )

    asyncio.run(_create())


# ═══════════════════════════════════════════════════════════════════════
# TOKEN GENERATION
# ═══════════════════════════════════════════════════════════════════════


def create_join_token(
    room_name: str,
    identity: str,
    name: str,
    ttl: Optional[timedelta] = None,
) -> str:
    """
    Generate a JWT access token that allows a participant to join a room.

    Args:
        room_name:  The LiveKit room to grant access to.
        identity:   Unique participant ID (e.g. user UUID or "patient-<uuid>").
        name:       Human-readable display name shown in the call UI.
        ttl:        Token validity duration. Defaults to 40 minutes.

    Returns:
        A signed JWT string ready for the client SDK.
    """
    token = (
        api.AccessToken(
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
        .with_identity(identity)
        .with_name(name)
        .with_ttl(ttl or DEFAULT_TOKEN_TTL)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
            )
        )
    )

    return token.to_jwt()


# ═══════════════════════════════════════════════════════════════════════
# EGRESS — CALL RECORDING
# ═══════════════════════════════════════════════════════════════════════


def start_room_composite_egress(room_name: str) -> str:
    """
    Start recording a LiveKit room via Room Composite Egress.

    Records audio-only as OGG and uploads to the local MinIO bucket
    (S3-compatible). LiveKit Cloud requires a cloud storage backend
    in EncodedFileOutput — local file paths are rejected.

    When the recording finishes, LiveKit fires an 'egress_ended'
    webhook that our /webhook/livekit endpoint catches.

    Args:
        room_name: The LiveKit room to record (e.g. "cc-<appointment_id>").

    Returns:
        The egress_id for tracking.
    """

    async def _start():
        async with api.LiveKitAPI(
            url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        ) as lk:
            result = await lk.egress.start_room_composite_egress(
                egress_pb.RoomCompositeEgressRequest(
                    room_name=room_name,
                    audio_only=True,
                    file_outputs=[
                        egress_pb.EncodedFileOutput(
                            file_type=egress_pb.EncodedFileType.OGG,
                            filepath=f"{room_name}.ogg",
                            azure=egress_pb.AzureBlobUpload(
                                account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
                                account_key=settings.AZURE_STORAGE_ACCOUNT_KEY,
                                container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
                            ),
                        )
                    ],
                )
            )
            return result.egress_id

    egress_id = asyncio.run(_start())
    logger.info(
        "Started Room Composite Egress for room %s (egress_id: %s)",
        room_name, egress_id,
    )
    return egress_id

