import asyncio
import json
import os
from urllib.parse import urlparse

from azure.search.documents.models import VectorizedQuery
from openai import AsyncOpenAI

from config import search_client
from utils import get_embedding

_SYSTEM_PROMPT = """
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


def _build_openai_client() -> AsyncOpenAI:
    model_url = os.getenv("MODEL_URL", "")
    resource_name = "YOUR-RESOURCE-NAME"
    if model_url:
        parsed = urlparse(model_url)
        resource_name = parsed.netloc.split(".")[0]
    return AsyncOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY", os.getenv("MODEL_KEY")),
        base_url=f"https://{resource_name}.openai.azure.com/openai/v1/",
    )


_openai_client = _build_openai_client()


async def get_context(question: str, course_code: str) -> tuple[str, list, int]:
    if not course_code or not course_code.strip():
        return "Tidak ada materi referensi spesifik yang ditemukan di database.", [], 0

    vector, embed_tokens = await asyncio.to_thread(get_embedding, question)
    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=3,
        fields="content_vector",
    )

    safe_course_code = course_code.replace("'", "''")
    search_results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        filter=f"courseCode eq '{safe_course_code}'",
        select=["content", "source_file"],
    )

    retrieved_contexts = []
    retrieved_sources = []

    for result in search_results:
        retrieved_contexts.append(f"[Dari File: {result['source_file']}]\n{result['content']}")
        if result["source_file"] not in retrieved_sources:
            retrieved_sources.append(result["source_file"])

    context_text = "\n\n".join(retrieved_contexts) or "Tidak ada materi referensi spesifik yang ditemukan di database."
    return context_text, retrieved_sources, embed_tokens


async def evaluate_answer(
    context_text: str, question: str, student_answer: str, rubric: str
) -> tuple[dict, int, int]:
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

    Berikan nilai dan alasan (reasoning) sesuai rubrik dan kasih alasan yang mengarah ke rubriknya. juga kasih secara ringkas apa jawaban yang kamu harapkan untuk nilai yang lebih maksimal. Jika rubrik kosong, berikan nilai berdasarkan tingkat kebenaran jawaban.
    """

    response = await _openai_client.responses.create(
        model="gpt-5.4-mini",
        tools=[{"type": "web_search"}],
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    result_content = response.output_text.strip()

    if result_content.startswith("```json"):
        result_content = result_content[7:-3].strip()
    elif result_content.startswith("```"):
        result_content = result_content[3:-3].strip()

    try:
        return json.loads(result_content), input_tokens, output_tokens
    except json.JSONDecodeError:
        return (
            {
                "reasoning": f"Sistem AI tidak dapat menghasilkan format penilaian yang benar. Harap periksa kembali rubrik atau konteks. (Respons AI: {result_content[:150]}...)",
                "score": 0,
                "sources": [],
            },
            input_tokens,
            output_tokens,
        )
