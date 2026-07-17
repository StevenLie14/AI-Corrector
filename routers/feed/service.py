import asyncio
import base64
import os
import uuid
from urllib.parse import urlparse

import httpx

from config import search_client
from config.constants import (
    EMBED_MODEL,
    FIELD_CLASS_SESSION_NUMBERS,
    FIELD_CONTENT,
    FIELD_COURSE_CODE,
    FIELD_ID,
    FIELD_PAGE,
    FIELD_RESOURCE_ID,
    FIELD_SOURCE,
    FIELD_VECTOR,
    VISION_MODEL_KEY,
)
from utils import chunk_text, extract_pages, get_embeddings_batch, sanitize_text
from utils.pricing import calculate_cost

_UPLOAD_BATCH_SIZE = 1000


def _escape_odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _document_key(resource_id: str, index: int) -> str:
    encoded = base64.urlsafe_b64encode(resource_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}-{index}"


def _raise_on_failed_results(results, operation: str) -> None:
    failed = [result for result in results if not result.succeeded]
    if not failed:
        return
    detail = "; ".join(f"{result.key}: {result.error_message}" for result in failed[:5])
    raise RuntimeError(f"Azure AI Search {operation} failed for {len(failed)} document(s): {detail}")


def _chunk_ids_of(resource_id: str) -> list[str]:
    results = search_client.search(
        search_text="*",
        filter=f"{FIELD_RESOURCE_ID} eq '{_escape_odata_literal(resource_id)}'",
        select=[FIELD_ID],
    )
    return [doc[FIELD_ID] for doc in results]


def _delete_ids_sync(ids: list[str]) -> int:
    for i in range(0, len(ids), _UPLOAD_BATCH_SIZE):
        batch = [{FIELD_ID: doc_id} for doc_id in ids[i:i + _UPLOAD_BATCH_SIZE]]
        _raise_on_failed_results(search_client.delete_documents(documents=batch), "delete")
    return len(ids)


def _delete_by_resource_id_sync(resource_id: str) -> int:
    return _delete_ids_sync(_chunk_ids_of(resource_id))


async def delete_by_resource_id(resource_id: str) -> int:
    return await asyncio.to_thread(_delete_by_resource_id_sync, resource_id)


def _process_and_upload_sync(
    file_bytes: bytes,
    filename: str,
    course_code: str,
    resource_id: str | None = None,
    class_session_numbers: list[int] | None = None,
) -> tuple[int, int, int]:
    course_code = course_code.strip().upper() if course_code else ""
    pages = extract_pages(file_bytes, filename)

    all_chunks: list[str] = []
    all_page_nums: list[int] = []
    total_vision_tokens = 0

    for page_num, page_text, vision_tokens in pages:
        total_vision_tokens += vision_tokens
        page_text = sanitize_text(page_text)
        if not page_text.strip():
            continue
        page_chunks = chunk_text(page_text)
        all_chunks.extend(page_chunks)
        all_page_nums.extend([page_num] * len(page_chunks))

    if not all_chunks:
        raise ValueError("Text extraction failed or returned empty content")

    vectors, embed_tokens = get_embeddings_batch(all_chunks)

    documents = []
    for idx, (chunk, page_num, vector) in enumerate(zip(all_chunks, all_page_nums, vectors)):
        document = {
            FIELD_ID: _document_key(resource_id, idx) if resource_id else str(uuid.uuid4()),
            FIELD_CONTENT: chunk,
            FIELD_SOURCE: filename,
            FIELD_PAGE: page_num,
            FIELD_COURSE_CODE: course_code,
            FIELD_VECTOR: vector,
        }
        if resource_id:
            document[FIELD_RESOURCE_ID] = resource_id
        if class_session_numbers:
            document[FIELD_CLASS_SESSION_NUMBERS] = class_session_numbers
        documents.append(document)

    stale_ids = _chunk_ids_of(resource_id) if resource_id else []

    for i in range(0, len(documents), _UPLOAD_BATCH_SIZE):
        _raise_on_failed_results(
            search_client.upload_documents(documents=documents[i:i + _UPLOAD_BATCH_SIZE]), "upload"
        )

    if stale_ids:
        current_ids = {document[FIELD_ID] for document in documents}
        _delete_ids_sync([doc_id for doc_id in stale_ids if doc_id not in current_ids])

    return len(all_chunks), embed_tokens, total_vision_tokens


async def process_file(
    file_bytes: bytes,
    filename: str,
    course_code: str,
    resource_id: str | None = None,
    class_session_numbers: list[int] | None = None,
) -> tuple[int, int, int]:
    return await asyncio.to_thread(
        _process_and_upload_sync, file_bytes, filename, course_code, resource_id, class_session_numbers
    )


async def process_url(
    url: str,
    course_code: str,
    token: str | None = None,
    resource_id: str | None = None,
    class_session_numbers: list[int] | None = None,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.get(url, headers=headers, timeout=60.0)
            if response.status_code != 200:
                return {
                    "url": url,
                    "status": "failed",
                    "error": f"Download failed (status: {response.status_code})",
                }

            filename = os.path.basename(urlparse(url).path) or "downloaded_file"
            chunks_count, embed_tokens, vision_tokens = await process_file(
                response.content, filename, course_code, resource_id, class_session_numbers
            )

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
