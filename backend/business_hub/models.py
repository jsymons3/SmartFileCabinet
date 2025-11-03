"""Pydantic data models for Business Hub backend."""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    EMAIL = "email"
    OTHER = "other"


class DocumentSource(str, Enum):
    UPLOAD = "upload"
    EMAIL = "email"
    CAMERA = "camera"
    IMPORT = "import"


class Document(BaseModel):
    id: str
    type: DocumentType
    mime: str
    source: DocumentSource
    created_at: dt.datetime
    pages: int = 1
    storage_path: str
    ocr_text_indexed: bool = False
    hash_sha256: Optional[str] = None


class Extraction(BaseModel):
    id: str
    doc_id: str
    model: str
    schema: str
    fields: dict
    confidence: float
    raw_json: dict
    created_at: dt.datetime


class LineItem(BaseModel):
    qty: Optional[float] = None
    description: str
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class InvoiceFields(BaseModel):
    vendor: str
    invoice_number: str
    invoice_date: Optional[dt.datetime] = None
    due_date: Optional[dt.datetime] = None
    currency: Optional[str] = None
    total: float
    tax: Optional[float] = None
    payment_terms: Optional[str] = None
    line_items: List[LineItem] = Field(default_factory=list)


class ReceiptFields(BaseModel):
    merchant: str
    datetime: dt.datetime | None = None
    subtotal: Optional[float] = None
    tip: Optional[float] = None
    total: float
    category: Optional[str] = None


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    SNOOZED = "snoozed"


class Task(BaseModel):
    id: str
    thread_id: str
    title: str
    due_at: Optional[dt.datetime] = None
    status: TaskStatus = TaskStatus.OPEN


class ThreadMessageType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    CARD = "card"


class ThreadMessage(BaseModel):
    id: str
    thread_id: str
    created_at: dt.datetime
    type: ThreadMessageType
    author: str
    content: dict


class Thread(BaseModel):
    id: str
    document_id: str
    created_at: dt.datetime
    title: str
    messages: List[ThreadMessage] = Field(default_factory=list)


class Record(BaseModel):
    id: str
    document_id: str
    extraction_id: Optional[str] = None
    type: DocumentType
    fields: dict
    created_at: dt.datetime


class StorageMode(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


class Settings(BaseModel):
    storage_mode: StorageMode = StorageMode.LOCAL
    privacy_mode: bool = False
    redact_pii: bool = False


class PdfFillRow(BaseModel):
    id: str
    label: str
    x: float
    y: float
    value: str
    opt_font_size: Optional[float] = None
    opt_page: Optional[int] = None


class PdfFillProfile(BaseModel):
    id: str
    pdf_template: str
    font: Optional[str] = None
    defaults: dict = Field(default_factory=lambda: {"fontSize": 10, "page": 1})
    csv_headers: List[str] = Field(
        default_factory=lambda: ["id", "label", "x", "y", "value", "opt_font_size", "opt_page"]
    )
    wrap: dict = Field(default_factory=lambda: {"maxWidth": 220, "lineHeight": 1.2})
    min_font: int = 8


__all__ = [name for name in globals() if not name.startswith("_")]
