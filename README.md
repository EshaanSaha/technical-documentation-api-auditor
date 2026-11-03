# Technical Documentation & API Consistency Auditor

An enterprise-grade, locally running NLP and structural verification tool that audits customer-facing API documentation (**PDF**, **DOCX**, **Markdown**) against **OpenAPI 3.x / Swagger 2.0** specifications (**YAML**, **JSON**).

All NLP entity extraction, identifier normalization, fuzzy alignment, and semantic similarity analysis (`sentence-transformers/all-MiniLM-L6-v2` and `spaCy`) run **100% locally** inside the project virtual environment (`.venv`) with zero external LLM APIs, paid services, or runtime internet dependencies.

---

## 1. Architecture Overview

```text
 Streamlit Frontend (app/frontend/dashboard.py)
   │  REST / JSON over HTTP (http://127.0.0.1:8000)
   ▼
 FastAPI Backend (app/backend/main.py)
   ├── Parsers (app/parsers/)
   │     ├── markdown_parser.py ──┐
   │     ├── docx_parser.py     ──┼─► Format-neutral Blocks ─► documentation_extractor.py ─► ApiModel
   │     ├── pdf_parser.py      ──┘
   │     └── openapi_parser.py  ───────────────────────────────────────────────────────────► ApiModel
   │
   ├── NLP Layer (app/nlp/)
   │     ├── preprocessing.py        (spaCy pipeline & sentence segmentation)
   │     ├── text_normalization.py   (snake_case/camelCase/kebab-case, types, path templates, auth)
   │     ├── entity_extraction.py    (spaCy POS/dependency filtering + custom technical spans)
   │     └── semantic_matching.py    (offline all-MiniLM-L6-v2 embeddings + RapidFuzz)
   │
   ├── Validation Engine (app/engine/)
   │     ├── endpoint_matcher.py     (Exact, Likely, Missing, Unexpected classifications)
   │     ├── parameter_validator.py  (Missing, extra, name, type, requiredness, location)
   │     ├── schema_validator.py     (Nested request/response schemas & HTTP status codes)
   │     ├── description_validator.py(Contextual cosine similarity & missing prose detection)
   │     └── validation_engine.py    (Pipeline orchestration & weighted completeness scoring)
   │
   ├── Persistence (app/database/)   (SQLite: deduplicated uploads, sessions, issues, reports, settings)
   └── Reporting (app/reports/)      (Downloadable CSV, multi-sheet Excel .xlsx, and PDF reports)
```

---

## 2. Project Directory Structure

```text
NLP_Project/
├── .venv/                          # Project-level Python virtual environment
├── .streamlit/
│   └── config.toml                 # Restrained light enterprise theme configuration
├── app/
│   ├── core/
│   │   ├── config.py               # Environment & threshold settings
│   │   ├── logging_config.py       # Centralised logging configuration
│   │   └── models.py               # Shared Pydantic domain & validation models
│   ├── frontend/
│   │   ├── dashboard.py            # Main Streamlit entrypoint
│   │   ├── pages/
│   │   │   ├── validation.py       # Overview landing page
│   │   │   ├── upload.py           # New Validation (file upload & sample runner)
│   │   │   ├── results.py          # Validation Results dashboard, filters & exports
│   │   │   ├── history.py          # Analysis History & session management
│   │   │   └── settings_page.py    # Heuristic threshold configuration
│   │   └── components/
│   │       ├── api_client.py       # HTTP client communicating with FastAPI
│   │       └── styles.py           # Developer-tool CSS & Plotly chart builders
│   ├── backend/
│   │   ├── main.py                 # FastAPI application & health endpoint
│   │   ├── routes/
│   │   │   ├── validation.py       # /api/validate, /api/validate/sample, /api/parse-preview
│   │   │   ├── history.py          # /api/sessions CRUD endpoints
│   │   │   ├── reports.py          # /api/reports/{session_id}/{csv|xlsx|pdf}
│   │   │   └── settings_routes.py  # /api/settings/thresholds endpoints
│   │   └── schemas/
│   │       └── api_schemas.py      # Request/response API contracts
│   ├── nlp/
│   │   ├── preprocessing.py
│   │   ├── text_normalization.py
│   │   ├── entity_extraction.py
│   │   └── semantic_matching.py
│   ├── parsers/
│   │   ├── blocks.py
│   │   ├── markdown_parser.py
│   │   ├── docx_parser.py
│   │   ├── pdf_parser.py
│   │   ├── openapi_parser.py
│   │   ├── documentation_extractor.py
│   │   └── loader.py
│   ├── engine/
│   │   ├── alignment.py
│   │   ├── endpoint_matcher.py
│   │   ├── parameter_validator.py
│   │   ├── schema_validator.py
│   │   ├── description_validator.py
│   │   └── validation_engine.py
│   ├── database/
│   │   ├── models.py
│   │   └── db.py
│   ├── reports/
│   │   └── report_generator.py
│   └── utils/
│       └── file_validation.py
├── data/
│   ├── uploads/                    # Content-addressed (SHA-256) uploaded files
│   ├── sample_data/                # Ready-to-run ShopWave API specs & docs (MD, DOCX, PDF, YAML, JSON)
│   └── models/
│       └── all-MiniLM-L6-v2/       # Local Sentence Transformers model files
├── scripts/
│   ├── download_models.py          # One-time local NLP model downloader
│   └── generate_sample_files.py    # Generates DOCX, PDF and JSON sample files
├── tests/
│   ├── test_nlp.py
│   ├── test_parsers.py
│   ├── test_engine.py
│   └── test_pipeline_and_api.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── run.py                          # Single-command launcher for FastAPI + Streamlit
```

