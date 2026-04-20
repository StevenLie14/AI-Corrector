from pydantic import BaseModel

class AssessRequest(BaseModel):
    question: str
    student_answer: str
    rubric: str
