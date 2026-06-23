"""
CareConnect API — Application Entry Point

Multi-tenant healthcare backend with JWT auth and PostgreSQL RLS.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers.auth import auth_router, api_router
from app.routers import doctors, patients, appointments, records, hospitals, webhooks, notes, admin
from app.constants import DEFAULT_HOSPITAL_ID, DEFAULT_HOSPITAL_NAME, DEFAULT_HOSPITAL_BRAND_COLOR
from app.database import engine


# ═══════════════════════════════════════════════════════════════════════
# STARTUP — seed the default CareConnect hospital
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed the default hospital on startup (idempotent)."""
    from app.database import AsyncSessionLocal
    from app import models

    async with AsyncSessionLocal() as db:
        existing = await db.get(models.Hospital, DEFAULT_HOSPITAL_ID)
        if not existing:
            db.add(models.Hospital(
                id=DEFAULT_HOSPITAL_ID,
                name=DEFAULT_HOSPITAL_NAME,
                brand_color=DEFAULT_HOSPITAL_BRAND_COLOR,
            ))
            await db.commit()
            print(f"✅ Seeded default hospital: {DEFAULT_HOSPITAL_NAME} ({DEFAULT_HOSPITAL_ID})")
        else:
            print(f"✅ Default hospital already exists: {existing.name}")

    yield

    # ── Shutdown: dispose the connection pool cleanly ───────────
    await engine.dispose()
    print("🔌 Connection pool disposed")


app = FastAPI(
    title="CareConnect API",
    description="Multi-tenant healthcare platform backend",
    version="0.1.0",
    lifespan=lifespan,
)

# ═══════════════════════════════════════════════════════════════════════
# CORS — allow frontends to connect
# ═══════════════════════════════════════════════════════════════════════

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"OMFG Validation Error: {exc.errors()}")
    print(f"OMFG Body: {exc.body}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

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
app.include_router(webhooks.router)      # /webhook/livekit
app.include_router(notes.router)         # /doctor-notes
app.include_router(admin.router)         # /admin/*

# Ensure uploads folder exists
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")



# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "service": "careconnect-api"}


@app.get("/health/db", tags=["System"])
def db_pool_health():
    """Report connection pool statistics for monitoring."""
    pool = engine.sync_engine.pool
    return {
        "status": "ok",
        "pool_size": pool.size(), # type: ignore
        "checked_out": pool.checkedout(), # type: ignore
        "checked_in": pool.checkedin(), # type: ignore
        "overflow": pool.overflow(), # type: ignore
        "total_active": pool.checkedout() + pool.checkedin(), # type: ignore
    }
