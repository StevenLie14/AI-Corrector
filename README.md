# AI Corrector

An AI-powered student answer evaluation REST API built on **Azure OpenAI** and **Azure AI Search**.

## Overview

AI Corrector lets instructors:

1. **Upload course materials** (PDF / PPT / PPTX) into a vector database — these become the reference context used during grading.
2. **Automatically evaluate student answers** using an LLM against a structured rubric, a key answer, or retrieved course materials.

Supports single, batch (many students / one question), and multi-batch (many questions at once) evaluation modes.

---

## Architecture

```
Client
  │
  ▼
FastAPI (main.py)
  ├── /feed*     → Feed Router    → Azure AI Search (vector index)
  └── /assess*   → Assess Router  → Azure OpenAI (LLM + embedding + vision)
                                  → Azure AI Search (vector search)
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

# Optional — override token prices (USD per 1M tokens)
PRICE_EMBED_INPUT=0.022
PRICE_LLM_INPUT=0.75
PRICE_LLM_OUTPUT=4.50
PRICE_VISION_INPUT=2.50
PRICE_VISION_OUTPUT=10.0

# Optional — enable debug endpoints
DEBUG=false

# Optional — override vector DB index name (default: lms-materials)
VECTORDB_INDEX=lms-materials
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
| `/docs` | Swagger UI (interactive) |
| `/redoc` | ReDoc |
| `/openapi.json` | OpenAPI schema (JSON) |

For full endpoint reference with example requests and responses, see [docs/endpoints.md](docs/endpoints.md).

---

## Assessment Modes

| Mode | `use_key_answer` | Context Source |
|---|---|---|
| **Key Answer** | `true` | Reference answer provided directly (`key_answer_text` / `key_answer_file`) |
| **Vector DB** | `false` | Course materials from vector database + automatic web search |

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

| Format | Feed (materials) | Key Answer | Student Answer (URL) |
|---|---|---|---|
| PDF | ✓ | ✓ | ✓ |
| PPTX | ✓ | ✓ | ✓ |
| PPT | ✓ | ✓ | ✓ |
| DOCX | — | ✓ | ✓ |
| TXT | — | ✓ | ✓ |

---

## How It Works

```
Feed:
  File / URL
    → Text + image extraction
    → Image description via vision model (gpt-4o)
    → Chunking (400 words, 50-word overlap)
    → Batch embedding (text-embedding-3-small)
    → Upload to Azure AI Search

Assess:
  Question + Student Answer + Rubric
    │
    ├─ [use_key_answer=true]  → use key_answer directly as context
    │
    ├─ [use_key_answer=false] → vector search in Azure AI Search
    │                          → automatic web search if context is insufficient
    │
    └─ gpt-5.4-mini → score + reasoning + confidence + feedback + sources
```

---

## Project Structure

```
AI-Corrector/
├── main.py                    # FastAPI entry point, lifespan, request-ID middleware
├── gunicorn.conf.py           # Gunicorn production config
├── requirements.txt
├── Dockerfile
│
├── config/
│   ├── __init__.py            # Azure client initialization
│   └── constants.py           # Centralized model names (overridable via env)
│
├── schemas/                   # Pydantic models
│   ├── __init__.py            # Re-exports all schemas
│   ├── common.py              # Shared sub-models (RubricItem, token usage, evaluation, source)
│   ├── request.py             # Request models (Feed & Assess)
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
│   ├── extraction.py          # Text extraction from PDF / PPTX / DOCX / TXT
│   ├── embedding.py           # Embedding via Azure OpenAI (with retry)
│   ├── image.py               # Image description via vision model
│   ├── similarity.py          # Cosine similarity & chunk selection
│   ├── pricing.py             # Token cost estimation (env-configurable prices)
│   ├── logging_config.py      # JSON structured logging + request_id ContextVar
│   └── json_response.py       # Custom JSON response (handles scientific notation)
│
└── docs/
    └── endpoints.md           # Full endpoint reference
```

---

## Reliability

| Feature | Details |
|---|---|
| **Retry logic** | Embedding and LLM calls retry up to 3× with exponential back-off on timeouts, connection errors, and rate limits (429 / 5xx) |
| **Per-item error isolation** | Failures within a batch are reported per-student/per-question — they never fail the entire request |
| **Structured error messages** | Azure API errors (auth failure, rate limit, timeout) surface as clear HTTP 500 messages |

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
