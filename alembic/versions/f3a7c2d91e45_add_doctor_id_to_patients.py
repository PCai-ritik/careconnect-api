"""add_doctor_id_to_patients

Revision ID: f3a7c2d91e45
Revises: 80bfb9544f9d
Create Date: 2026-05-02 08:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a7c2d91e45'
down_revision: Union[str, Sequence[str], None] = '80bfb9544f9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add doctor_id FK to patients table and backfill existing rows."""
    # 1. Add the column (nullable initially for backfill)
    op.add_column('patients', sa.Column('doctor_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_patients_doctor_id',
        'patients', 'doctors',
        ['doctor_id'], ['id'],
    )

    # 2. Backfill: assign all existing patients to the first doctor in the doctors table
    op.execute("""
        UPDATE patients
        SET doctor_id = (SELECT id FROM doctors ORDER BY created_at ASC LIMIT 1)
        WHERE doctor_id IS NULL
    """)


def downgrade() -> None:
    """Remove doctor_id from patients table."""
    op.drop_constraint('fk_patients_doctor_id', 'patients', type_='foreignkey')
    op.drop_column('patients', 'doctor_id')
