from pydantic import BaseModel, Field

from .common import RubricItem


class StudentAnswer(BaseModel):
    student_id: str = Field(..., examples=["2501001234"], description="Unique identifier for the student")
    answer: str = Field(
        ...,
        examples=["Machine learning is a subset of artificial intelligence that allows systems to learn from data."],
        description="Student's answer text, or a URL pointing to a document (PDF, DOCX, etc.)",
    )
    token: str | None = Field(None, description="Bearer token for accessing a protected URL in the answer")


class BatchAssessRequest(BaseModel):
    question: str = Field(
        ...,
        examples=["Jelaskan apa yang dimaksud dengan machine learning!"],
        description="The exam/quiz question to be assessed",
    )
    rubric: list[RubricItem] = Field(
        default_factory=list,
        description="Scoring rubric as a list of proficiency bands with score ranges and criteria",
        examples=[
            [
                {"minScore": 0, "maxScore": 64, "proficiency": "Poor", "criteria": "Able to illustrate less than 4 kinds of data structures in Computer Science"},
                {"minScore": 65, "maxScore": 74, "proficiency": "Average", "criteria": "Able to illustrate 4 kinds of data structures in Computer Science"},
                {"minScore": 75, "maxScore": 84, "proficiency": "Good", "criteria": "Able to illustrate 5 kinds of data structures in Computer Science"},
                {"minScore": 85, "maxScore": 100, "proficiency": "Excellent", "criteria": "Able to illustrate at least 6 kinds of data structures in Computer Science"},
            ]
        ],
    )
    course_code: str = Field(
        "",
        examples=["COMP6100"],
        description="Course code used to filter course materials from the vector database",
    )
    use_key_answer: bool = Field(
        True,
        description="If `true`, use `key_answer` as the reference; if `false`, retrieve context from the vector database and enable web search",
    )
    key_answer: str = Field(
        "",
        examples=["Machine learning adalah subset dari AI yang memungkinkan sistem belajar dari data tanpa diprogram secara eksplisit."],
        description="Reference/model answer used for scoring when `use_key_answer=true`",
    )
    students: list[StudentAnswer] = Field(default_factory=list, description="List of students to evaluate in this batch")


class FeedUrlRequest(BaseModel):
    url: str = Field(..., examples=["https://example.com/lecture1.pdf"], description="Publicly accessible URL to a PDF, PPT, or PPTX file")
    course_code: str = Field(..., examples=["COMP6100"], description="Course code to associate the material with")
    token: str | None = Field(None, description="Bearer token for accessing a protected URL")
    resource_id: str | None = Field(
        None,
        examples=["a0cd0e23-e990-4b39-9d09-d529890c1749"],
        min_length=1,
        description=(
            "Stable LMS identifier of this material. When supplied, previously indexed chunks "
            "with the same resource_id are replaced instead of duplicated (idempotent re-feed)."
        ),
    )
    class_session_numbers: list[int] | None = Field(
        None,
        examples=[[19, 20, 21]],
        description=(
            "Session numbers this material belongs to; stored on each chunk for filtering. "
            "A single material can be reused across several sessions."
        ),
    )


class FeedUrlsRequest(BaseModel):
    urls: list[str] = Field(
        ...,
        examples=[["https://example.com/lecture1.pdf", "https://example.com/lecture2.pptx"]],
        description="List of URLs to PDF, PPT, or PPTX files to ingest concurrently",
    )
    course_code: str = Field(..., examples=["COMP6100"], description="Course code to associate all materials with")
    token: str | None = Field(None, description="Bearer token for accessing protected URLs")
