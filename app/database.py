from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=20,        # 20 persistent connections
    max_overflow=30,     # burst up to 50 total (20 + 30)
    pool_pre_ping=True,  # verify connection is alive before using
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
    cursor.execute("RESET app.current_hospital_id")
    cursor.execute("RESET app.current_user_id")
    cursor.execute("RESET app.current_role")
    cursor.execute("RESET app.current_doctor_id")
    cursor.execute("RESET app.current_caregiver_id")
    cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
