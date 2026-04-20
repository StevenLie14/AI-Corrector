from fastapi import UploadFile
from pypdf import PdfReader
from pptx import Presentation
from config import embed_client

def extract_text(file: UploadFile) -> str:
    text = ""
    try:
        if file.filename.endswith(".pdf"):
            reader = PdfReader(file.file)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif file.filename.endswith(".pptx"):
            prs = Presentation(file.file)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
        else:
            raise ValueError("baru ppt or pdf")
    except Exception as e:
        raise Exception(f"err: {str(e)}")
    
    return text

def chunk_text(text: str, chunk_size: int = 400) -> list:
    words = text.split()
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    return chunks

def get_embedding(text: str) -> list:
    response = embed_client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding