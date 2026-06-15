from pydantic import BaseModel, Field

from .common import AssessTokenUsage, EvaluationResult, RetrievedSource


class AssessResponse(BaseModel):
    status: str = Field(..., examples=["success"])
    retrieved_sources: list[RetrievedSource] = Field(
        ...,
        description="Source files retrieved from vector DB (empty list when using key answer)",
    )
    evaluation: EvaluationResult
    student_answer: str = Field(..., description="Resolved student answer (URL content is extracted and substituted)")
    token_usage: AssessTokenUsage


class StudentResult(BaseModel):
    student_id: str
    status: str = Field(..., examples=["success"])
    evaluation: EvaluationResult | None = None
    student_answer: str | None = None
    error: str | None = Field(None, description="Error message when status is 'error'")


class BatchAssessResponse(BaseModel):
    status: str = Field(..., examples=["success"])
    retrieved_sources: list[RetrievedSource]
    results: list[StudentResult]
    token_usage: AssessTokenUsage


class MultiBatchResultItem(BaseModel):
    question: str
    retrieved_sources: list[RetrievedSource]
    results: list[StudentResult]


class MultiBatchAssessResponse(BaseModel):
    status: str = Field(..., examples=["success"])
    results: list[MultiBatchResultItem]
    token_usage: AssessTokenUsage
