# AI Corrector

An AI-powered student answer evaluation REST API built on **Azure OpenAI** and **Azure AI Search**.

## Overview

AI Corrector lets instructors:

1. **Upload course materials** (PDF / PPT / PPTX / DOCX / TXT) into a vector database — these become the reference context used during grading.
2. **Automatically evaluate student answers** using an LLM against a structured rubric, a key answer, or retrieved course materials.
3. **Accept student answers in any form** — plain text, a URL to a document, a Google Docs link, or a web article URL.

Supports single, batch (many students / one question), and multi-batch (many questions at once) evaluation modes.

---

## Architecture

```
Client
  │
  ▼
FastAPI (main.py)
  ├── /feed*     → Feed Router    → Azure AI Search (vector index)
  ├── /assess*   → Assess Router  → Azure OpenAI (LLM + embedding + vision)
  │                               → Azure AI Search (vector search)
  └── /debug*    → Debug Router   → inspection, seeding, vector DB management
                                    (only available when DEBUG=true)
```

| Component | Technology |
|---|---|
| Framework | FastAPI + Uvicorn / Gunicorn |
| LLM | Azure OpenAI — `gpt-5.4-mini` (Responses API) |
| Vision | Azure OpenAI — `gpt-4o` |
| Embedding | Azure OpenAI — `text-embedding-3-small` |
| Vector DB | Azure AI Search (index: `lms-materials`) |
| Document Parsing | PyMuPDF, python-pptx, ppt2txt, python-docx |
| Containerization | Docker (port 3100) |

---

## Prerequisites

- Python 3.11+
- An Azure account with:
  - Azure OpenAI resource (deployments: `gpt-5.4-mini`, `gpt-4o`, `text-embedding-3-small`)
  - Azure AI Search resource with an index named `lms-materials`

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd AI-Corrector

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Environment Configuration

Create a `.env` file in the project root:

```env
# Azure OpenAI — LLM (gpt-5.4-mini)
MODEL_URL=https://<resource>.openai.azure.com/openai/v1/
MODEL_KEY=<api-key>

# Azure OpenAI — Embedding (text-embedding-3-small)
EMBED_URL=https://<resource>.openai.azure.com/
EMBED_KEY=<api-key>

# Azure OpenAI — Vision (gpt-4o)
MULTI_MODAL_URL=https://<resource>.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-15-preview
MULTI_MODAL_KEY=<api-key>

# Azure AI Search
VECTORDB_URL=https://<search-resource>.search.windows.net
VECTORDB_KEY=<api-key>

# Optional — override default model names
LLM_MODEL=gpt-5.4-mini
EMBED_MODEL=text-embedding-3-small

# Optional — API key authentication (leave empty to disable)
API_KEY=your-secret-key

# Optional — vector search & chunking tuning
VECTOR_TOP_K=3              # chunks retrieved per vector query (default: 3)
CHUNK_SIZE=400              # words per chunk (default: 400)
CHUNK_OVERLAP=50            # overlap between chunks in words (default: 50)
MAX_CONCURRENT_EVALS=5      # max parallel student evaluations per batch (default: 5)
MAX_FILE_SIZE_BYTES=10485760  # max download size for student answer URLs (default: 10 MB)

# Optional — override token prices (USD per 1M tokens)
PRICE_EMBED_INPUT=0.022
PRICE_LLM_INPUT=0.75
PRICE_LLM_OUTPUT=4.50
PRICE_VISION_INPUT=2.50
PRICE_VISION_OUTPUT=10.0

# Optional — enable debug endpoints
DEBUG=false

# Optional — path to knowledge folder used by /debug/seed
KNOWLEDGE_DIR=knowledge

# Optional — override vector DB field names
VECTORDB_INDEX=lms-materials
VECTORDB_FIELD_ID=id
VECTORDB_FIELD_CONTENT=content
VECTORDB_FIELD_SOURCE=source_file
VECTORDB_FIELD_COURSE_CODE=course_code
VECTORDB_FIELD_PAGE=page_number
VECTORDB_FIELD_VECTOR=content_vector
```

---

## Running the Application

### Development

```bash
uvicorn main:app --reload --port 8000
```

### Production

```bash
gunicorn main:app -c gunicorn.conf.py
```

### Docker

```bash
docker build -t ai-corrector .
docker run -p 3100:3100 --env-file .env ai-corrector
```

---

## API Documentation

Once the server is running, interactive docs are available at:

| URL | Description |
|---|---|
| `/docs` | Swagger UI (interactive) — includes **Authorize 🔒** button for API key |
| `/redoc` | ReDoc |
| `/openapi.json` | OpenAPI schema (JSON) |
| `/health` | Health check — verifies Azure AI Search connectivity |

