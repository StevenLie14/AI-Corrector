"""Buat index Azure AI Search dari scripts/index.json.

    python create_index.py --name ai-corrector-v2
    python create_index.py --name <nama> --replace   # timpa, ISI HILANG

Env: VECTORDB_URL, VECTORDB_KEY.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API_VERSION = "2024-07-01"
INDEX_JSON = Path(__file__).with_name("index.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="Nama index. Default: dari index.json")
    parser.add_argument("--replace", action="store_true",
                        help="Timpa index yang sudah ada. TANPA ini, index yang sudah ada ditolak.")
    parser.add_argument("--file", default=str(INDEX_JSON), help="Path definisi index")
    args = parser.parse_args()

    endpoint = (os.getenv("VECTORDB_URL") or "").rstrip("/")
    key = os.getenv("VECTORDB_KEY")
    if not endpoint or not key:
        print("VECTORDB_URL / VECTORDB_KEY belum diset.", file=sys.stderr)
        return 2

    definition = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if args.name:
        definition["name"] = args.name
    name = definition["name"]

    definition = {k: v for k, v in definition.items() if v not in ([], {}, None)}

    headers = {"api-key": key, "Content-Type": "application/json"}
    url = f"{endpoint}/indexes/{name}?api-version={API_VERSION}"

    existing = httpx.get(url, headers=headers, timeout=30.0)
    if existing.status_code == 200:
        if not args.replace:
            fields = [f["name"] for f in existing.json().get("fields", [])]
            print(f"Index '{name}' SUDAH ADA. Field sekarang: {fields}")
            print("Tidak diapa-apakan. Pakai --name lain, atau --replace kalau memang mau ditimpa.")
            return 1
        print(f"--replace: menghapus index '{name}' beserta seluruh isinya...")
        httpx.delete(url, headers=headers, timeout=60.0).raise_for_status()

    response = httpx.put(url, headers=headers, json=definition, timeout=60.0)
    if response.status_code not in (200, 201):
        print(f"GAGAL {response.status_code}: {response.text[:600]}", file=sys.stderr)
        return 1

    created = response.json()
    print(f"Index '{name}' dibuat.")
    for field in created.get("fields", []):
        flags = [k for k in ("filterable", "sortable", "facetable", "searchable") if field.get(k)]
        print(f"   {field['name']:16s} {field['type']:26s} {','.join(flags)}")

    if name != "ai-corrector":
        print(f"\nBELUM dipakai aplikasi. Untuk memakainya, set VECTORDB_INDEX={name}")
        print("   lokal   : local.settings.json / .env")
        print("   deployed: App Service Configuration LMS-AI-CORRECTOR (restart otomatis)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
