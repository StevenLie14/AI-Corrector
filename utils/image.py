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

    if is_student_answer:
        prompt_text = (
            "Lihat gambar ini dengan seksama. Deskripsikan HANYA berdasarkan apa yang benar-benar terlihat di gambar, bukan dari konteks teks.\n\n"
            "- Jika TABEL atau TEKS: ekstrak semua data secara lengkap dan terstruktur.\n"
            "- Jika DIAGRAM, FLOWCHART, atau GRAFIK: jelaskan struktur, alur, dan temuan utama.\n"
            "- Jika LOGO atau IKON TOOL/TEKNOLOGI: sebutkan nama tool/teknologi tersebut jika dapat dikenali, beserta fungsi singkatnya.\n"
            "- Jika gambar gelap, buram, atau tidak dapat dibaca: katakan gambar tidak dapat dibaca, jangan tebak isinya.\n"
            "- Untuk gambar lainnya: jelaskan isi gambar secara singkat.\n\n"
            "DILARANG menebak atau mengarang isi gambar berdasarkan teks di sekitarnya."
        )
    else:
        prompt_text = (
            "Lihat gambar ini dengan seksama. Deskripsikan HANYA berdasarkan apa yang benar-benar terlihat di gambar, bukan dari konteks teks.\n\n"
            "- Jika TABEL atau TEKS: ekstrak semua data secara lengkap dan terstruktur.\n"
            "- Jika DIAGRAM, FLOWCHART, atau GRAFIK: jelaskan struktur, alur, dan temuan utama.\n"
            "- Jika DEKORATIF atau TIDAK RELEVAN (foto orang, gambar hewan, clipart, dsb): balas hanya dengan kata SKIP.\n"
            "- Jika gambar gelap, buram, atau tidak dapat dibaca: balas hanya dengan kata SKIP.\n\n"
            "DILARANG menebak atau mengarang isi gambar berdasarkan teks di sekitarnya."
        )
    if context_text:
        prompt_text += f"\n\nKonteks dokumen di sekitar gambar ini (ditandai [GAMBAR INI]):\n{context_text}"

    payload = {
        "model": os.getenv("VISION_MODEL", "gpt-4o"),
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt_text},
                    {"type": "input_image", "image_url": f"data:{mime_type};base64,{base64_image}"},
                ],
            }
        ],
    }

    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                data = response.json()
                description = "\n".join(
                    part.get("text", "")
                    for item in data.get("output", [])
                    for part in (item.get("content") or [])
                    if part.get("type") == "output_text"
                ).strip()
                usage = data.get("usage", {})
                tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                return description, tokens
            print(f"Multi-modal API returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"Error calling multi-modal API: {e}")

    return "", 0