For the full endpoint reference with example requests and responses, see [ENDPOINTS.md](ENDPOINTS.md).

---

## Security

### API Key Authentication

Set the `API_KEY` environment variable to enable authentication. When set, all endpoints except `/health`, `/docs`, `/redoc`, and `/openapi.json` require the header:

```
X-API-Key: <your-api-key>
```

If `API_KEY` is not set, the server runs without authentication (suitable for internal/dev use).

**In Swagger UI:** click the **Authorize ** button in the top-right corner and enter your API key. Swagger will automatically include the `X-API-Key` header in all requests.

**curl example:**
```bash
curl -X POST http://localhost:8000/assess \
  -H "X-API-Key: your-secret-key" \
  -F "question=..." \
  -F "student_answer=..."
```

---

## Assessment Modes

| Mode | `use_key_answer` | Context Source |
|---|---|---|
| **Key Answer** | `true` | Reference answer provided directly (`key_answer_text` / `key_answer_file`) |
| **Vector DB** | `false` | Course materials from vector database + automatic web search if context is insufficient |

---

## Rubric Format

Rubrics are passed as a structured array of proficiency bands. Each band defines a score range, a proficiency label, and the criteria the student must meet.

**Example:**

```json
[
  { "minScore": 0,  "maxScore": 64,  "proficiency": "Poor",      "criteria": "Able to illustrate less than 4 kinds of data structures in Computer Science" },
  { "minScore": 65, "maxScore": 74,  "proficiency": "Average",   "criteria": "Able to illustrate 4 kinds of data structures in Computer Science" },
  { "minScore": 75, "maxScore": 84,  "proficiency": "Good",      "criteria": "Able to illustrate 5 kinds of data structures in Computer Science" },
  { "minScore": 85, "maxScore": 100, "proficiency": "Excellent", "criteria": "Able to illustrate at least 6 kinds of data structures in Computer Science" }
]
```

- For **batch endpoints** (`/assess-batch`, `/assess-batch-multi`): pass the array directly in the JSON body under the `rubric` field.
- For the **single endpoint** (`/assess`): pass the array serialized as a JSON string in the `rubric` form field.

---

## Supported Document Formats

### Feed (course materials)

| Format | `/feed` (file upload) | `/feed-url` / `/feed-urls` (URL) | `/debug/seed` (folder) |
|---|---|---|---|
| PDF | ✓ | ✓ | ✓ |
| PPTX | ✓ | ✓ | ✓ |
| PPT | ✓ | ✓ | ✓ |
| DOCX | ✓ | ✓ | ✓ |
| TXT | ✓ | ✓ | ✓ |

### Assess (student answers)

| Format | `key_answer_file` | `student_answer` (URL) |
|---|---|---|
| PDF | ✓ | ✓ |
| PPTX | ✓ | ✓ |
| PPT | ✓ | ✓ |
| DOCX | ✓ | ✓ |
| TXT | ✓ | ✓ |
| Google Docs URL | — | ✓ (auto-exported as DOCX, images included) |
| Web article / HTML | — | ✓ (HTML tags stripped) |

---

## Student Answer URL Support

The `student_answer` field in `/assess` accepts a URL in addition to plain text. The server resolves it automatically:

| URL Type | Example | How It's Handled |
|---|---|---|
| Document file | `https://example.com/answer.pdf` | Download → `extract_text()` |
| Google Docs | `https://docs.google.com/document/d/ID/edit` | Auto-converted to `export?format=docx` → parsed including images |
| Web article | `https://medium.com/some-article` | Download → HTML tag stripping via `extract_html_text()` |
| Protected URL | LMS URL with `student_answer_token` | Download with `Authorization: Bearer {token}` |

> Google Docs must be shared as **"Anyone with the link can view"**.

---

## How It Works

```
Feed:
  File / URL
    → Text + image extraction (per page/slide)
    → Image description via vision model (gpt-4o)
    → Chunking (400 words, 50-word overlap)
    → Batch embedding (text-embedding-3-small)
    → Upload to Azure AI Search

Assess:
  Question + Student Answer + Rubric
    │
    ├─ Student answer URL? → download + extract (doc/HTML/Google Docs)
    │
    ├─ [use_key_answer=true]  → use key_answer directly as context
    │
    ├─ [use_key_answer=false] → vector search in Azure AI Search (top-K chunks)
    │                          → automatic web search if context is insufficient
    │
    └─ gpt-5.4-mini → score + reasoning + confidence + feedback + sources
```

---

## Debug Endpoints

