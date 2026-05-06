import uuid
import asyncio
import httpx
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Body, Form, HTTPException
from utils import extract_text, chunk_text, get_embedding
from config import search_client

router = APIRouter(tags=["masukin vector db"])

def _process_and_upload_sync(file_bytes: bytes, filename: str, courseCode: str) -> int:
    raw_text = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("Text extraction failed or returned empty content")

    chunks = chunk_text(raw_text)
    documents_to_upload = []
    
    for chunk in chunks:
        vector = get_embedding(chunk)
        doc = {
            "id": str(uuid.uuid4()),
            "content": chunk,
            "source_file": filename,
            "courseCode": courseCode,
            "content_vector": vector
        }
        documents_to_upload.append(doc)

    search_client.upload_documents(documents=documents_to_upload)
    return len(chunks)

async def _download_and_process(url: str, courseCode: str, token: Optional[str] = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=60.0)
            if response.status_code != 200:
                return {"url": url, "status": "failed", "error": f"Download failed (Status: {response.status_code})"}
            
            filename = url.split("/")[-1] or "downloaded_file"
            chunks_count = await asyncio.to_thread(_process_and_upload_sync, response.content, filename, courseCode)
            
            return {
                "url": url,
                "status": "success",
                "filename": filename,
                "total_chunks_saved": chunks_count
            }
        except Exception as e:
            return {"url": url, "status": "failed", "error": str(e)}

@router.post("/feed")
async def feed_material(
    courseCode: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        file_bytes = await file.read()
        chunks_count = await asyncio.to_thread(_process_and_upload_sync, file_bytes, file.filename, courseCode)
        
        return {
            "status": "success",
            "message": f"'{file.filename}' inserted",
            "total_chunks_saved": chunks_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/feed-url")
async def feed_material_by_url(
    url: str = Body(...),
    courseCode: str = Body(...),
    token: Optional[str] = Body(None)
):
    result = await _download_and_process(url, courseCode, token)
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    
    return {
        "status": "success",
        "message": f"'{result['filename']}' inserted from URL",
        "total_chunks_saved": result["total_chunks_saved"]
    }

@router.post("/feed-urls")
async def feed_multiple_urls(
    urls: List[str] = Body(...),
    courseCode: str = Body(...),
    token: Optional[str] = Body(None)
):
    tasks = [_download_and_process(url, courseCode, token) for url in urls]
    results = await asyncio.gather(*tasks)
    
    return {
        "status": "completed",
        "results": results
    }