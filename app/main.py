"""
CareConnect API — Application Entry Point

Multi-tenant healthcare backend with JWT auth and PostgreSQL RLS.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.auth import auth_router, api_router
from app.routers import doctors, patients

app = FastAPI(
    title="CareConnect API",
    description="Multi-tenant healthcare platform backend",
    version="0.1.0",
)

# ═══════════════════════════════════════════════════════════════════════
# CORS — allow frontends to connect
# ═══════════════════════════════════════════════════════════════════════

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js web app
        "http://localhost:8081",   # Expo mobile dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════
# ROUTERS
# ═══════════════════════════════════════════════════════════════════════

app.include_router(auth_router)       # /auth/register/*, /auth/login
app.include_router(api_router)        # /api/me
app.include_router(doctors.router)    # /doctors/profile, /doctors/onboarding, /doctors/availability
app.include_router(patients.router)   # /patients


# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "service": "careconnect-api"}
