"""Crea índices de lectura en gueo2021.incidents (tolerante, idempotente).

Uso:
    backend\\.venv\\Scripts\\python backend\\scripts\\ensure_indexes.py

Crea (si faltan) índices simples para los filtros/sort/ticket más usados:
  incident_state, category_name, workgroup_name, incident_district,
  incident_creation_date (-1), incident_ticket_number.

Nunca raisea por un índice individual: reporta created/skipped y sigue.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import INCIDENT_INDEXES, get_db  # noqa: E402


def main() -> int:
    db = get_db()
    coll = db["incidents"]
    try:
        info = coll.index_information()
        existing = set(info.keys())
        covered = set()
        for spec in info.values():
            key = spec.get("key") or []
            if len(key) == 1:
                covered.add(key[0][0])
    except Exception as exc:
        print(f"No pude listar índices: {exc}")
        existing, covered = set(), set()
    created, skipped = [], []
    for field, direction in INCIDENT_INDEXES:
        name = f"idx_{field}"
        if name in existing or field in covered:
            skipped.append(name)
            continue
        try:
            coll.create_index([(field, direction)], name=name, background=True)
            created.append(name)
            print(f"OK created {name} on {field} ({direction})")
        except Exception as exc:
            skipped.append(name)
            print(f"SKIP {name}: {exc}")
    print(f"\ncreated={created} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
