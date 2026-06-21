import base64
import logging
from pydantic import BaseModel, Field, SecretStr
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langchain_core.output_parsers import PydanticOutputParser
from app.config import settings

logger = logging.getLogger(__name__)

class LicenseVerificationResult(BaseModel):
    is_valid: bool = Field(description="True if the document appears to be a valid medical license, false otherwise.")
    license_number: str = Field(description="The extracted medical license number, or empty string if not found.")
    license_state: str = Field(description="The state or region where the license was issued, or empty string if not found.")

def _get_vision_llm() -> ChatGroq:
    return ChatGroq(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        api_key=SecretStr(settings.GROQ_API_KEY),
        temperature=0,
    )

def _convert_pdf_to_base64_image(file_bytes: bytes) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open("pdf", file_bytes)
    page = doc.load_page(0)  # first page
    pix = page.get_pixmap()
    img_bytes = pix.tobytes("jpeg")
    return base64.b64encode(img_bytes).decode("utf-8")

async def verify_medical_license(file_bytes: bytes, filename: str) -> dict:
    """
    Verifies if a document is a medical license and extracts details.
    Uses PyMuPDF to convert PDFs to an image, then uses Groq Vision.
    """
    # 1. Prepare base64 image
    base64_image = ""
    if filename.lower().endswith(".pdf"):
        logger.info("Converting PDF to image for vision processing")
        base64_image = _convert_pdf_to_base64_image(file_bytes)
    else:
        # Assume it's an image
        base64_image = base64.b64encode(file_bytes).decode("utf-8")

    # 2. Prepare Langchain parser and prompt
    parser = PydanticOutputParser(pydantic_object=LicenseVerificationResult)
    format_instructions = parser.get_format_instructions()

    prompt_text = (
        "You are an AI assistant that verifies medical licenses. "
        "Examine the provided document image. Determine if it is a valid medical license. "
        "If it is, extract the license number and the state/region of issuance.\n\n"
        f"{format_instructions}"
    )

    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]
    )

    llm = _get_vision_llm()

    try:
        response = await llm.ainvoke([message])
        content_str = response.content if isinstance(response.content, str) else str(response.content)
        result = parser.parse(content_str)
        return result.model_dump()
    except Exception as e:
        logger.error(f"Vision API error: {e}")
        # Return a safe fallback if parsing fails
        return {
            "is_valid": False,
            "license_number": "",
            "license_state": "",
        }
