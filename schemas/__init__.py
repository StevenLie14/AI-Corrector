from typing import List

from pydantic import BaseModel


class AssessRequest(BaseModel):
    question: str
    student_answer: str
    rubric: str
    courseCode: str


class StudentAnswer(BaseModel):
    student_id: str
    answer: str


class BatchAssessRequest(BaseModel):
    question: str
    rubric: str
    courseCode: str
    students: List[StudentAnswer]
