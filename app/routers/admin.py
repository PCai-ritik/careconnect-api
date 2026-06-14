"""
CareConnect — Hospital Admin Router

Endpoints for SUPER_ADMIN role to manage their hospital branding and staff affiliation requests.
"""

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
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
def get_pending_staff(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users who have requested affiliation with the admin's hospital and are pending approval."""
    if current_user.hospital_id == DEFAULT_HOSPITAL_ID:
        return []
        
    return db.query(models.User).filter(
        models.User.hospital_id == current_user.hospital_id,
        models.User.affiliation_status == models.AffiliationStatusEnum.PENDING
    ).all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/approve-staff/{user_id}
# ═══════════════════════════════════════════════════════════════════════

@router.post("/approve-staff/{user_id}", response_model=schemas.UserResponse)
def approve_staff(
    user_id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a pending staff member's affiliation request."""
    user_to_approve = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.hospital_id == current_user.hospital_id
    ).first()

    if not user_to_approve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending user not found for this hospital."
        )

    user_to_approve.affiliation_status = models.AffiliationStatusEnum.APPROVED
    db.commit()
    db.refresh(user_to_approve)
    return user_to_approve


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/reject-staff/{user_id}
# ═══════════════════════════════════════════════════════════════════════

@router.post("/reject-staff/{user_id}", response_model=schemas.UserResponse)
def reject_staff(
    user_id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending staff member's affiliation request. Resets their hospital to default."""
    user_to_reject = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.hospital_id == current_user.hospital_id
    ).first()

    if not user_to_reject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending user not found for this hospital."
        )

    # Revert user's hospital to default and set status back to APPROVED
    user_to_reject.hospital_id = DEFAULT_HOSPITAL_ID
    user_to_reject.affiliation_status = models.AffiliationStatusEnum.APPROVED
    
    db.commit()
    db.refresh(user_to_reject)
    return user_to_reject


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/branding
# ═══════════════════════════════════════════════════════════════════════

@router.get("/branding", response_model=schemas.HospitalLookupResponse)
def get_branding(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch branding information for the admin's hospital."""
    hospital = db.query(models.Hospital).filter(models.Hospital.id == current_user.hospital_id).first()
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
def update_branding(
    payload: schemas.HospitalBrandingUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update branding config for the admin's hospital."""
    hospital = db.query(models.Hospital).filter(models.Hospital.id == current_user.hospital_id).first()
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
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain or subdomain is already in use by another hospital."
        )

    db.refresh(hospital)
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/hospitals (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/hospitals", response_model=List[schemas.HospitalLookupResponse], dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def list_hospitals(
    db: Session = Depends(get_db)
):
    """List all hospitals. Restricted to SUPER_ADMIN."""
    return db.query(models.Hospital).order_by(models.Hospital.name).all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/hospitals (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/hospitals", response_model=schemas.HospitalLookupResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def create_hospital(
    payload: schemas.HospitalCreate,
    db: Session = Depends(get_db)
):
    """Create a new hospital tenant. Restricted to SUPER_ADMIN."""
    if payload.domain:
        existing_domain = db.query(models.Hospital).filter(models.Hospital.domain == payload.domain.strip().lower()).first()
        if existing_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A hospital with this domain already exists."
            )
    if payload.subdomain:
        existing_subdomain = db.query(models.Hospital).filter(models.Hospital.subdomain == payload.subdomain.strip().lower()).first()
        if existing_subdomain:
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
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A hospital with this domain or subdomain already exists."
        )
    db.refresh(db_hospital)
    return db_hospital


# ═══════════════════════════════════════════════════════════════════════
# GET /admin/admins (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/admins", response_model=List[schemas.UserResponse], dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def list_admins(
    db: Session = Depends(get_db)
):
    """List all administrators (both SUPER_ADMIN and ADMIN). Restricted to SUPER_ADMIN."""
    return db.query(models.User).filter(
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ).order_by(models.User.email).all()


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/admins (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/admins", response_model=schemas.UserResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def create_admin(
    payload: schemas.AdminCreate,
    db: Session = Depends(get_db)
):
    """Create a new ADMIN user for a specific hospital. Restricted to SUPER_ADMIN."""
    # Check if hospital exists
    hospital = db.query(models.Hospital).filter(models.Hospital.id == payload.hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # Check if email is already taken
    existing_user = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered."
        )

    # Check if this hospital already has an administrator (RoleEnum.SUPER_ADMIN or RoleEnum.ADMIN)
    existing_admin = db.query(models.User).filter(
        models.User.hospital_id == payload.hospital_id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ).first()
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This hospital already has an administrator account ({existing_admin.email}). Only one administrator is allowed per hospital."
        )

    try:
        db_user = crud.create_user(
            db=db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            hospital_id=payload.hospital_id,
            role=models.RoleEnum.ADMIN
        )
        return db_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An error occurred while creating the admin account."
        )


