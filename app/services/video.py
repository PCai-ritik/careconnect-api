"""
CareConnect — LiveKit Video Service

Thin wrapper over the `livekit-api` Python SDK.
Provides synchronous helpers for room creation and join-token generation
to match the existing sync FastAPI codebase.
"""

import asyncio
from datetime import timedelta
from typing import Optional

from livekit import api

from app.config import settings


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
