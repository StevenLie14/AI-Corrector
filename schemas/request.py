from pydantic import BaseModel, Field, field_validator, model_validator

from .common import RubricItem


def _normalize_course_codes(value: str | list[str] | None) -> list[str]:
    """Terima satu string atau daftar string, kembalikan daftar bersih & unik.

    Satu materi bisa dipakai di beberapa course code (mis. kode induk `ISYS6362`
    dan kode kelas `ISYS6362036`), jadi field ini menerima keduanya. Bentuk string
    tunggal tetap didukung supaya pemanggil lama tidak perlu berubah.
    """
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    seen: list[str] = []
    for item in items:
        code = (item or "").strip().upper()
        if code and code not in seen:
            seen.append(code)
    return seen


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
    assignment_instruction: str | None = Field(
        None,
        examples=["Explain why gambling is bad"],
        description="Assessment-level task instruction. Sent for the `criteria` format, where `question` holds a grading criterion instead of a question.",
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


class MetadataUpdateRequest(BaseModel):
    """Perbarui HANYA keterangan materi di index, tanpa memproses ulang isinya.

    Dipakai saat daftar kode mata kuliah berubah tapi filenya sama — mis. kelas
    baru dibuka memakai materi lama. Chunk dan vektornya tidak disentuh, jadi tidak ada biaya
    embedding maupun vision.
    """

    course_code: str | list[str] | None = Field(None, description="Course code(s) baru.")
    revision: float | None = Field(None, description="Nomor revisi materi terbaru.")
    academic_period: str | list[str] | None = Field(
        None,
        examples=[["2512", "2521"]],
        description=(
            "Periode akademik materi ini. Daftar, karena satu materi bisa ditawarkan di lebih "
            "dari satu periode. Kosongkan (jangan kirim) kalau tidak ingin mengubahnya."
        ),
    )
    academic_career: str | list[str] | None = Field(
        None,
        examples=[["OS1"]],
        description="Academic career materi ini. Daftar, mengikuti bentuk academic_period.",
    )

    @field_validator("course_code", "academic_period", "academic_career")
    @classmethod
    def _codes(cls, value: str | list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_course_codes(value)

    @model_validator(mode="after")
    def _require_something(self):
        """Tolak body tanpa course_code.

        Kalau dibiarkan kosong, `{}` akan lolos dan meng-merge daftar KOSONG ke semua chunk —
        materi kehilangan seluruh keterangannya dan tidak pernah ketemu lagi saat dicari, tanpa
        error apa pun. course_code adalah satu-satunya field yang difilter saat pencarian.
        """
        if not self.course_code:
            raise ValueError("course_code wajib diisi")
        return self


class FeedUrlRequest(BaseModel):
    url: str = Field(..., examples=["https://example.com/lecture1.pdf"], description="Publicly accessible URL to a PDF, PPT, or PPTX file")
    course_code: str | list[str] | None = Field(
        None,
        examples=[["ISYS6362", "ISYS6362036"]],
        description=(
            "Course code(s) to associate the material with. Accepts a single string or a list. "
            "This is the only field the retrieval side filters on."
        ),
    )
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
    revision: float | None = Field(
        None,
        examples=[3],
        description=(
            "Revision number of this material. Only the latest revision is ever present in the "
            "index: re-feeding a resource_id deletes its previous chunks first."
        ),
    )
    academic_period: str | list[str] | None = Field(
        None,
        examples=[["2512", "2521"]],
        description=(
            "Academic period(s) this material belongs to. A list, because the same material can "
            "be offered in more than one period. Stored for traceability only - the retrieval "
            "side does not filter on it."
        ),
    )
    academic_career: str | list[str] | None = Field(
        None,
        examples=[["OS1"]],
        description="Academic career(s) this material belongs to. Stored for traceability only.",
    )
    callback_url: str | None = Field(
        None,
        description=(
            "When supplied, the request returns **202 Accepted** immediately and the material is "
            "processed in the background. The result is POSTed to this URL when finished. Use this "
            "for large materials whose processing exceeds the caller's HTTP timeout."
        ),
    )
    callback_token: str | None = Field(
        None,
        description="Opaque token echoed back in the callback so the caller can verify it.",
    )

    @field_validator("course_code", "academic_period", "academic_career")
    @classmethod
    def _codes(cls, value: str | list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_course_codes(value)


class FeedUrlsRequest(BaseModel):
    urls: list[str] = Field(
        ...,
        examples=[["https://example.com/lecture1.pdf", "https://example.com/lecture2.pptx"]],
        description="List of URLs to PDF, PPT, or PPTX files to ingest concurrently",
    )
    course_code: str | list[str] = Field(
        ..., examples=["COMP6100"], description="Course code(s) to associate all materials with"
    )
    token: str | None = Field(None, description="Bearer token for accessing protected URLs")

    @field_validator("course_code")
    @classmethod
    def _course_codes(cls, value: str | list[str]) -> list[str]:
        return _normalize_course_codes(value)
