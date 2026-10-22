from datetime import datetime, timezone
import pytest
from data_mind.contracts import Scope
from data_mind.synthetic import incident, fingerprint, Manifest

ANCHOR = datetime(2026, 10, 23, tzinfo=timezone.utc)

def test_deterministic_generator():
    rows = [incident(i, 42, ANCHOR) for i in range(1, 101)]
    assert rows == [incident(i, 42, ANCHOR) for i in range(1, 101)]
    assert {r[2] for r in rows} == {1, 2, 3, 4, 5}
    assert all(r[3] < ANCHOR for r in rows)
    assert all(r[7] is None or r[7] >= r[3] for r in rows)

def test_generator_fingerprint():
    assert fingerprint(100, 42, ANCHOR, 730) != fingerprint(101, 42, ANCHOR, 730)
    assert fingerprint(100, 42, ANCHOR, 730) != fingerprint(100, 43, ANCHOR, 730)

def test_local_day_and_dst():
    lima = Scope(tenant_id=1, from_date='2026-10-22', to_date_exclusive='2026-10-23')
    start, end = lima.utc_bounds()
    assert start.hour == 5 and (end-start).total_seconds() == 86400
    ny = Scope(tenant_id=1, from_date='2026-03-08', to_date_exclusive='2026-03-09', timezone='America/New_York')
    start, end = ny.utc_bounds()
    assert (end-start).total_seconds() == 23 * 3600
    with pytest.raises(ValueError): Scope(tenant_id=1, from_date='2026-10-22', to_date_exclusive='2026-10-22')

def test_manifest_independent_totals():
    rows = [incident(i, 42, ANCHOR) for i in range(1, 101)]
    manifest = Manifest()
    for row in rows:
        manifest.add(row)
    value = manifest.as_dict()
    assert value['count'] == 100
    assert sum(value['tenants'].values()) == 100
    assert sum(value['categories'].values()) == 100
    assert value['duration_sum_seconds'] == sum(int((r[7]-r[3]).total_seconds()) for r in rows if r[7])
    assert len(value['sha256']) == 64
