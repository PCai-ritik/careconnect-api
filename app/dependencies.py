from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app import models, database, crud, schemas
from app.config import settings

# This looks for "Authorization: Bearer <token>" in the headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(database.get_db)
) -> models.User:
    """
    The main guard. Decodes the JWT and validates the user.
    """
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 1. Decode the token using our secret key
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # 2. Extract and validate payload data
        user_id: str | None = payload.get("sub")
        payload_hospital_id: str | None = payload.get("hospital_id")
        token_type: str | None = payload.get("type")

        if user_id is None or token_type != "access":
            raise credentials_exception

        token_data = schemas.TokenData(
            user_id=user_id, hospital_id=payload_hospital_id, role=payload.get("role")
        )

    except JWTError:
        raise credentials_exception

    # 3. Verify user still exists in the database
    user = await crud.get_user_by_id(db, user_id=user_id)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is deactivated. Please contact support.",
        )

    # ═══════════════════════════════════════════════════════════════════
    # RLS HOOK: Setting session variables for PostgreSQL RLS policies
    # ═══════════════════════════════════════════════════════════════════

    # 1. THE WHERE: Which hospital does this user belong to? (Fallback to DEFAULT_HOSPITAL_ID if PENDING)
    hospital_id = user.hospital_id
    if user.affiliation_status == models.AffiliationStatusEnum.PENDING:
        from app.constants import DEFAULT_HOSPITAL_ID
        hospital_id = DEFAULT_HOSPITAL_ID

    await db.execute(
        select(func.set_config("app.current_hospital_id", str(hospital_id), True))
    )

    # 2. THE WHO: Which user.id is this? (Used by transaction policy)
    await db.execute(
        select(func.set_config("app.current_user_id", str(user.id), True))
    )

    # 3. THE WHAT: What is their role? (For branching in SQL policies)
    # RLS Bypass strategy: Map RoleEnum.ADMIN to 'SUPER_ADMIN' so RLS policy logic is bypassed for their hospital.
    db_role = "SUPER_ADMIN" if user.role == models.RoleEnum.ADMIN else user.role.value
    await db.execute(
        select(func.set_config("app.current_role", db_role, True))
    )

    # 4. THE PROFILE: Resolve the doctor/caregiver profile ID.
    #    RLS policies compare against doctors.id / caregivers.id,
    #    NOT users.id — so we must look up the profile.
    #    If the var is unset, current_setting(..., true) returns NULL,
    #    which safely fails the UUID comparison (= Deny).
    if user.role == models.RoleEnum.DOCTOR:
        result = await db.execute(
            select(models.Doctor.id)
            .where(models.Doctor.user_id == user.id)
        )
        doctor = result.first()
        if doctor:
            await db.execute(
                select(func.set_config("app.current_doctor_id", str(doctor.id), True))
            )
    elif user.role == models.RoleEnum.CAREGIVER:
        result = await db.execute(
            select(models.Caregiver.id)
            .where(models.Caregiver.user_id == user.id)
        )
        caregiver = result.first()
        if caregiver:
            await db.execute(
                select(func.set_config("app.current_caregiver_id", str(caregiver.id), True))
            )

    return user


# ═══════════════════════════════════════════════════════════════════════
# ROLE-BASED ACCESS CONTROL (RBAC) GUARDS
# ═══════════════════════════════════════════════════════════════════════


def require_role(allowed_roles: List[models.RoleEnum]):
    """
    A factory function to create role-specific guards.
    Usage: Depends(require_role([RoleEnum.DOCTOR]))
    """

    async def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the required permissions",
            )
        return current_user

    return role_checker
