"""
CareConnect — Hospital Admin Router

Endpoints for SUPER_ADMIN role to manage their hospital branding and staff affiliation requests.
"""

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, delete, func, outerjoin
import uuid
import os
import shutil
from typing import List

from app import models, schemas, crud
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.constants import DEFAULT_HOSPITAL_ID

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN]))]
)


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/pending-staff
# ═══════════════════════════════════════════════════════════════════════

@router.get("/pending-staff", response_model=List[schemas.UserResponse])
async def get_pending_staff(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all users who have requested affiliation with the admin's hospital and are pending approval."""
    if current_user.hospital_id == DEFAULT_HOSPITAL_ID:
        return []
        
    result = await db.execute(select(models.User).where(
        models.User.hospital_id == current_user.hospital_id,
        models.User.affiliation_status == models.AffiliationStatusEnum.PENDING
    ))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/approve-staff/{user_id}
# ═══════════════════════════════════════════════════════════════════════

@router.post("/approve-staff/{user_id}", response_model=schemas.UserResponse)
async def approve_staff(
    user_id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending staff member's affiliation request."""
    result = await db.execute(select(models.User).where(
        models.User.id == user_id,
        models.User.hospital_id == current_user.hospital_id
    ))
    user_to_approve = result.scalar_one_or_none()

    if not user_to_approve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending user not found for this hospital."
        )

    user_to_approve.affiliation_status = models.AffiliationStatusEnum.APPROVED
    await db.commit()
    await db.refresh(user_to_approve)
    return user_to_approve


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/reject-staff/{user_id}
# ═══════════════════════════════════════════════════════════════════════

@router.post("/reject-staff/{user_id}", response_model=schemas.UserResponse)
async def reject_staff(
    user_id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending staff member's affiliation request. Resets their hospital to default."""
    result = await db.execute(select(models.User).where(
        models.User.id == user_id,
        models.User.hospital_id == current_user.hospital_id
    ))
    user_to_reject = result.scalar_one_or_none()

    if not user_to_reject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending user not found for this hospital."
        )

    # Revert user's hospital to default and set status back to APPROVED
    user_to_reject.hospital_id = DEFAULT_HOSPITAL_ID
    user_to_reject.affiliation_status = models.AffiliationStatusEnum.APPROVED
    
    await db.commit()
    await db.refresh(user_to_reject)
    return user_to_reject


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/branding
# ═══════════════════════════════════════════════════════════════════════

@router.get("/branding", response_model=schemas.HospitalLookupResponse)
async def get_branding(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch branding information for the admin's hospital."""
    result = await db.execute(select(models.Hospital).where(
        models.Hospital.id == current_user.hospital_id
    ))
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# PUT /admin/branding
# ═══════════════════════════════════════════════════════════════════════

@router.put("/branding", response_model=schemas.HospitalLookupResponse)
async def update_branding(
    payload: schemas.HospitalBrandingUpdate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update branding config for the admin's hospital."""
    result = await db.execute(select(models.Hospital).where(
        models.Hospital.id == current_user.hospital_id
    ))
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # Prevent editing the default hospital branding
    if hospital.id == DEFAULT_HOSPITAL_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update default hospital branding."
        )

    # Update name if provided
    if payload.name is not None:
        hospital.name = payload.name

    # Update brand_color & logo_url directly if provided
    if payload.brand_color is not None:
        hospital.brand_color = payload.brand_color
    if payload.logo_url is not None:
        hospital.logo_url = payload.logo_url

    # Update domain / subdomain
    if payload.domain is not None:
        hospital.domain = payload.domain.strip().lower() if payload.domain.strip() else None
    if payload.subdomain is not None:
        hospital.subdomain = payload.subdomain.strip().lower() if payload.subdomain.strip() else None

    # Update white label config JSONB
    if payload.white_label_config is not None:
        hospital.white_label_config = payload.white_label_config.model_dump()
        # Sync root fields from white_label_config
        if hospital.white_label_config.get("primary_color"):
            hospital.brand_color = hospital.white_label_config["primary_color"]
        if hospital.white_label_config.get("logo_url"):
            hospital.logo_url = hospital.white_label_config["logo_url"]

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain or subdomain is already in use by another hospital."
        )

    await db.refresh(hospital)
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/hospitals (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/hospitals", response_model=List[schemas.HospitalLookupResponse], dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def list_hospitals(
    db: AsyncSession = Depends(get_db)
):
    """List all hospitals. Restricted to SUPER_ADMIN."""
    return (await db.execute(select(models.Hospital).order_by(models.Hospital.name))).scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/hospitals (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/hospitals", response_model=schemas.HospitalLookupResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def create_hospital(
    payload: schemas.HospitalCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new hospital tenant. Restricted to SUPER_ADMIN."""
    if payload.domain:
        existing_domain = await db.execute(select(models.Hospital).where(
            models.Hospital.domain == payload.domain.strip().lower()
        ))
        if existing_domain.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A hospital with this domain already exists."
            )
    if payload.subdomain:
        existing_subdomain = await db.execute(select(models.Hospital).where(
            models.Hospital.subdomain == payload.subdomain.strip().lower()
        ))
        if existing_subdomain.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A hospital with this subdomain already exists."
            )

    db_hospital = models.Hospital(
        name=payload.name,
        brand_color=payload.brand_color,
        logo_url=payload.logo_url,
        domain=payload.domain.strip().lower() if payload.domain else None,
        subdomain=payload.subdomain.strip().lower() if payload.subdomain else None,
        white_label_config=payload.white_label_config.model_dump() if payload.white_label_config else {}
    )
    db.add(db_hospital)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A hospital with this domain or subdomain already exists."
        )
    await db.refresh(db_hospital)
    return db_hospital


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/admins (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/admins", response_model=List[schemas.UserResponse], dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def list_admins(
    db: AsyncSession = Depends(get_db)
):
    """List all administrators (both SUPER_ADMIN and ADMIN). Restricted to SUPER_ADMIN."""
    return (await db.execute(select(models.User).where(
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ).order_by(models.User.email))).scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/admins (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/admins", response_model=schemas.UserResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def create_admin(
    payload: schemas.AdminCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new ADMIN user for a specific hospital. Restricted to SUPER_ADMIN."""
    # Check if hospital exists
    result = await db.execute(select(models.Hospital).where(
        models.Hospital.id == payload.hospital_id
    ))
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # Check if email is already taken
    result = await db.execute(select(models.User).where(
        models.User.email == payload.email
    ))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered."
        )

    # Check if this hospital already has an administrator (RoleEnum.SUPER_ADMIN or RoleEnum.ADMIN)
    result = await db.execute(select(models.User).where(
        models.User.hospital_id == payload.hospital_id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ))
    existing_admin = result.scalar_one_or_none()
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This hospital already has an administrator account ({existing_admin.email}). Only one administrator is allowed per hospital."
        )

    try:
        db_user = await crud.create_user(
            db=db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            hospital_id=payload.hospital_id,
            role=models.RoleEnum.ADMIN
        )
        return db_user
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An error occurred while creating the admin account."
        )


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/upload-logo
# ═══════════════════════════════════════════════════════════════════════

