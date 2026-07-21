"""Tambahkan field BARU ke index Azure AI Search yang sudah berisi data.

Kenapa ini terpisah dari create_index.py: Azure Search tidak bisa menghapus field atau mengubah
tipenya, tapi MENAMBAH field ke index yang sudah ada itu boleh dan tidak merusak isinya. Jadi
untuk penambahan murni tidak perlu membangun index baru dan mengisi ulang seluruh chunk.

Cara kerjanya: GET definisi index yang sedang jalan, tambahkan field yang belum ada dari
index.json, lalu PUT balik. Definisi yang dipakai adalah milik index yang jalan, BUKAN
index.json apa adanya - supaya perbedaan lain yang sudah ada di sana tidak ikut tertimpa.

    python add_index_fields.py --name ai-corrector-v2
    python add_index_fields.py --name ai-corrector-v2 --apply     # benar-benar menulis

Tanpa --apply ia hanya menampilkan apa yang AKAN dilakukan.

CATATAN: dokumen yang sudah ada TIDAK ikut terisi. Field barunya null sampai materinya di-feed
ulang atau di-merge lewat PATCH /feed/{id}/metadata.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_VERSION = "2024-07-01"
INDEX_JSON = Path(__file__).with_name("index.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Nama index yang mau ditambah field-nya")
    parser.add_argument("--apply", action="store_true", help="Tulis perubahan. Tanpa ini cuma pratinjau.")
    parser.add_argument("--file", default=str(INDEX_JSON), help="Sumber definisi field")
    args = parser.parse_args()

    endpoint = (os.getenv("VECTORDB_URL") or "").rstrip("/")
    key = os.getenv("VECTORDB_KEY")
    if not endpoint or not key:
        print("VECTORDB_URL / VECTORDB_KEY belum diset.", file=sys.stderr)
        return 2

    headers = {"api-key": key, "Content-Type": "application/json"}
    url = f"{endpoint}/indexes/{args.name}?api-version={API_VERSION}"

    response = httpx.get(url, headers=headers, timeout=30.0)
    if response.status_code != 200:
        print(f"Index '{args.name}' tidak terbaca: {response.status_code} {response.text[:300]}",
              file=sys.stderr)
        return 1

    live = response.json()
    live_names = {f["name"] for f in live.get("fields", [])}
    wanted = json.loads(Path(args.file).read_text(encoding="utf-8"))["fields"]

    missing = [f for f in wanted if f["name"] not in live_names]
    if not missing:
        print(f"Index '{args.name}' sudah punya semua field dari {Path(args.file).name}. "
              "Tidak ada yang perlu ditambahkan.")
        return 0

    print(f"Index '{args.name}' sekarang punya {len(live_names)} field.")
    print("Akan DITAMBAHKAN:")
    for f in missing:
        flags = [k for k in ("filterable", "sortable", "facetable", "searchable") if f.get(k)]
        print(f"   {f['name']:18s} {f['type']:26s} {','.join(flags)}")

    if not args.apply:
        print("\nPratinjau saja. Tambahkan --apply untuk benar-benar menulis.")
        return 0

    live["fields"] = live["fields"] + missing
    write = httpx.put(url, headers=headers, json=live, timeout=60.0)

    if write.status_code not in (200, 201, 204):
        print(f"GAGAL {write.status_code}: {write.text[:600]}", file=sys.stderr)
        return 1

    verify = httpx.get(url, headers=headers, timeout=30.0)
    after = {f["name"] for f in verify.json().get("fields", [])} if verify.status_code == 200 else set()
    still_missing = [f["name"] for f in missing if f["name"] not in after]
    if still_missing:
        print(f"GAGAL: {still_missing} tidak muncul setelah PUT.", file=sys.stderr)
        return 1

    print(f"\nBerhasil. Field sekarang: {sorted(after)}")
    print("Dokumen lama masih null di field baru - perlu feed ulang atau PATCH metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
