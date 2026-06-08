import base64
import os

import httpx


def _detect_mime_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"GIF8":
        return "image/gif"
    if image_bytes[:4] in (b"RIFF", b"WEBP"):
        return "image/webp"
    return "image/jpeg"


def get_image_description(image_bytes: bytes, context_text: str = "", is_student_answer: bool = False) -> tuple[str, int]:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = _detect_mime_type(image_bytes)
    url = os.getenv("MULTI_MODAL_URL")
    api_key = os.getenv("MULTI_MODAL_KEY")

    if not url or not api_key:
        return "", 0

    headers = {"Content-Type": "application/json", "api-key": api_key}

    skip_instruction = (
        "\n- Jika DEKORATIF atau TIDAK RELEVAN (foto orang, gambar hewan, clipart, logo, dsb): balas hanya dengan kata SKIP."
        if not is_student_answer else ""
    )
    prompt_text = (
        "Analisis gambar ini dari sebuah dokumen formal (laporan, kebijakan, materi kuliah, dsb). "
        "Tentukan apakah gambar ini relevan dengan konten dokumen:\n\n"
        "- Jika TABEL atau TEKS: ekstrak semua data secara lengkap dan terstruktur. Tanpa deskripsi visual.\n"
        "- Jika DIAGRAM, FLOWCHART, atau GRAFIK: jelaskan struktur, alur, dan temuan utama.\n"
        f"- Jika gambar tidak termasuk kategori di atas: jelaskan isi gambar secara singkat.{skip_instruction}\n\n"
        "Jangan berhalusinasi."
    )
    if context_text:
        prompt_text += f"\n\nKonteks dokumen di sekitar gambar ini (ditandai [GAMBAR INI]):\n{context_text}"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
                ],
            }
        ],
    }

    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                data = response.json()
                description = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                return description, tokens
    except Exception as e:
        print(f"Error calling multi-modal API: {e}")

    return "", 0
