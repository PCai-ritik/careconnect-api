"""
CareConnect API — Application Entry Point

Multi-tenant healthcare backend with JWT auth and PostgreSQL RLS.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.auth import auth_router, api_router
from app.routers import doctors, patients, appointments, records, hospitals
from app.constants import DEFAULT_HOSPITAL_ID, DEFAULT_HOSPITAL_NAME, DEFAULT_HOSPITAL_BRAND_COLOR


# ═══════════════════════════════════════════════════════════════════════
# STARTUP — seed the default CareConnect hospital
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed the default hospital on startup (idempotent)."""
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        existing = db.get(models.Hospital, DEFAULT_HOSPITAL_ID)
        if not existing:
            db.add(models.Hospital(
                id=DEFAULT_HOSPITAL_ID,
                name=DEFAULT_HOSPITAL_NAME,
                brand_color=DEFAULT_HOSPITAL_BRAND_COLOR,
            ))
            db.commit()
            print(f"✅ Seeded default hospital: {DEFAULT_HOSPITAL_NAME} ({DEFAULT_HOSPITAL_ID})")
        else:
            print(f"✅ Default hospital already exists: {existing.name}")
    finally:
        db.close()
    yield


app = FastAPI(
    title="CareConnect API",
    description="Multi-tenant healthcare platform backend",
    version="0.1.0",
    lifespan=lifespan,
)

# ═══════════════════════════════════════════════════════════════════════
# CORS — allow frontends to connect
# ═══════════════════════════════════════════════════════════════════════

# 1. Define the origins that are allowed to talk to this backend
origins = [
    "http://localhost:3000",      # Your Next.js web dashboard
    "http://127.0.0.1:3000",      # Alternate localhost syntax
    "http://localhost:8081",      # Expo web (if you run it in a browser)
    "*"                           # Wildcard for local mobile development
]

# 2. Add the CORS middleware to the application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,        # Allows the origins listed above
    allow_credentials=True,       # Allows cookies and credentials
    allow_methods=["*"],          # Allows all HTTP methods (GET, POST, PUT, DELETE, OPTIONS)
    allow_headers=["*"],          # Allows all headers (Authorization, Content-Type, etc.)
)

# ═══════════════════════════════════════════════════════════════════════
# ROUTERS
# ═══════════════════════════════════════════════════════════════════════

app.include_router(auth_router)       # /auth/register/*, /auth/login
app.include_router(api_router)        # /api/me
app.include_router(hospitals.router)  # /hospitals, /hospitals/{id}/branding
app.include_router(doctors.router)    # /doctors, /doctors/profile, /doctors/onboarding, /doctors/availability
app.include_router(patients.router)   # /patients
app.include_router(appointments.router)  # /appointments
app.include_router(records.router)       # /medical-records, /patients/{id}/records


# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "service": "careconnect-api"}
