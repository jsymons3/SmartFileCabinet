<<<<<<< HEAD
# Business Hub

Business Hub is a unified workspace for ingesting business documents, extracting structured data, organizing conversations, and filling PDF forms using CSV mapping profiles. This repository contains:

- **FastAPI backend** that handles ingestion, OpenAI-powered extraction, records storage, and the PDF fill pipeline.
- **CLI utilities** for developers to run PDF fill workflows offline.
- **Automated tests** for the PDF fill path.

> **Note**: Set `OPENAI_API_KEY` (and optionally `OPENAI_CLASSIFIER_MODEL` / `OPENAI_EXTRACTION_MODEL`) before running the backend to enable live model calls.

## Getting Started

### Prerequisites

- Python 3.11+
- Node 18+ (for future desktop app shell)

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. Use `/docs` for interactive exploration.

### CLI Usage

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python cli.py pdf-fill --template /path/to/form.pdf --csv /path/to/fields.csv --out filled.pdf
```

### Running Tests

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Key Features Implemented

1. **Document ingestion** with hashing, MIME detection, and SQLite-backed persistence.
2. **OpenAI extraction** generating normalized invoice and receipt records with confidence scores.
3. **Record export endpoint** producing CSV output for downstream tools.
4. **CSV-driven PDF fill** workflow supporting optional font sizes, per-page placement, and developer-friendly logs.
5. **CLI** mirroring the PDF fill pipeline for batch operations.

## Next Steps

- Add Electron + React shell for the desktop experience described in the product spec.
- Implement offline-first job queue and synchronization logic for the storage modes.
- Expand tests to cover ingestion, extraction accuracy, and CSV exports.

## License

MIT
=======
# SmartFileCabinet
A chatbased file cabinet system
>>>>>>> df6a47a1ef8214a98b6f3b1c4e26200518d61989
