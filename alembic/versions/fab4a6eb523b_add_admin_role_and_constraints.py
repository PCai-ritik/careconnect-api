"""add_admin_role_and_constraints

Revision ID: fab4a6eb523b
Revises: 31ec2284c8f2
Create Date: 2026-05-22 10:14:40.474385

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fab4a6eb523b'
down_revision: Union[str, Sequence[str], None] = '31ec2284c8f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add 'ADMIN' to roleenum enum
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE roleenum ADD VALUE IF NOT EXISTS 'ADMIN'")

    # 2. Seed/Update admin@careconnect.com to be SUPER_ADMIN linked to CareConnect default hospital (00000000-0000-4000-8000-000000000001)
    bind = op.get_bind()
    import bcrypt
    pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode("utf-8")

    res = bind.execute(sa.text("SELECT id FROM users WHERE email = 'admin@careconnect.com'")).fetchone()
    if res:
        bind.execute(
            sa.text(
                "UPDATE users SET role = 'SUPER_ADMIN', hospital_id = '00000000-0000-4000-8000-000000000001' WHERE email = 'admin@careconnect.com'"
            )
        )
    else:
        bind.execute(
            sa.text(
                "INSERT INTO users (id, email, password_hash, full_name, role, affiliation_status, is_active, hospital_id) "
                "VALUES ('88888888-8888-4888-8888-888888888888', 'admin@careconnect.com', :pw_hash, 'CareConnect Super Admin', 'SUPER_ADMIN', 'APPROVED', true, '00000000-0000-4000-8000-000000000001')"
            ),
            {"pw_hash": pw_hash}
        )

    # 3. Create unique index idx_unique_admin_per_hospital on users(hospital_id) where role IN ('SUPER_ADMIN', 'ADMIN')
    op.create_index(
        'idx_unique_admin_per_hospital',
        'users',
        ['hospital_id'],
        unique=True,
        postgresql_where=sa.text("role IN ('SUPER_ADMIN', 'ADMIN')")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_unique_admin_per_hospital', table_name='users')
