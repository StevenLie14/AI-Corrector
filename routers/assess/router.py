import asyncio

from fastapi import APIRouter, HTTPException

from schemas import AssessRequest, BatchAssessRequest

from .service import evaluate_answer, get_context

router = APIRouter(tags=["Assessment"])


@router.post("/assess")
async def assess_answer(request: AssessRequest):
    try:
        context_text, retrieved_sources = await get_context(request.question, request.courseCode)
        evaluation = await evaluate_answer(
            context_text,
            request.question,
            request.student_answer,
            request.rubric,
        )
        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "evaluation": evaluation,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assess-batch")
async def assess_batch(request: BatchAssessRequest):
    try:
        context_text, retrieved_sources = await get_context(request.question, request.courseCode)

        evaluations = await asyncio.gather(
            *[
                evaluate_answer(context_text, request.question, student.answer, request.rubric)
                for student in request.students
            ],
            return_exceptions=True,
        )

        results = [
            {
                "student_id": request.students[i].student_id,
                "status": "error",
                "error": str(result),
            }
            if isinstance(result, Exception)
            else {
                "student_id": request.students[i].student_id,
                "status": "success",
                "evaluation": result,
            }
            for i, result in enumerate(evaluations)
        ]

        return {
            "status": "success",
            "retrieved_sources": retrieved_sources,
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
