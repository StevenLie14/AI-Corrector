import asyncio
import json
import logging
import os
from urllib.parse import urlparse

import httpx
from azure.search.documents.models import VectorizedQuery
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import search_client
from config.constants import FIELD_CONTENT, FIELD_COURSE_CODE, FIELD_PAGE, FIELD_SOURCE, FIELD_VECTOR, LLM_MODEL, VECTOR_TOP_K
from utils import get_embedding

logger = logging.getLogger(__name__)

_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

def _detect_language(text: str) -> str:
    from langdetect import detect, LangDetectException
    if not text or len(text.split()) < 4:
        return "id"
    try:
        return detect(text)
    except LangDetectException:
        return "id"

_SYSTEM_PROMPT_ID = """
Kamu adalah asisten dosen yang ahli dan objektif. Tugasmu adalah menilai jawaban mahasiswa.

- Jika context dari vector db tidak relevan, gunakan web search.
- Jika menggunakan web search, kamu WAJIB menyertakan sumber dari internet.
- Setiap klaim penting HARUS memiliki sumber yang valid (URL).
- Jangan membuat sumber jika tidak yakin.
- Jika link yang diberikan mahasiswa tidak bisa diakses, jangan masukkan sources, infokan bahwa kamu tidak dapat mengaksesnya, jangan halusinasi konten URLnya.

Berikan jawaban dalam format JSON berikut:

{
    "reasoning": "<alasan logis, evaluasi secara mendalam berdasarkan jawaban mahasiswa dan rubrik. Maksimal 2 kalimat. JANGAN memasukkan confidence level atau tingkat keyakinan. WAJIB ditulis dalam BAHASA INDONESIA.>",
    "score": <angka yang sesuai dengan reasoning dan rubrik>,
    "confidence": <tingkat confidence kamu dalam bentuk angka dari 0 hingga 100, dengan 0 melambangkan tidak percaya sama sekali dan 100 menggambarkan sangat percaya>,
    "feedback": "<saran/masukan konstruktif agar jawaban mahasiswa bisa lebih baik dan lengkap di kemudian hari. Maksimal 2 kalimat, namun harus cukup lengkap. Jika score adalah 0, bagian ini wajib dikosongkan (diisi string kosong \"\"). WAJIB ditulis dalam BAHASA INDONESIA.>",
    "sources": [
        {
            "title": "<judul sumber>",
            "url": "<link sumber>",
            "content": "20 kata pertama yang didapatkan dari url tersebut"
        }
    ]
}

Catatan PENTING:
- Jika tidak menggunakan web search, "sources" boleh kosong []
- JANGAN menambahkan teks di luar JSON. Hasil akhir HANYA boleh JSON yang valid.
- Jika materi atau rubrik kosong, TETAP berikan penilaian berdasarkan standar kebenaran logis dan akal sehat, lalu tulis alasannya di "reasoning".
- Baik "reasoning" maupun "feedback" dibatasi MAKSIMAL 2 KALIMAT.
- Jika score yang diberikan adalah 0, maka "feedback" WAJIB dikosongkan (diisi "").
- "reasoning" dan "feedback" HARUS selalu ditulis dalam BAHASA INDONESIA, tidak peduli bahasa apapun yang digunakan dalam konteks atau materi.
"""

