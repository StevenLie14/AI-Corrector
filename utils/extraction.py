import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from pptx import Presentation
from pypdf import PdfReader

from .image import get_image_description

_IMAGE_MIN_BYTES = 10240


def extract_text(file_bytes: bytes, filename: str) -> tuple[str, int]:
    try:
        return _parse_file(BytesIO(file_bytes), file_bytes, filename)
    except Exception as e:
        raise Exception(f"Error extracting text: {str(e)}")


def _parse_file(file_stream, file_bytes: bytes, filename: str) -> tuple[str, int]:
    filename_lower = filename.lower()
    images_to_process = []

    if filename_lower.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="ignore"), 0

    elif filename_lower.endswith(".docx"):
        import docx
        doc = docx.Document(BytesIO(file_bytes))
        return "\n".join(para.text for para in doc.paragraphs), 0

    elif filename_lower.endswith(".pdf"):
        full_text = ""
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
        full_text = ""
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
        return full_text, 0

    else:
        raise ValueError("Unsupported file type. Supported: PDF, PPT, PPTX, TXT, DOCX")

    if images_to_process:
        full_text, vision_tokens = _replace_image_placeholders(full_text, images_to_process)
        return full_text, vision_tokens

    return full_text, 0


def _replace_image_placeholders(full_text: str, images_to_process: list) -> tuple[str, int]:
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

    total_vision_tokens = 0

    if tasks:
        def describe(task_info):
            ph, img_bytes, ctx, src = task_info
            try:
                desc, tokens = get_image_description(img_bytes, context_text=ctx)
                return ph, f"\n[Deskripsi Gambar: {desc}]\n" if desc else "", tokens
            except Exception as e:
                print(f"Gagal mengekstrak gambar {ph} dari {src}: {e}")
                return ph, "", 0

        with ThreadPoolExecutor(max_workers=10) as executor:
            for ph, replacement, tokens in executor.map(describe, tasks):
                replacements[ph] = replacement
                total_vision_tokens += tokens

    for placeholder, replacement in replacements.items():
        full_text = full_text.replace(placeholder, replacement)

    return full_text, total_vision_tokens


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list:
    words = text.split()
    step = chunk_size - overlap
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), step)]
