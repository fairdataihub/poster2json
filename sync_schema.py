#!/usr/bin/env python3
"""
Sync poster_schema.json from the canonical poster-json-schema repository.

Usage:
    python sync_schema.py          # fetch latest (root poster_schema.json)
    python sync_schema.py v0.2     # fetch specific version
    python sync_schema.py v0.1     # fetch older version
"""

import json
import sys
import urllib.request

CANONICAL_BASE = "https://raw.githubusercontent.com/fairdataihub/poster-json-schema/main"
LOCAL_PATH = "poster2json/schemas/poster_schema.json"


def sync(version: str | None = None) -> None:
    if version:
        url = f"{CANONICAL_BASE}/schemas/{version}/poster_schema.json"
    else:
        url = f"{CANONICAL_BASE}/poster_schema.json"

    print(f"Fetching schema from {url}")
    with urllib.request.urlopen(url) as resp:
        schema = json.loads(resp.read().decode())

    with open(LOCAL_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Updated {LOCAL_PATH}")
    print(f"  $id: {schema.get('$id', 'unknown')}")
    print(f"  description: {schema.get('description', '')[:80]}...")


if __name__ == "__main__":
    version = sys.argv[1] if len(sys.argv) > 1 else None
    sync(version)
