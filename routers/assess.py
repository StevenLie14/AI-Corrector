import os
import json
import httpx
from fastapi import APIRouter, HTTPException
from azure.search.documents.models import VectorizedQuery
from utils import get_embedding
from config import search_client
from schemas import AssessRequest

router = APIRouter(tags=["Assessment"])

@router.post("/assess")
async def assess_answer(request: AssessRequest):
    try:
        query_vector = get_embedding(request.question)

        vector_query = VectorizedQuery(
            vector=query_vector, 
            k_nearest_neighbors=3, 
            fields="content_vector"
        )
        
        search_results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            select=["content", "source_file"]
        )

        results_list = list(search_results)
        
        retrieved_contexts = []
        retrieved_sources = []
        for result in results_list:
            retrieved_contexts.append(f"[Dari File: {result['source_file']}]\n{result['content']}")
            if result['source_file'] not in retrieved_sources:
                retrieved_sources.append(result['source_file'])
        
        context_text = "\n\n".join(retrieved_contexts)

        if not context_text:
            context_text = "Tidak ada materi referensi spesifik yang ditemukan di database."

        system_prompt = """
        Kamu adalah asisten dosen yang ahli dan objektif. Tugasmu adalah menilai jawaban mahasiswa.
        Kamu harus merespons HANYA dalam format JSON dengan struktur:
        {
            "score": <angka>,
            "reasoning": "<alasan logis berbahasa Indonesia>"
        }
        """

        user_prompt = f"""
        Berdasarkan materi kuliah berikut, evaluasi jawaban mahasiswa.

        MATERI KULIAH:
        {context_text}

        SOAL:
        {request.question}

        JAWABAN MAHASISWA:
        {request.student_answer}

        RUBRIK PENILAIAN:
        {request.rubric}

        Berikan nilai dan alasan (reasoning) sesuai rubrik.
        """

        endpoint = os.getenv("MODEL_URL")
        
        
        headers = {
            "api-key": os.getenv("MODEL_KEY"),
            "Content-Type": "application/json"
        }
        
        payload = {
            "model":"gpt-5.4-mini",
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            
            if resp.status_code != 200:
                print("Azure Error:", resp.text)
            resp.raise_for_status()
            
            data = resp.json()

        output_data = data.get("output", [])

        if not output_data:
            raise ValueError(f"Format respons Azure tidak sesuai: {data}")
            
        result_content = output_data[0].get("content", [])[0].get("text", "").strip()
        
        # kalau return code ilangin
        if result_content.startswith("```json"):
            result_content = result_content[7:-3].strip()
        elif result_content.startswith("```"):
            result_content = result_content[3:-3].strip()

        final_assessment = json.loads(result_content)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": final_assessment
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))