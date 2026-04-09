from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List

from app import models, database, crud, schemas
from app.config import settings

# This looks for "Authorization: Bearer <token>" in the headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)
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
        user_id: str = payload.get("sub")
        hospital_id: str = payload.get("hospital_id")
        token_type: str = payload.get("type")

        if user_id is None or token_type != "access":
            raise credentials_exception

        token_data = schemas.TokenData(
            user_id=user_id, hospital_id=hospital_id, role=payload.get("role")
        )

    except JWTError:
        raise credentials_exception

    # 3. Verify user still exists in the database
    user = crud.get_user_by_id(db, user_id=token_data.user_id)
    if user is None:
        raise credentials_exception

    # ═══════════════════════════════════════════════════════════════════
    # RLS HOOK: Setting session variables for PostgreSQL RLS policies
    # ═══════════════════════════════════════════════════════════════════

    # 1. THE WHERE: Which hospital does this user belong to?
    db.execute(
        text("SET app.current_hospital_id = :hid"), {"hid": str(user.hospital_id)}
    )

    # 2. THE WHO: Which user.id is this? (Used by transaction policy)
    db.execute(text("SET app.current_user_id = :uid"), {"uid": str(user.id)})

    # 3. THE WHAT: What is their role? (For branching in SQL policies)
    db.execute(text("SET app.current_role = :role"), {"role": user.role.value})

    # 4. THE PROFILE: Resolve the doctor/caregiver profile ID.
    #    RLS policies compare against doctors.id / caregivers.id,
    #    NOT users.id — so we must look up the profile.
    #    If the var is unset, current_setting(..., true) returns NULL,
    #    which safely fails the UUID comparison (= Deny).
    if user.role == models.RoleEnum.DOCTOR:
        doctor = (
            db.query(models.Doctor.id)
            .filter(models.Doctor.user_id == user.id)
            .first()
        )
        if doctor:
            db.execute(
                text("SET app.current_doctor_id = :did"),
                {"did": str(doctor.id)},
            )
    elif user.role == models.RoleEnum.CAREGIVER:
        caregiver = (
            db.query(models.Caregiver.id)
            .filter(models.Caregiver.user_id == user.id)
            .first()
        )
        if caregiver:
            db.execute(
                text("SET app.current_caregiver_id = :cid"),
                {"cid": str(caregiver.id)},
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

    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the required permissions",
            )
        return current_user

    return role_checker