When `DEBUG=true`, additional endpoints are available for development and operations:

| Endpoint | Description |
|---|---|
| `POST /debug/extract` | Extract raw text and chunks from an uploaded file |
| `POST /debug/images` | List images found in a PDF or PPTX |
| `POST /debug/images/view` | View images rendered in a browser (HTML response) |
| `DELETE /debug/clear` | Delete documents from vector DB (by `course_code` or all) |
| `POST /debug/seed` | Seed vector DB from the `knowledge/` folder |
| `POST /debug/resolve-url` | Test URL resolution step-by-step without running AI evaluation |

### knowledge/ Folder Structure (for `/debug/seed`)

```
knowledge/
├── comp6100001/        ← subfolder name becomes course_code (auto-uppercased)
│   ├── Session01.pptx
│   └── Session02.pdf
└── comp6200002/
    └── materials.docx
```

---

## Project Structure

```
AI-Corrector/
├── main.py                    # FastAPI entry point, lifespan, request-ID middleware
├── gunicorn.conf.py           # Gunicorn production config
├── requirements.txt
├── Dockerfile
├── ENDPOINTS.md               # Full endpoint reference
│
├── config/
│   ├── __init__.py            # Azure client initialization
│   └── constants.py           # Centralized constants (model names, field names, tuning)
│
├── schemas/                   # Pydantic models
│   ├── __init__.py
│   ├── common.py              # Shared sub-models (RubricItem, token usage, evaluation, source)
│   ├── request.py             # Request models
│   ├── feed.py                # Feed response models
│   ├── assess.py              # Assessment response models
│   └── debug.py               # Debug response models
│
├── routers/
│   ├── feed/
│   │   ├── router.py          # Endpoints: /feed, /feed-url, /feed-urls
│   │   └── service.py         # Document parsing & indexing logic
│   ├── assess/
│   │   ├── router.py          # Endpoints: /assess, /assess-batch, /assess-batch-multi
│   │   └── service.py         # AI evaluation & vector search logic
│   └── debug/
│       └── router.py          # Endpoints: /debug/* (only when DEBUG=true)
│
├── utils/
│   ├── extraction.py          # Text + image extraction (PDF/PPTX/DOCX/TXT/HTML)
│   ├── embedding.py           # Embedding via Azure OpenAI (with retry)
│   ├── image.py               # Image description via vision model
│   ├── similarity.py          # Cosine similarity & chunk selection
│   ├── pricing.py             # Token cost estimation (env-configurable prices)
│   ├── logging_config.py      # JSON structured logging + request_id ContextVar
│   └── json_response.py       # Custom JSON response (handles scientific notation)
│
└── knowledge/                 # Optional: course material files for /debug/seed
    └── <course_code>/
        └── <files>
```

---

## Reliability

| Feature | Details |
|---|---|
| **API key auth** | Optional `X-API-Key` header auth — enabled by setting `API_KEY` env var |
| **Retry logic** | Embedding and LLM calls retry up to 3× with exponential back-off on timeouts, connection errors, and rate limits (429 / 5xx) |
| **Per-item error isolation** | Failures within a batch are reported per-student/per-question — they never fail the entire request |
| **Structured error messages** | Azure API errors (auth failure, rate limit, timeout) surface as clear HTTP 500 messages |
| **URL size guard** | Student answer URLs are size-checked via HEAD before download; oversized files are skipped gracefully |
| **Health check** | `GET /health` pings Azure AI Search and returns 503 if degraded — suitable for Docker/k8s liveness probes |

---

## Observability

Every request gets a unique `X-Request-ID` header (generated if not provided by the client). All log lines are emitted as **JSON** and include the `request_id`, making it easy to correlate logs across a single request in any log aggregation system.

```json
{"time": "2026-06-15 10:23:01,123", "level": "INFO", "logger": "main", "request_id": "a1b2c3d4", "message": "Starting AI Corrector v0.6.7"}
```

---

## Token Cost Estimation

Default prices (USD per 1M tokens) — override via environment variables:

| Model | Env var | Default |
|---|---|---|
| `text-embedding-3-small` input | `PRICE_EMBED_INPUT` | $0.022 |
| `gpt-5.4-mini` input | `PRICE_LLM_INPUT` | $0.75 |
| `gpt-5.4-mini` output | `PRICE_LLM_OUTPUT` | $4.50 |
| `gpt-4o` vision input | `PRICE_VISION_INPUT` | $2.50 |
| `gpt-4o` vision output | `PRICE_VISION_OUTPUT` | $10.00 |

Every API response includes a `token_usage` breakdown with the estimated USD cost.
