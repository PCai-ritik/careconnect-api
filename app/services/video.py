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


async def create_room(room_name: str) -> None:
    """
    Create a LiveKit room with sensible defaults.

    LiveKit auto-creates rooms on first join, but calling this explicitly
    lets us set empty_timeout and max_participants up front.
    """
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


async def stop_egress_for_room(room_name: str) -> None:
    """
    Stop all active egress jobs for a room (called when a call ends).

    LiveKit rooms have an empty_timeout, so the room can stay open for
    up to 10 minutes after everyone leaves and the egress would keep
    recording silence against the quota. Calling this immediately on
    end-call tears down the recording straight away.
    """
    async with api.LiveKitAPI(
        url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
    ) as lk:
        from livekit.protocol import egress as egress_pb  # local import to avoid circular
        egresses = await lk.egress.list_egress(
            egress_pb.ListEgressRequest(room_name=room_name, active=True)
        )
        for eg in egresses.items:
            try:
                await lk.egress.stop_egress(
                    egress_pb.StopEgressRequest(egress_id=eg.egress_id)
                )
                logger.info("Stopped egress %s for room %s", eg.egress_id, room_name)
            except Exception as e:
                logger.warning("Could not stop egress %s: %s", eg.egress_id, e)


async def delete_room(room_name: str) -> None:
    """
    Delete a LiveKit room immediately, disconnecting all participants.

    This bypasses the empty_timeout grace period so no further
    compute or egress quota is consumed after the call ends.
    """
    async with api.LiveKitAPI(
        url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
    ) as lk:
        try:
            await lk.room.delete_room(
                api.DeleteRoomRequest(room=room_name)
            )
            logger.info("Deleted LiveKit room %s", room_name)
        except Exception as e:
            logger.warning("Could not delete room %s: %s", room_name, e)


async def start_room_composite_egress(room_name: str) -> str:
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
                        # Azure setup (Temporarily disabled while awaiting credentials)
                        # azure=egress_pb.AzureBlobUpload(
                        #     account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
                        #     account_key=settings.AZURE_STORAGE_ACCOUNT_KEY,
                        #     container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
                        # ),
                        # AWS S3 setup (Active for beta testing)
                        s3=egress_pb.S3Upload(
                            access_key=settings.AWS_ACCESS_KEY_ID,
                            secret=settings.AWS_SECRET_ACCESS_KEY,
                            region=settings.AWS_REGION,
                            bucket=settings.AWS_S3_BUCKET_NAME,
                        ),
                    )
                ],
            )
        )
        logger.info(
            "Started Room Composite Egress for room %s (egress_id: %s)",
            room_name, result.egress_id,
        )
        return result.egress_id