---

## 3. Windows PowerShell Setup & Installation

Run the following commands from the project root in **Windows PowerShell**:

```powershell
# 1. Create the project-level virtual environment (.venv)
python -m venv .venv

# 2. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip inside .venv
python -m pip install --upgrade pip

# 4. Install all project dependencies into .venv
pip install -r requirements.txt

# 5. Download and verify local NLP models (spaCy en_core_web_sm + all-MiniLM-L6-v2 in data/models/)
python scripts/download_models.py

# 6. (Optional) Regenerate sample DOCX, PDF and JSON datasets
python scripts/generate_sample_files.py
```

---

## 4. Starting the Application

With `.venv` activated, launch both the FastAPI backend and the Streamlit frontend with a single command:

```powershell
python run.py
```

### Application URLs

| Service | URL |
|---|---|
| **Streamlit Frontend UI** | http://localhost:8501 |
| **FastAPI Backend Base URL** | http://127.0.0.1:8000 |
| **FastAPI Interactive OpenAPI Docs** | http://127.0.0.1:8000/docs |
| **Health & Model Readiness Check** | http://127.0.0.1:8000/api/health |

---

## 5. Running the Test Suite

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

---

## 6. Completeness Scoring Methodology

The overall documentation completeness score (`0–100%`) is computed transparently from actual validation counts across five weighted dimensions:

1. **Endpoint Coverage & Accuracy (30%)**: `(exact_matches + 0.5 * likely_matches) / max(1, spec_endpoints + unexpected_doc_endpoints)`
2. **Parameter Accuracy (25%)**: `(correct + 0.5 * mismatched) / (total_spec_params + extra_doc_params)`
3. **Request & Response Schema Accuracy (25%)**: `(correct + 0.5 * mismatched) / (total_spec_fields + extra_doc_fields)`
4. **Status Codes & Authentication (10%)**: `(correct + 0.5 * mismatched) / (total_spec_items + extra_doc_items)`
5. **Description Consistency (10%)**: `(consistent + 0.5 * inconsistent) / total_compared_descriptions`

Semantic similarity is used as a heuristic signal (`>= 0.85` High, `0.65–0.84` Moderate, `< 0.65` Potential inconsistency) and is never treated as standalone proof of structural correctness.

---

## 7. Troubleshooting

* **PowerShell Execution Policy blocks `Activate.ps1`**:
  Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in the current PowerShell window, or invoke binaries directly via `.\.venv\Scripts\python.exe`.
* **Embedding model not found error**:
  Run `.\.venv\Scripts\python.exe scripts/download_models.py` once while connected to the internet so `sentence-transformers/all-MiniLM-L6-v2` is saved into `data/models/all-MiniLM-L6-v2`. After this initial setup, the application runs completely offline (`HF_HUB_OFFLINE=1`).
* **Port `8000` or `8501` already in use**:
  Copy `.env.example` to `.env` and adjust `AUDITOR_API_PORT`, `AUDITOR_UI_PORT`, and `AUDITOR_API_URL`.

---

## 8. Known Technical Limitations

* **PDF Layout Reconstruction**: PDF table and heading extraction relies on `PyMuPDF` (`page.find_tables()` and font-size heuristics). Scanned image-only PDFs without an embedded text layer require external OCR before upload, and heavily multi-column or borderless PDF tables may extract fewer structured attributes than Markdown or DOCX sources.
* **Polymorphic OpenAPI Schemas (`oneOf` / `anyOf`)**: When an OpenAPI schema uses `oneOf` or `anyOf`, the schema flattener evaluates the primary (first) schema branch.
* **JSON Example Optionality**: When documentation provides only a JSON code example without a field table, optional specification fields omitted from that example are not penalized as missing, since a single example payload rarely includes every optional attribute.

