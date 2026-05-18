import asyncio

from fastapi import APIRouter, HTTPException

from schemas import AssessRequest, BatchAssessRequest
from utils.pricing import calculate_cost

from .service import evaluate_answer, get_context

router = APIRouter(tags=["Assessment"])

_LLM_MODEL = "gpt-5.4-mini"
_EMBED_MODEL = "text-embedding-3-small"


@router.post("/assess")
async def assess_answer(request: AssessRequest):
    try:
        context_text, retrieved_sources, embed_tokens = await get_context(
            request.question, request.courseCode
        )
        evaluation, input_tokens, output_tokens = await evaluate_answer(
            context_text,
            request.question,
            request.student_answer,
            request.rubric,
        )

        embed_cost = calculate_cost(_EMBED_MODEL, embed_tokens)
        completion_cost = calculate_cost(_LLM_MODEL, input_tokens, output_tokens)

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": evaluation,
            "token_usage": {
                "embedding_tokens": embed_tokens,
                "embedding_cost_usd": embed_cost,
                "completion_input_tokens": input_tokens,
                "completion_output_tokens": output_tokens,
                "completion_cost_usd": completion_cost,
                "total_cost_usd": round(embed_cost + completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assess-batch")
async def assess_batch(request: BatchAssessRequest):
    try:
        context_text, retrieved_sources, embed_tokens = await get_context(
            request.question, request.courseCode
        )

        evaluations = await asyncio.gather(
            *[
                evaluate_answer(context_text, request.question, student.answer, request.rubric)
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
                "completion_input_tokens": total_input_tokens,
                "completion_output_tokens": total_output_tokens,
                "completion_cost_usd": completion_cost,
                "total_cost_usd": round(embed_cost + completion_cost, 8),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
