import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import fitz

from pptx import Presentation

from .image import get_image_description

def extract_text(file_bytes: bytes, filename: str, is_student_answer: bool = False) -> tuple[str, int]:
    try:
        return _parse_file(BytesIO(file_bytes), file_bytes, filename, is_student_answer)
    except Exception as e:
        raise Exception(f"Error extracting text: {str(e)}")


def _parse_file(file_stream, file_bytes: bytes, filename: str, is_student_answer: bool = False) -> tuple[str, int]:
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
        seen_xrefs = set()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Collect text blocks and image blocks with their vertical positions
            blocks = []
            for block in page.get_text("blocks"):
                # block: (x0, y0, x1, y1, text, block_no, block_type)
                if block[6] == 0:  # text block
                    blocks.append(("text", block[1], block[4]))

            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                y0 = rects[0].y0
                clip = rects[0]
                mat = fitz.Matrix(2, 2)  # 2x scale for better quality
                pm = page.get_pixmap(matrix=mat, clip=clip)
                img_bytes = pm.tobytes("png")
                placeholder = f"[IMAGE_PLACEHOLDER_{len(images_to_process)}]"
                blocks.append(("image", y0, placeholder, img_bytes))
                images_to_process.append((img_bytes, "PDF"))

            # Sort all blocks by vertical position and build page text
            blocks.sort(key=lambda b: b[1])
            for block in blocks:
                if block[0] == "text":
                    full_text += block[2].strip() + "\n"
                else:
                    full_text += block[2] + "\n"  # placeholder

            full_text += "\n"

    elif filename_lower.endswith(".pptx"):
        full_text = ""
        prs = Presentation(file_stream)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    full_text += shape.text + "\n"
                if hasattr(shape, "image"):
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
        full_text, vision_tokens = _replace_image_placeholders(full_text, images_to_process, is_student_answer)
        return full_text, vision_tokens

    return full_text, 0


def _replace_image_placeholders(full_text: str, images_to_process: list, is_student_answer: bool = False) -> tuple[str, int]:
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
                desc, tokens = get_image_description(img_bytes, context_text=ctx, is_student_answer=is_student_answer)
                if not desc or (desc.strip().upper() == "SKIP" and not is_student_answer):
                    return ph, "", tokens
                return ph, f"\n[Deskripsi Gambar: {desc}]\n", tokens
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


def extract_pages(file_bytes: bytes, filename: str) -> list[tuple[int, str, int]]:
    """Returns list of (page_num, text, vision_tokens) per page/slide."""
    try:
        return _parse_file_by_pages(BytesIO(file_bytes), file_bytes, filename)
    except Exception as e:
        raise Exception(f"Error extracting pages: {str(e)}")


def _parse_file_by_pages(file_stream, file_bytes: bytes, filename: str) -> list[tuple[int, str, int]]:
    filename_lower = filename.lower()

    if filename_lower.endswith(".txt"):
        return [(1, file_bytes.decode("utf-8", errors="ignore"), 0)]

    elif filename_lower.endswith(".docx"):
        import docx
        doc = docx.Document(BytesIO(file_bytes))
        return [(1, "\n".join(para.text for para in doc.paragraphs), 0)]

    elif filename_lower.endswith(".pptx"):
        pages = []
        prs = Presentation(file_stream)
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_text = ""
            slide_images = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    slide_text += shape.text + "\n"
                if hasattr(shape, "image"):
                    placeholder = f"[IMAGE_PLACEHOLDER_{len(slide_images)}]"
                    slide_text += placeholder + "\n"
                    slide_images.append((shape.image.blob, "PPTX"))
            if slide_images:
                slide_text, vtokens = _replace_image_placeholders(slide_text, slide_images)
            else:
                vtokens = 0
            pages.append((slide_num, slide_text.strip(), vtokens))
        return pages

    elif filename_lower.endswith(".pdf"):
        pages = []
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page_num, page in enumerate(doc, 1):
            page_text = ""
            page_images = []
            blocks = []
            seen_xrefs = set()
            for block in page.get_text("blocks"):
                if block[6] == 0:
                    blocks.append(("text", block[1], block[4]))
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                y0 = rects[0].y0
                clip = rects[0]
                mat = fitz.Matrix(2, 2)
                pm = page.get_pixmap(matrix=mat, clip=clip)
                img_bytes = pm.tobytes("png")
                placeholder = f"[IMAGE_PLACEHOLDER_{len(page_images)}]"
                blocks.append(("image", y0, placeholder, img_bytes))
                page_images.append((img_bytes, "PDF"))
            blocks.sort(key=lambda b: b[1])
            for block in blocks:
                page_text += (block[2].strip() if block[0] == "text" else block[2]) + "\n"
            if page_images:
                page_text, vtokens = _replace_image_placeholders(page_text, page_images)
            else:
                vtokens = 0
            pages.append((page_num, page_text.strip(), vtokens))
        return pages

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
            return [(int(k) if k.isdigit() else i + 1, content_dict[k], 0) for i, k in enumerate(sorted_keys)]
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    else:
        raise ValueError("Unsupported file type. Supported: PDF, PPT, PPTX, TXT, DOCX")


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list:
    words = text.split()
    step = chunk_size - overlap
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), step)]
