from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,

    # ── Pool sizing ─────────────────────────────────────────────
    pool_size=settings.DB_POOL_SIZE,        # persistent connections kept alive
    max_overflow=settings.DB_MAX_OVERFLOW,   # burst connections beyond pool_size

    # ── Pool safety ─────────────────────────────────────────────
    pool_pre_ping=True,                     # verify connection liveness on checkout
    pool_recycle=settings.DB_POOL_RECYCLE,   # recycle conns after N seconds (prevents stale conns)
    pool_timeout=settings.DB_POOL_TIMEOUT,   # max wait for a free connection before TimeoutError

    # ── Debugging ───────────────────────────────────────────────
    echo_pool="debug" if settings.DB_ECHO_POOL else False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════
# POOL SAFETY: Reset RLS variables on every connection checkout.
#
# When a connection returns to the pool after a request, it may still
# carry SET session variables from the previous user. Without this
# listener, the next user to grab that connection would inherit stale
# RLS context — a cross-tenant data leak.
#
# With this reset, every connection starts CLEAN. If get_current_user
# doesn't run (e.g., unauthenticated route), all RLS policies
# default to DENY because current_setting(..., true) returns NULL.
# ═══════════════════════════════════════════════════════════════════════


@event.listens_for(engine, "checkout")
def reset_rls_variables(dbapi_conn, connection_record, connection_proxy):
    """Reset all RLS session variables when a connection is checked out."""
    cursor = dbapi_conn.cursor()
    # RESET doesn't support dotted GUC names — use SET ... TO DEFAULT instead
    cursor.execute("SET \"app.current_hospital_id\" TO DEFAULT")
    cursor.execute("SET \"app.current_user_id\" TO DEFAULT")
    cursor.execute("SET \"app.current_role\" TO DEFAULT")
    cursor.execute("SET \"app.current_doctor_id\" TO DEFAULT")
    cursor.execute("SET \"app.current_caregiver_id\" TO DEFAULT")
    cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
