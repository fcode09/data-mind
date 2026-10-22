"""Deterministic fictional incidents. Generation never reads a production source."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

CATEGORIES = ('Limpieza pública', 'Alumbrado', 'Vías', 'Áreas verdes', 'Seguridad vial')
STATUSES = ('Abierto', 'En proceso', 'Resuelto')
GENERATOR_VERSION = 'synthetic-v2.0'

def mix(value: int) -> int:
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9 & ((1 << 64)-1)
    value = (value ^ (value >> 27)) * 0x94d049bb133111eb & ((1 << 64)-1)
    return value ^ (value >> 31)

def incident(row_id: int, seed: int, anchor: datetime, days: int = 730, batch_key: str = 'base') -> tuple:
    if row_id < 1 or days < 1 or anchor.tzinfo is None:
        raise ValueError('Positive row ID/day window and timezone-aware anchor required')
    number = mix(row_id + seed * 1000000007)
    tenant = number % 5 + 1
    category = CATEGORIES[(number >> 5) % len(CATEGORIES)]
    status = STATUSES[(number >> 9) % 3]
    seconds = (number >> 14) % (days * 86400)
    event_at = anchor - timedelta(seconds=seconds + 1)
    duration = 60 + ((number >> 25) % 172740)
    resolved_at = event_at + timedelta(seconds=duration) if status == 'Resuelto' else None
    return (row_id, f'SYN-{row_id:012d}', tenant, event_at, category, status,
            f'Sector ficticio {(number >> 42) % 20 + 1}', resolved_at,
            f'Incidente ficticio de {category.lower()} número {row_id}. Sin datos personales reales.', batch_key)

def fingerprint(rows: int, seed: int, anchor: datetime, days: int, offset: int = 0) -> str:
    spec = dict(generator=GENERATOR_VERSION, rows=rows, seed=seed, anchor=anchor.isoformat(), days=days, offset=offset)
    return sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()

class Manifest:
    def __init__(self):
        self.count = 0
        self.tenants = Counter()
        self.categories = Counter()
        self.resolved_count = 0
        self.duration_sum_seconds = 0
        self.digest = sha256()
        self.minimum = None
        self.maximum = None
    def add(self, row):
        self.count += 1
        self.tenants[str(row[2])] += 1
        self.categories[row[4]] += 1
        if row[7]:
            self.resolved_count += 1
            self.duration_sum_seconds += int((row[7]-row[3]).total_seconds())
        self.minimum = min(self.minimum,row[3]) if self.minimum else row[3]
        self.maximum = max(self.maximum,row[3]) if self.maximum else row[3]
        self.digest.update(json.dumps([v.isoformat() if isinstance(v,datetime) else v for v in row],ensure_ascii=False,separators=(',',':')).encode()+b'\n')
    def as_dict(self):
        return dict(count=self.count, tenants=dict(sorted(self.tenants.items())), categories=dict(sorted(self.categories.items())), resolved_count=self.resolved_count, duration_sum_seconds=self.duration_sum_seconds, min_event_at=self.minimum.isoformat() if self.minimum else None, max_event_at=self.maximum.isoformat() if self.maximum else None, sha256=self.digest.hexdigest())
