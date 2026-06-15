import asyncio
import json
import logging
import os
import re
from typing import List
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from config.constants import EMBED_MODEL, LLM_MODEL, VISION_MODEL_KEY
from schemas import (
    AssessResponse,
    BatchAssessRequest,
    BatchAssessResponse,
    MultiBatchAssessResponse,
    RubricItem,
)
from utils import extract_html_text, extract_text, select_relevant_chunks
from utils.pricing import calculate_cost

from .service import evaluate_answer, get_context, _detect_language

router = APIRouter(tags=["Assessment"])

_EVAL_SEMAPHORE = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_EVALS", "5")))
_MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024)))

URL_REGEX = r"https?://[^\s]+"
_GDOCS_RE = re.compile(r"https://docs\.google\.com/document/d/([^/?#]+)")

_ERROR_500 = {"description": "Internal server error — AI evaluation or vector search failed"}


def _format_rubric(items: list[RubricItem]) -> str:
    if not items:
        return ""
    return "\n".join(
        f"- Score {item.minScore}-{item.maxScore} ({item.proficiency}): {item.criteria}"
        for item in items
    )


def _parse_rubric_json(raw: str) -> list[RubricItem]:
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [RubricItem(**item) for item in data]
    except Exception:
        pass
    return []


def _has_url(text: str) -> bool:
    try:
        for word in text.split():
            result = urlparse(word)
            if all([result.scheme, result.netloc]):
                return True
        return False
    except Exception:
        return False


