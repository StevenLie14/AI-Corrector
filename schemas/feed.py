from pydantic import BaseModel, Field

from .common import FeedTokenUsage


class FeedResponse(BaseModel):
    status: str = Field(..., examples=["success"])
    message: str = Field(..., examples=["'lecture1.pdf' inserted"])
    total_chunks_saved: int = Field(..., description="Number of text chunks indexed in the vector database")
    token_usage: FeedTokenUsage


class FeedDeleteResponse(BaseModel):
    status: str = Field(..., examples=["success"])
    resource_id: str = Field(..., examples=["a0cd0e23-e990-4b39-9d09-d529890c1749"])
    total_chunks_deleted: int = Field(..., description="Number of chunks removed from the vector database")


class FeedUrlsItemResult(BaseModel):
    status: str = Field(..., examples=["success"])
    filename: str | None = Field(None, description="Filename of the downloaded document")
    total_chunks_saved: int | None = None
    token_usage: FeedTokenUsage | None = None
    error: str | None = Field(None, description="Error message when status is 'failed'")


class FeedUrlsResponse(BaseModel):
    status: str = Field(..., examples=["completed"])
    results: list[FeedUrlsItemResult]
    token_usage: FeedTokenUsage
