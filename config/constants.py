import os

from dotenv import load_dotenv

load_dotenv()

LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.4-mini")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")
VISION_MODEL_KEY: str = "vision"

VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "3"))
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "400"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

FIELD_ID: str = os.getenv("VECTORDB_FIELD_ID", "id")
FIELD_CONTENT: str = os.getenv("VECTORDB_FIELD_CONTENT", "content")
FIELD_SOURCE: str = os.getenv("VECTORDB_FIELD_SOURCE", "source_file")
FIELD_COURSE_CODE: str = os.getenv("VECTORDB_FIELD_COURSE_CODE", "course_code")
FIELD_PAGE: str = os.getenv("VECTORDB_FIELD_PAGE", "page_number")
FIELD_VECTOR: str = os.getenv("VECTORDB_FIELD_VECTOR", "content_vector")
FIELD_RESOURCE_ID: str = os.getenv("VECTORDB_FIELD_RESOURCE_ID", "resource_id")
FIELD_REVISION: str = os.getenv("VECTORDB_FIELD_REVISION", "revision")

FIELD_ACADEMIC_PERIOD: str = os.getenv("VECTORDB_FIELD_ACADEMIC_PERIOD", "academic_period")
FIELD_ACADEMIC_CAREER: str = os.getenv("VECTORDB_FIELD_ACADEMIC_CAREER", "academic_career")
