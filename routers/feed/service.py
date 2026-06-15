import asyncio
import os
import uuid
from urllib.parse import urlparse

import httpx

from config import search_client
from config.constants import (
    EMBED_MODEL,
    FIELD_CONTENT,
    FIELD_COURSE_CODE,
    FIELD_ID,
    FIELD_SOURCE,
    FIELD_VECTOR,
    VISION_MODEL_KEY,
)
from utils import chunk_text, extract_text, get_embeddings_batch
from utils.pricing import calculate_cost

_UPLOAD_BATCH_SIZE = 1000


def _process_and_upload_sync(file_bytes: bytes, filename: str, course_code: str) -> tuple[int, int, int]:
    raw_text, vision_tokens = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("Text extraction failed or returned empty content")

    chunks = chunk_text(raw_text)
    vectors, embed_tokens = get_embeddings_batch(chunks)
    documents = [
        {
            FIELD_ID: str(uuid.uuid4()),
            FIELD_CONTENT: chunk,
            FIELD_SOURCE: filename,
            FIELD_COURSE_CODE: course_code,
            FIELD_VECTOR: vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    for i in range(0, len(documents), _UPLOAD_BATCH_SIZE):
        search_client.upload_documents(documents=documents[i:i + _UPLOAD_BATCH_SIZE])
    return len(chunks), embed_tokens, vision_tokens


async def process_file(file_bytes: bytes, filename: str, course_code: str) -> tuple[int, int, int]:
    return await asyncio.to_thread(_process_and_upload_sync, file_bytes, filename, course_code)


async def process_url(url: str, course_code: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=60.0)
            if response.status_code != 200:
                return {
                    "url": url,
                    "status": "failed",
                    "error": f"Download failed (status: {response.status_code})",
                }

            filename = os.path.basename(urlparse(url).path) or "downloaded_file"
            chunks_count, embed_tokens, vision_tokens = await process_file(response.content, filename, course_code)

            embed_cost = calculate_cost(EMBED_MODEL, embed_tokens)
            vision_cost = calculate_cost(VISION_MODEL_KEY, vision_tokens)

            return {
                "url": url,
                "status": "success",
                "filename": filename,
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
            return {"url": url, "status": "failed", "error": str(e)}
