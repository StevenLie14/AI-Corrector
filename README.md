# AI Corrector

An AI-powered automated answer assessment system for educational institutions. Course materials are indexed into a vector database, and student answers are evaluated using Retrieval-Augmented Generation (RAG) with Azure OpenAI.

## Features

- **Material ingestion** — Upload PDF, PPT, or PPTX files (or URLs) as course materials; text and embedded images are extracted, chunked, embedded, and stored in Azure AI Search
- **Image understanding** — Embedded images in documents are described by a vision model and included as text context
- **RAG-based assessment** — Student answers are graded using retrieved course material as context, scored against a provided rubric
- **Key answer support** — Optionally provide a model answer (as text or file) to guide grading; long files are automatically condensed via in-memory semantic search
- **Web search fallback** — If course materials lack sufficient context, the model queries the web
- **Batch assessment** — Multiple student answers for the same question are evaluated concurrently
- **Token usage & cost tracking** — Every AI endpoint returns token counts and estimated USD cost

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI + Uvicorn/Gunicorn |
| LLM | Azure OpenAI (GPT-4.1-mini) |
| Vision | Azure OpenAI (GPT-4o) |
| Embeddings | Azure OpenAI (text-embedding-3-small) |
| Vector DB | Azure AI Search |
| Document parsing | PyPDF, python-pptx, python-docx |
| Containerization | Docker |

## Prerequisites

- Python 3.11+
- An Azure subscription with:
  - Azure OpenAI resource (chat + vision + embeddings deployments)
  - Azure AI Search resource

## Setup

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd AI-Corrector
pip install -r requirements.txt
```

**2. Configure environment variables**

Copy `.env.example` to `.env` and fill in your Azure credentials:

```env
MODEL_URL=<Azure OpenAI endpoint for chat model>
MODEL_KEY=<API key>

EMBED_URL=<Azure OpenAI endpoint for embeddings>
EMBED_KEY=<API key>

VECTORDB_URL=<Azure AI Search endpoint>
VECTORDB_KEY=<API key>

MULTI_MODAL_URL=<Azure OpenAI endpoint for vision model>
MULTI_MODAL_KEY=<API key>
```

**3. Run locally**

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `/docs`.

## Docker

```bash
docker build -t ai-corrector .
docker run -p 3100:3100 --env-file .env ai-corrector
```

The container binds to port `3100`.

---

## API Reference

### Feed — Ingest Course Materials

**Upload a file**
```
POST /feed
Content-Type: multipart/form-data

courseCode: string        # e.g. "COMP6100"
file:       PDF | PPT | PPTX
```

Response:
```json
{
  "status": "success",
  "message": "'slides.pdf' inserted",
  "total_chunks_saved": 42,
  "token_usage": {
    "embedding_tokens": 18500,
    "embedding_cost_usd": 0.00037,
    "total_cost_usd": 0.00037
  }
}
```

**Ingest from a URL**
```
POST /feed-url
Content-Type: application/json

{
  "courseCode": "COMP6100",
  "url": "https://example.com/slides.pdf",
  "token": "optional-bearer-token"
}
```

**Ingest from multiple URLs (concurrent)**
```
POST /feed-urls
Content-Type: application/json

{
  "courseCode": "COMP6100",
  "urls": ["https://...", "https://..."],
  "token": "optional-bearer-token"
}
```

---

### Assess — Evaluate Student Answers

**Single assessment**
```
POST /assess
Content-Type: multipart/form-data

question:         string   (required)
student_answer:   string   (required)
rubric:           string   (optional)
courseCode:       string   (optional) — course to query in vector DB
use_key_answer:   bool     (optional, default true)
key_answer_text:  string   (optional) — model answer as plain text
key_answer_file:  file     (optional) — model answer as PDF | PPT | PPTX | TXT | DOCX
```

> If `key_answer_file` is provided it takes priority over `key_answer_text`. Files longer than 500 words are automatically condensed — the most semantically relevant sections are selected using cosine similarity against the question.

Response:
```json
{
  "status": "success",
  "retrieved_sources": ["lecture1.pdf", "lecture2.pptx"],
  "evaluation": {
    "reasoning": "Jawaban mahasiswa mencakup konsep dasar rekursi...",
    "score": 85,
    "sources": []
  },
  "token_usage": {
    "embedding_tokens": 142,
    "embedding_cost_usd": 0.00000284,
    "completion_input_tokens": 820,
    "completion_output_tokens": 195,
    "completion_cost_usd": 0.000646,
    "total_cost_usd": 0.00064884
  }
}
```

**Batch assessment**
```
POST /assess-batch
Content-Type: application/json

{
  "courseCode": "COMP6100",
  "question": "Jelaskan konsep rekursi.",
  "rubric": "Skor penuh jika menyebutkan base case dan recursive case.",
  "use_key_answer": true,
  "key_answer": "Rekursi adalah teknik pemrograman di mana fungsi memanggil dirinya sendiri...",
  "students": [
    { "student_id": "2501001", "answer": "..." },
    { "student_id": "2501002", "answer": "..." }
  ]
}
```

> `key_answer` in batch is text only. All students share the same retrieved context and key answer — context retrieval runs once, evaluations run concurrently.

Response:
```json
{
  "status": "success",
  "retrieved_sources": ["lecture1.pdf"],
  "results": [
    { "student_id": "2501001", "status": "success", "evaluation": { "reasoning": "...", "score": 90, "sources": [] } },
    { "student_id": "2501002", "status": "success", "evaluation": { "reasoning": "...", "score": 75, "sources": [] } }
  ],
  "token_usage": {
    "embedding_tokens": 142,
    "embedding_cost_usd": 0.00000284,
    "completion_input_tokens": 9800,
    "completion_output_tokens": 420,
    "completion_cost_usd": 0.00059,
    "total_cost_usd": 0.00059284
  }
}
```

---

## How It Works

```
Feed:
  File/URL → Extract text + images → Image descriptions via vision model
           → Chunk (400 words, 50-word overlap)
           → Batch embed → Upload to Azure AI Search

Assess:
  Question + Student Answer + Rubric
    │
    ├─ [courseCode provided] → Vector search → Retrieved course material
    │
    ├─ [key_answer provided] → Short (<500 words): use directly
    │                          Long (≥500 words): chunk → embed → top-3 by cosine similarity
    │
    └─ GPT model → score + reasoning + sources
```

## Supported File Types

| Format | Feed | Key Answer |
|---|---|---|
| PDF | ✓ | ✓ |
| PPTX | ✓ | ✓ |
| PPT | ✓ | ✓ |
| TXT | — | ✓ |
| DOCX | — | ✓ |

## Cost Estimation

Token prices used for cost estimates (verify against your Azure deployment pricing):

| Model | Input | Output |
|---|---|---|
| text-embedding-3-small | $0.02 / 1M tokens | — |
| gpt-5.4-mini | $0.40 / 1M tokens | $1.60 / 1M tokens |

Prices are defined in `utils/pricing.py` and can be adjusted to match your actual deployment.