# ═══════════════════════════════════════════════════════════════════════
# POST /admin/upload-logo
# ═══════════════════════════════════════════════════════════════════════

@router.post("/upload-logo")
def upload_logo(
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
def update_hospital(
    id: uuid.UUID,
    payload: schemas.HospitalUpdate,
    db: Session = Depends(get_db)
):
    """Update hospital tenant. Restricted to SUPER_ADMIN."""
    if id == DEFAULT_HOSPITAL_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify the default platform hospital branding through Super Controls."
        )
    
    hospital = db.query(models.Hospital).filter(models.Hospital.id == id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # Check domain uniqueness
    if payload.domain is not None:
        domain_str = payload.domain.strip().lower() if payload.domain.strip() else None
        if domain_str:
            existing = db.query(models.Hospital).filter(
                models.Hospital.domain == domain_str,
                models.Hospital.id != id
            ).first()
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
            existing = db.query(models.Hospital).filter(
                models.Hospital.subdomain == subdomain_str,
                models.Hospital.id != id
            ).first()
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
        hospital.logo_url = payload.logo_url.strip() or None

    if payload.white_label_config is not None:
        hospital.white_label_config = payload.white_label_config.model_dump()
        # Sync root color/logo if present in white label config
        if hospital.white_label_config.get("primary_color"):
            hospital.brand_color = hospital.white_label_config["primary_color"]
        if hospital.white_label_config.get("logo_url"):
            hospital.logo_url = hospital.white_label_config["logo_url"]

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrity constraint violated during update."
        )
    db.refresh(hospital)
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# DELETE /admin/hospitals/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.delete("/hospitals/{id}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def delete_hospital(
    id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete a hospital tenant and all its associated data. Restricted to SUPER_ADMIN."""
    if id == DEFAULT_HOSPITAL_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default platform hospital."
        )
    
    hospital = db.query(models.Hospital).filter(models.Hospital.id == id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found."
        )

    # 1. Gather all related entity IDs
    user_ids = [u.id for u in db.query(models.User.id).filter(models.User.hospital_id == id).all()]
    doctor_ids = [d.id for d in db.query(models.Doctor.id).filter(models.Doctor.user_id.in_(user_ids)).all()] if user_ids else []
    caregiver_ids = [c.id for c in db.query(models.Caregiver.id).filter(models.Caregiver.user_id.in_(user_ids)).all()] if user_ids else []
    patient_ids = [p.id for p in db.query(models.Patient.id).filter(models.Patient.hospital_id == id).all()]
    appointment_ids = [a.id for a in db.query(models.Appointment.id).filter(models.Appointment.hospital_id == id).all()]
    medical_record_ids = [m.id for m in db.query(models.MedicalRecord.id).filter(models.MedicalRecord.patient_id.in_(patient_ids)).all()] if patient_ids else []

    try:
        # 2. Delete third-tier children/logs
        # transactions (FK to appointment and doctor)
        if appointment_ids or doctor_ids:
            db.query(models.Transaction).filter(
                (models.Transaction.appointment_id.in_(appointment_ids)) | 
                (models.Transaction.doctor_id.in_(doctor_ids))
            ).delete(synchronize_session=False)

        # post_call_summaries (FK to appointment)
        if appointment_ids:
            db.query(models.PostCallSummary).filter(models.PostCallSummary.appointment_id.in_(appointment_ids)).delete(synchronize_session=False)

        # video_sessions (FK to appointment)
        if appointment_ids:
            db.query(models.VideoSession).filter(models.VideoSession.appointment_id.in_(appointment_ids)).delete(synchronize_session=False)

        # prescriptions (FK to patient, doctor, medical_record)
        if patient_ids or doctor_ids or medical_record_ids:
            db.query(models.Prescription).filter(
                (models.Prescription.patient_id.in_(patient_ids)) | 
                (models.Prescription.doctor_id.in_(doctor_ids)) | 
                (models.Prescription.medical_record_id.in_(medical_record_ids))
            ).delete(synchronize_session=False)

        # doctor_notes (FK to appointment, doctor)
        if appointment_ids or doctor_ids:
            db.query(models.DoctorNote).filter(
                (models.DoctorNote.appointment_id.in_(appointment_ids)) | 
                (models.DoctorNote.doctor_id.in_(doctor_ids))
            ).delete(synchronize_session=False)

        # medical_records (FK to patient, doctor)
        if patient_ids or doctor_ids:
            db.query(models.MedicalRecord).filter(
                (models.MedicalRecord.patient_id.in_(patient_ids)) | 
                (models.MedicalRecord.doctor_id.in_(doctor_ids))
            ).delete(synchronize_session=False)

        # doctor_availabilities (FK to doctor)
        if doctor_ids:
            db.query(models.DoctorAvailability).filter(models.DoctorAvailability.doctor_id.in_(doctor_ids)).delete(synchronize_session=False)

        # 3. Delete second-tier entities
        # appointments
        db.query(models.Appointment).filter(models.Appointment.hospital_id == id).delete(synchronize_session=False)

        # patients
        db.query(models.Patient).filter(models.Patient.hospital_id == id).delete(synchronize_session=False)

        # doctors
        if doctor_ids:
            db.query(models.Doctor).filter(models.Doctor.id.in_(doctor_ids)).delete(synchronize_session=False)

        # caregivers
        if caregiver_ids:
            db.query(models.Caregiver).filter(models.Caregiver.id.in_(caregiver_ids)).delete(synchronize_session=False)

        # notifications (FK to user)
        if user_ids:
            db.query(models.Notification).filter(models.Notification.user_id.in_(user_ids)).delete(synchronize_session=False)

        # 4. Delete users
        db.query(models.User).filter(models.User.hospital_id == id).delete(synchronize_session=False)

        # 5. Delete hospital
        db.delete(hospital)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete hospital tenant: {str(e)}"
        )

    return {"detail": "Hospital tenant and all associated data deleted successfully."}


# ═══════════════════════════════════════════════════════════════════════
# PUT /admin/admins/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.put("/admins/{id}", response_model=schemas.UserResponse, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def update_admin(
    id: uuid.UUID,
    payload: schemas.AdminUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update administrator account. Restricted to SUPER_ADMIN."""
    admin = db.query(models.User).filter(
        models.User.id == id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ).first()
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
            existing = db.query(models.User).filter(models.User.email == email_str).first()
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
        existing_admin = db.query(models.User).filter(
            models.User.hospital_id == payload.hospital_id,
            models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN]),
            models.User.id != id
        ).first()
        if existing_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target hospital already has an administrator account ({existing_admin.email})."
            )
        
        # Verify target hospital exists
        hospital = db.query(models.Hospital).filter(models.Hospital.id == payload.hospital_id).first()
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
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrity constraint violated during update."
        )
    db.refresh(admin)
    return admin