@router.post("/upload-logo")
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
):
    """Upload a logo image file for the admin's hospital."""
    # 1. Validate file content type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image (JPEG, PNG, etc.)."
        )
    
    # 2. Ensure folder exists
    os.makedirs("uploads", exist_ok=True)
    
    # 3. Resolve file extension
    ext = os.path.splitext(file.filename)[1] if file.filename else ".png"
    if not ext:
        ext = ".png"
        
    # 4. Save unique file
    filename = f"logo_{current_user.hospital_id}_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join("uploads", filename)
    
    try:
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )
        
    # 5. Build absolute URL
    base_url = str(request.base_url)
    logo_url = f"{base_url}uploads/{filename}"
    
    return {"logo_url": logo_url}


# ═══════════════════════════════════════════════════════════════════════
# PUT /admin/hospitals/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.put("/hospitals/{id}", response_model=schemas.HospitalLookupResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def update_hospital(
    id: uuid.UUID,
    payload: schemas.HospitalUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update hospital tenant. Restricted to SUPER_ADMIN."""
    if id == DEFAULT_HOSPITAL_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify the default platform hospital branding through Super Controls."
        )
    
    result = await db.execute(select(models.Hospital).where(models.Hospital.id == id))
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # Check domain uniqueness
    if payload.domain is not None:
        domain_str = payload.domain.strip().lower() if payload.domain.strip() else None
        if domain_str:
            result = await db.execute(select(models.Hospital).where(
                models.Hospital.domain == domain_str,
                models.Hospital.id != id
            ))
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A hospital with this domain already exists."
                )
            hospital.domain = domain_str
        else:
            hospital.domain = None

    # Check subdomain uniqueness
    if payload.subdomain is not None:
        subdomain_str = payload.subdomain.strip().lower() if payload.subdomain.strip() else None
        if subdomain_str:
            result = await db.execute(select(models.Hospital).where(
                models.Hospital.subdomain == subdomain_str,
                models.Hospital.id != id
            ))
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A hospital with this subdomain already exists."
                )
            hospital.subdomain = subdomain_str
        else:
            hospital.subdomain = None

    if payload.name is not None:
        hospital.name = payload.name.strip()
    
    if payload.brand_color is not None:
        hospital.brand_color = payload.brand_color.strip()

    if payload.logo_url is not None:
        hospital.logo_url = payload.logo_url.strip() or None  # type: ignore

    if payload.white_label_config is not None:
        hospital.white_label_config = payload.white_label_config.model_dump()
        # Sync root color/logo if present in white label config
        if hospital.white_label_config.get("primary_color"):
            hospital.brand_color = hospital.white_label_config["primary_color"]
        if hospital.white_label_config.get("logo_url"):
            hospital.logo_url = hospital.white_label_config["logo_url"]

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrity constraint violated during update."
        )
    await db.refresh(hospital)
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# DELETE /admin/hospitals/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.delete("/hospitals/{id}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def delete_hospital(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete a hospital tenant and all its associated data. Restricted to SUPER_ADMIN."""
    if id == DEFAULT_HOSPITAL_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default platform hospital."
        )
    
    result = await db.execute(select(models.Hospital).where(models.Hospital.id == id))
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # 1. Gather all related entity IDs
    user_ids = [u.id for u in (await db.execute(select(models.User.id).where(models.User.hospital_id == id)))]
    doctor_ids = [d.id for d in (await db.execute(select(models.Doctor.id).where(models.Doctor.user_id.in_(user_ids))))] if user_ids else []
    caregiver_ids = [c.id for c in (await db.execute(select(models.Caregiver.id).where(models.Caregiver.user_id.in_(user_ids))))] if user_ids else []
    patient_ids = [p.id for p in (await db.execute(select(models.Patient.id).where(models.Patient.hospital_id == id)))]
    appointment_ids = [a.id for a in (await db.execute(select(models.Appointment.id).where(models.Appointment.hospital_id == id)))]
    medical_record_ids = [m.id for m in (await db.execute(select(models.MedicalRecord.id).where(models.MedicalRecord.patient_id.in_(patient_ids))))] if patient_ids else []

    try:
        # 2. Delete third-tier children/logs
        # transactions (FK to appointment and doctor)
        if appointment_ids or doctor_ids:
            await db.execute(
                delete(models.Transaction).where(
                    (models.Transaction.appointment_id.in_(appointment_ids)) | 
                    (models.Transaction.doctor_id.in_(doctor_ids))
                )
            )

        # post_call_summaries (FK to appointment)
        if appointment_ids:
            await db.execute(
                delete(models.PostCallSummary).where(models.PostCallSummary.appointment_id.in_(appointment_ids))
            )

        # video_sessions (FK to appointment)
        if appointment_ids:
            await db.execute(
                delete(models.VideoSession).where(models.VideoSession.appointment_id.in_(appointment_ids))
            )

        # prescriptions (FK to patient, doctor, medical_record)
        if patient_ids or doctor_ids or medical_record_ids:
            await db.execute(
                delete(models.Prescription).where(
                    (models.Prescription.patient_id.in_(patient_ids)) | 
                    (models.Prescription.doctor_id.in_(doctor_ids)) | 
                    (models.Prescription.medical_record_id.in_(medical_record_ids))
                )
            )

        # doctor_notes (FK to appointment, doctor)
        if appointment_ids or doctor_ids:
            await db.execute(
                delete(models.DoctorNote).where(
                    (models.DoctorNote.appointment_id.in_(appointment_ids)) | 
                    (models.DoctorNote.doctor_id.in_(doctor_ids))
                )
            )

        # medical_records (FK to patient, doctor)
        if patient_ids or doctor_ids:
            await db.execute(
                delete(models.MedicalRecord).where(
                    (models.MedicalRecord.patient_id.in_(patient_ids)) | 
                    (models.MedicalRecord.doctor_id.in_(doctor_ids))
                )
            )

        # doctor_availabilities (FK to doctor)
        if doctor_ids:
            await db.execute(
                delete(models.DoctorAvailability).where(models.DoctorAvailability.doctor_id.in_(doctor_ids))
            )

        # 3. Delete second-tier entities
        # appointments
        await db.execute(
            delete(models.Appointment).where(models.Appointment.hospital_id == id)
        )

        # patients
        await db.execute(
            delete(models.Patient).where(models.Patient.hospital_id == id)
        )

        # doctors
        if doctor_ids:
            await db.execute(
                delete(models.Doctor).where(models.Doctor.id.in_(doctor_ids))
            )

        # caregivers
        if caregiver_ids:
            await db.execute(
                delete(models.Caregiver).where(models.Caregiver.id.in_(caregiver_ids))
            )

        # notifications (FK to user)
        if user_ids:
            await db.execute(
                delete(models.Notification).where(models.Notification.user_id.in_(user_ids))
            )

        # 4. Delete users
        await db.execute(
            delete(models.User).where(models.User.hospital_id == id)
        )

        # 5. Delete hospital
        await db.delete(hospital)

        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete hospital tenant: {str(e)}"
        )

    return {"detail": "Hospital tenant and all associated data deleted successfully."}


