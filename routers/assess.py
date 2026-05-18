import os
import json
import asyncio
from urllib.parse import urlparse
from openai import AsyncOpenAI
from fastapi import APIRouter, HTTPException
from azure.search.documents.models import VectorizedQuery
from utils import get_embedding
from config import search_client
from schemas import AssessRequest, BatchAssessRequest

router = APIRouter(tags=["Assessment"])

async def _get_context(question: str, courseCode: str):
    if not courseCode or not courseCode.strip():
        return "Tidak ada materi referensi spesifik yang ditemukan di database.", []

    query_vector = get_embedding(question)
    vector_query = VectorizedQuery(
        vector=query_vector, 
        k_nearest_neighbors=3, 
        fields="content_vector"
    )
    
    search_results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        filter=f"courseCode eq '{courseCode}'",
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
    
    return context_text, retrieved_sources

async def _evaluate_answer(context_text: str, question: str, student_answer: str, rubric: str):
    system_prompt = """
Kamu adalah asisten dosen yang ahli dan objektif. Tugasmu adalah menilai jawaban mahasiswa.

- Jika context dari vector db tidak relevan, gunakan web search.
- Jika menggunakan web search, kamu WAJIB menyertakan sumber dari internet.
- Setiap klaim penting HARUS memiliki sumber yang valid (URL).
- Jangan membuat sumber jika tidak yakin.

Berikan jawaban dalam format JSON berikut:

{
    "reasoning": "<alasan logis berbahasa Indonesia, evaluasi dulu secara mendalam sebelum memberikan nilai, sertakan confidence secara ringkas>",
    "score": <angka yang sesuai dengan reasoning dan rubrik>,
    "sources": [
        {
            "title": "<judul sumber>",
            "url": "<link sumber>"
        }
    ]
}

Catatan PENTING:
- Jika tidak menggunakan web search, "sources" boleh kosong []
- JANGAN menambahkan teks di luar JSON. Hasil akhir HANYA boleh JSON yang valid.
- Jika materi atau rubrik kosong, TETAP berikan penilaian berdasarkan standar kebenaran logis dan akal sehat, lalu tulis alasannya di "reasoning".
    """

    user_prompt = f"""
    Berdasarkan materi kuliah berikut, evaluasi jawaban mahasiswa.

    MATERI KULIAH:
    {context_text}

    SOAL:
    {question}

    JAWABAN MAHASISWA:
    {student_answer}

    RUBRIK PENILAIAN:
    {rubric if rubric and rubric.strip() else "Tidak ada rubrik khusus. Gunakan standar kebenaran logis, ilmu pengetahuan, dan akal sehat untuk menilai."}

    Berikan nilai dan alasan (reasoning) sesuai rubrik dan kasih alasan yang mengarah ke rubriknya. juga kasih secara ringkas apa jawaban yang  kamu harapkan untuk nilai yang lebih maksimal. Jika rubrik kosong, berikan nilai berdasarkan tingkat kebenaran jawaban.
    """

    model_url = os.getenv("MODEL_URL", "")
    resource_name = "YOUR-RESOURCE-NAME"
    if model_url:
        parsed = urlparse(model_url)
        resource_name = parsed.netloc.split('.')[0]
        
    base_url = f"https://{resource_name}.openai.azure.com/openai/v1/"
    api_key = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("MODEL_KEY"))

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    response = await client.responses.create(
        model="gpt-5.4-mini",
        tools=[{"type": "web_search"}],
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    print(f"Response: {response}")

    result_content = response.output_text.strip()

    print(f"Result content: {result_content}")
    
    if result_content.startswith("```json"):
        result_content = result_content[7:-3].strip()
    elif result_content.startswith("```"):
        result_content = result_content[3:-3].strip()

    try:
        return json.loads(result_content)
    except json.JSONDecodeError:
        return {
            "reasoning": f"Sistem AI tidak dapat menghasilkan format penilaian yang benar. Harap periksa kembali rubrik atau konteks. (Respons AI: {result_content[:150]}...)",
            "score": 0,
            "sources": []
        }

@router.post("/assess")
async def assess_answer(request: AssessRequest):
    try:
        context_text, retrieved_sources = await _get_context(request.question, request.courseCode)
        final_assessment = await _evaluate_answer(
            context_text, 
            request.question, 
            request.student_answer, 
            request.rubric
        )

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": final_assessment
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/assess-batch")
async def assess_batch(request: BatchAssessRequest):
    try:
        context_text, retrieved_sources = await _get_context(request.question, request.courseCode)
        
        tasks = []
        for student in request.students:
            tasks.append(_evaluate_answer(
                context_text,
                request.question,
                student.answer,
                request.rubric
            ))
        
        evaluations = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for i, eval_result in enumerate(evaluations):
            student_id = request.students[i].student_id
            if isinstance(eval_result, Exception):
                results.append({
                    "student_id": student_id,
                    "status": "error",
                    "error": str(eval_result)
                })
            else:
                results.append({
                    "student_id": student_id,
                    "status": "success",
                    "evaluation": eval_result
                })
        
        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))