import uuid
import asyncio
import httpx
from typing import Optional

from utils import extract_text, chunk_text, get_embedding
from config import search_client


def _process_and_upload_sync(file_bytes: bytes, filename: str, course_code: str) -> int:
    raw_text = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("Text extraction failed or returned empty content")

    chunks = chunk_text(raw_text)
    documents = [
        {
            "id": str(uuid.uuid4()),
            "content": chunk,
            "source_file": filename,
            "courseCode": course_code,
            "content_vector": get_embedding(chunk),
        }
        for chunk in chunks
    ]

    search_client.upload_documents(documents=documents)
    return len(chunks)


async def process_file(file_bytes: bytes, filename: str, course_code: str) -> int:
    return await asyncio.to_thread(_process_and_upload_sync, file_bytes, filename, course_code)


async def process_url(url: str, course_code: str, token: Optional[str] = None) -> dict:
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

            filename = url.split("/")[-1] or "downloaded_file"
            chunks_count = await process_file(response.content, filename, course_code)

            return {
                "url": url,
                "status": "success",
                "filename": filename,
                "total_chunks_saved": chunks_count,
            }
        except Exception as e:
            return {"url": url, "status": "failed", "error": str(e)}
