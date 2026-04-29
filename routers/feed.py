import uuid
from fastapi import APIRouter, UploadFile, File, Body, HTTPException
from utils import extract_text, chunk_text, get_embedding
from config import search_client
import httpx

router = APIRouter(tags=["masukin vector db"])

@router.post("/feed")
async def feed_material(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        raw_text = extract_text(file_bytes, file.filename)
        
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="text gk dapet")

        chunks = chunk_text(raw_text)

        documents_to_upload = []
        for chunk in chunks:
            vector = get_embedding(chunk)
            doc = {
                "id": str(uuid.uuid4()),
                "content": chunk,
                "source_file": file.filename,
                "content_vector": vector
            }
            documents_to_upload.append(doc)

        search_client.upload_documents(documents=documents_to_upload)

        return {
            "status": "success",
            "message": f"'{file.filename}' inserted",
            "total_chunks_saved": len(chunks)
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/feed-url")
async def feed_material_by_url(
    url: str = Body(...),
    token: str = Body(...)
):
    try:
        headers = {}

        if token:
            headers = {
                "Authorization": f"Bearer {token}"
            }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to download file")
        
        file_bytes = response.content
        
        # Extract filename from URL
        filename = url.split("/")[-1] or "downloaded_file"

        raw_text = extract_text(file_bytes, filename)

        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Text gak dapet")
        
        chunks = chunk_text(text=raw_text)

        documents_to_upload = []
        for chunk in chunks:
            vector = get_embedding(chunk)
            doc = {
                "id": str(uuid.uuid4()),
                "content": chunk,
                "source_file": filename,
                "content_vector": vector
            }
            documents_to_upload.append(doc)

        search_client.upload_documents(documents=documents_to_upload)

        return {
            "status": "success",
            "message": f"'{filename}' inserted from URL",
            "total_chunks_saved": len(chunks)
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))