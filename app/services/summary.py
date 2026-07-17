"""
CareConnect — Clinical Summary Service

LangChain pipeline that merges a call transcript with database prescriptions
and doctor notes, then generates a strict dual-language (English + patient's
native language) clinical summary via Groq's high-speed inference.

LLM:    ChatGroq  →  openai/gpt-oss-120b  →  temperature=0
Output: ClinicalSummary (Pydantic structured output)

Interface:
  async def generate_clinical_summary(
      transcript: str,
      prescriptions: List[dict] = [],
      doctor_notes: List[dict] = [],
  ) -> dict
"""

import time
import logging
from typing import List

from pydantic import BaseModel, Field, SecretStr
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# PYDANTIC OUTPUT SCHEMA — Bilingual Clinical Summary
# ═══════════════════════════════════════════════════════════════════════


class BilingualText(BaseModel):
    english: str
    local_language: str


class BilingualList(BaseModel):
    english: List[str]
    local_language: List[str]


class ClinicalSummary(BaseModel):
    detected_patient_language: str = Field(
        description="The primary language the patient spoke "
                    "(e.g., 'Hindi', 'Marathi', 'English')."
    )
    diagnosis: BilingualText = Field(
        description="The primary diagnosis inferred from the "
                    "doctor's notes and transcript."
    )
    symptoms: BilingualList = Field(
        description="List of symptoms mentioned by the patient."
    )
    treatment_plan: BilingualText = Field(
        description="Overall treatment plan and advice."
    )
    next_steps: BilingualText = Field(
        description="Follow-up instructions or immediate next steps."
    )
    structured_prescriptions: List[str] = Field(
        description="Formatted list of medications, dosages, "
                    "and frequencies in English."
    )


# ═══════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════

CLINICAL_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert clinical AI. Analyze the provided Call Transcript, "
        "the Doctor's Private Notes, and the Patient's Medical History (Prescribed Medications). "
        "IMPORTANT: The 'Prescribed Medications' list contains the patient's PAST and CHRONIC medications. "
        "This medical history is provided ONLY as context to prevent hallucinations and clarify any ambiguous information mentioned during the call (e.g., garbled medication names). "
        "If the call transcript can be summarized without ambiguity using just the data provided during the call, do NOT mix the contextual medical history into the call summary. "
        "Your generated summary, diagnosis, and prescription list MUST ONLY reflect the acute issues, advice, and new medications provided during THIS specific call. "
        "Generate the summary in both English and the language the patient "
        "was speaking. Ensure the translation uses culturally appropriate "
        "medical terminology."
    ),
    (
        "human",
        "## Call Transcript\n{transcript}\n\n"
        "## Doctor's Private Notes\n{doctor_notes}\n\n"
        "## Prescribed Medications\n{prescriptions}"
    ),
])


# ═══════════════════════════════════════════════════════════════════════
# LLM INITIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _get_llm() -> ChatGroq:
    """
    Initialise the Groq LLM client.

    Deferred initialisation so we fail fast with a clear message
    if the API key is missing, rather than at module import time.
    """
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GROQ_API_KEY is not configured.",
        )

    return ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0,
        api_key=SecretStr(settings.GROQ_API_KEY),
    )


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ═══════════════════════════════════════════════════════════════════════


async def generate_clinical_summary(
    transcript: str,
    prescriptions: List[dict] = [],
    doctor_notes: List[dict] = [],
) -> dict:
    """
    Generate a bilingual clinical summary from a consultation.

    Args:
        transcript:     Raw text transcript of the video call.
        prescriptions:  List of prescription dicts from the database
                        (e.g. [{"medication_name": "...", "dosage": "...", ...}]).
        doctor_notes:   List of doctor note dicts from the database
                        (e.g. [{"content": "...", "created_at": "..."}]).

    Returns:
        A dict matching the ClinicalSummary schema with bilingual fields.

    Raises:
        HTTPException(500) if the LLM call fails.
    """
    llm = _get_llm()

    # Build the structured LLM chain
    chain = CLINICAL_PROMPT | llm.with_structured_output(ClinicalSummary)

    # Stringify the context for injection into the prompt
    prescriptions_str = "\n".join(
        f"- {p.get('medication_name', 'Unknown')}: "
        f"{p.get('dosage', '')} {p.get('frequency', '')} "
        f"for {p.get('duration', 'unspecified')}"
        f"{' — ' + p['notes'] if p.get('notes') else ''}"
        for p in prescriptions
    ) or "No prescriptions recorded."

    doctor_notes_str = "\n".join(
        f"- {n.get('content', '')}"
        for n in doctor_notes
    ) or "No doctor notes recorded."

    logger.info(
        "Generating clinical summary — transcript: %d chars, "
        "%d prescriptions, %d doctor notes",
        len(transcript), len(prescriptions), len(doctor_notes),
    )

    start = time.perf_counter()

    try:
        result: ClinicalSummary = await chain.ainvoke({ # type: ignore
            "transcript": transcript or "No transcript available.",
            "prescriptions": prescriptions_str,
            "doctor_notes": doctor_notes_str,
        })
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error(
            "Groq LLM call failed after %.2fs: %s", elapsed, e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Clinical summary generation failed: {e}",
        )

    elapsed = time.perf_counter() - start
    logger.info("Clinical summary generated in %.2fs via Groq", elapsed)

    return result.model_dump()
