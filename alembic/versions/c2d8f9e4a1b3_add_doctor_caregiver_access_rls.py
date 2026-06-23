"""add_doctor_caregiver_access_rls

Revision ID: c2d8f9e4a1b3
Revises: e74120d1fb31
Create Date: 2026-06-23 13:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d8f9e4a1b3'
down_revision: Union[str, Sequence[str], None] = 'e74120d1fb31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add RLS policies for caregiver access to doctor profiles.
    
    DEFENSE-IN-DEPTH SECURITY:
    - Database level: RLS policies prevent caregivers from seeing all doctors
    - Application level: FastAPI endpoint validates same logic
    
    Caregivers can only see doctor profiles if the doctor has medical records
    for patients assigned to that caregiver.
    """
    
    # Drop existing doctor RLS policies if they exist (for clean re-application)
    op.execute("DROP POLICY IF EXISTS \"doctors_admin_bypass\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_own_profile\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_caregiver_access\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_deny_default\" ON doctors;")

    # Ensure RLS is enabled
    op.execute("ALTER TABLE doctors ENABLE ROW LEVEL SECURITY;")

    # Policy 1: Admins (SUPER_ADMIN role) bypass all restrictions
    op.execute("""
        CREATE POLICY "doctors_admin_bypass" ON doctors
        FOR SELECT
        USING (
            current_setting('app.current_role', true)::text = 'SUPER_ADMIN'
        );
    """)

    # Policy 2: Doctors can see their own profile
    op.execute("""
        CREATE POLICY "doctors_own_profile" ON doctors
        FOR SELECT
        USING (
            current_setting('app.current_role', true)::text = 'DOCTOR'
            AND id = current_setting('app.current_doctor_id', true)::uuid
        );
    """)

    # Policy 3: Caregivers can see doctor profiles IF the doctor has medical records for their patients
    op.execute("""
        CREATE POLICY "doctors_caregiver_access" ON doctors
        FOR SELECT
        USING (
            current_setting('app.current_role', true)::text = 'CAREGIVER'
            AND EXISTS (
                SELECT 1 FROM medical_records mr
                JOIN patients p ON mr.patient_id = p.id
                WHERE mr.doctor_id = doctors.id
                AND p.caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
            )
        );
    """)

    # Policy 4: Default deny for any other access attempts
    op.execute("""
        CREATE POLICY "doctors_deny_default" ON doctors
        FOR SELECT
        USING (false);
    """)


def downgrade() -> None:
    """Downgrade: remove caregiver access policies."""
    op.execute("DROP POLICY IF EXISTS \"doctors_admin_bypass\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_own_profile\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_caregiver_access\" ON doctors;")
    op.execute("DROP POLICY IF EXISTS \"doctors_deny_default\" ON doctors;")