# ═══════════════════════════════════════════════════════════════════════
# PUT /admin/admins/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.put("/admins/{id}", response_model=schemas.UserResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def update_admin(
    id: uuid.UUID,
    payload: schemas.AdminUpdate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update administrator account. Restricted to SUPER_ADMIN."""
    admin = (await db.execute(select(models.User).where(
        models.User.id == id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ))).scalar()
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Administrator not found."
        )

    # Protect main super admin from modification
    if admin.email == "admin@careconnect.com":
        # Don't allow deactivating or changing hospital for primary super admin
        if payload.is_active is False or (payload.hospital_id and payload.hospital_id != DEFAULT_HOSPITAL_ID):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate or change tenant of the primary platform super administrator."
            )

    if payload.email is not None:
        email_str = payload.email.strip().lower()
        if email_str != admin.email:
            # Check email uniqueness
            existing = (await db.execute(select(models.User).where(models.User.email == email_str))).scalar()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email is already registered."
                )
            admin.email = email_str

    if payload.full_name is not None:
        admin.full_name = payload.full_name.strip()

    if payload.password is not None and payload.password.strip():
        if len(payload.password.strip()) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters."
            )
        from app import security
        admin.password_hash = security.hash_password(payload.password.strip())

    if payload.hospital_id is not None and payload.hospital_id != admin.hospital_id:
        # Check if the target hospital already has an admin
        existing_admin = (await db.execute(select(models.User).where(
            models.User.hospital_id == payload.hospital_id,
            models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN]),
            models.User.id != id
        ))).scalar()
        if existing_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target hospital already has an administrator account ({existing_admin.email})."
            )
        
        # Verify target hospital exists
        hospital = (await db.execute(select(models.Hospital).where(models.Hospital.id == payload.hospital_id))).scalar_one_or_none()
        if not hospital:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target hospital not found."
            )
        admin.hospital_id = payload.hospital_id

    if payload.is_active is not None:
        # Prevent self-deactivation
        if admin.id == current_user.id and payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own active super admin session."
            )
        admin.is_active = payload.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrity constraint violated during update."
        )
    await db.refresh(admin)
    return admin


# ═══════════════════════════════════════════════════════════════════════
# DELETE /admin/admins/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.delete("/admins/{id}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
async def delete_admin(
    id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an administrator account. Restricted to SUPER_ADMIN."""
    admin = (await db.execute(select(models.User).where(
        models.User.id == id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ))).scalar_one_or_none()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Administrator not found."
        )

    # Protect main super admin and self-deletion
    if admin.email == "admin@careconnect.com":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the primary platform super administrator."
        )
    if admin.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own active super admin account."
        )

    # Delete notifications first
    await db.execute(
        delete(models.Notification).where(models.Notification.user_id == id)
    )

    # Delete doctor / caregiver profile if exist
    await db.execute(
        delete(models.DoctorAvailability).where(models.DoctorAvailability.doctor_id.in_(
            select(models.Doctor.id).where(models.Doctor.user_id == id)
        ))
    )
    await db.execute(
        delete(models.Doctor).where(models.Doctor.user_id == id)
    )
    await db.execute(
        delete(models.Caregiver).where(models.Caregiver.user_id == id)
    )

    await db.delete(admin)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete administrator: {str(e)}"
        )

    return {"detail": "Administrator account deleted successfully."}



