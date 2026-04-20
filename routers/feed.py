import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from utils import extract_text, chunk_text, get_embedding
from config import search_client

router = APIRouter(tags=["masukin vector db"])

@router.post("/feed")
async def feed_material(file: UploadFile = File(...)):
    try:
        raw_text = extract_text(file)
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))