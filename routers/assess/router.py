import asyncio
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from schemas import BatchAssessRequest
from utils import extract_text, select_relevant_chunks
from utils.pricing import calculate_cost

from .service import evaluate_answer, get_context

router = APIRouter(tags=["Assessment"])

_LLM_MODEL = "gpt-5.4-mini"
_EMBED_MODEL = "text-embedding-3-small"
_VISION_MODEL = "vision"


async def _resolve_key_answer(
    text: str, file: Optional[UploadFile], question: str
) -> tuple[str, int, int]:
    raw = ""
    vision_tokens = 0
    if file and file.filename:
        file_bytes = await file.read()
        raw, vision_tokens = await asyncio.to_thread(extract_text, file_bytes, file.filename)
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
    rubric: str = Form(""),
    courseCode: str = Form(""),
    use_key_answer: bool = Form(True),
    key_answer_text: str = Form(""),
    key_answer_file: Optional[UploadFile] = File(None),
):
    try:
        if use_key_answer:
            key_answer, key_answer_embed_tokens, vision_tokens = await _resolve_key_answer(key_answer_text, key_answer_file, question)
            context_text, retrieved_sources, context_tokens = "", [], 0
        else:
            key_answer, key_answer_embed_tokens, vision_tokens = "", 0, 0
            context_text, retrieved_sources, context_tokens = await get_context(question, courseCode)

        evaluation, input_tokens, output_tokens = await evaluate_answer(
            context_text, question, student_answer, rubric, key_answer,
            allow_web_search=not use_key_answer,
        )

        total_embed_tokens = context_tokens + key_answer_embed_tokens
        embed_cost = calculate_cost(_EMBED_MODEL, total_embed_tokens)
        vision_cost = calculate_cost(_VISION_MODEL, vision_tokens)
        completion_cost = calculate_cost(_LLM_MODEL, input_tokens, output_tokens)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": evaluation,
            "token_usage": {
                "embedding_tokens": total_embed_tokens,
                "embedding_cost_usd": embed_cost,
                "vision_tokens": vision_tokens,
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

        evaluations = await asyncio.gather(
            *[
                evaluate_answer(
                    context_text,
                    request.question,
                    student.answer,
                    request.rubric,
                    request.key_answer if request.use_key_answer else "",
                    allow_web_search=not request.use_key_answer,
                )
                for student in request.students
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
                results.append({"student_id": student_id, "status": "success", "evaluation": eval_dict})

        embed_cost = calculate_cost(_EMBED_MODEL, embed_tokens)
        completion_cost = calculate_cost(_LLM_MODEL, total_input_tokens, total_output_tokens)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "results": results,
            "token_usage": {
                "embedding_tokens": embed_tokens,
                "embedding_cost_usd": embed_cost,
                "vision_tokens": 0,
                "vision_cost_usd": 0,
                "completion_input_tokens": total_input_tokens,
                "completion_output_tokens": total_output_tokens,
                "completion_cost_usd": completion_cost,
                "total_cost_usd": round(embed_cost + completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