_SYSTEM_PROMPT_EN = """
You are an expert and objective lecturer assistant. Your task is to evaluate a student's answer.

- If the vector DB context is not relevant, use web search.
- If you use web search, you MUST include internet sources.
- Every important claim MUST have a valid source (URL).
- Do not fabricate sources if uncertain.
- If a link provided by the student is inaccessible, do not include it in sources — inform that you could not access it, do not hallucinate its content.

Respond in the following JSON format:

{
    "reasoning": "<logical reasoning, evaluate thoroughly based on the student's answer and rubric. Maximum 2 sentences. DO NOT include confidence level or degree of certainty. MUST be written in ENGLISH.>",
    "score": <number matching the reasoning and rubric>,
    "confidence": <your confidence level as a number from 0 to 100, where 0 means not confident at all and 100 means fully confident>,
    "feedback": "<constructive suggestions for the student to improve future answers. Maximum 2 sentences but must be sufficiently complete. If score is 0, this field must be empty (empty string \"\"). MUST be written in ENGLISH.>",
    "sources": [
        {
            "title": "<source title>",
            "url": "<source link>",
            "content": "first 20 words retrieved from that URL"
        }
    ]
}

IMPORTANT notes:
- If web search is not used, "sources" may be empty []
- DO NOT add any text outside the JSON. The final output MUST be valid JSON only.
- If material or rubric is empty, STILL provide an evaluation based on logical correctness and common sense, and state the reasoning in "reasoning".
- Both "reasoning" and "feedback" are limited to a MAXIMUM of 2 SENTENCES.
- If the score given is 0, "feedback" MUST be empty (set to "").
- "reasoning" and "feedback" MUST always be written in ENGLISH, regardless of the language used in the context or materials.
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
    try:
        vector, embed_tokens = await asyncio.to_thread(get_embedding, question)
    except Exception as e:
        raise ValueError(f"Embedding failed: {e}") from e

    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=VECTOR_TOP_K,
        fields="content_vector",
    )

    safe_course_code = course_code.strip().upper().replace("'", "''") if course_code else ""
    try:
        search_results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            filter=f"{FIELD_COURSE_CODE} eq '{safe_course_code}'" if safe_course_code else None,
            select=[FIELD_CONTENT, FIELD_SOURCE, FIELD_PAGE],
        )
    except Exception as e:
        raise ValueError(f"Vector search failed: {e}") from e

    retrieved_contexts = []
    retrieved_sources = []

    for result in search_results:
        source = result[FIELD_SOURCE]
        content = result[FIELD_CONTENT]
        page = result.get(FIELD_PAGE)
        page_label = f", Slide/Halaman {page}" if page is not None else ""
        retrieved_contexts.append(f"[Dari File: {source}{page_label}]\n{content}")
        retrieved_sources.append({"source": source, "page": page, "content": content})

    context_text = "\n\n".join(retrieved_contexts)
    return context_text, retrieved_sources, embed_tokens


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
async def evaluate_answer(
    context_text: str,
    question: str,
    student_answer: str,
    rubric: str,
    key_answer: str = "",
    allow_web_search: bool = True,
    language: str | None = None,
) -> tuple[dict, int, int]:
    detected_lang = language or _detect_language(student_answer)
    is_english = detected_lang == "en"

    if is_english:
        system_prompt = _SYSTEM_PROMPT_EN
        context_label = "COURSE MATERIAL (from Vector DB)"
        key_answer_label = "KEY ANSWER"
        no_context_msg = "No reference material or key answer provided."
        no_rubric_msg = "No specific rubric. Evaluate based on logical correctness, academic knowledge, and common sense."
        user_prompt_intro = "Based on the following information, evaluate the student's answer."
        question_label = "QUESTION"
        answer_label = "STUDENT ANSWER"
        rubric_label = "GRADING RUBRIC"
        instruction = (
            "Provide a score, reasoning aligned with the rubric, and feedback (if any) to help the student improve. "
            "Both reasoning and feedback are limited to 2 sentences. Do not include confidence level in reasoning. "
            "If score is 0, leave feedback empty. If rubric is empty, evaluate based on correctness of the answer."
        )
    else:
        system_prompt = _SYSTEM_PROMPT_ID
        context_label = "MATERI KULIAH (dari Vector DB)"
        key_answer_label = "KUNCI JAWABAN"
        no_context_msg = "Tidak ada materi referensi atau kunci jawaban yang disediakan."
        no_rubric_msg = "Tidak ada rubrik khusus. Gunakan standar kebenaran logis, ilmu pengetahuan, dan akal sehat untuk menilai."
        user_prompt_intro = "Berdasarkan informasi berikut, evaluasi jawaban mahasiswa."
        question_label = "SOAL"
        answer_label = "JAWABAN MAHASISWA"
        rubric_label = "RUBRIK PENILAIAN"
        instruction = (
            "Berikan nilai (score), alasan (reasoning) yang mengarah ke rubriknya, dan saran perbaikan (feedback) jika ada "
            "agar jawaban mahasiswa berikutnya bisa lebih baik. Baik alasan (reasoning) maupun saran perbaikan (feedback) "
            "dibatasi maksimal 2 kalimat. Jangan sertakan confidence level di reasoning. Jika score adalah 0, feedback "
            "dikosongkan. Jika rubrik kosong, berikan penilaian berdasarkan tingkat kebenaran jawaban."
        )

    sections = []
    if context_text and context_text.strip():
        sections.append(f"{context_label}:\n    {context_text}")
    if key_answer and key_answer.strip():
        sections.append(f"{key_answer_label}:\n    {key_answer}")
    if not sections:
        sections.append(no_context_msg)
    context_block = "\n\n    ".join(sections)

    rubric_text = rubric.strip() if rubric and rubric.strip() else no_rubric_msg

    user_prompt = f"""
    {user_prompt_intro}

    {context_block}

    {question_label}:
    {question}

    {answer_label}:
    {student_answer}

    {rubric_label}:
    {rubric_text}

    {instruction}
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
        "model": LLM_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if allow_web_search:
        create_kwargs["tools"] = [{"type": "web_search"}]

    try:
        response = await _openai_client.responses.create(**create_kwargs)
    except APITimeoutError as e:
        raise APITimeoutError("AI evaluation timed out") from e
    except APIConnectionError as e:
        raise APIConnectionError("Cannot reach AI service") from e
    except APIStatusError as e:
        if e.status_code == 401:
            raise ValueError("Invalid AI API key") from e
        if e.status_code == 429:
            raise RateLimitError("AI rate limit exceeded — retry later") from e
        raise ValueError(f"AI service error {e.status_code}") from e

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
