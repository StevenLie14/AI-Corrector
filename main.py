import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from routers import feed, assess
from utils.logging_config import configure_logging, request_id_var

_DEBUG = os.getenv("DEBUG", "").lower() == "true"
_API_KEY = os.getenv("API_KEY", "")
_NO_AUTH_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json"}

configure_logging(_DEBUG)
logger = logging.getLogger(__name__)


class _RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_var.reset(token)


class _ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _API_KEY and request.url.path not in _NO_AUTH_PATHS:
            if request.headers.get("X-API-Key") != _API_KEY:
                return JSONResponse(status_code=401, content={"detail": "Invalid or missing Auth API key"})
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Corrector v%s", app.version)
    try:
        import config
        logger.info("Azure clients initialized successfully")
    except RuntimeError as e:
        logger.critical("Startup failed: %s", e)
        raise
    yield
    logger.info("Shutting down AI Corrector")


_tags_metadata = [
    {
        "name": "Health",
        "description": "Service health check — verifies connectivity to Azure AI Search.",
    },
    {
        "name": "Feed",
        "description": (
            "Upload course materials (PDF, PPT, PPTX, DOCX, TXT) into the Azure AI Search vector database. "
            "Uploaded files are chunked, embedded, and indexed so they can later be used as "
            "reference context during student answer assessment."
        ),
    },
    {
        "name": "Assessment",
        "description": (
            "Evaluate student answers using Azure OpenAI. "
            "The AI scores each answer against the provided rubric and either a **key answer** "
            "or **course materials** retrieved from the vector database. "
            "Student answers may be plain text, a document URL, a Google Docs link, or a web article URL. "
            "Supports single, batch (one question / many students), and multi-batch (many questions) modes."
        ),
    },
    {
        "name": "Debug",
        "description": (
            "Inspect document parsing internals — extracted text, chunks, images, and URL resolution. "
            "Manage the vector DB (seed from folder, clear by course). "
            "**Only available when the `DEBUG` environment variable is set to `true`.**"
        ),
    },
]

app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    title="AI Corrector",
    description="""
## AI Corrector API

Platform penilaian jawaban mahasiswa berbasis AI menggunakan **Azure OpenAI** dan **Azure AI Search**.

### Autentikasi

Jika `API_KEY` dikonfigurasi, semua endpoint (kecuali `/health`) membutuhkan header:
```
X-API-Key: <your-api-key>
```
Klik tombol **Authorize** di kanan atas untuk mengisi API key di Swagger UI.

### Alur Penggunaan

1. **Feed** — Upload materi kuliah ke vector database via `/feed` atau `/feed-url`
2. **Assess** — Evaluasi jawaban mahasiswa via `/assess`, `/assess-batch`, atau `/assess-batch-multi`

### Mode Penilaian

| Mode | `use_key_answer` | Sumber Konteks |
|---|---|---|
| Key Answer | `true` | Kunci jawaban yang diberikan langsung |
| Vector DB | `false` | Materi kuliah dari vector database + web search otomatis |

### Format Dokumen yang Didukung

Feed: **PDF, PPT, PPTX, DOCX, TXT** · Student Answer: **PDF, PPTX, PPT, DOCX, TXT, Google Docs URL, Web Article URL**
""",
    version="2.0.2",
    openapi_tags=_tags_metadata,
    contact={
        "name": "AI Corrector Team",
        "email": "test@gmail.com",
    },
)

app.add_middleware(_RequestIdMiddleware)
app.add_middleware(_ApiKeyMiddleware)
app.include_router(feed.router)
app.include_router(assess.router)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version="3.0.3",
        description=app.description,
        contact={"name": "AI Corrector Team", "email": "shinkudo3741@gmail.com"},
        tags=_tags_metadata,
        routes=app.routes,
    )

    feed_body = schema.get("components", {}).get("schemas", {}).get("Body_feed_material_feed_post", {})
    props = feed_body.get("properties", {})
    if props.get("files", {}).get("type") == "array":
        props["files"]["items"] = {"type": "string", "format": "binary"}

    schema.setdefault("components", {})["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Set `API_KEY` env var to enable auth. Pass the key in this header.",
        }
    }
    if _API_KEY:
        schema["security"] = [{"ApiKeyAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = _custom_openapi


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )

if _DEBUG:
    from routers import debug
    app.include_router(debug.router)


@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check service health. Pings Azure AI Search. Returns 503 if degraded. **Does not require API key.**",
)
async def health():
    from config import search_client
    checks: dict = {}
    try:
        count = await asyncio.to_thread(search_client.get_document_count)
        checks["vectordb"] = {"status": "ok", "document_count": count}
    except Exception as e:
        checks["vectordb"] = {"status": "error", "error": str(e)}
    overall = "ok" if all(v["status"] == "ok" for v in checks.values()) else "degraded"
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(status_code=status_code, content={"status": overall, "checks": checks})


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "api api. ->/docs"}

