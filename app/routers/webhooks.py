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

# from azure.storage.blob.aio import BlobServiceClient
import boto3
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
    db: AsyncSession = Depends(database.get_db),
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

    # ── 3. Handle participant_joined — track remote participants ─────
    # When a non-doctor participant (caregiver/patient) joins the room,
    # set remote_participant_joined = True on the VideoSession so the
    # egress_ended handler knows the AI pipeline should run.
    if event.event == "participant_joined":
        participant = event.participant
        room_name = event.room.name if event.room else None
        if participant and room_name and not participant.identity.startswith("doctor-"):
            try:
                appointment_id = _parse_appointment_id(room_name)
                video_session = (await db.execute(
                    select(models.VideoSession).where(
                        models.VideoSession.appointment_id == appointment_id
                    )
                )).scalar_one_or_none()
                if video_session and not video_session.remote_participant_joined:
                    video_session.remote_participant_joined = True
                    await db.commit()
                    logger.info(
                        "Remote participant joined room %s (identity: %s)",
                        room_name, participant.identity,
                    )
            except Exception as e:
                logger.warning("Could not update remote_participant_joined: %s", e)
        return {"status": "ok", "event": event.event}

    # ── 4. Only continue for egress_ended ────────────────────────────
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

    appointment = await crud.get_appointment_by_id(db, appointment_id) # type: ignore
    if not appointment:
        logger.error("Appointment %s not found in database", appointment_id)
        return {"status": "error", "detail": "Appointment not found"}

    # ── 5b. Guard: skip AI pipeline if no remote participant ever joined ──
    # If only the doctor was in the room (solo/aborted session), the recording
    # contains no patient/caregiver audio. Running transcription wastes quota
    # and causes Sarvam errors. Only proceed when remote_participant_joined=True.
    video_session_check = (await db.execute(
        select(models.VideoSession).where(
            models.VideoSession.appointment_id == appointment_id
        )
    )).scalar_one_or_none()

    if not video_session_check or not video_session_check.remote_participant_joined:
        logger.info(
            "Skipping AI pipeline for appointment %s — no remote participant joined",
            appointment_id,
        )
        return {"status": "skipped", "reason": "no_remote_participants", "appointment_id": str(appointment_id)}

    # ── 6. Download audio from AWS S3 ──────────
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )

    try:
        response = await asyncio.to_thread(
            s3_client.get_object,
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key
        )
        audio_bytes = response["Body"].read()
    except Exception as e:
        logger.critical("Recording NOT FOUND in S3 at key '%s'. Error: %s", s3_key, e)
        return {"status": "error", "detail": f"Recording not found in S3: {s3_key}"}

    # ── 6.5. IMMEDIATE CLEANUP — Delete recording from S3 to prevent leaks ─────
    # We delete it immediately after reading into RAM. If transcription fails later,
    # we don't leave orphaned files in S3 racking up storage costs.
    try:
        await asyncio.to_thread(
            s3_client.delete_object,
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key
        )
        logger.info("Deleted recording from S3 immediately after download: %s", s3_key)
    except Exception as e:
        logger.warning("Could not delete object %s from S3: %s", s3_key, e)

    if not audio_bytes:
        logger.critical("Recording is empty: %s", s3_key)
        return {"status": "error", "detail": f"Recording is empty: {s3_key}"}

    logger.info("Read %d bytes from recording: %s", len(audio_bytes), s3_key)

    # ── 7. TRANSCRIPTION — Convert audio to text ─────────────────────
    logger.info("Starting transcription for appointment %s...", appointment_id)
    try:
        transcript = await generate_transcript(audio_bytes, vendor="deepgram")
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
    prescriptions_raw = (await db.execute(
        select(models.Prescription)
        .where(models.Prescription.patient_id == appointment.patient_id)
    )).scalars().all()
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
    doctor_notes_raw = await crud.get_notes_by_appointment(db, appointment_id) # type: ignore
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
        "doctor_notes": "\n".join(str(n.get("content", "")) for n in doctor_notes) or None,
        "transcript": transcript,
        "summary": json.dumps(summary, ensure_ascii=False),  # Valid JSON for frontend
    }

    try:
        post_call_summary = await crud.create_post_call_summary(
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
        appointment.status = models.AppointmentStatusEnum.COMPLETED # type: ignore
        await db.commit()
        logger.info("Appointment %s status updated to COMPLETED", appointment_id)
    except Exception as e:
        logger.error("Failed to update appointment status: %s", e)

    # ── 12. UPDATE VIDEO SESSION — Set ended_at + duration ───────────
    try:
        video_session = (await db.execute(
            select(models.VideoSession)
            .where(models.VideoSession.appointment_id == appointment_id)
        )).scalar_one_or_none()
        if video_session:
            now = datetime.now(timezone.utc)
            video_session.ended_at = now
            if video_session.started_at:
                duration = (now - video_session.started_at).total_seconds() / 60
                video_session.actual_duration_minutes = int(duration)
            await db.commit()
            logger.info(
                "VideoSession updated — ended_at: %s, duration: %s min",
                video_session.ended_at,
                video_session.actual_duration_minutes,
            )
    except Exception as e:
        logger.error("Failed to update VideoSession: %s", e)

    # S3 Cleanup was handled immediately after download in Step 6.5

    return {
        "status": "ok",
        "event": "egress_ended",
        "appointment_id": str(appointment_id),
        "summary_id": str(post_call_summary.id),
        "transcript_length": len(transcript),
        "detected_language": summary.get("detected_patient_language", "unknown"),
    }
