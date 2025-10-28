# backend/main.py
"""FastAPI application for Business Hub."""
from __future__ import annotations

import io
import json
import os, json, sqlite3
from pathlib import Path
from typing import Optional
from fastapi import Body
from typing import List


from pydantic import BaseModel
import sqlite3, json


from business_hub.models import Extraction, Record, DocumentType
from business_hub.storage import upsert_extraction, upsert_record
from datetime import datetime
import uuid


from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from business_hub.ai import run_extraction
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
    extraction = Extraction(
        id=f"ext_{uuid.uuid4().hex[:12]}",
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
