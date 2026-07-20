import asyncio
import uuid
from typing import Annotated, List

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import JSONResponse

from config.constants import EMBED_MODEL, VISION_MODEL_KEY
from schemas import FeedDeleteResponse, FeedResponse, FeedUrlRequest, FeedUrlsRequest, FeedUrlsResponse
from schemas.request import MetadataUpdateRequest
from utils.pricing import calculate_cost

from .service import delete_by_resource_id, process_file, process_url, process_url_with_callback, update_metadata

router = APIRouter(tags=["Feed"])

_ERROR_500 = {"description": "Internal server error — file parsing or upload failed"}
_ERROR_400 = {"description": "Bad request — URL is unreachable or the document could not be processed"}


@router.post(
    "/feed",
    response_model=FeedUrlsResponse,
    summary="Upload one or more course material files",
    description=(
        "Upload one or more **PDF**, **PPT**, **PPTX**, **DOCX**, or **TXT** files. "
        "Files are parsed into text chunks, embedded using `text-embedding-3-small`, "
        "and indexed in Azure AI Search under the given `course_code`.\n\n"
        "When multiple files are supplied, each is processed concurrently. "
        "Failed files are reported with `status: 'failed'` inside `results` — they do **not** cause the entire request to fail.\n\n"
        "Images in PDF and PPTX documents are described by the vision model and included as text chunks. "
        "DOCX and TXT are treated as a single page (no per-page splitting)."
    ),
    responses={500: _ERROR_500},
)
async def feed_material(
    course_code: Annotated[str, Form(examples=["COMP6100"], description="Course code to associate the material with")],
    files: Annotated[List[UploadFile], File(description="One or more PDF, PPT, PPTX, DOCX, or TXT files to ingest")],
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
        "Download a **PDF**, **PPT**, **PPTX**, **DOCX**, or **TXT** file from a URL and ingest it into the vector database. "
        "Optionally supply a `token` for downloading from protected LMS endpoints.\n\n"
        "When `resource_id` is supplied, chunks previously indexed under the same `resource_id` are deleted "
        "before the new chunks are uploaded, so re-feeding the same material never creates duplicates."
    ),
    responses={400: _ERROR_400, 500: _ERROR_500},
)
async def feed_material_by_url(request: FeedUrlRequest, background: BackgroundTasks):
    # Mode callback: balas 202 seketika supaya pemanggil tidak menahan koneksi HTTP
    # selama menit-menit pemrosesan, lalu laporkan hasilnya lewat callback.
    if request.callback_url:
        background.add_task(
            process_url_with_callback,
            request.url, request.course_code, request.token, request.resource_id,
            request.class_session_numbers, request.callback_url, request.callback_token,
            request.course_sessions,
        )
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "job_id": str(uuid.uuid4())},
        )

    result = await process_url(
        request.url, request.course_code, request.token, request.resource_id,
        request.class_session_numbers, request.course_sessions
    )
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
        "Download and ingest multiple **PDF**, **PPT**, **PPTX**, **DOCX**, or **TXT** files concurrently. "
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


@router.delete(
    "/feed/{resource_id:path}",
    response_model=FeedDeleteResponse,
    summary="Delete all indexed chunks of a material",
    description=(
        "Remove every chunk whose `resource_id` matches from the vector database. "
        "Used when a material is deleted or unpublished in the LMS."
    ),
    responses={500: _ERROR_500},
)
async def delete_material(
    resource_id: Annotated[str, Path(min_length=1, description="Stable LMS identifier of the material")],
):
    deleted = await delete_by_resource_id(resource_id)
    return {
        "status": "success",
        "resource_id": resource_id,
        "total_chunks_deleted": deleted,
    }


@router.patch(
    "/feed/{resource_id}/metadata",
    summary="Update material metadata only (no re-processing)",
    description=(
        "Update the course/class/session links of an already indexed material **without** "
        "re-downloading, re-extracting, or re-embedding it.\n\n"
        "Use this when only the links changed (e.g. a new class started using an existing "
        "material) while the file itself is unchanged. Costs nothing in AI tokens.\n\n"
        "Returns **404** when no chunk exists for `resource_id` — in that case the caller must "
        "perform a full feed instead."
    ),
    responses={404: {"description": "No indexed chunk found for this resource_id"}, 500: _ERROR_500},
)
async def update_material_metadata(
    resource_id: Annotated[str, Path(examples=["a0cd0e23-e990-4b39-9d09-d529890c1749"])],
    request: MetadataUpdateRequest,
):
    try:
        updated = await update_metadata(
            resource_id, request.course_code, request.class_session_numbers, request.course_sessions
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "resource_id": resource_id, "chunks_updated": updated}