# ═══════════════════════════════════════════════════════════════════════
# DOCTOR MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.post("/doctors", response_model=schemas.UserResponse)
async def create_doctor(
    payload: schemas.AdminDoctorCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    existing = await crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await crud.create_user(
        db=db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=current_user.hospital_id, # type: ignore
        role=models.RoleEnum.DOCTOR
    )
    user.affiliation_status = models.AffiliationStatusEnum.APPROVED
    await db.commit()
    
    db_doctor = models.Doctor(
        user_id=user.id,
        full_name=payload.full_name,
        specialization=payload.specialization,
        onboarding_completed=False
    )
    db.add(db_doctor)
    await db.commit()
    
    return user


@router.get("/doctors", response_model=List[schemas.AdminDoctorListItem])
async def list_doctors(
    hospital_id: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_count_sq = (
        select(models.Patient.doctor_id, func.count(models.Patient.id).label("patient_count"))
        .group_by(models.Patient.doctor_id)
        .subquery()
    )

    stmt = (
        select(
            models.Doctor.id,
            models.User.id.label("user_id"),
            models.User.full_name,
            models.User.email,
            models.Doctor.specialization,
            models.Doctor.onboarding_completed,
            models.User.is_active,
            models.User.created_at,
            func.coalesce(patient_count_sq.c.patient_count, 0).label("patient_count")
        )
        .select_from(models.Doctor)
        .join(models.User, models.Doctor.user_id == models.User.id)
        .outerjoin(patient_count_sq, models.Doctor.id == patient_count_sq.c.doctor_id)
    )

    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        if hospital_id:
            import uuid as _uuid
            stmt = stmt.where(models.User.hospital_id == _uuid.UUID(hospital_id))
    else:
        stmt = stmt.where(models.User.hospital_id == current_user.hospital_id)

    stmt = stmt.order_by(models.User.created_at.desc())
    result = await db.execute(stmt)
    return result.mappings().all()


# ═══════════════════════════════════════════════════════════════════════
# CAREGIVER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.post("/caregivers", response_model=schemas.UserResponse)
async def create_caregiver(
    payload: schemas.AdminCaregiverCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    existing = await crud.get_user_by_email(db, email=payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await crud.create_user(
        db=db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        hospital_id=current_user.hospital_id, # type: ignore
        role=models.RoleEnum.CAREGIVER
    )
    user.affiliation_status = models.AffiliationStatusEnum.APPROVED
    await db.commit()
    
    db_cg = models.Caregiver(
        user_id=user.id,
        full_name=payload.full_name,
        whatsapp_number=payload.whatsapp_number
    )
    db.add(db_cg)
    await db.commit()
    await db.refresh(db_cg)

    if payload.patient_ids:
        await db.execute(
            models.Patient.__table__.update()
            .where(models.Patient.id.in_(payload.patient_ids))
            .where(models.Patient.hospital_id == current_user.hospital_id)
            .values(caregiver_id=db_cg.id)
        )
        await db.commit()

    return user


@router.get("/caregivers", response_model=List[schemas.AdminCaregiverListItem])
async def list_caregivers(
    hospital_id: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_count_sq = (
        select(models.Patient.caregiver_id, func.count(models.Patient.id).label("patient_count"))
        .group_by(models.Patient.caregiver_id)
        .subquery()
    )

    stmt = (
        select(
            models.Caregiver.id,
            models.User.id.label("user_id"),
            models.User.full_name,
            models.User.email,
            models.Caregiver.whatsapp_number,
            models.User.is_active,
            models.User.created_at,
            func.coalesce(patient_count_sq.c.patient_count, 0).label("patient_count")
        )
        .select_from(models.Caregiver)
        .join(models.User, models.Caregiver.user_id == models.User.id)
        .outerjoin(patient_count_sq, models.Caregiver.id == patient_count_sq.c.caregiver_id)
    )

    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        if hospital_id:
            import uuid as _uuid
            stmt = stmt.where(models.User.hospital_id == _uuid.UUID(hospital_id))
    else:
        stmt = stmt.where(models.User.hospital_id == current_user.hospital_id)

    stmt = stmt.order_by(models.User.created_at.desc())
    result = await db.execute(stmt)
    return result.mappings().all()


# ═══════════════════════════════════════════════════════════════════════
# PATIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.post("/patients", response_model=schemas.PatientResponse)
async def create_patient(
    payload: schemas.AdminPatientCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify doctor exists in hospital
    doc_stmt = select(models.Doctor).join(models.User).where(
        models.Doctor.id == payload.doctor_id,
        models.User.hospital_id == current_user.hospital_id
    )
    doctor = (await db.execute(doc_stmt)).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=400, detail="Invalid doctor ID for this hospital")
        
    if payload.caregiver_id:
        cg_stmt = select(models.Caregiver).join(models.User).where(
            models.Caregiver.id == payload.caregiver_id,
            models.User.hospital_id == current_user.hospital_id
        )
        cg = (await db.execute(cg_stmt)).scalar_one_or_none()
        if not cg:
            raise HTTPException(status_code=400, detail="Invalid caregiver ID for this hospital")

    patient_data = payload.model_dump(exclude={"doctor_id", "caregiver_id"})
    patient = await crud.create_patient(
        db,
        hospital_id=current_user.hospital_id, # type: ignore
        doctor_id=payload.doctor_id,
        caregiver_id=payload.caregiver_id,
        patient_data=patient_data
    )
    return patient


@router.get("/patients", response_model=List[schemas.AdminPatientListItem])
async def list_patients(
    hospital_id: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy.orm import aliased
    
    DoctorUser = aliased(models.User)
    CaregiverUser = aliased(models.User)

    stmt = (
        select(
            models.Patient.id,
            models.Patient.full_name,
            models.Patient.whatsapp_number,
            models.Patient.created_at,
            models.Hospital.name.label("hospital_name"),
            DoctorUser.full_name.label("doctor_name"),
            CaregiverUser.full_name.label("caregiver_name")
        )
        .select_from(models.Patient)
        .join(models.Hospital, models.Patient.hospital_id == models.Hospital.id)
        .outerjoin(models.Doctor, models.Patient.doctor_id == models.Doctor.id)
        .outerjoin(DoctorUser, models.Doctor.user_id == DoctorUser.id)
        .outerjoin(models.Caregiver, models.Patient.caregiver_id == models.Caregiver.id)
        .outerjoin(CaregiverUser, models.Caregiver.user_id == CaregiverUser.id)
    )

    if current_user.role == models.RoleEnum.SUPER_ADMIN:
        if hospital_id:
            import uuid as _uuid
            stmt = stmt.where(models.Patient.hospital_id == _uuid.UUID(hospital_id))
    else:
        stmt = stmt.where(models.Patient.hospital_id == current_user.hospital_id)

    stmt = stmt.order_by(models.Patient.created_at.desc())
    result = await db.execute(stmt)
    return result.mappings().all()
