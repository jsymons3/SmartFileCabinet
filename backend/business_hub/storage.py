"""Local SQLite-backed storage utilities."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

from .models import Document, Extraction, Record, Task

DEFAULT_DB_PATH = Path(os.getenv("BUSINESS_HUB_DB", "data/business_hub.db"))


def ensure_db(path: Path = DEFAULT_DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                mime TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                pages INTEGER NOT NULL,
                storage_path TEXT NOT NULL,
                ocr_text_indexed INTEGER DEFAULT 0,
                hash_sha256 TEXT
            );
            CREATE TABLE IF NOT EXISTS extractions (
                id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                schema TEXT NOT NULL,
                fields TEXT NOT NULL,
                confidence REAL NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                extraction_id TEXT REFERENCES extractions(id) ON DELETE SET NULL,
                type TEXT NOT NULL,
                fields TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                title TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL
            );
            """
        )


@contextmanager
def connect(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    ensure_db(path)
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def upsert_document(document: Document, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO documents (id, type, mime, source, created_at, pages, storage_path, ocr_text_indexed, hash_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                mime=excluded.mime,
                source=excluded.source,
                created_at=excluded.created_at,
                pages=excluded.pages,
                storage_path=excluded.storage_path,
                ocr_text_indexed=excluded.ocr_text_indexed,
                hash_sha256=excluded.hash_sha256
            """,
            (
                document.id,
                document.type.value,
                document.mime,
                document.source.value,
                document.created_at.isoformat(),
                document.pages,
                document.storage_path,
                int(document.ocr_text_indexed),
                document.hash_sha256,
            ),
        )


def upsert_extraction(extraction: Extraction, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO extractions (id, doc_id, model, schema, fields, confidence, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                doc_id=excluded.doc_id,
                model=excluded.model,
                schema=excluded.schema,
                fields=excluded.fields,
                confidence=excluded.confidence,
                raw_json=excluded.raw_json,
                created_at=excluded.created_at
            """,
            (
                extraction.id,
                extraction.doc_id,
                extraction.model,
                extraction.schema,
                json.dumps(extraction.fields),
                extraction.confidence,
                json.dumps(extraction.raw_json),
                extraction.created_at.isoformat(),
            ),
        )


def upsert_record(record: Record, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO records (id, document_id, extraction_id, type, fields, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                document_id=excluded.document_id,
                extraction_id=excluded.extraction_id,
                type=excluded.type,
                fields=excluded.fields,
                created_at=excluded.created_at
            """,
            (
                record.id,
                record.document_id,
                record.extraction_id,
                record.type.value,
                json.dumps(record.fields),
                record.created_at.isoformat(),
            ),
        )


def list_records(path: Path = DEFAULT_DB_PATH, filters: Optional[Dict[str, str]] = None) -> Iterable[Record]:
    filters = filters or {}
    query = "SELECT id, document_id, extraction_id, type, fields, created_at FROM records"
    clauses = []
    params: list = []
    if doc_type := filters.get("type"):
        clauses.append("type = ?")
        params.append(doc_type)
    if text := filters.get("query"):
        clauses.append("fields LIKE ?")
        params.append(f"%{text}%")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    with connect(path) as conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
    for row in rows:
        yield Record(
            id=row[0],
            document_id=row[1],
            extraction_id=row[2],
            type=row[3],
            fields=json.loads(row[4]),
            created_at=datetime.fromisoformat(row[5]),
        )


def export_records(path: Path = DEFAULT_DB_PATH) -> Iterable[Dict[str, str]]:
    for record in list_records(path):
        row = {"id": record.id, "document_id": record.document_id, "type": record.type.value}
        row.update({f"field_{k}": str(v) for k, v in record.fields.items()})
        yield row


def upsert_task(task: Task, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO tasks (id, thread_id, title, due_at, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                thread_id=excluded.thread_id,
                title=excluded.title,
                due_at=excluded.due_at,
                status=excluded.status
            """,
            (
                task.id,
                task.thread_id,
                task.title,
                task.due_at.isoformat() if task.due_at else None,
                task.status.value,
            ),
        )


__all__ = [name for name in globals() if not name.startswith("_")]
