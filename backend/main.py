# backend/main.py
"""FastAPI application for Business Hub."""
from __future__ import annotations
from difflib import SequenceMatcher
import hashlib
import re
import io
import json
import os, json, sqlite3
from pathlib import Path
from typing import Optional
from fastapi import Body
from typing import List


from pydantic import BaseModel, Field
import sqlite3, json


from business_hub.models import Extraction, Record, DocumentType
from business_hub.storage import upsert_extraction, upsert_record
from datetime import datetime
import uuid


from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from business_hub.ai import run_extraction, chat_with_ingestion
from business_hub.ingest import ingest_file
from business_hub.models import PdfFillProfile
from business_hub.pdf_fill import PdfFillError, fill_pdf
from business_hub.storage import export_records, list_records

# ---------------------------
# 1) Create the app ONCE
# ---------------------------
app = FastAPI(title="Smart File Cabinet", version="0.1.0")
DB_PATH = os.getenv("BUSINESS_HUB_DB", os.path.join("data", "business_hub.db"))

# CORS (keep as you had it)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ---------------------------
# 2) Serve / and /public/*
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
INDEX_FILE = PUBLIC_DIR / "index.html"

if PUBLIC_DIR.is_dir():
    # Mount /public for any additional assets
    app.mount("/public", StaticFiles(directory=str(PUBLIC_DIR)), name="public")

    @app.get("/", include_in_schema=False)
    def index():
        if INDEX_FILE.is_file():
            return FileResponse(str(INDEX_FILE))
        return PlainTextResponse(
            f"Missing file: {INDEX_FILE}. Create it or place your HTML there.",
            status_code=404,
        )
else:
    @app.get("/", include_in_schema=False)
    def index_missing():
        return PlainTextResponse(
            f"Missing folder: {PUBLIC_DIR}. Create it and add index.html.",
            status_code=404,
        )

# ---------------------------
# 3) Your existing endpoints
# ---------------------------


