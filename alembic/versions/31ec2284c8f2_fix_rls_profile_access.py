"""fix_rls_profile_access

Revision ID: 31ec2284c8f2
Revises: 3bed83b18c3f
Create Date: 2026-05-21 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31ec2284c8f2'
down_revision: Union[str, Sequence[str], None] = '3bed83b18c3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing doctor and caregiver RLS policies
    op.execute("DROP POLICY IF EXISTS doctor_access ON doctors;")
    op.execute("DROP POLICY IF EXISTS caregiver_access ON caregivers;")

    # Recreate doctor_access policy with user_id bypass
    op.execute("""
        CREATE POLICY doctor_access ON doctors FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = doctors.user_id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
            ) OR doctors.user_id = current_setting('app.current_user_id', true)::uuid
        );
    """)

    # Recreate caregiver_access policy with user_id bypass
    op.execute("""
        CREATE POLICY caregiver_access ON caregivers FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = caregivers.user_id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
            ) OR caregivers.user_id = current_setting('app.current_user_id', true)::uuid
        );
    """)


def downgrade() -> None:
    # Drop updated doctor and caregiver RLS policies
    op.execute("DROP POLICY IF EXISTS doctor_access ON doctors;")
    op.execute("DROP POLICY IF EXISTS caregiver_access ON caregivers;")

    # Recreate original doctor_access policy
    op.execute("""
        CREATE POLICY doctor_access ON doctors FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = doctors.user_id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
            )
        );
    """)

    # Recreate original caregiver_access policy
    op.execute("""
        CREATE POLICY caregiver_access ON caregivers FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = caregivers.user_id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
            )
        );
    """)
