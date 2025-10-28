"""OpenAI Vision extraction for PDFs/images (Chat Completions JSON mode) with robust error logging and fallback.
Drop-in replacement for business_hub/ai.py.

Requires:
  pip install openai==2.1.0 pymupdf pillow

Environment knobs (optional):
  - OPENAI_API_KEY                 : your key
  - OPENAI_CLASSIFIER_MODEL        : default "o3" (fallback to "gpt-4o-mini" if needed)
  - OPENAI_EXTRACTION_MODEL        : default "o3" (fallback to "gpt-4o-mini" if needed)
  - VISION_MAX_PAGES               : default 2
  - VISION_DPI                     : default 180
  - VISION_MAX_WIDTH               : default 1800 (pixels) - images larger than this are downscaled
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple

from PIL import Image
import fitz  # PyMuPDF

from openai import (
    OpenAI,
    APIError,
    APIConnectionError,
    RateLimitError,
    BadRequestError,
    AuthenticationError,
)

from .models import (
    Document,
    DocumentType,
    Extraction,
    InvoiceFields,
    LineItem,
    ReceiptFields,
    Record,
)
from .storage import upsert_extraction, upsert_record

logger = logging.getLogger(__name__)

# Defaults can be overridden via env vars
MAX_PAGES = int(os.getenv("VISION_MAX_PAGES", "2"))
DPI = int(os.getenv("VISION_DPI", "180"))
MAX_WIDTH = int(os.getenv("VISION_MAX_WIDTH", "1800"))
CLASSIFIER_MODEL = os.getenv("OPENAI_CLASSIFIER_MODEL", "o3")
EXTRACTION_MODEL = os.getenv("OPENAI_EXTRACTION_MODEL", "o3")
FALLBACK_MODEL = "gpt-4o-mini"

# --- company + classifier prompt -------------------------------------------------
COMPANY_NAME = os.getenv("BUSINESS_NAME", "TDS Distilling")

# Teach the model that “invoice” can mean AR (ours) or AP (vendor bill),
# and ask it to also return a direction (incoming/outgoing).
CLASSIFIER_PROMPT = (
    "You classify business documents from images for the company '" + COMPANY_NAME + "'. "
    "Return JSON only with fields: "
    "`type` in {invoice_ar, vendor_bill_ap, receipt, estimate, purchase_order, email, shipping_record, other}, "
    "`confidence` in [0,1], and `direction` in {incoming, outgoing}. "
    "Important: the word 'invoice' is ambiguous. "
    "If a vendor is billing us (payables), set type=vendor_bill_ap and direction=incoming. "
    "If it is OUR invoice to a customer (receivables), set type=invoice_ar and direction=outgoing. "
    "Use visible headers (Invoice/Estimate), Bill To / Ship To, Remit/Pay To, who is charging whom, "
    "line items, totals, and payment instructions to decide."
)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def _downscale(img: Image.Image, max_width: int = MAX_WIDTH) -> Image.Image:
    if img.width <= max_width:
        return img
    ratio = max_width / float(img.width)
    new_size = (max_width, int(img.height * ratio))
    return img.resize(new_size, Image.LANCZOS)


def _img_to_b64(img: Image.Image, *, fmt: str = "JPEG", quality: int = 80) -> str:
    """Encode a PIL image to base64 for a data URL (with optional downscale)."""
    img = _downscale(img)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _pdf_to_images(path: str, max_pages: int = MAX_PAGES, dpi: int = DPI) -> List[Image.Image]:
    images: List[Image.Image] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pm = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pm.width, pm.height], pm.samples)
            images.append(img)
    return images


def _chat_json_with_images(system_prompt: str, user_prompt: str, images: List[Image.Image], *, model: str) -> Dict[str, Any]:
    """Send images + prompt to Chat Completions JSON mode and return parsed dict.
       Uses 'text' and 'image_url' parts; falls back to FALLBACK_MODEL on BadRequestError.
    """
    client = _get_client()

    # Build the user content as a list of parts: text + one part per page image.
    content_parts: List[dict] = [
        {"type": "text", "text": user_prompt + "\n\nReturn JSON only."}
    ]
    for img in images:
        b64 = _img_to_b64(img)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    def _once(use_model: str) -> Dict[str, Any]:
        kwargs = {
            "model": use_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt + " Always respond with a valid JSON object and nothing else."},
                {"role": "user", "content": content_parts},
            ],
        }
        # o3/o3-mini reject non-default temperature; only set for non-o3 models
        if not use_model.startswith("o3"):
            kwargs["temperature"] = 0.2

        chat = client.chat.completions.create(**kwargs)
        raw = chat.choices[0].message.content
        return json.loads(raw)

    try:
        try:
            return _once(model)
        except BadRequestError as bre:
            # Surface detailed error for logs
            logger.error("Model %s rejected vision request: %s", model, getattr(bre, "message", str(bre)))
            # If the primary model fails (e.g., o3 not enabled for vision), try a safe fallback
            if model != FALLBACK_MODEL:
                logger.info("Falling back to %s for vision call...", FALLBACK_MODEL)
                return _once(FALLBACK_MODEL)
            raise
    except (APIError, APIConnectionError, RateLimitError, BadRequestError, AuthenticationError) as exc:
        # Bubble up a helpful error that includes model and (if present) API message
        msg = getattr(exc, "message", str(exc))
        body = getattr(exc, "body", None)
        raise RuntimeError(f"OpenAI vision call failed for model '{model}'. Message: {msg}. Body: {body}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON returned by OpenAI (non-JSON output).") from exc


# Map both AR and AP flavors to your storage type (INVOICE) while preserving nuance in payload
DOC_TYPE_MAP = {
    "invoice_ar": DocumentType.INVOICE,      # our outbound invoice (AR)
    "vendor_bill_ap": DocumentType.INVOICE,  # inbound vendor bill (AP)
    "receipt": DocumentType.RECEIPT,
    "estimate": DocumentType.PURCHASE_ORDER,   # map however your app expects
    "purchase_order": DocumentType.PURCHASE_ORDER,
    "email": DocumentType.EMAIL,
    "shipping_record": DocumentType.OTHER,
    "other": DocumentType.OTHER,
}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string"},
        "due_date": {"type": "string"},
        "currency": {"type": "string"},
        "total": {"type": "number"},
        "tax": {"type": "number"},
        "payment_terms": {"type": "string"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "qty": {"type": "number"},
                    "description": {"type": "string"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["vendor", "invoice_number", "total"],
    "additionalProperties": False,
}

INVOICE_PROMPT = (
    "Extract an invoice into JSON matching this schema. Use the PDF images to read values. "
    "Schema: {schema}. For line items, include cost/amount for each row when visible."
)

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "datetime": {"type": "string"},
        "subtotal": {"type": "number"},
        "tip": {"type": "number"},
        "total": {"type": "number"},
        "category": {"type": "string"},
    },
    "required": ["merchant", "total"],
    "additionalProperties": False,
}

RECEIPT_PROMPT = (
    "Extract a purchase receipt into JSON matching this schema. Use the PDF images to read values. "
    "Schema: {schema}. If unclear, leave fields out rather than guessing."
)


def _classify_document_vision(images: List[Image.Image]) -> Tuple[DocumentType, float, Dict[str, Any]]:
    payload = _chat_json_with_images(
        system_prompt=CLASSIFIER_PROMPT,
        user_prompt="Classify the document shown in the following images.",
        images=images,
        model=CLASSIFIER_MODEL,
    )
    # payload: { type: ..., confidence: ..., direction: incoming|outgoing }
    kind = payload.get("type", "other")
    doc_type = DOC_TYPE_MAP.get(kind, DocumentType.OTHER)
    confidence = float(payload.get("confidence", 0.0))
    # Keep raw payload (includes direction)
    metadata = {"payload": payload, "model": CLASSIFIER_MODEL}
    return doc_type, confidence, metadata


def _extract_invoice_fields_vision(images: List[Image.Image]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    schema_json = json.dumps(INVOICE_SCHEMA, separators=(",", ":"))
    payload = _chat_json_with_images(
        system_prompt="You are an expert at reading invoices from images into strict JSON.",
        user_prompt=INVOICE_PROMPT.format(schema=schema_json),
        images=images,
        model=EXTRACTION_MODEL,
    )
    metadata = {"model": EXTRACTION_MODEL, "payload": payload}
    return payload, metadata


def _extract_receipt_fields_vision(images: List[Image.Image]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    schema_json = json.dumps(RECEIPT_SCHEMA, separators=(",", ":"))
    payload = _chat_json_with_images(
        system_prompt="You are an expert at reading receipts from images into strict JSON.",
        user_prompt=RECEIPT_PROMPT.format(schema=schema_json),
        images=images,
        model=EXTRACTION_MODEL,
    )
    metadata = {"model": EXTRACTION_MODEL, "payload": payload}
    return payload, metadata


def _normalize_invoice_fields(fields: Dict[str, Any], fallback_id: str) -> Dict[str, Any]:
    from datetime import datetime as _dt, date as _date, datetime as _datetime

    data = dict(fields)
    data.setdefault("vendor", "Unknown Vendor")
    data.setdefault("invoice_number", f"INV-{fallback_id[-6:]}" if fallback_id else "INV-UNKNOWN")
    data.setdefault("total", 0.0)

    # normalize line items into model
    line_items = data.get("line_items", [])
    normalized_items = [LineItem(**item) for item in line_items]
    data["line_items"] = normalized_items

    # 1) Parse common string dates into real date objects
    for k in ("invoice_date", "due_date"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    data[k] = _dt.strptime(v.strip(), fmt).date()
                    break
                except Exception:
                    pass

    # Validate against pydantic model
    normalized = InvoiceFields(**data).dict(exclude_none=True)
    normalized["line_items"] = [item.dict(exclude_none=True) for item in normalized_items]

    # 2) Make dates JSON-safe (strings) for storage
    for k in ("invoice_date", "due_date"):
        v = normalized.get(k)
        if isinstance(v, (_date, _datetime)):
            normalized[k] = v.isoformat()

    return normalized

def _normalize_receipt_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(fields)
    data.setdefault("merchant", "Unknown Merchant")
    data.setdefault("total", 0.0)
    normalized = ReceiptFields(**data).dict(exclude_none=True)
    return normalized


def run_extraction(document: Document, text: str) -> Extraction:
    """Vision-first extraction: render PDF pages -> images -> vision model.
    Falls back to a text summary if rendering fails.
    """
    images: List[Image.Image] = []
    try:
        if document.mime == "application/pdf" and os.path.exists(document.storage_path):
            images = _pdf_to_images(document.storage_path, max_pages=MAX_PAGES, dpi=DPI)
    except Exception as e:
        logger.exception("PDF render failed: %s", e)

    raw_json: Dict[str, Any] = {}
    fields: Dict[str, Any]
    schema = "generic_v1"
    model_used = EXTRACTION_MODEL
    confidence = 0.0
    doc_type = DocumentType.OTHER

    if images:
        doc_type, confidence, classifier_meta = _classify_document_vision(images)
        payload = (classifier_meta.get("payload") or {}) if classifier_meta else {}
        direction = payload.get("direction")
        raw_json = {"classifier": classifier_meta, "direction": direction}

        if doc_type == DocumentType.INVOICE:
            invoice_payload, meta = _extract_invoice_fields_vision(images)
            fields = _normalize_invoice_fields(invoice_payload, document.id)
            raw_json["extraction"] = meta
            model_used = meta.get("model", EXTRACTION_MODEL)
            schema = "invoice_v1"
        elif doc_type == DocumentType.RECEIPT:
            receipt_payload, meta = _extract_receipt_fields_vision(images)
            fields = _normalize_receipt_fields(receipt_payload)
            raw_json["extraction"] = meta
            model_used = meta.get("model", EXTRACTION_MODEL)
            schema = "receipt_v1"
        else:
            payload = _chat_json_with_images(
                system_prompt="Summarize the main contents of the document as JSON.",
                user_prompt='Return JSON with {"summary": "..."} capturing totals, parties, dates if visible.',
                images=images,
                model=EXTRACTION_MODEL,
            )
            fields = {"summary": payload.get("summary", "")}



        # add direction for the UI (if present)
        if isinstance(fields, dict) and direction:
            fields["direction"] = direction

    else:
        # Could not render images; degrade gracefully to a text-only summary
        fields = {"summary": text[:500]}
        raw_json["classifier"] = {"payload": {"type": "other", "confidence": 0.0}, "model": CLASSIFIER_MODEL}

    # Friendly suggestion string for the chat UI
    try:
        vendor = (
            fields.get("vendor")
            or (fields.get("bill_to") or {}).get("company")
            or (fields.get("ship_to") or {}).get("company")
            or "Unknown vendor"
        ) if isinstance(fields, dict) else "Unknown vendor"
        number = None
        if isinstance(fields, dict):
            number = fields.get("invoice_number") or fields.get("estimate_number") or fields.get("po_number")
        qty_total = None
        if isinstance(fields, dict) and isinstance(fields.get("line_items"), list) and fields["line_items"]:
            qty_total = sum((li.get("qty") or li.get("quantity") or 0) for li in fields["line_items"] if isinstance(li, dict))
        total_amount = fields.get("total") if isinstance(fields, dict) else None
        kind_word = (
            "estimate" if (isinstance(fields, dict) and ("estimate_number" in fields or "estimate" in (fields.get("type") or ""))) 
            else ("invoice" if isinstance(fields, dict) and ("invoice_number" in fields or (fields.get("direction") in ("incoming","outgoing"))) else "document")
        )

        suggestion = (
            f"I think this is an {kind_word} from {vendor}"
            + (f" for ~{qty_total} units" if qty_total else "")
            + (f" totaling ${total_amount}" if isinstance(total_amount, (int, float)) else "")
            + f". Would you like me to add this to {COMPANY_NAME}'s database?"
        )
        raw_json["suggestion"] = suggestion
    except Exception:
        # never block extraction on UX sugar
        pass

    extraction = Extraction(
        id=f"ext_{uuid.uuid4().hex[:12]}",
        doc_id=document.id,
        model=model_used,
        schema=schema,
        fields=fields,
        confidence=confidence,
        raw_json=raw_json,
        created_at=datetime.utcnow(),
    )
    upsert_extraction(extraction)

    record = Record(
        id=f"rec_{uuid.uuid4().hex[:12]}",
        document_id=document.id,
        extraction_id=extraction.id,
        type=doc_type,
        fields=fields,
        created_at=datetime.utcnow(),
    )
    upsert_record(record)
    return extraction