# ═══════════════════════════════════════════════════════════════════════
# DELETE /admin/admins/{id} (SUPER_ADMIN only)
# ═══════════════════════════════════════════════════════════════════════

@router.delete("/admins/{id}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_role([models.RoleEnum.SUPER_ADMIN]))])
def delete_admin(
    id: uuid.UUID,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an administrator account. Restricted to SUPER_ADMIN."""
    admin = db.query(models.User).filter(
        models.User.id == id,
        models.User.role.in_([models.RoleEnum.SUPER_ADMIN, models.RoleEnum.ADMIN])
    ).first()
    
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
    db.query(models.Notification).filter(models.Notification.user_id == id).delete(synchronize_session=False)

    # Delete doctor / caregiver profile if exist
    db.query(models.DoctorAvailability).filter(models.DoctorAvailability.doctor_id.in_(
        db.query(models.Doctor.id).filter(models.Doctor.user_id == id)
    )).delete(synchronize_session=False)
    db.query(models.Doctor).filter(models.Doctor.user_id == id).delete(synchronize_session=False)
    db.query(models.Caregiver).filter(models.Caregiver.user_id == id).delete(synchronize_session=False)

    db.delete(admin)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete administrator: {str(e)}"
        )

    return {"detail": "Administrator account deleted successfully."}


