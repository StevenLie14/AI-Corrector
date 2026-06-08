import asyncio
import logging
import os
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from schemas import BatchAssessRequest
from utils import extract_text, select_relevant_chunks
from utils.pricing import calculate_cost

from .service import evaluate_answer, get_context

router = APIRouter(tags=["Assessment"])

_LLM_MODEL = "gpt-5.4-mini"
_EMBED_MODEL = "text-embedding-3-small"
_VISION_MODEL = "vision"

URL_REGEX = r"https?://[^\s]+"

def _has_url(text: str) -> bool:
    try:
        for word in text.split():
            result = urlparse(word)
            if all([result.scheme, result.netloc]):
                return True
        return False
    except Exception:
        return False
    
def _get_url(text: str) -> tuple[str, Optional[str]]:
    match = re.search(URL_REGEX, text)
    if not match:
        return text, None

    url = match.group()
    cleaned_text = re.sub(URL_REGEX, f"[URL PLACEHOLDER {url}]", text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    return cleaned_text, url

def extract_filename_from_url(url: str , response: httpx.Response) -> str:
    cd = response.headers.get("Content-Disposition")
    if cd and "filename=" in cd:
        return cd.split("filename=")[-1].strip('"')

    parsed = urlparse(url)
    query_file = parse_qs(parsed.query).get("file")
    if query_file:
        return query_file[0]

    path_file = os.path.basename(parsed.path)
    if path_file and "." in path_file:
        return path_file

    return "downloaded_file"

async def _resolve_student_answer(answer_text: str, token: Optional[str] = None) -> tuple[str, int, int]:
    """
    Resolve student answer. If it's a URL pointing to a PDF, download and extract text.
    Otherwise, return the answer as-is.
    """
    if not answer_text or not _has_url(answer_text):
        return answer_text, 0, 0
    
    _, url = _get_url(answer_text)

    if not url:
        return answer_text, 0, 0
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        logging.info(f"Attempting to download student answer from URL: {url} with headers: {headers}")

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=60.0)
        
        logging.info(f"Download response status: {response.status_code} for URL: {url} with headers: {headers}")

        if response.status_code != 200:
            return answer_text, 0, 0

        filename = extract_filename_from_url(url, response)

        logging.info(f"Processing student answer from URL: {url} with headers: {headers} (filename: {filename})")

        raw = ""
        vision_tokens = 0
        raw, vision_tokens = await asyncio.to_thread(extract_text, response.content, filename, True)

        logging.info(f"Extracted text length: {len(raw)} characters, vision tokens: {vision_tokens}")

        if not raw:
            return answer_text, 0, 0
        
        raw = f"\n{raw}\n"

        return f"{answer_text.replace(url, raw)}", 0, vision_tokens
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to process URL {url} with headers: {headers}: {str(e)}")
        return answer_text, 0, 0


async def _resolve_key_answer(  
    text: str, file: Optional[UploadFile], question: str
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


@router.post("/assess")
async def assess_answer(
    question: str = Form(...),
    student_answer: str = Form(...),
    student_answer_token: Optional[str] = Form(None),
    rubric: str = Form(""),
    courseCode: str = Form(""),
    use_key_answer: bool = Form(True),
    key_answer_text: str = Form(""),
    key_answer_file: Optional[UploadFile] = File(None),
):
    try:
        resolved_student_answer, student_answer_embed_tokens, student_answer_vision_tokens = await _resolve_student_answer(student_answer, student_answer_token)
        
        if use_key_answer:
            key_answer, key_answer_embed_tokens, key_answer_vision_tokens = await _resolve_key_answer(key_answer_text, key_answer_file, question)
            context_text, retrieved_sources, context_tokens = "", [], 0
        else:
            key_answer, key_answer_embed_tokens, key_answer_vision_tokens = "", 0, 0
            context_text, retrieved_sources, context_tokens = await get_context(question, courseCode)

        evaluation, input_tokens, output_tokens = await evaluate_answer(
            context_text, question, resolved_student_answer, rubric, key_answer,
            allow_web_search=not use_key_answer,
        )

        total_embed_tokens = context_tokens + key_answer_embed_tokens + student_answer_embed_tokens
        embed_cost = calculate_cost(_EMBED_MODEL, total_embed_tokens)
        total_vision_tokens = key_answer_vision_tokens + student_answer_vision_tokens
        vision_cost = calculate_cost(_VISION_MODEL, total_vision_tokens)
        completion_cost = calculate_cost(_LLM_MODEL, input_tokens, output_tokens)

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


@router.post("/assess-batch")
async def assess_batch(request: BatchAssessRequest):
    try:
        if request.use_key_answer:
            context_text, retrieved_sources, embed_tokens = "", [], 0
        else:
            context_text, retrieved_sources, embed_tokens = await get_context(
                request.question, request.courseCode
            )

        resolved_answers = await asyncio.gather(
            *[_resolve_student_answer(student.answer, student.token) for student in request.students]
        )

        evaluations = await asyncio.gather(
            *[
                evaluate_answer(
                    context_text,
                    request.question,
                    resolved_answer[0],
                    request.rubric,
                    request.key_answer if request.use_key_answer else "",
                    allow_web_search=not request.use_key_answer,
                )
                for resolved_answer in resolved_answers
            ],
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
                results.append({"student_id": student_id, "status": "success", "evaluation": eval_dict, "student_answer": resolved_answers[i]})

        total_embed_tokens = embed_tokens + sum([ans[1] for ans in resolved_answers])
        embed_cost = calculate_cost(_EMBED_MODEL, total_embed_tokens)
        total_vision_tokens = sum([ans[2] for ans in resolved_answers]) 
        vision_cost = calculate_cost(_VISION_MODEL, total_vision_tokens)
        completion_cost = calculate_cost(_LLM_MODEL, total_input_tokens, total_output_tokens)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "results": results,
            "token_usage": {
                "embedding_tokens": total_embed_tokens,
                "embedding_cost_usd": embed_cost,
                "vision_tokens": total_vision_tokens,
                "vision_cost_usd": vision_cost,
                "completion_input_tokens": total_input_tokens,
                "completion_output_tokens": total_output_tokens,
                "completion_cost_usd": completion_cost,
                "total_cost_usd": round(embed_cost + vision_cost + completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
