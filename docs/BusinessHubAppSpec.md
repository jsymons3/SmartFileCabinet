# Business Hub Application – Product Requirements & Technical Specification

**Owner:** Ryan  
**Audience:** iOS & Desktop Engineering, Backend, Design, QA, DevOps  
**Goal:** Deliver a unified, chat-style workspace that ingests business documents, extracts actionable data with OpenAI, stores normalized records locally or in the cloud, and supports PDF form filling from CSV coordinate maps.

---

## 1. Problem Statement & Objectives

### Problems
- Business-critical documents and conversations live across email, SMS, file shares, and personal notes.
- Manual re-entry of totals, vendors, dates, and line items into trackers or forms is slow and error-prone.
- Filling repetitive PDF forms by hand is tedious and inconsistent.

### Objectives
1. **Ingest** invoices, receipts, purchase orders, emails, and images via drag-drop, share sheet, or connected inbox/storage.
2. **Understand** documents with OpenAI (classification, summaries, key-value extraction, line items).
3. **Act** on structured data with approvals, tasks, and exports to CSV/Sheets/QuickBooks.
4. **Fill PDFs** using a CSV of `(id, label, x, y [, value, font_size, page])` coordinates.
5. Provide a **chat-style UI**: each upload creates a threaded conversation with cards for previews, extracted data, and actions.
6. Support **local-only or cloud-synced storage**, user selectable at onboarding.

*Out of scope (v1):* Full accounting, bank sync, payments (export only).

---

## 2. Platforms & Technology

| Layer | Preferred Options | Notes |
| --- | --- | --- |
| iOS | SwiftUI + Combine, PDFKit, Vision/VisionKit OCR, URLSession | Native share sheet ingestion; on-device encryption via Keychain. |
| Desktop | Electron (React + TypeScript) *or* native macOS (SwiftUI) + Windows (WinUI) | Desktop MVP targets Electron for shared UI. |
| Shared Core | Rust/Node/Swift modules | PDF parsing/writing, OCR (Tesseract or Apple Vision), AES-GCM encryption. |
| Backend (sync) | FastAPI (Python) or NestJS (Node) + Postgres + S3-compatible storage | Optional for cloud mode; local filesystem for offline mode. |
| Vector Search | SQLite-VSS or Postgres `pgvector` | Enables semantic recall across records. |
| AI | OpenAI GPT-4o-mini / GPT-4.1-mini via Responses API | Use function/tool calls for deterministic JSON extraction. |

---

## 3. Core User Stories & Acceptance Criteria

### 3.1 Document Ingestion
- **US-INGEST-1:** Drag-drop PDF/JPG/PNG/HEIC/EML/MSG/TXT or paste text to spawn a thread.  
  *AC:* Preview renders, metadata card posts, OCR runs as needed, extraction card appears.
- **US-INGEST-2:** iOS share sheet uploads appear in main feed within 5 seconds, auto-processed.
- **US-INGEST-3:** Connect IMAP/Gmail (read-only) to auto-ingest tagged "Invoices" emails with attachments.  
  *AC:* Thread shows sender, subject, date, attachments.

### 3.2 AI Understanding & Normalization
- **US-AI-1:** Invoice extraction: vendor, invoice number/date, due date, totals, taxes, currency, payment terms, and line items (qty, desc, unit price, amount).  
  *AC:* ≥95% precision on sample set; confidence scores stored.
- **US-AI-2:** Receipt extraction: merchant, datetime, subtotal, tip, total, category (Supplies/Travel/Meals/Software/Other).  
  *AC:* User override available.
- **US-AI-3:** Each thread shows ≤120-word summary and suggested actions (e.g., "Schedule payment before due date").

### 3.3 Central Records & Search
- **US-DATA-1:** Every document creates/updates a normalized Record table, filterable/exportable (CSV/Excel).
- **US-DATA-2:** Full-text + semantic search supports vendor lookup and intent queries like "last month MGP receipts".

### 3.4 PDF Form Filling
- **US-PDF-1:** Select PDF template + CSV (`id,label,x,y,value,opt_font_size,opt_page`) to generate filled, flattened PDF.  
  *AC:* Placement tolerance ±2 pts; multi-page via `opt_page`.
- **US-PDF-2:** Save mapping profiles (CSV + font/position settings) and reuse with new values.  
  *AC:* One-click refills with different value CSVs.

### 3.5 Chat & Actions
- **US-CHAT-1:** Thread timeline contains messages, AI cards (summary, extracted JSON), tasks, approvals.  
  *AC:* Timestamped, reactions, pinning, mentions, attachments.
