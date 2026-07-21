import base64
import os
import threading
import time

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class VisionUnavailableError(Exception):
    """Panggilan vision gagal dan sudah habis percobaan ulangnya.

    Dilempar, bukan dikembalikan sebagai deskripsi kosong. Deskripsi kosong tidak bisa
    dibedakan dari SKIP (gambar dekoratif yang memang sengaja dilewati), sehingga materi
    ter-index tanpa isi gambarnya sambil tetap dilaporkan sukses.

    `retry_after` diisi dari header balasan kalau server memberitahunya (429 biasanya
    menyertakannya). Kita menunggu selama yang DIMINTA server, bukan menebak sendiri:
    backoff tebakan yang mentok di 8 detik akan menyerah terlalu cepat kalau kuota baru
    pulih 30 detik lagi.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class VisionCircuitOpenError(Exception):
    """Layanan vision sedang dianggap tumbang; permintaan ditolak TANPA memanggilnya.

    Tanpa ini, saat Azure OpenAI benar-benar down setiap materi menabrak tembok yang sama
    sendiri-sendiri: tiap gambar 3x retry, tiap materi 2 ronde, tiap sapuan 5 percobaan.
    Ratusan materi x semua itu = ribuan panggilan sia-sia dan MaxAttempts habis untuk materi
    yang sebenarnya sehat.

    Diperlakukan TRANSIENT oleh Course-Service (default klasifikasi), jadi materi tetap
    dicoba lagi di sapuan berikutnya - bukan menyerah.
    """


class _VisionCircuit:
    """Circuit breaker sederhana khusus kegagalan LAYANAN (429/5xx/timeout).

    Kegagalan per-gambar (mis. gambar rusak) TIDAK dihitung - yang dijaga di sini cuma
    "layanannya sedang tidak bisa dipakai", bukan "gambar ini bermasalah".

    Ambangnya sengaja longgar: 429 sesekali itu normal dan sudah ditangani Retry-After.
    Yang ingin ditangkap adalah kegagalan BERUNTUN yang menandakan layanan benar-benar tumbang.
    """

    def __init__(self, threshold: int, cooldown: float):
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._opened_at == 0.0:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self._cooldown:
                raise VisionCircuitOpenError(
                    f"Vision service circuit open after {self._failures} consecutive failures; "
                    f"retry in {self._cooldown - elapsed:.0f}s")
            self._opened_at = 0.0
            self._failures = self._threshold - 1

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at == 0.0:
                self._opened_at = time.monotonic()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0


_circuit = _VisionCircuit(
    threshold=int(os.getenv("VISION_CIRCUIT_THRESHOLD", "12")),
    cooldown=float(os.getenv("VISION_CIRCUIT_COOLDOWN", "60")),
)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# Batas atas kepatuhan pada Retry-After. Tanpa ini, satu header yang keliru (atau kuota yang
_MAX_RETRY_AFTER_SECONDS = 60.0


def _parse_retry_after(response) -> float | None:
    raw = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset-requests")
    if not raw:
        return None
    try:
        return min(float(raw), _MAX_RETRY_AFTER_SECONDS)
    except (TypeError, ValueError):
        # Retry-After boleh berupa tanggal HTTP, bukan hanya detik. Formatnya jarang dipakai
        # Azure OpenAI, jadi cukup diabaikan daripada salah mengurai.
        return None


def _wait_vision(retry_state) -> float:
    """Pakai Retry-After dari server kalau ada; kalau tidak, backoff eksponensial biasa."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    hinted = getattr(exc, "retry_after", None)
    if hinted:
        return hinted
    return wait_exponential(multiplier=1, min=1, max=8)(retry_state)


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


@retry(
    stop=stop_after_attempt(3),
    wait=_wait_vision,
    retry=retry_if_exception_type((VisionUnavailableError, httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
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

    _circuit.check()

    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=60.0)
    except (httpx.TimeoutException, httpx.TransportError):
        _circuit.record_failure()
        raise

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
        _circuit.record_success()
        return description, tokens

    # 429 (kuota per menit terlampaui) dan 5xx bersifat sementara -> dicoba ulang oleh @retry.
    # Sisanya (400/401/413 dsb) tidak akan membaik dengan diulang, jadi langsung menyerah.
    detail = f"Multi-modal API returned {response.status_code}: {response.text[:200]}"
    if response.status_code in _RETRYABLE_STATUS:
        _circuit.record_failure()
        raise VisionUnavailableError(detail, retry_after=_parse_retry_after(response))
    raise RuntimeError(detail)
