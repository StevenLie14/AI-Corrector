import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi import UploadFile
from pptx import Presentation
from pypdf import PdfReader

from .image import get_image_description

_IMAGE_MIN_BYTES = 10240


def extract_text(file_input, filename: str = None) -> str:
    if isinstance(file_input, UploadFile):
        file_stream = file_input.file
        filename_to_check = file_input.filename
    elif isinstance(file_input, bytes):
        if not filename:
            raise ValueError("Filename is required when passing bytes")
        file_stream = BytesIO(file_input)
        filename_to_check = filename
    else:
        raise ValueError("Input must be UploadFile or bytes")

    try:
        return _parse_file(file_stream, file_input, filename_to_check)
    except Exception as e:
        raise Exception(f"Error extracting text: {str(e)}")


def _parse_file(file_stream, file_input, filename: str) -> str:
    filename_lower = filename.lower()
    full_text = ""
    images_to_process = []

    if filename_lower.endswith(".pdf"):
        reader = PdfReader(file_stream)
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
            if hasattr(page, "images"):
                for image_file_object in page.images:
                    if len(image_file_object.data) < _IMAGE_MIN_BYTES:
                        continue
                    placeholder = f"[IMAGE_PLACEHOLDER_{len(images_to_process)}]"
                    full_text += placeholder + "\n"
                    images_to_process.append((image_file_object.data, "PDF"))

    elif filename_lower.endswith(".pptx"):
        prs = Presentation(file_stream)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    full_text += shape.text + "\n"
                if hasattr(shape, "image"):
                    if len(shape.image.blob) < _IMAGE_MIN_BYTES:
                        continue
                    placeholder = f"[IMAGE_PLACEHOLDER_{len(images_to_process)}]"
                    full_text += placeholder + "\n"
                    images_to_process.append((shape.image.blob, "PPTX"))

    elif filename_lower.endswith(".ppt"):
        import tempfile
        import ppt2txt

        if isinstance(file_input, bytes):
            file_bytes = file_input
        else:
            file_stream.seek(0)
            file_bytes = file_stream.read()
            file_stream.seek(0)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ppt") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            parsed = ppt2txt.process(tmp_path)
            content_dict = parsed.get("content", {})
            sorted_keys = sorted(content_dict.keys(), key=lambda k: int(k) if k.isdigit() else k)
            full_text = "\n".join(content_dict[k] for k in sorted_keys) + "\n"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    else:
        raise ValueError("Only PDF, PPT, and PPTX files are supported")

    if images_to_process:
        full_text = _replace_image_placeholders(full_text, images_to_process)

    return full_text


def _replace_image_placeholders(full_text: str, images_to_process: list) -> str:
    replacements = {}
    tasks = []

    for i, (img_bytes, source) in enumerate(images_to_process):
        placeholder = f"[IMAGE_PLACEHOLDER_{i}]"
        idx = full_text.find(placeholder)

        if idx == -1:
            replacements[placeholder] = ""
            continue

        start = max(0, idx - 2000)
        end = min(len(full_text), idx + len(placeholder) + 2000)
        context = full_text[start:end].replace(placeholder, "\n[GAMBAR INI]\n")
        tasks.append((placeholder, img_bytes, context, source))

    if tasks:
        def describe(task_info):
            ph, img_bytes, ctx, src = task_info
            try:
                desc = get_image_description(img_bytes, context_text=ctx)
                return ph, f"\n[Deskripsi Gambar: {desc}]\n" if desc else ""
            except Exception as e:
                print(f"Gagal mengekstrak gambar {ph} dari {src}: {e}")
                return ph, ""

        with ThreadPoolExecutor(max_workers=10) as executor:
            for ph, replacement in executor.map(describe, tasks):
                replacements[ph] = replacement

    for placeholder, replacement in replacements.items():
        full_text = full_text.replace(placeholder, replacement)

    return full_text


def chunk_text(text: str, chunk_size: int = 400) -> list:
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