class ChatTurn(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    document: Optional[dict] = None
    extraction: Optional[dict] = None
    history: List[ChatTurn] = Field(default_factory=list)
    message: str


# In-memory demo store (replace with real DB later)
def _db():
    # row_factory returns dict-like rows
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _row_to_ap_item(row):
    """
    Convert a records row to the AP item the widget expects.
    We only include invoices that are vendor bills (direction='incoming').
    """
    try:
        fields = json.loads(row["fields"]) if isinstance(row["fields"], str) else row["fields"]
    except Exception:
        fields = {}

    direction = (fields or {}).get("direction")
    status = (fields or {}).get("status") or "open"  # default to open if missing
    if direction != "incoming":
        return None

    # Try to pull standard fields
    vendor = fields.get("vendor") or (
        (fields.get("bill_to") or {}).get("company")
        or (fields.get("ship_to") or {}).get("company")
        or "Unknown vendor"
    )
    total = fields.get("total") or 0
    due = fields.get("due_date") or ""
    number = fields.get("invoice_number") or fields.get("number") or ""
    memo = fields.get("memo") or fields.get("summary") or fields.get("description") or ""
    description = fields.get("description") or ""

    return {
        "id": row["id"],                 # use record id as bill id
        "vendor": vendor,
        "total": total,
        "due_date": due,
        "number": number,
        "memo": memo,
        "description": description,
        "status": status,
    }

@app.get("/ap/bills")
def list_ap_bills(status: str = "open"):
    """
    Return vendor bills from the records table:
    - type='invoice'
    - fields.direction == 'incoming'
    - filter by fields.status (default 'open')
    """
    con = _db()
    cur = con.cursor()
    # Get all invoice records; we'll filter by direction/status in Python for portability.
    cur.execute("SELECT id, document_id, extraction_id, type, fields, created_at FROM records WHERE type = ?", ("invoice",))
    items = []
    for row in cur.fetchall():
        item = _row_to_ap_item(row)
        if not item:
            continue
        if status == "open":
            if (item.get("status") or "open") == "open":
                items.append(item)
        else:
            items.append(item)
    con.close()
    return items

@app.post("/ap/bills/mark-paid")
def mark_ap_bills_paid(payload: dict = Body(...)):
    """
    Payload: {"ids": ["rec_xxx", ...]}
    Updates each matching record's fields.status = 'paid'
    """
    ids = payload.get("ids") or []
    if not ids:
        return {"ok": True, "updated": 0, "open": []}

    con = _db()
    cur = con.cursor()

    updated = 0
    for rid in ids:
        cur.execute("SELECT id, fields FROM records WHERE id = ?", (rid,))
        row = cur.fetchone()
        if not row:
            continue
        try:
            fields = json.loads(row["fields"]) if isinstance(row["fields"], str) else row["fields"]
        except Exception:
            fields = {}
        if not isinstance(fields, dict):
            fields = {}
        fields["status"] = "paid"
        cur.execute("UPDATE records SET fields = ? WHERE id = ?", (json.dumps(fields, default=str), rid))
        updated += 1

    con.commit()

    # Return remaining open for convenience
    cur.execute("SELECT id, document_id, extraction_id, type, fields, created_at FROM records WHERE type = ?", ("invoice",))
    open_items = []
    for row in cur.fetchall():
        item = _row_to_ap_item(row)
        if not item:
            continue
        if (item.get("status") or "open") == "open":
            open_items.append(item)

    con.close()
    return {"ok": True, "updated": updated, "open": open_items}


@app.post("/assistant/chat")
async def assistant_chat(payload: AssistantChatRequest):
    history = [turn.model_dump() for turn in payload.history]
    try:
        result = chat_with_ingestion(
            payload.document,
            payload.extraction,
            history,
            payload.message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    tmp_path = BASE_DIR / "tmp"
    tmp_path.mkdir(parents=True, exist_ok=True)

    buffer = await file.read()
    temp_file = tmp_path / file.filename
    temp_file.write_bytes(buffer)

    document, _ = ingest_file(temp_file)
    extraction = run_extraction(document, buffer.decode("utf-8", errors="ignore"))
    return {"document": document.dict(), "extraction": extraction.dict()}


@app.post("/records/confirm")
def confirm_record(payload: dict = Body(...)):
    """
    Payload can include doc_id, fields, type, model, schema, and optionally extraction_id.
    We create a Record if it doesn't exist yet. If ingest already saved it, this is basically idempotent.
    """
    doc_id = payload.get("doc_id")
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required")
    fields = payload.get("fields") or {}
    model = payload.get("model") or "o3"
    schema = payload.get("schema") or "generic_v1"
    kind = (payload.get("type") or "other").lower()

    # Map incoming kind to your enum (keep simple)
    type_map = {
        "invoice": DocumentType.INVOICE,
        "vendor_bill_ap": DocumentType.INVOICE,
        "invoice_ar": DocumentType.INVOICE,
        "receipt": DocumentType.RECEIPT,
        "purchase_order": DocumentType.PURCHASE_ORDER,
        "email": DocumentType.EMAIL,
    }
    doc_type = type_map.get(kind, DocumentType.OTHER)

    # If the frontend passed an extraction, we could upsert it; otherwise create a slim one.
    extraction_id = payload.get("extraction_id")
    extraction = Extraction(
        id=extraction_id or f"ext_{uuid.uuid4().hex[:12]}",
        doc_id=doc_id,
        model=model,
        schema=schema,
        fields=fields,
        confidence=float(payload.get("confidence") or 0.0),
        raw_json=payload.get("raw_json") or {},
        created_at=datetime.utcnow(),
    )
    upsert_extraction(extraction)

    record = Record(
        id=f"rec_{uuid.uuid4().hex[:12]}",
        document_id=doc_id,
        extraction_id=extraction.id,
        type=doc_type,
        fields=fields,
        created_at=datetime.utcnow(),
    )
    upsert_record(record)

    return {"ok": True, "record_id": record.id}

@app.get("/records")
async def get_records(type: Optional[str] = None, query: Optional[str] = None):
    filters = {}
    if type:
        filters["type"] = type
    if query:
        filters["query"] = query
    return [record.dict() for record in list_records(filters=filters)]


@app.get("/records/export")
async def export_records_csv():
    rows = list(export_records())
    if not rows:
        return []
    headers = list(rows[0].keys())
    output = io.StringIO()
    output.write(",".join(headers) + "\n")
    for row in rows:
        output.write(",".join(str(row[h]) for h in headers) + "\n")
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv")


@app.post("/pdf/fill")
async def pdf_fill(template_path: str, csv_path: str, profile: Optional[str] = None):
    parsed_profile = PdfFillProfile(**json.loads(profile)) if profile else None
    try:
        output_path, log = fill_pdf(Path(template_path), Path(csv_path), profile=parsed_profile)
    except PdfFillError as exc:
        return {"error": str(exc)}
    return {
        "output_path": str(output_path),
        "log": [
            {
                "row": placement.row.dict(),
                "page_index": placement.page_index,
                "font_size": placement.font_size,
            }
            for placement in log
        ],
    }


@app.get("/pdf/download")
async def download_pdf(path: str):
    file_path = Path(path)
    if not file_path.exists():
        return {"error": "file not found"}
    return FileResponse(file_path)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True}


__all__ = ["app"]



# === Duplicate-friendly indexes (created on startup) ===
def ensure_indexes():
    con = sqlite3.connect(DB_PATH if 'DB_PATH' in globals() else 'data/business_hub.db')
    cur = con.cursor()
    try:
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256_unique
                        ON documents(hash_sha256)
                        WHERE hash_sha256 IS NOT NULL""" )
    except Exception:
        pass
    try:
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_records_vendor_norm
                        ON records(lower(json_extract(fields,'$.vendor_norm')))""" )
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_records_vendor_invno_norm
                        ON records(
                          lower(json_extract(fields,'$.vendor_norm')),
                          lower(json_extract(fields,'$.invoice_number_norm'))
                        )""" )
    except Exception:
        pass
    con.commit()
    con.close()

try:
    app
except NameError:
    pass
else:
    try:
        @app.on_event("startup")
        def _startup_indexes():
            ensure_indexes()
    except Exception:
        ensure_indexes()



# === Duplicate detection helpers ===
def _norm_invoice_no(s):
    if not s: return None
    s = s.lower()
    s = re.sub(r'[\s\-_/\.]', '', s)
    s = re.sub(r'^0+', '', s)
    return s or None

def _norm_vendor(s):
    if not s: return None
    s = s.lower().strip()
    s = re.sub(r'\b(llc|inc|corp|co\.?|ltd)\b', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s or None

def _similar(a, b):
    if not a or not b: return 0.0
    try:
        return SequenceMatcher(None, a, b).ratio()
    except Exception:
        return 0.0

def detect_duplicates(con, file_hash, fields):
    cur = con.cursor()
    row = cur.execute("SELECT id FROM documents WHERE hash_sha256=?", (file_hash,)).fetchone()
    if row:
        return {
            "certainty": "exact",
            "reason": "hash_sha256 matched an existing document",
            "matches": [{"type": "document", "id": row[0]}]
        }
    vend = _norm_vendor(fields.get("vendor"))
    invn = _norm_invoice_no(fields.get("invoice_number"))
    total = fields.get("total")
    invdate = fields.get("invoice_date")
    if vend and invn:
        rec = cur.execute("""
          SELECT id, fields FROM records
          WHERE lower(json_extract(fields,'$.vendor_norm')) = ?
            AND lower(json_extract(fields,'$.invoice_number_norm')) = ?
        """, (vend, invn)).fetchone()
        if rec:
            return {
                "certainty": "likely",
                "reason": "Same vendor + invoice number found",
                "matches": [{"type":"record","id":rec[0]}]
            }
    suspects = []
    if vend:
        for rid, fjson in cur.execute("""
           SELECT id, fields FROM records
           WHERE lower(json_extract(fields,'$.vendor_norm')) = ?
        """, (vend,)):
            try:
                f = json.loads(fjson)
            except Exception:
                f = {}
            score = _similar(invn, f.get("invoice_number_norm"))
            total_close = False
            try:
                total_close = (isinstance(total,(int,float)) and isinstance(f.get("total"),(int,float))
                               and abs(float(total) - float(f.get("total"))) <= 1.00)
            except Exception:
                pass
            date_match = bool(invdate and f.get("invoice_date") and invdate == f.get("invoice_date"))
            if (score >= 0.90) or (invn and f.get("invoice_number_norm") == invn) or (total_close and date_match):
                suspects.append({"type":"record","id":rid, "similarity": round(score,3)})
    if suspects:
        return {
            "certainty": "possible",
            "reason": "Near-duplicate by vendor+invoice heuristics",
            "matches": suspects[:5]
        }
    return None



# === Status toggle and record delete endpoints ===
class StatusBody(BaseModel):
    status: str  # 'open' or 'paid'

def _db_conn():
    path = globals().get('DB_PATH') or 'data/business_hub.db'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

@app.patch("/records/{record_id}/status")
def set_record_status(record_id: str, body: StatusBody):
    if body.status not in ("open", "paid"):
        raise HTTPException(status_code=400, detail="status must be 'open' or 'paid'")
    con = _db_conn()
    cur = con.cursor()
    row = cur.execute("SELECT id, fields FROM records WHERE id=?", (record_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="record not found")
    try:
        fields = json.loads(row["fields"])
    except Exception:
        fields = {}
    fields["status"] = body.status
    cur.execute("UPDATE records SET fields=? WHERE id=?", (json.dumps(fields), record_id))
    con.commit(); con.close()
    return {"id": record_id, "status": body.status}

@app.delete("/records/{record_id}")
def delete_record(record_id: str):
    con = _db_conn()
    cur = con.cursor()
    r = cur.execute("SELECT document_id FROM records WHERE id=?", (record_id,)).fetchone()
    if not r:
        con.close()
        raise HTTPException(status_code=404, detail="record not found")
    document_id = r[0]
    cur.execute("DELETE FROM records WHERE id=?", (record_id,))
    con.commit(); con.close()
    return {"deleted": record_id}



# === Duplicate-aware upload wrapper (non-destructive) ===
from typing import Optional

# === Duplicate-aware upload wrapper (human-friendly responses) ===
from typing import Optional

@app.post("/upload_dupcheck")
async def upload_dupcheck(file: UploadFile = File(...), fields_json: Optional[str] = None):
    b = await file.read()
    file_hash = hashlib.sha256(b).hexdigest()
    try:
        fields = json.loads(fields_json) if fields_json else {}
    except Exception:
        fields = {}
    fields["vendor_norm"] = _norm_vendor(fields.get("vendor"))
    fields["invoice_number_norm"] = _norm_invoice_no(fields.get("invoice_number"))
    con = _db_conn()
    dup = detect_duplicates(con, file_hash, fields)
    con.close()
    if dup and dup.get("certainty") == "exact":
        existing_id = None
        try:
            existing_id = (dup.get("matches") or [{}])[0].get("id")
        except Exception:
            pass
        raise HTTPException(status_code=409, detail={
            "title": "Exact duplicate",
            "message": "Looks like you’ve already uploaded this exact file.",
            "existing_document_id": existing_id,
            "reason": dup.get("reason", "exact duplicate"),
            "matches": dup.get("matches", [])
        })
    notice = None
    if dup:
        if dup.get("certainty") == "likely":
            notice = "This appears to be the same invoice (same vendor and invoice number)."
        elif dup.get("certainty") == "possible":
            notice = "This looks similar to a previous invoice. Want to review the matches?"
    return {
        "notice": notice,
        "duplicate_suspect": dup,
        "proposed_record": {
            "document": {"hash_sha256": file_hash, "filename": file.filename},
            "fields": fields
        }
    }
