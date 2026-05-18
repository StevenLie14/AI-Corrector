from typing import List, Optional

from pydantic import BaseModel


class StudentAnswer(BaseModel):
    student_id: str
    answer: str


class BatchAssessRequest(BaseModel):
    question: str
    student_answer: str = ""
    rubric: str = ""
    courseCode: str = ""
    use_key_answer: bool = True
    key_answer: str = ""
    students: List[StudentAnswer] = []
