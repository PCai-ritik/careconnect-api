"""
CareConnect — Hospital Router (Public)

Endpoints:
  GET  /hospitals              → List all hospitals (id + name for dropdowns)
  GET  /hospitals/{id}/branding → Get hospital branding (name, brand_color, logo_url)

These routes are public (no authentication required) because:
  - Registration forms need to display a hospital selector
  - Frontends need to fetch branding on app init (before login)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])


# ═══════════════════════════════════════════════════════════════════════
# GET /hospitals
# Returns a lightweight list of hospitals for registration dropdowns.
# Public — no auth needed.
# ═══════════════════════════════════════════════════════════════════════


@router.get("", response_model=List[schemas.HospitalListItem])
def list_hospitals(db: Session = Depends(get_db)):
    """List all hospitals. Used by registration forms to populate a selector."""
    return db.query(models.Hospital).order_by(models.Hospital.name).all()


# ═══════════════════════════════════════════════════════════════════════
# GET /hospitals/{id}/branding
# Returns full branding details for white-label theming.
# Public — frontends call this on app init before user authenticates.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/{hospital_id}/branding", response_model=schemas.HospitalBrandingResponse)
def get_hospital_branding(
    hospital_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get hospital branding (name, color, logo) for white-label theming."""
    hospital = db.query(models.Hospital).filter(models.Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )
    return hospital
