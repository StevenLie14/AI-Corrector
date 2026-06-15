import asyncio
from typing import Annotated, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from config.constants import EMBED_MODEL, VISION_MODEL_KEY
from schemas import FeedResponse, FeedUrlRequest, FeedUrlsRequest, FeedUrlsResponse
from utils.pricing import calculate_cost

from .service import process_file, process_url

router = APIRouter(tags=["Feed"])

_ERROR_500 = {"description": "Internal server error — file parsing or upload failed"}
_ERROR_400 = {"description": "Bad request — URL is unreachable or the document could not be processed"}


@router.post(
    "/feed",
    response_model=FeedUrlsResponse,
    summary="Upload one or more course material files",
    description=(
        "Upload one or more **PDF**, **PPT**, or **PPTX** files. "
        "Files are parsed into text chunks, embedded using `text-embedding-3-small`, "
        "and indexed in Azure AI Search under the given `course_code`.\n\n"
        "When multiple files are supplied, each is processed concurrently. "
        "Failed files are reported with `status: 'failed'` inside `results` — they do **not** cause the entire request to fail.\n\n"
        "Images in the documents are described by the vision model and included as text chunks."
    ),
    responses={500: _ERROR_500},
)
async def feed_material(
    course_code: Annotated[str, Form(examples=["COMP6100"], description="Course code to associate the material with")],
    files: Annotated[List[UploadFile], File(description="One or more PDF, PPT, or PPTX files to ingest")],
):
    async def _process(file: UploadFile) -> dict:
        try:
            chunks_count, embed_tokens, vision_tokens = await process_file(await file.read(), file.filename, course_code)
            embed_cost = calculate_cost(EMBED_MODEL, embed_tokens)
            vision_cost = calculate_cost(VISION_MODEL_KEY, vision_tokens)
            return {
                "status": "success",
                "filename": file.filename,
                "total_chunks_saved": chunks_count,
                "token_usage": {
                    "embedding_tokens": embed_tokens,
                    "embedding_cost_usd": embed_cost,
                    "vision_tokens": vision_tokens,
                    "vision_cost_usd": vision_cost,
                    "total_cost_usd": round(embed_cost + vision_cost, 8),
                },
            }
        except Exception as e:
            return {"status": "failed", "filename": file.filename, "error": str(e)}

    results = await asyncio.gather(*[_process(f) for f in files])

    successful = [r for r in results if r.get("status") == "success"]
    total_embed_tokens = sum(r["token_usage"]["embedding_tokens"] for r in successful)
    total_vision_tokens = sum(r["token_usage"]["vision_tokens"] for r in successful)
    embed_cost = calculate_cost(EMBED_MODEL, total_embed_tokens)
    vision_cost = calculate_cost(VISION_MODEL_KEY, total_vision_tokens)

    return {
        "status": "completed",
        "results": list(results),
        "token_usage": {
            "embedding_tokens": total_embed_tokens,
            "embedding_cost_usd": embed_cost,
            "vision_tokens": total_vision_tokens,
            "vision_cost_usd": vision_cost,
            "total_cost_usd": round(embed_cost + vision_cost, 8),
        },
    }


@router.post(
    "/feed-url",
    response_model=FeedResponse,
    summary="Ingest a course material from a URL",
    description=(
        "Download a **PDF**, **PPT**, or **PPTX** file from a URL and ingest it into the vector database. "
        "Optionally supply a `token` for downloading from protected LMS endpoints."
    ),
    responses={400: _ERROR_400, 500: _ERROR_500},
)
async def feed_material_by_url(request: FeedUrlRequest):
    result = await process_url(request.url, request.course_code, request.token)
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    return {
        "status": "success",
        "message": f"'{result['filename']}' inserted from URL",
        "total_chunks_saved": result["total_chunks_saved"],
        "token_usage": result["token_usage"],
    }


@router.post(
    "/feed-urls",
    response_model=FeedUrlsResponse,
    summary="Ingest multiple course materials from URLs",
    description=(
        "Download and ingest multiple **PDF**, **PPT**, or **PPTX** files concurrently. "
        "Each URL is processed in parallel. Per-URL results are returned individually; "
        "the `token_usage` field reflects the aggregated cost across all successful ingestions.\n\n"
        "Failed URLs are reported with `status: 'failed'` inside `results` — they do **not** cause the entire request to fail."
    ),
    responses={500: _ERROR_500},
)
async def feed_multiple_urls(request: FeedUrlsRequest):
    tasks = [process_url(url, request.course_code, request.token) for url in request.urls]
    results = await asyncio.gather(*tasks)

    successful = [r for r in results if r.get("status") == "success"]
    total_embed_tokens = sum(r["token_usage"]["embedding_tokens"] for r in successful)
    total_vision_tokens = sum(r["token_usage"]["vision_tokens"] for r in successful)
    embed_cost = calculate_cost(EMBED_MODEL, total_embed_tokens)
    vision_cost = calculate_cost(VISION_MODEL_KEY, total_vision_tokens)

    return {
        "status": "completed",
        "results": list(results),
        "token_usage": {
            "embedding_tokens": total_embed_tokens,
            "embedding_cost_usd": embed_cost,
            "vision_tokens": total_vision_tokens,
            "vision_cost_usd": vision_cost,
            "total_cost_usd": round(embed_cost + vision_cost, 8),
        },
    }
