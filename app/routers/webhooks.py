"""
CareConnect — LiveKit Webhook Router

Endpoint:
  POST /webhook/livekit  →  Receives signed events from LiveKit Egress

Flow:
  1. Validate the webhook signature (401 if invalid)
  2. Ignore all events except 'egress_ended'
  3. Extract the recording file path from the egress payload
  4. Download the audio bytes from MinIO (S3-compatible storage)
  5. Pipe into the AI pipeline (transcription → summarisation)
  6. Persist the PostCallSummary and update appointment status
  7. Delete the recording from MinIO to free storage

This endpoint is NOT protected by get_current_user — it is called
by LiveKit's infrastructure, not by a browser/app user. Security
comes from cryptographic signature validation instead.
"""

import json
import logging
import asyncio
import uuid
from datetime import datetime, timezone

from azure.storage.blob.aio import BlobServiceClient
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

from livekit import api as livekit_api

from app.config import settings
from app import models, crud, database
from app.services.transcription import generate_transcript
from app.services.summary import generate_clinical_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Webhooks"])

# ═══════════════════════════════════════════════════════════════════════
# WEBHOOK RECEIVER — initialised once at module load
# ═══════════════════════════════════════════════════════════════════════

_token_verifier = livekit_api.TokenVerifier(
    api_key=settings.LIVEKIT_API_KEY,
    api_secret=settings.LIVEKIT_API_SECRET,
)
_webhook_receiver = livekit_api.WebhookReceiver(token_verifier=_token_verifier)

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _parse_appointment_id(room_name: str) -> uuid.UUID:
    """
    Our rooms are named 'cc-{appointment_id}'.
    Extract and return the UUID portion.
    """
    if not room_name or not room_name.startswith("cc-"):
        raise ValueError(f"Unexpected room name format: {room_name}")
    return uuid.UUID(room_name[3:])


# ═══════════════════════════════════════════════════════════════════════
# POST /webhooks/livekit — LiveKit event receiver
# ═══════════════════════════════════════════════════════════════════════


