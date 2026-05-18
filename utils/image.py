import base64
import os

import httpx


def get_image_description(image_bytes: bytes, context_text: str = "") -> tuple[str, int]:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    url = os.getenv("MULTI_MODAL_URL")
    api_key = os.getenv("MULTI_MODAL_KEY")

    if not url or not api_key:
        return "", 0

    headers = {"Content-Type": "application/json", "api-key": api_key}

    prompt_text = "Tolong ekstrak dan deskripsikan informasi tekstual serta konteks visual penting (seperti grafik, diagram) dari gambar ini. Hanya berikan teks yang diekstrak dan deskripsinya, jangan berhalusinasi."
    if context_text:
        prompt_text += f"\n\nBerikut adalah teks konteks dari dokumen di sekitar gambar ini (sebelum dan sesudah gambar, ditandai dengan [GAMBAR INI], berguna jika gambar merujuk pada 'slide sebelumnya' atau 'slide selanjutnya'):\n{context_text}"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ],
            }
        ],
        "max_tokens": 1000,
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
