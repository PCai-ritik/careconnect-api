"""add_rls_policies

Revision ID: 1074b0bc6fbd
Revises: ad390b8e6e0d
Create Date: 2026-04-07 22:46:54.441348

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1074b0bc6fbd"
down_revision: Union[str, Sequence[str], None] = "ad390b8e6e0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════
    # 1. ENABLE ROW LEVEL SECURITY ON ALL TABLES
    # ═══════════════════════════════════════════════════════════════════
    tables = [
        "hospitals",
        "users",
        "doctors",
        "doctor_availability",
        "caregivers",
        "patients",
        "appointments",
        "medical_records",
        "prescriptions",
        "video_sessions",
        "transactions",
        "post_call_summaries",
    ]

    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    # ═══════════════════════════════════════════════════════════════════
    # 2. BASE TENANT POLICIES (Direct hospital_id column)
    # ═══════════════════════════════════════════════════════════════════

    # hospitals: only see your own hospital row
    op.execute("""
        CREATE POLICY tenant_isolation_hospitals ON hospitals FOR ALL
        USING (id = current_setting('app.current_hospital_id', true)::uuid);
    """)

    # users: only see users in your hospital
    op.execute("""
        CREATE POLICY tenant_isolation_users ON users FOR ALL
        USING (hospital_id = current_setting('app.current_hospital_id', true)::uuid);
    """)

    # ═══════════════════════════════════════════════════════════════════
    # 3. DUAL-KEY PATIENT POLICY
    #    SUPER_ADMIN / DOCTOR = see all patients in hospital
    #    CAREGIVER = only see patients they manage
    # ═══════════════════════════════════════════════════════════════════

    op.execute("""
        CREATE POLICY patient_access ON patients FOR ALL
        USING (
            hospital_id = current_setting('app.current_hospital_id', true)::uuid
            AND (
                current_setting('app.current_role', true) IN ('SUPER_ADMIN', 'DOCTOR')
                OR caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
            )
        );
    """)

    # ═══════════════════════════════════════════════════════════════════
    # 4. APPOINTMENT POLICY (Participants & Admins)
    #    Must pass hospital check + be a participant or admin
    # ═══════════════════════════════════════════════════════════════════

    op.execute("""
        CREATE POLICY appointment_access ON appointments FOR ALL
        USING (
            hospital_id = current_setting('app.current_hospital_id', true)::uuid
            AND (
                current_setting('app.current_role', true) = 'SUPER_ADMIN'
                OR doctor_id = current_setting('app.current_doctor_id', true)::uuid
                OR caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
            )
        );
    """)

    # ═══════════════════════════════════════════════════════════════════
    # 5. SUBQUERY HOP POLICIES (Tables without hospital_id)
    # ═══════════════════════════════════════════════════════════════════

    # DOCTORS: Hop through users → hospital_id
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

    # CAREGIVERS: Hop through users → hospital_id
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

    # DOCTOR AVAILABILITY: Hop through doctors → users → hospital_id
    op.execute("""
        CREATE POLICY availability_access ON doctor_availability FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM doctors
                JOIN users ON doctors.user_id = users.id
                WHERE doctors.id = doctor_availability.doctor_id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
            )
        );
    """)

    # MEDICAL RECORDS: Hop through patients → hospital_id
    # Doctors/Admins see all in hospital; Caregivers only see their patients'
    op.execute("""
        CREATE POLICY med_record_access ON medical_records FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM patients
                WHERE patients.id = medical_records.patient_id
                AND patients.hospital_id = current_setting('app.current_hospital_id', true)::uuid
                AND (
                    current_setting('app.current_role', true) IN ('SUPER_ADMIN', 'DOCTOR')
                    OR patients.caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
                )
            )
        );
    """)

    # PRESCRIPTIONS: Same logic as medical_records, hop through patients
    op.execute("""
        CREATE POLICY prescription_access ON prescriptions FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM patients
                WHERE patients.id = prescriptions.patient_id
                AND patients.hospital_id = current_setting('app.current_hospital_id', true)::uuid
                AND (
                    current_setting('app.current_role', true) IN ('SUPER_ADMIN', 'DOCTOR')
                    OR patients.caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
                )
            )
        );
    """)

    # VIDEO SESSIONS: Hop through appointments → hospital_id + participants
    op.execute("""
        CREATE POLICY video_session_access ON video_sessions FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM appointments
                WHERE appointments.id = video_sessions.appointment_id
                AND appointments.hospital_id = current_setting('app.current_hospital_id', true)::uuid
                AND (
                    current_setting('app.current_role', true) = 'SUPER_ADMIN'
                    OR appointments.doctor_id = current_setting('app.current_doctor_id', true)::uuid
                    OR appointments.caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
                )
            )
        );
    """)

    # TRANSACTIONS: Hop through doctors → users → hospital_id
    # Admins see all in hospital; Doctors see only their own
    op.execute("""
        CREATE POLICY transaction_access ON transactions FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM doctors
                JOIN users ON doctors.user_id = users.id
                WHERE transactions.doctor_id = doctors.id
                AND users.hospital_id = current_setting('app.current_hospital_id', true)::uuid
                AND (
                    current_setting('app.current_role', true) = 'SUPER_ADMIN'
                    OR doctors.id = current_setting('app.current_doctor_id', true)::uuid
                )
            )
        );
    """)

    # POST-CALL SUMMARIES: Hop through appointments → hospital_id + participants
    op.execute("""
        CREATE POLICY post_call_summary_access ON post_call_summaries FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM appointments
                WHERE appointments.id = post_call_summaries.appointment_id
                AND appointments.hospital_id = current_setting('app.current_hospital_id', true)::uuid
                AND (
                    current_setting('app.current_role', true) = 'SUPER_ADMIN'
                    OR appointments.doctor_id = current_setting('app.current_doctor_id', true)::uuid
                    OR appointments.caregiver_id = current_setting('app.current_caregiver_id', true)::uuid
                )
            )
        );
    """)


def downgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════
    # DROP ALL POLICIES THEN DISABLE RLS
    # ═══════════════════════════════════════════════════════════════════
    policies = [
        ("tenant_isolation_hospitals", "hospitals"),
        ("tenant_isolation_users", "users"),
        ("patient_access", "patients"),
        ("appointment_access", "appointments"),
        ("doctor_access", "doctors"),
        ("caregiver_access", "caregivers"),
        ("availability_access", "doctor_availability"),
        ("med_record_access", "medical_records"),
        ("prescription_access", "prescriptions"),
        ("video_session_access", "video_sessions"),
        ("transaction_access", "transactions"),
        ("post_call_summary_access", "post_call_summaries"),
    ]

    for policy, table in policies:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")

    tables = [
        "hospitals",
        "users",
        "doctors",
        "doctor_availability",
        "caregivers",
        "patients",
        "appointments",
        "medical_records",
        "prescriptions",
        "video_sessions",
        "transactions",
        "post_call_summaries",
    ]

    for table in tables:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

