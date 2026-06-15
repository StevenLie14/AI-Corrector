import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware

from routers import feed, assess
from utils.json_response import NeatJSONResponse
from utils.logging_config import configure_logging, request_id_var

_DEBUG = os.getenv("DEBUG", "").lower() == "true"
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
        "name": "Feed",
        "description": (
            "Upload course materials (PDF, PPT, PPTX) into the Azure AI Search vector database. "
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
            "Supports single, batch (one question / many students), and multi-batch (many questions) modes."
        ),
    },
    {
        "name": "Debug",
        "description": (
            "Inspect document parsing internals — extracted text, chunks, and embedded images. "
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

### Alur Penggunaan

1. **Feed** — Upload materi kuliah ke vector database via `/feed` atau `/feed-url`
2. **Assess** — Evaluasi jawaban mahasiswa via `/assess`, `/assess-batch`, atau `/assess-batch-multi`

### Mode Penilaian

| Mode | `use_key_answer` | Sumber Konteks |
|---|---|---|
| Key Answer | `true` | Kunci jawaban yang diberikan langsung |
| Vector DB | `false` | Materi kuliah dari vector database + web search |

### Format Dokumen yang Didukung

Feed: **PDF, PPT, PPTX** · Jawaban Mahasiswa: **PDF, PPTX, PPT, DOCX, TXT**
""",
    version="0.6.7",
    default_response_class=NeatJSONResponse,
    openapi_tags=_tags_metadata,
    contact={
        "name": "AI Corrector Team",
        "email": "shinkudo3741@gmail.com",
    },
)

app.add_middleware(_RequestIdMiddleware)
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


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "api api. ->/docs"}