@router.post("/livekit", status_code=status.HTTP_200_OK)
async def handle_livekit_webhook(
    request: Request,
    db: Session = Depends(database.get_db),
):
    """
    Receive and process signed webhook events from LiveKit.

    Only 'egress_ended' events trigger the AI pipeline.
    All other events are acknowledged with 200 OK and ignored.
    """

    # ── 1. Read raw body (required for signature validation) ─────────
    raw_body = await request.body()
    auth_header = request.headers.get("Authorization", "")

    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    # ── 2. Validate signature ────────────────────────────────────────
    try:
        event = _webhook_receiver.receive(raw_body.decode("utf-8"), auth_header)
    except Exception as e:
        logger.warning("Webhook signature validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    logger.info("Received LiveKit event: %s", event.event)

    # ── 3. Only process egress_ended ─────────────────────────────────
    if event.event != "egress_ended":
        return {"status": "ignored", "event": event.event}

    # ── 4. Extract recording info from egress payload ────────────────
    egress_info = event.egress_info
    if not egress_info:
        logger.error("egress_ended event received but egress_info is missing")
        return {"status": "error", "detail": "No egress_info in payload"}

    room_name = egress_info.room_name
    logger.info("Egress ended for room: %s (egress_id: %s)", room_name, egress_info.egress_id)

    # Extract the recording file key from egress results
    s3_key = None
    if egress_info.file_results:
        file_info = egress_info.file_results[0]
        s3_key = file_info.filename
        logger.info(
            "Recording file: %s (size: %s bytes, duration: %ss)",
            file_info.filename, file_info.size, file_info.duration,
        )

    if not s3_key:
        logger.error("No file_results found in egress_ended event for room %s", room_name)
        return {"status": "error", "detail": "No recording file in egress payload"}

    # ── 5. Resolve the appointment from room name ────────────────────
    try:
        appointment_id = _parse_appointment_id(room_name)
    except ValueError as e:
        logger.error("Could not parse appointment ID from room name: %s", e)
        return {"status": "error", "detail": str(e)}

    appointment = crud.get_appointment_by_id(db, appointment_id)
    if not appointment:
        logger.error("Appointment %s not found in database", appointment_id)
        return {"status": "error", "detail": "Appointment not found"}

    # ── 6. Download audio from Azure Blob Storage ──────────
    conn_str = f"DefaultEndpointsProtocol=https;AccountName={settings.AZURE_STORAGE_ACCOUNT_NAME};AccountKey={settings.AZURE_STORAGE_ACCOUNT_KEY};EndpointSuffix=core.windows.net"
    blob_service_client = BlobServiceClient.from_connection_string(conn_str)
    blob_client = blob_service_client.get_blob_client(container=settings.AZURE_STORAGE_CONTAINER_NAME, blob=s3_key)

    try:
        stream = await blob_client.download_blob()
        audio_bytes = await stream.readall()
    except Exception as e:
        logger.critical("Recording NOT FOUND in Azure at blob '%s'. Error: %s", s3_key, e)
        await blob_service_client.close()
        return {"status": "error", "detail": f"Recording not found in Azure: {s3_key}"}

    if not audio_bytes:
        logger.critical("Recording is empty: %s", s3_key)
        await blob_service_client.close()
        return {"status": "error", "detail": f"Recording is empty: {s3_key}"}

    logger.info("Read %d bytes from recording: %s", len(audio_bytes), s3_key)

    # ── 7. TRANSCRIPTION — Convert audio to text ─────────────────────
    logger.info("Starting transcription for appointment %s...", appointment_id)
    try:
        transcript = await generate_transcript(audio_bytes, vendor="sarvam")
    except HTTPException:
        raise  # Let FastAPI handle it
    except Exception as e:
        logger.error("Transcription failed for appointment %s: %s", appointment_id, e)
        return {"status": "error", "detail": f"Transcription failed: {e}"}

    logger.info(
        "Transcription complete for appointment %s — %d chars",
        appointment_id, len(transcript),
    )

    # ── 8. GATHER CONTEXT — Prescriptions + Doctor Notes ─────────────
    # Fetch prescriptions for this patient
    prescriptions_raw = (
        db.query(models.Prescription)
        .filter(models.Prescription.patient_id == appointment.patient_id)
        .all()
    )
    prescriptions = [
        {
            "medication_name": p.medication_name,
            "dosage": p.dosage,
            "frequency": p.frequency,
            "duration": p.duration,
            "notes": p.notes,
        }
        for p in prescriptions_raw
    ]

    # Fetch doctor notes for this appointment
    doctor_notes_raw = crud.get_notes_by_appointment(db, appointment_id)
    doctor_notes = [
        {"content": n.content}
        for n in doctor_notes_raw
    ]

    logger.info(
        "Context gathered — %d prescriptions, %d doctor notes",
        len(prescriptions), len(doctor_notes),
    )

    # ── 9. SUMMARISATION — Generate bilingual clinical summary ───────
    logger.info("Starting clinical summary generation for appointment %s...", appointment_id)
    try:
        summary = await generate_clinical_summary(
            transcript=transcript,
            prescriptions=prescriptions,
            doctor_notes=doctor_notes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Summary generation failed for appointment %s: %s", appointment_id, e)
        return {"status": "error", "detail": f"Summary generation failed: {e}"}

    logger.info("Clinical summary generated for appointment %s", appointment_id)

    # ── 10. PERSIST — Save PostCallSummary to database ───────────────
    # Refresh DB session — the AI pipeline above may have taken minutes,
    # and the connection pool may have reclaimed our connection.
    db.expire_all()

    summary_data = {
        "diagnosis": summary.get("diagnosis", {}).get("english", ""),
        "symptoms": summary.get("symptoms", {}).get("english", []),
        "treatment_plan": summary.get("treatment_plan", {}).get("english", ""),
        "prescriptions": summary.get("structured_prescriptions", []),
        "follow_up": summary.get("next_steps", {}).get("english", ""),
        "doctor_notes": "\n".join(n.get("content", "") for n in doctor_notes) or None,
        "transcript": transcript,
        "summary": json.dumps(summary, ensure_ascii=False),  # Valid JSON for frontend
    }

    try:
        post_call_summary = crud.create_post_call_summary(
            db=db,
            appointment_id=appointment_id,
            summary_data=summary_data,
        )
        logger.info(
            "PostCallSummary created (id: %s) for appointment %s",
            post_call_summary.id, appointment_id,
        )
    except Exception as e:
        logger.error("Failed to persist PostCallSummary: %s", e)
        return {"status": "error", "detail": f"Database save failed: {e}"}

    # ── 11. UPDATE STATUS — Mark appointment as COMPLETED ────────────
    try:
        appointment.status = models.AppointmentStatusEnum.COMPLETED
        db.commit()
        logger.info("Appointment %s status updated to COMPLETED", appointment_id)
    except Exception as e:
        logger.error("Failed to update appointment status: %s", e)

    # ── 12. UPDATE VIDEO SESSION — Set ended_at + duration ───────────
    try:
        video_session = (
            db.query(models.VideoSession)
            .filter(models.VideoSession.appointment_id == appointment_id)
            .first()
        )
        if video_session:
            now = datetime.now(timezone.utc)
            video_session.ended_at = now
            if video_session.started_at:
                duration = (now - video_session.started_at).total_seconds() / 60
                video_session.actual_duration_minutes = int(duration)
            db.commit()
            logger.info(
                "VideoSession updated — ended_at: %s, duration: %s min",
                video_session.ended_at,
                video_session.actual_duration_minutes,
            )
    except Exception as e:
        logger.error("Failed to update VideoSession: %s", e)

    # ── 13. CLEANUP — Delete recording from Azure to free storage ─────
    try:
        await blob_client.delete_blob()
        logger.info("Deleted recording from Azure: %s", s3_key)
    except Exception as e:
        logger.warning("Could not delete blob %s from Azure: %s", s3_key, e)
    finally:
        await blob_service_client.close()

    return {
        "status": "ok",
        "event": "egress_ended",
        "appointment_id": str(appointment_id),
        "summary_id": str(post_call_summary.id),
        "transcript_length": len(transcript),
        "detected_language": summary.get("detected_patient_language", "unknown"),
    }
