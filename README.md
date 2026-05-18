# AI Corrector

An AI-powered automated answer assessment system for educational institutions. Course materials are indexed into a vector database, and student answers are evaluated using Retrieval-Augmented Generation (RAG) with Azure OpenAI.

## Features

- **Material ingestion** — Upload PDF or PPTX files (or URLs) as course materials; text and embedded images are extracted, chunked, embedded, and stored in Azure Cognitive Search
- **Image understanding** — Embedded images in documents are described by a vision model and included as text context
- **RAG-based assessment** — Student answers are graded using retrieved course material as context, scored against a provided rubric
- **Web search fallback** — If course materials lack sufficient context, the model can query the web
- **Batch assessment** — Multiple student answers for the same question are evaluated concurrently

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI + Uvicorn/Gunicorn |
| LLM | Azure OpenAI (GPT-4.1-mini) |
| Vision | Azure OpenAI (GPT-4o) |
| Embeddings | Azure OpenAI (text-embedding-3-small) |
| Vector DB | Azure AI Search |
| Document parsing | PyPDF, python-pptx |
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

The API will be available at `http://localhost:8000`. Interactive docs are at `/docs`.

## Docker

```bash
docker build -t ai-corrector .
docker run -p 3100:3100 --env-file .env ai-corrector
```

The container binds to port `3100`.

## API Reference

### Feed — Ingest Course Materials

**Upload a file**
```
POST /feed
Content-Type: multipart/form-data

courseCode: string   # e.g. "COMP6100"
file: PDF or PPTX
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

**Ingest from multiple URLs**
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
Content-Type: application/json

{
  "courseCode": "COMP6100",
  "question": "Jelaskan konsep rekursi.",
  "student_answer": "Rekursi adalah ...",
  "rubric": "Skor penuh jika ..."
}
```

Response:
```json
{
  "status": "success",
  "retrieved_sources": ["lecture1.pdf", "lecture2.pptx"],
  "evaluation": {
    "reasoning": "...",
    "score": 85,
    "sources": []
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
  "rubric": "Skor penuh jika ...",
  "students": [
    { "student_id": "2501001", "answer": "..." },
    { "student_id": "2501002", "answer": "..." }
  ]
}
```

Response:
```json
{
  "status": "success",
  "retrieved_sources": ["lecture1.pdf"],
  "results": [
    { "student_id": "2501001", "evaluation": { "reasoning": "...", "score": 90 } },
    { "student_id": "2501002", "evaluation": { "reasoning": "...", "score": 75 } }
  ]
}
```

## How It Works

```
Feed:
  File/URL → Extract text + images → Image descriptions via GPT-4o
           → Chunk text (400 words) → Embed → Store in Azure AI Search

Assess:
  Question + Student Answer + Rubric + courseCode
  → Vector search for relevant course material
  → Send to GPT-4.1-mini with retrieved context
  → Return score + reasoning
```
