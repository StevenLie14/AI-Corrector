from fastapi import APIRouter, UploadFile, File, Body, HTTPException
from config import search_client

router = APIRouter(tags=["masukin vector db"])

@router.get("/get-vector-db")
async def get_vector_db():
    try:
        # Coba lakukan pencarian sederhana untuk memastikan koneksi ke vector DB berfungsi
        results = search_client.search()
        return {"status": "success", "results": f"{results.}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vector DB connection failed: {str(e)}")