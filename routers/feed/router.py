import asyncio
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from utils.pricing import calculate_cost

from .service import process_file, process_url

router = APIRouter(tags=["Feed"])

_EMBED_MODEL = "text-embedding-3-small"


class FeedUrlRequest(BaseModel):
    url: str
    courseCode: str
    token: Optional[str] = None


class FeedUrlsRequest(BaseModel):
    urls: List[str]
    courseCode: str
    token: Optional[str] = None


@router.post("/feed")
async def feed_material(
    courseCode: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        chunks_count, embed_tokens = await process_file(await file.read(), file.filename, courseCode)
        embed_cost = calculate_cost(_EMBED_MODEL, embed_tokens)
        return {
            "status": "success",
            "message": f"'{file.filename}' inserted",
            "total_chunks_saved": chunks_count,
            "token_usage": {
                "embedding_tokens": embed_tokens,
                "embedding_cost_usd": embed_cost,
                "total_cost_usd": embed_cost,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feed-url")
async def feed_material_by_url(request: FeedUrlRequest):
    result = await process_url(request.url, request.courseCode, request.token)
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    return {
        "status": "success",
        "message": f"'{result['filename']}' inserted from URL",
        "total_chunks_saved": result["total_chunks_saved"],
        "token_usage": result["token_usage"],
    }


@router.post("/feed-urls")
async def feed_multiple_urls(request: FeedUrlsRequest):
    tasks = [process_url(url, request.courseCode, request.token) for url in request.urls]
    results = await asyncio.gather(*tasks)

    total_embed_tokens = sum(
        r.get("token_usage", {}).get("embedding_tokens", 0)
        for r in results
        if r.get("status") == "success"
    )
    total_cost = calculate_cost(_EMBED_MODEL, total_embed_tokens)

    return {
        "status": "completed",
        "results": list(results),
        "token_usage": {
            "embedding_tokens": total_embed_tokens,
            "embedding_cost_usd": total_cost,
            "total_cost_usd": total_cost,
        },
    }
