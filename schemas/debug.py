from pydantic import BaseModel, Field


class DebugExtractResponse(BaseModel):
    filename: str
    vision_tokens_used: int
    total_words: int
    total_chunks: int
    raw_text: str
    chunks: list[str]


class DebugImageItem(BaseModel):
    source: str = Field(..., description="Location of the image (e.g. 'PDF page 1', 'PPTX slide 3')")
    size_bytes: int
    skipped: bool = Field(..., description="True if the image was too small (<10 KB) and was not processed")
    data: str | None = Field(None, description="Base64-encoded image data (null if skipped)")


class DebugImagesResponse(BaseModel):
    filename: str
    total_images_found: int
    total_processed: int
    total_skipped: int
    images: list[DebugImageItem]
