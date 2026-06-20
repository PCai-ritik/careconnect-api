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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import uuid

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])


# ═══════════════════════════════════════════════════════════════════════
# GET /hospitals/lookup
# Resolves a hospital's white-label branding and config via hostname/domain/subdomain.
# Falls back to default hospital if hostname is not found.
# Public — no auth needed.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/lookup", response_model=schemas.HospitalLookupResponse)
async def lookup_hospital(
    hostname: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Lookup hospital by domain or subdomain, falling back to default hospital."""
    hospital = None
    if hostname:
        # Clean port if present (e.g. localhost:3000 -> localhost)
        cleaned_hostname = hostname.split(":")[0].strip().lower()
        
        # 1. Match exact domain
        hospital = (await db.execute(select(models.Hospital).where(models.Hospital.domain == cleaned_hostname))).scalar_one_or_none()
        
        # 2. Match subdomain if not matched by domain
        if not hospital:
            parts = cleaned_hostname.split(".")
            if len(parts) > 1:
                subdomain_part = parts[0]
                if subdomain_part == "www" and len(parts) > 2:
                    subdomain_part = parts[1]
                hospital = (await db.execute(select(models.Hospital).where(models.Hospital.subdomain == subdomain_part))).scalar_one_or_none()
            else:
                hospital = (await db.execute(select(models.Hospital).where(models.Hospital.subdomain == cleaned_hostname))).scalar_one_or_none()

    if not hospital:
        from app.constants import DEFAULT_HOSPITAL_ID
        hospital = (await db.execute(select(models.Hospital).where(models.Hospital.id == DEFAULT_HOSPITAL_ID))).scalar_one_or_none()

    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital/tenant configuration not found.",
        )
    return hospital


# ═══════════════════════════════════════════════════════════════════════
# GET /hospitals
# Returns a lightweight list of hospitals for registration dropdowns.
# Public — no auth needed.
# ═══════════════════════════════════════════════════════════════════════


@router.get("", response_model=List[schemas.HospitalListItem])
async def list_hospitals(db: AsyncSession = Depends(get_db)):
    """List all hospitals. Used by registration forms to populate a selector."""
    return (await db.execute(select(models.Hospital).order_by(models.Hospital.name))).scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# GET /hospitals/{id}/branding
# Returns full branding details for white-label theming.
# Public — frontends call this on app init before user authenticates.
# ═══════════════════════════════════════════════════════════════════════


@router.get("/{hospital_id}/branding", response_model=schemas.HospitalBrandingResponse)
async def get_hospital_branding(
    hospital_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get hospital branding (name, color, logo) for white-label theming."""
    hospital = (await db.execute(select(models.Hospital).where(models.Hospital.id == hospital_id))).scalar_one_or_none()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )
    return hospital
