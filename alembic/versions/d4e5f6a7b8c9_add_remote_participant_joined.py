"""add_remote_participant_joined_to_video_sessions

Revision ID: d4e5f6a7b8c9
Revises: c2d8f9e4a1b3
Create Date: 2026-06-23 17:30:00.000000

Adds remote_participant_joined boolean to video_sessions.
The webhook sets this to True when a non-doctor participant joins the
LiveKit room. The egress_ended handler uses it to skip the AI pipeline
when only the doctor was ever in the room.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c2d8f9e4a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_sessions',
        sa.Column(
            'remote_participant_joined',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('video_sessions', 'remote_participant_joined')
