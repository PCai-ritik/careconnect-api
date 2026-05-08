"""nullable_caregiver_on_appointments

Revision ID: a1b2c3d4e5f6
Revises: 80bfb9544f9d
Create Date: 2026-05-03 10:15:00.000000

Allow appointments to be created without a caregiver.
Doctor-added patients don't have caregivers; the follow-up
appointment flow needs this to work.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f3a7c2d91e45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make caregiver_id nullable on appointments."""
    op.alter_column(
        'appointments',
        'caregiver_id',
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    """Revert caregiver_id to NOT NULL."""
    op.alter_column(
        'appointments',
        'caregiver_id',
        existing_type=sa.Uuid(),
        nullable=False,
    )