def _get_url(text: str) -> tuple[str, str | None]:
    match = re.search(URL_REGEX, text)
    if not match:
        return text, None

    url = match.group()
    cleaned_text = re.sub(URL_REGEX, f"[URL PLACEHOLDER {url}]", text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    return cleaned_text, url


def extract_filename_from_url(url: str, response: httpx.Response) -> str:
    cd = response.headers.get("Content-Disposition")
    if cd and "filename=" in cd:
        return cd.split("filename=")[-1].strip('"').strip("'")

    parsed = urlparse(url)
    query_file = parse_qs(parsed.query).get("file")
    if query_file:
        return query_file[0]

    path_file = os.path.basename(parsed.path)
    if path_file and "." in path_file:
        return path_file

    fmt = parse_qs(parsed.query).get("format")
    if fmt:
        return f"document.{fmt[0]}"

    return "downloaded_file"


def _normalize_url(url: str) -> str:
    """Convert Google Docs view/edit URLs to DOCX export URLs."""
    m = _GDOCS_RE.match(url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=docx"
    return url


async def _resolve_student_answer(answer_text: str, token: str | None = None) -> tuple[str, int, int]:
    if not answer_text or not _has_url(answer_text):
        return answer_text, 0, 0

    _, url = _get_url(answer_text)
    if not url:
        return answer_text, 0, 0

    fetch_url = _normalize_url(url)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        async with httpx.AsyncClient() as client:
            head = await client.head(fetch_url, headers=headers, timeout=10.0, follow_redirects=True)
            content_length = head.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_FILE_SIZE_BYTES:
                logging.warning(f"File at {fetch_url} exceeds size limit ({content_length} bytes), skipping")
                return answer_text, 0, 0

            logging.info(f"Downloading student answer from URL: {fetch_url}")
            response = await client.get(fetch_url, headers=headers, timeout=60.0, follow_redirects=True)

        if response.status_code != 200:
            return answer_text, 0, 0

        if len(response.content) > _MAX_FILE_SIZE_BYTES:
            logging.warning(f"Downloaded file from {fetch_url} exceeds size limit, skipping")
            return answer_text, 0, 0

        content_type = response.headers.get("content-type", "")
        vision_tokens = 0

        if "text/html" in content_type:
            raw = await asyncio.to_thread(extract_html_text, response.content)
        elif "text/plain" in content_type:
            raw = response.content.decode("utf-8", errors="ignore")
        else:
            filename = extract_filename_from_url(fetch_url, response)
            raw, vision_tokens = await asyncio.to_thread(extract_text, response.content, filename, True)

        if not raw:
            return answer_text, 0, 0

        # Strip URLs from extracted content to prevent the AI from following level-2 URLs
        raw = re.sub(URL_REGEX, "[URL dihapus]", raw)

        return f"{answer_text.replace(url, f'{chr(10)}{raw}{chr(10)}')}", 0, vision_tokens
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to process URL {url}: {str(e)}")
        return answer_text, 0, 0


async def _resolve_key_answer(
    text: str, file: UploadFile | None, question: str
) -> tuple[str, int, int]:
    raw = ""
    vision_tokens = 0
    if file and file.filename:
        file_bytes = await file.read()
        raw, vision_tokens = await asyncio.to_thread(extract_text, file_bytes, file.filename, True)
    elif text:
        raw = text

    if not raw:
        return "", 0, 0

    key_answer, embed_tokens = await asyncio.to_thread(select_relevant_chunks, raw, question)
    return key_answer, embed_tokens, vision_tokens


@router.post(
    "/assess",
    response_model=AssessResponse,
    summary="Evaluate a single student answer",
    description=(
        "Evaluate one student's answer against a question and rubric using Azure OpenAI.\n\n"
        "**Context source** is determined by `use_key_answer`:\n"
        "- `true` — use the provided `key_answer_text` or `key_answer_file` as the reference answer\n"
        "- `false` — perform a vector DB search using `course_code` and enable web search\n\n"
        "The `student_answer` field may contain a URL. If a document URL is detected, "
        "it is downloaded and its text is extracted automatically before evaluation.\n\n"
        "Pass `rubric` as a JSON string containing an array of proficiency band objects, e.g.:\n"
        "`[{\"minScore\":0,\"maxScore\":64,\"proficiency\":\"Poor\",\"criteria\":\"...\"}]`"
    ),
    responses={500: _ERROR_500},
)
async def assess_answer(
    question: str = Form(..., examples=["Jelaskan konsep machine learning!"], description="The exam question"),
    student_answer: str = Form(..., examples=["Machine learning adalah..."], description="Student's answer text, or a URL to a document"),
    student_answer_token: str | None = Form(None, description="Bearer token for downloading the student answer URL"),
    rubric: str = Form(
        "[]",
        description='Rubric as a JSON array of proficiency band objects: [{"minScore":int,"maxScore":int,"proficiency":str,"criteria":str}]',
    ),
    course_code: str = Form("", examples=["COMP6100"], description="Course code for vector DB filtering (used when `use_key_answer=false`)"),
    use_key_answer: bool = Form(True, description="If true, use the key answer; if false, retrieve context from vector DB"),
    key_answer_text: str = Form("", description="Reference answer text (used when `use_key_answer=true` and no file is provided)"),
    key_answer_file: UploadFile | None = File(None, description="Reference answer file — PDF, PPT, PPTX, DOCX, or TXT (used when `use_key_answer=true`)"),
):
    try:
        rubric_items = _parse_rubric_json(rubric)
        rubric_text = _format_rubric(rubric_items)

        language = _detect_language(student_answer)
        resolved_student_answer, student_answer_embed_tokens, student_answer_vision_tokens = await _resolve_student_answer(student_answer, student_answer_token)

        if use_key_answer:
            key_answer, key_answer_embed_tokens, key_answer_vision_tokens = await _resolve_key_answer(key_answer_text, key_answer_file, question)
            context_text, retrieved_sources, context_tokens = "", [], 0
        else:
            key_answer, key_answer_embed_tokens, key_answer_vision_tokens = "", 0, 0
            context_text, retrieved_sources, context_tokens = await get_context(question, course_code)

        evaluation, input_tokens, output_tokens = await evaluate_answer(
            context_text, question, resolved_student_answer, rubric_text, key_answer,
            allow_web_search=not use_key_answer,
            language=language,
        )

        total_embed_tokens = context_tokens + key_answer_embed_tokens + student_answer_embed_tokens
        embed_cost = calculate_cost(EMBED_MODEL, total_embed_tokens)
        total_vision_tokens = key_answer_vision_tokens + student_answer_vision_tokens
        vision_cost = calculate_cost(VISION_MODEL_KEY, total_vision_tokens)
        completion_cost = calculate_cost(LLM_MODEL, input_tokens, output_tokens)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": evaluation,
            "student_answer": resolved_student_answer,
            "token_usage": {
                "embedding_tokens": total_embed_tokens,
                "embedding_cost_usd": embed_cost,
                "vision_tokens": total_vision_tokens,
                "vision_cost_usd": vision_cost,
                "completion_input_tokens": input_tokens,
                "completion_output_tokens": output_tokens,
                "completion_cost_usd": completion_cost,
                "total_cost_usd": round(embed_cost + vision_cost + completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _process_batch_assess_item(request: BatchAssessRequest) -> dict:
    if request.use_key_answer:
        context_text, retrieved_sources, embed_tokens = "", [], 0
    else:
        context_text, retrieved_sources, embed_tokens = await get_context(
            request.question, request.course_code
        )

    rubric_text = _format_rubric(request.rubric)

    languages = [_detect_language(student.answer) for student in request.students]

    resolved_answers = await asyncio.gather(
        *[_resolve_student_answer(student.answer, student.token) for student in request.students]
    )

    async def _eval_with_sem(resolved_answer, lang):
        async with _EVAL_SEMAPHORE:
            return await evaluate_answer(
                context_text,
                request.question,
                resolved_answer[0],
                rubric_text,
                request.key_answer if request.use_key_answer else "",
                allow_web_search=not request.use_key_answer,
                language=lang,
            )

    evaluations = await asyncio.gather(
        *[_eval_with_sem(ans, lang) for ans, lang in zip(resolved_answers, languages)],
        return_exceptions=True,
    )

    results = []
    total_input_tokens = 0
    total_output_tokens = 0

    for i, result in enumerate(evaluations):
        student_id = request.students[i].student_id
        if isinstance(result, Exception):
            results.append({"student_id": student_id, "status": "error", "error": str(result)})
        else:
            eval_dict, in_tok, out_tok = result
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            results.append({"student_id": student_id, "status": "success", "evaluation": eval_dict, "student_answer": resolved_answers[i][0]})

    total_embed_tokens = embed_tokens + sum([ans[1] for ans in resolved_answers])
    embed_cost = calculate_cost(EMBED_MODEL, total_embed_tokens)
    total_vision_tokens = sum([ans[2] for ans in resolved_answers])
    vision_cost = calculate_cost(VISION_MODEL_KEY, total_vision_tokens)
    completion_cost = calculate_cost(LLM_MODEL, total_input_tokens, total_output_tokens)

    return {
        "question": request.question,
        "retrieved_sources": retrieved_sources,
        "results": results,
        "embedding_tokens": total_embed_tokens,
        "embedding_cost_usd": embed_cost,
        "vision_tokens": total_vision_tokens,
        "vision_cost_usd": vision_cost,
        "completion_input_tokens": total_input_tokens,
        "completion_output_tokens": total_output_tokens,
        "completion_cost_usd": completion_cost,
    }


@router.post(
    "/assess-batch",
    response_model=BatchAssessResponse,
    summary="Evaluate multiple students for one question",
    description=(
        "Evaluate a batch of students' answers for a **single question** in parallel.\n\n"
        "All students share the same question, rubric, course code, and context source. "
        "Individual student answers may still be URLs to documents.\n\n"
        "Failed individual evaluations are reported with `status: 'error'` inside `results` "
        "and do **not** cause the entire request to fail."
    ),
    responses={500: _ERROR_500},
)
async def assess_batch(request: BatchAssessRequest):
    try:
        res = await _process_batch_assess_item(request)
        return {
            "status": "success",
            "retrieved_sources": res["retrieved_sources"],
            "results": res["results"],
            "token_usage": {
                "embedding_tokens": res["embedding_tokens"],
                "embedding_cost_usd": res["embedding_cost_usd"],
                "vision_tokens": res["vision_tokens"],
                "vision_cost_usd": res["vision_cost_usd"],
                "completion_input_tokens": res["completion_input_tokens"],
                "completion_output_tokens": res["completion_output_tokens"],
                "completion_cost_usd": res["completion_cost_usd"],
                "total_cost_usd": round(res["embedding_cost_usd"] + res["vision_cost_usd"] + res["completion_cost_usd"], 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/assess-batch-multi",
    response_model=MultiBatchAssessResponse,
    summary="Evaluate multiple questions with multiple students each",
    description=(
        "Evaluate **multiple questions**, each with its own set of students, rubric, and context source, "
        "all processed concurrently.\n\n"
        "The request body is a list of `BatchAssessRequest` objects. "
        "The `token_usage` in the response is the aggregated total across all questions and all students."
    ),
    responses={500: _ERROR_500},
)
async def assess_batch_multi(request: List[BatchAssessRequest]):
    try:
        batch_results = await asyncio.gather(
            *[_process_batch_assess_item(item) for item in request]
        )

        total_embed_tokens = 0
        total_embed_cost = 0.0
        total_vision_tokens = 0
        total_vision_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        total_completion_cost = 0.0

        results = []
        for res in batch_results:
            total_embed_tokens += res["embedding_tokens"]
            total_embed_cost += res["embedding_cost_usd"]
            total_vision_tokens += res["vision_tokens"]
            total_vision_cost += res["vision_cost_usd"]
            total_input_tokens += res["completion_input_tokens"]
            total_output_tokens += res["completion_output_tokens"]
            total_completion_cost += res["completion_cost_usd"]

            results.append({
                "question": res["question"],
                "retrieved_sources": res["retrieved_sources"],
                "results": res["results"]
            })

        return {
            "status": "success",
            "results": results,
            "token_usage": {
                "embedding_tokens": total_embed_tokens,
                "embedding_cost_usd": total_embed_cost,
                "vision_tokens": total_vision_tokens,
                "vision_cost_usd": total_vision_cost,
                "completion_input_tokens": total_input_tokens,
                "completion_output_tokens": total_output_tokens,
                "completion_cost_usd": total_completion_cost,
                "total_cost_usd": round(total_embed_cost + total_vision_cost + total_completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
