"""
CareConnect — Application Constants

Shared constants used across the application.
"""

import uuid


# ═══════════════════════════════════════════════════════════════════════
# DEFAULT HOSPITAL
#
# Every user, patient, and appointment belongs to a hospital (multi-tenancy).
# Users who sign up without selecting a specific hospital are assigned to
# the default "CareConnect" platform hospital.
#
# This unblocks registration and allows a future "enlist to hospital"
# flow where doctors/caregivers can join a specific hospital later.
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_HOSPITAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_HOSPITAL_NAME = "CareConnect"
DEFAULT_HOSPITAL_BRAND_COLOR = "#4F46E5"
