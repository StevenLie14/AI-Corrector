"""Cache deskripsi gambar yang bertahan antar pemrosesan.

MASALAH YANG DIPECAHKAN. Cache lama hidup di dalam satu request lalu hilang. Akibatnya tiga hal
membayar vision dari nol padahal gambarnya sama persis:

  1. Percobaan ulang setelah gagal. Materi 100 gambar yang gagal di gambar ke-99 mendeskripsikan
     100 lagi pada sapuan berikutnya. Dengan MaxAttempts=5 itu 5x biaya penuh sebelum menyerah.
  2. Materi berbagi gambar. Logo kampus, template jurusan, diagram lintas mata kuliah - tiap
     materi bayar sendiri-sendiri walau byte-nya identik.
  3. Revisi kecil. Ubah 2 slide dari 40 -> revision naik -> feed penuh -> bayar 40 gambar.

Vision 98-99% dari biaya feed, jadi ini bukan optimasi pinggiran.

SIFAT YANG WAJIB DIPEGANG: cache ini OPTIONAL dan GAGAL-AMAN. Kalau tidak dikonfigurasi, atau
tabelnya tidak bisa dihubungi, atau apa pun error-nya, ia berperilaku persis seperti dict biasa
di memori dan pemrosesan tetap jalan. Cache yang rusak boleh membuat biaya naik; ia TIDAK BOLEH
membuat materi gagal.

Karena itu SEMUA operasi tabel dibungkus try/except yang menelan error - satu-satunya tempat di
kode ini yang menelan exception dengan sengaja.

KENAPA BUKAN AZURE SEARCH. Fitur ini punya aturan "Search tidak boleh jadi penyimpan state"
karena indexing lag-nya beberapa detik. Untuk cache aturan itu sebenarnya tidak berlaku (cache
miss cuma berarti bayar vision lagi, bukan salah hasil), tapi Search jauh lebih mahal per GB
daripada Table dan tidak dirancang sebagai key-value store.

KUNCI. Bukan cuma hash gambar. Model dan versi prompt IKUT jadi kunci - kalau tidak, mengganti
prompt akan diam-diam memakai deskripsi lama yang dibuat prompt berbeda, dan tidak ada yang tahu.
"""
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

PROMPT_VERSION = os.getenv("VISION_PROMPT_VERSION", "v1")

_CONNECTION = os.getenv("VISION_CACHE_CONNECTION")
_TABLE_NAME = os.getenv("VISION_CACHE_TABLE", "visioncache")
_MODEL = os.getenv("MULTI_MODAL_MODEL") or os.getenv("LLM_MODEL") or "vision"

_MAX_VALUE_CHARS = 60000


def cache_key(image_bytes: bytes) -> str:
    """Kunci stabil untuk satu gambar pada satu kombinasi model+prompt."""
    return cache_key_from_digest(hashlib.sha256(image_bytes).hexdigest())


def cache_key_from_digest(digest: str) -> str:
    """Varian untuk pemanggil yang sudah punya hash isi gambar (mis. PPTX menyediakan sha1).

    WAJIB hash ISI. Pengenal yang cuma unik di dalam satu dokumen (seperti xref PDF) TIDAK
    boleh dipakai: xref 5 dokumen A akan menabrak xref 5 dokumen B, dan cache mengembalikan
    deskripsi gambar yang sama sekali berbeda tanpa ada yang tahu.
    """
    return f"{_MODEL}|{PROMPT_VERSION}|{digest}"


class VisionCache:
    """Berperilaku seperti dict (`in`, `[]`, `[]=`) supaya pemanggil tidak perlu tahu backend-nya.

    Lapisan memori selalu ada dan dibaca lebih dulu: dalam satu dokumen, gambar yang sama
    tidak perlu bolak-balik ke tabel.
    """

    def __init__(self):
        self._memory: dict[str, str] = {}
        self._table = _open_table()
        self.hits_remote = 0
        self.hits_memory = 0
        self.misses = 0

    # --- protokol dict ---------------------------------------------------
    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: str) -> None:
        self._memory[key] = value
        if self._table is None or value is None or len(value) > _MAX_VALUE_CHARS:
            return
        try:
            self._table.upsert_entity({
                "PartitionKey": _partition_of(key),
                "RowKey": _row_of(key),
                "description": value,
            })
        except Exception as e:
            logger.warning("gagal menulis cache vision (diabaikan): %s: %s", type(e).__name__, e)

    # --- inti ------------------------------------------------------------
    def get(self, key: str):
        if key in self._memory:
            self.hits_memory += 1
            return self._memory[key]

        if self._table is not None:
            try:
                entity = self._table.get_entity(_partition_of(key), _row_of(key))
                value = entity.get("description")
                if value is not None:
                    self._memory[key] = value
                    self.hits_remote += 1
                    return value
            except Exception:
                pass

        self.misses += 1
        return None

    def stats(self) -> dict:
        return {
            "hits_memory": self.hits_memory,
            "hits_remote": self.hits_remote,
            "misses": self.misses,
            "persistent": self._table is not None,
        }


def _partition_of(key: str) -> str:
    """Partisi = model|prompt. Mengganti versi prompt otomatis memindahkan seluruh cache
    ke partisi baru, jadi entri lama tidak pernah terbaca dan bisa dihapus per-partisi."""
    return key.rsplit("|", 1)[0].replace("/", "_")


def _row_of(key: str) -> str:
    return key.rsplit("|", 1)[1]


def _open_table():
    """None kalau tidak dikonfigurasi atau tidak bisa dibuka. Itu keadaan yang SAH."""
    if not _CONNECTION:
        return None
    try:
        from azure.data.tables import TableServiceClient

        service = TableServiceClient.from_connection_string(_CONNECTION)
        try:
            service.create_table(_TABLE_NAME)
        except Exception:
            pass
        return service.get_table_client(_TABLE_NAME)
    except Exception as e:
        logger.warning("cache vision persisten dimatikan (%s: %s) - jatuh balik ke memori",
                       type(e).__name__, e)
        return None
