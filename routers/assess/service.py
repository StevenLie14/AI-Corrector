import asyncio
import json
import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

import httpx
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
    "reasoning": "<alasan logis berbahasa Indonesia, evaluasi secara mendalam berdasarkan jawaban mahasiswa dan rubrik. Maksimal 2 kalimat. JANGAN memasukkan confidence level atau tingkat keyakinan.>",
    "score": <angka yang sesuai dengan reasoning dan rubrik>,
    "confidence": <tingkat confidence kamu dalam bentuk angka dari 0 hingga 100, dengan 0 melambangkan tidak percaya sama sekali dan 100 menggambarkan sangat percaya>,
    "feedback": "<saran/masukan konstruktif agar jawaban mahasiswa bisa lebih baik dan lengkap di kemudian hari. Maksimal 2 kalimat, namun harus cukup lengkap. Jika score adalah 0, bagian ini wajib dikosongkan (diisi string kosong \"\"). bahasa yang digunakan untuk ini mengikuti bahasa jawaban mahasiswa.>",
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
- Baik "reasoning" maupun "feedback" dibatasi MAKSIMAL 2 KALIMAT.
- Jika score yang diberikan adalah 0, maka "feedback" WAJIB dikosongkan (diisi "").
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


async def _validate_sources(sources: list) -> list:
    if not sources:
        return []

    async def is_reachable(source: dict) -> bool:
        url = source.get("url", "")
        if not url or not url.startswith("http"):
            return False
        try:
            async with httpx.AsyncClient() as client:
                r = await client.head(url, timeout=5.0, follow_redirects=True)
                return r.status_code != 404
        except Exception:
            return False

    valid_flags = await asyncio.gather(*[is_reachable(s) for s in sources])
    return [s for s, ok in zip(sources, valid_flags) if ok]


async def get_context(question: str, course_code: str) -> tuple[str, list, int]:
    vector, embed_tokens = await asyncio.to_thread(get_embedding, question)
    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=3,
        fields="content_vector",
    )

    safe_course_code = course_code.strip().replace("'", "''") if course_code else ""
    search_results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        filter=f"courseCode eq '{safe_course_code}'" if safe_course_code else None,
        select=["content", "source_file"],
    )

    retrieved_contexts = []
    retrieved_sources = []

    for result in search_results:
        retrieved_contexts.append(f"[Dari File: {result['source_file']}]\n{result['content']}")
        if result["source_file"] not in retrieved_sources:
            retrieved_sources.append(result["source_file"])

    context_text = "\n\n".join(retrieved_contexts)
    return context_text, retrieved_sources, embed_tokens


async def evaluate_answer(
    context_text: str,
    question: str,
    student_answer: str,
    rubric: str,
    key_answer: str = "",
    allow_web_search: bool = True,
) -> tuple[dict, int, int]:
    sections = []

    if context_text and context_text.strip():
        sections.append(f"MATERI KULIAH (dari Vector DB):\n    {context_text}")

    if key_answer and key_answer.strip():
        sections.append(f"KUNCI JAWABAN:\n    {key_answer}")

    if not sections:
        sections.append("Tidak ada materi referensi atau kunci jawaban yang disediakan.")

    context_block = "\n\n    ".join(sections)

    rubric_text = (
        rubric.strip()
        if rubric and rubric.strip()
        else "Tidak ada rubrik khusus. Gunakan standar kebenaran logis, ilmu pengetahuan, dan akal sehat untuk menilai."
    )

    user_prompt = f"""
    Berdasarkan informasi berikut, evaluasi jawaban mahasiswa.

    {context_block}

    SOAL:
    {question}

    JAWABAN MAHASISWA:
    {student_answer}

    RUBRIK PENILAIAN:
    {rubric_text}

    Berikan nilai (score), alasan (reasoning) yang mengarah ke rubriknya, dan saran perbaikan (feedback) jika ada agar jawaban mahasiswa berikutnya bisa lebih baik. Baik alasan (reasoning) maupun saran perbaikan (feedback) dibatasi maksimal 2 kalimat. Jangan sertakan confidence level di reasoning. Jika score adalah 0, feedback dikosongkan. Jika rubrik kosong, berikan penilaian berdasarkan tingkat kebenaran jawaban.
    """

    logger.debug(
        "\n--- ASSESS CONTEXT ---\n"
        "VECTOR DB CONTEXT:\n%s\n\n"
        "KEY ANSWER:\n%s\n"
        "----------------------",
        context_text or "(none)",
        key_answer or "(none)",
    )

    create_kwargs = {
        "model": "gpt-5.4-mini",
        "input": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    if allow_web_search:
        create_kwargs["tools"] = [{"type": "web_search"}]

    response = await _openai_client.responses.create(**create_kwargs)

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    result_content = response.output_text.strip()

    if result_content.startswith("```json"):
        result_content = result_content[7:-3].strip()
    elif result_content.startswith("```"):
        result_content = result_content[3:-3].strip()

    try:
        result = json.loads(result_content)
        if "reasoning" not in result:
            result["reasoning"] = ""
        if "score" not in result:
            result["score"] = 0
        if "feedback" not in result:
            result["feedback"] = ""

        try:
            is_zero_score = float(result.get("score")) == 0
        except (ValueError, TypeError):
            is_zero_score = result.get("score") in (0, "0", 0.0)

        if is_zero_score:
            result["feedback"] = ""

        result["sources"] = await _validate_sources(result.get("sources", []))
        return result, input_tokens, output_tokens
    except json.JSONDecodeError:
        return (
            {
                "reasoning": f"Sistem AI tidak dapat menghasilkan format penilaian yang benar. Harap periksa kembali rubrik atau konteks. (Respons AI: {result_content[:150]}...)",
                "score": 0,
                "feedback": "",
                "sources": [],
            },
            input_tokens,
            output_tokens,
        )

import os
import uuid
import asyncio
import httpx
from typing import Optional
from urllib.parse import urlparse

from utils import extract_text, chunk_text, get_embeddings_batch
from utils.pricing import calculate_cost
from config import search_client

_UPLOAD_BATCH_SIZE = 1000
_EMBED_MODEL = "text-embedding-3-small"
_VISION_MODEL = "vision"


def _process_and_upload_sync(file_bytes: bytes, filename: str, course_code: str) -> tuple[int, int, int]:
    raw_text, vision_tokens = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("Text extraction failed or returned empty content")

    chunks = chunk_text(raw_text)
    vectors, embed_tokens = get_embeddings_batch(chunks)
    documents = [
        {
            "id": str(uuid.uuid4()),
            "content": chunk,
            "source_file": filename,
            "courseCode": course_code,
            "content_vector": vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    return len(chunks), embed_tokens, vision_tokens


async def process_file(file_bytes: bytes, filename: str, course_code: str) -> tuple[int, int, int]:
    return await asyncio.to_thread(_process_and_upload_sync, file_bytes, filename, course_code)


async def process_url(url: str, token: Optional[str] = None) -> dict:
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

            embed_cost = calculate_cost(_EMBED_MODEL, embed_tokens)
            vision_cost = calculate_cost(_VISION_MODEL, vision_tokens)

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
