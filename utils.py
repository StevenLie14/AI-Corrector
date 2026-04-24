from fastapi import UploadFile
from pypdf import PdfReader
from pptx import Presentation
from config import embed_client
from io import BytesIO

def extract_text(file_input, filename: str = None) -> str:
    """
    Extract text from PDF or PPTX files.
    
    Args:
        file_input: Either an UploadFile object or bytes
        filename: Required when file_input is bytes, ignored for UploadFile
    
    Returns:
        Extracted text as string
    """
    text = ""
    try:
        # Handle UploadFile object
        if isinstance(file_input, UploadFile):
            file_stream = file_input.file
            filename_to_check = file_input.filename
        # Handle bytes
        elif isinstance(file_input, bytes):
            if not filename:
                raise ValueError("Filename is required when passing bytes")
            file_stream = BytesIO(file_input)
            filename_to_check = filename
        else:
            raise ValueError("Input must be UploadFile or bytes")
        
        filename_lower = filename_to_check.lower()

        if filename_lower.endswith(".pdf"):
            reader = PdfReader(file_stream)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif filename_lower.endswith(".pptx"):
            prs = Presentation(file_stream)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
        else:
            raise ValueError("Only PDF and PPTX files are supported")
    except Exception as e:
        raise Exception(f"Error extracting text: {str(e)}")
    
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