- **US-CHAT-2:** Convert card to Task (e.g., "Pay invoice" with due date).  
  *AC:* Task panel listing, local notifications.

### 3.6 Storage & Sync
- **US-STORE-1:** Onboarding toggle for Local-Only (encrypted on device) vs Cloud Sync (E2E encrypted).  
  *AC:* Guided migration flow available later.
- **US-STORE-2:** Offline ingestion/PDF fill function; AI tasks queue until connectivity restored.  
  *AC:* Queued jobs auto-run on reconnection.

---

## 4. Data Model (v1)

```json
{
  "Document": {
    "id": "doc_...",
    "type": "invoice|receipt|po|email|other",
    "mime": "application/pdf",
    "source": "upload|email|camera|import",
    "created_at": "ISO",
    "pages": 3,
    "storage_path": "s3://... or file:///...",
    "ocr_text_indexed": true,
    "hash_sha256": "..."
  },
  "Extraction": {
    "id": "ext_...",
    "doc_id": "doc_...",
    "model": "gpt-4o-mini",
    "schema": "invoice_v1",
    "fields": {},
    "confidence": 0.0,
    "raw_json": {},
    "created_at": "ISO"
  },
  "InvoiceFields": {
    "vendor": "Acme Co.",
    "invoice_number": "INV-1234",
    "invoice_date": "2025-09-10",
    "due_date": "2025-10-10",
    "currency": "USD",
    "total": 1234.56,
    "tax": 45.00,
    "payment_terms": "Net 30",
    "line_items": [
      {"qty": 2, "description": "Widget", "unit_price": 100, "amount": 200}
    ]
  },
  "Task": {
    "id": "task_...",
    "thread_id": "thr_...",
    "title": "Pay Invoice INV-1234",
    "due_at": "ISO",
    "status": "open|done|snoozed"
  }
}
```

**CSV format for PDF fill (v1)**

```
id,label,x,y,value,opt_font_size,opt_page
1,Vendor Name,72,644,Acme Co.,10,1
2,Invoice #,410,644,INV-1234,10,1
3,Total,480,132,$1,234.56,12,1
```

- Coordinates in PDF points, origin bottom-left.
- `opt_page` defaults to 1; optional columns ignored if absent.
- Support `\n` for multiline values.

---

## 5. OpenAI Integration Strategy

**Use cases:**
1. Document type classification (router prompt).
2. Key-value extraction using JSON schema tool calls.
3. Line-item parsing with function-calling schema enforcement.
4. Summaries and action suggestions per thread.
5. Embeddings for semantic search.

**Implementation notes:**
- Use Responses API with tools enforcing schemas; retry invalid JSON with `seed` + `temperature=0.2`.
- Batch large documents by page; merge with heuristics.
- Optional Privacy Mode: redact PII (hash emails, mask card numbers) before sending to OpenAI.

**Example tool schema (`invoice_extract_v1`):**

```json
{
  "name": "invoice_extract_v1",
  "parameters": {
    "type": "object",
    "properties": {
      "vendor": {"type": "string"},
      "invoice_number": {"type": "string"},
      "invoice_date": {"type": "string", "format": "date"},
      "due_date": {"type": "string", "format": "date"},
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
            "amount": {"type": "number"}
          },
          "required": ["description"]
        }
      }
    },
    "required": ["vendor", "invoice_number", "total"]
  }
}
```

**Prompt skeletons:**
- *Classifier:* "You are a strict document classifier. Return one of: invoice, receipt, purchase_order, email, other. Respond as JSON `{type:string, confidence:number}`."
- *Extractor:* "Return **only** valid JSON for tool `invoice_extract_v1`. If a field is absent, omit it. Use currency ISO codes."
- *Summarizer:* "Summarize for a business owner in ≤120 words. Include: who sent it, what it’s about, total/due date if present, and suggested next action."

---

## 6. PDF Fill Pipeline

1. Load PDF bytes.
2. Parse CSV and validate headers.
3. For each row: determine page, x, y, font size (default 10pt).
4. Draw text with wrapping and optional max width.
5. Optional debug overlay for placement boxes.
6. Flatten and save new PDF; preserve metadata.
7. Return output path plus audit log of placements.

**Edge cases:** long text shrink-to-fit (min 8pt) or multi-line wrap; embed NotoSans fallback for Unicode; warn on out-of-range pages; clamp coordinates to page box.

---

## 7. Information Architecture & UI

- **Left Rail (collapsible):** Inbox, All Docs, Invoices, Receipts, POs, Tasks, Vendors, Exports, Settings.
- **Main Feed:** Chat-style threads with cards (Upload, Summary, Extracted Fields JSON, Suggested Actions, Comments).
- **Right Pane:** Record details, timeline, related docs, quick actions (Export CSV, Create Task, Fill PDF from Profile).
- **Top Bar:** Global search, New button, Sync status, Profile.
- **Visual Style:** Dark theme, rounded 16px cards, subtle shadows, line charts for spend trends; Inter typography.

**Primary flows:**
1. Upload → Processing → Summary/Extraction → Confirm/Edit → Save Record.
2. Select Record → Export/Task → optional PDF fill via saved profile.

---

## 8. Settings & Privacy

- Storage mode selection (local encrypted vault vs cloud sync with E2E keys).
- OpenAI data controls: disable training usage, enable PII redaction.
- Secure API key storage (Keychain/Keystore).
- Backups: local snapshot + optional S3 versioning.
- Compliance guidance: SOC2-aligned practices, audit logs, signed download URLs.

---

## 9. Integrations (v1 Candidates)
- Email (IMAP/Gmail read-only).
- Cloud storage (Dropbox/Google Drive/OneDrive) read-only folders.
- Accounting exports (CSV for QuickBooks/Xero) and Calendar (.ics) reminders for due dates.

---

## 10. Non-Functional Requirements
- **Performance:** Extraction <10s for 3-page PDF on broadband; initial UI paint <2s.
- **Reliability:** Local processing queue survives restarts; crash-safe writes.
- **Security:** AES-256 at rest, TLS 1.3 in transit, signed JWT for cloud sync.
- **Observability:** Local debug console; optional Sentry for error telemetry.

---

## 11. MVP Scope (6–8 Weeks)
1. Electron desktop app (Mac/Windows).
2. Drag-drop ingestion + previews for PDFs/images.
3. OpenAI classification/extraction for invoices and receipts.
4. Records table with CSV export.
5. PDF fill from CSV coordinates (single page).
6. Local-only encrypted storage.
7. Basic chat timeline + task creation.

*Stretch:* Gmail import, multi-page PDF fill, vector search, iOS share sheet alpha.

---

## 12. API Sketches
- `POST /ingest {file}` → `{doc_id}`
- `POST /extract {doc_id, type?}` → `{ext_id, fields, confidence}`
- `GET /records?type=invoice&query=...` → list
- `POST /pdf/fill {template_id, csv_id}` → `{output_path, log}`

**OpenAI pseudo-code:**

```ts
const resp = await openai.responses.create({
  model: "gpt-4o-mini",
  input: [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: ocrText }
  ],
  tools: [invoice_extract_v1],
  temperature: 0.2,
});
```

---

## 13. QA Test Matrix (excerpt)
- Upload PDF (text), PDF (scanned), JPG, PNG, HEIC, Email (.eml).
- Invoice vendors: 20 templates across currencies.
- OCR accuracy ≥98% character level on high-res images.
- PDF placements validated on Letter and A4 coordinates.
- Offline queue behavior and conflict resolution scenarios.

---

## 14. Risks & Mitigations
- **OCR variance:** Prefer native Vision on iOS; allow manual correction UI.
- **Model drift:** Pin model versions; maintain eval set with nightly regression.
- **PDF font issues:** Bundle fallback fonts; add preflight validator.
- **Security:** Provide on-device-only processing mode.

---

## 15. Pre-Build Deliverables
- Figma dark UI kit plus six key screens (feed, thread, record, CSV mapper, PDF viewer, settings).
- Sample datasets: 50 invoices/receipts, 3 PDF templates, 3 CSV mappings.
- Evaluation harness scripts + acceptance thresholds above.

---

## 16. CSV-to-PDF Mapping Profile (Appendix)

```json
{
  "id": "prof_invoice_001",
  "pdf_template": "templates/invoice_form_v1.pdf",
  "font": "Inter-Regular.ttf",
  "defaults": { "fontSize": 10, "page": 1 },
  "csv_headers": ["id","label","x","y","value","opt_font_size","opt_page"],
  "wrap": { "maxWidth": 220, "lineHeight": 1.2 },
  "minFont": 8
}
```

**CLI utility (dev):**
```
$ hub pdf-fill --template form.pdf --csv fields.csv --out filled.pdf --debug
```

---

**Design Note:** Match reference dark UI with card-based feed, side navigation, inline charts, generous spacing, and subtle motion.
