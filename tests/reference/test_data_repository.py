import os
from datetime import datetime, timezone
import pytest
from data_mind.contracts import Scope
from data_mind.repository import Repository

@pytest.fixture
def scope():
    return Scope(tenant_id=1, from_date='2024-10-23', to_date_exclusive='2026-10-24')

@pytest.fixture
def repo():
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('Requires a migrated and seeded PostgreSQL test database')
    value = Repository(os.environ['TEST_DATABASE_URL'], cursor_secret='test-only-cursor-key')
    yield value
    value.close()

def test_cursor_bound_to_scope():
    repo = object.__new__(Repository)
    repo.cursor_secret = b'test-only'
    token = repo._encode_cursor('scope-a', {'event_at': datetime.now(timezone.utc), 'id': 1})
    assert repo._decode_cursor(token, 'scope-a')[1] == 1
    with pytest.raises(ValueError): repo._decode_cursor(token, 'scope-b')
    with pytest.raises(ValueError): repo._decode_cursor(token[:-2] + 'aa', 'scope-a')

def test_totals_not_page_limits(repo, scope):
    small = repo.incidents_summary(scope, limit=1)
    full = repo.incidents_summary(scope, limit=100)
    assert small.total_matching == full.total_matching > 0
    assert small.truncated
    assert full.total_matching == sum(row['count'] for row in full.rows)
    assert repo.incidents_timeseries(scope).total_matching == full.total_matching

def test_keyset_and_tenant_isolation(repo, scope):
    first = repo.incidents_search(scope, limit=2)
    second = repo.incidents_search(scope, limit=2, cursor=first.next_cursor)
    assert not {r['id'] for r in first.rows} & {r['id'] for r in second.rows}
    other = scope.model_copy(update={'tenant_id': 2})
    assert repo.incident_detail(other, first.rows[0]['id']).total_matching == 0
    with pytest.raises(ValueError): repo.incidents_search(other, cursor=first.next_cursor)
    with repo._connection(scope) as connection:
        assert connection.execute('SELECT count(*) n FROM incidents WHERE tenant_id=2').fetchone()['n'] == 0

def test_query_bounds(repo, scope):
    with pytest.raises(ValueError): repo.incidents_summary(scope, group_by='status; DROP TABLE incidents')
    with pytest.raises(ValueError): repo.incidents_search(scope, limit=100000)
    with pytest.raises(ValueError): repo.incidents_search(scope, text='x' * 301)
    with pytest.raises(ValueError): repo.incidents_summary(scope, category='unknown')

def test_knowledge_and_statistics(repo):
    scope = Scope(tenant_id=1, from_date='2026-01-01', to_date_exclusive='2026-10-24')
    result = repo.resolution_statistics(scope)
    assert result.rows[0]['resolved_count'] <= result.total_matching
    docs = repo.knowledge_search(scope, 'procedimiento', limit=2)
    assert docs.returned_rows <= 2
    assert all(row['id'] < 2000 for row in docs.rows)

def test_repeatable_read_snapshot_and_role(repo, scope):
    with repo._connection(scope) as connection:
        assert connection.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] == 'repeatable read'
        assert connection.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        assert connection.execute('SELECT current_user role').fetchone()['role'] == 'data_mind_reader'
        assert connection.execute("SELECT current_setting('app.tenant_id') tenant").fetchone()['tenant'] == '1'
    with repo._connection(scope.model_copy(update={'tenant_id': 2})) as connection:
        assert connection.execute("SELECT current_setting('app.tenant_id') tenant").fetchone()['tenant'] == '2'

def test_snapshot_does_not_change_during_ingestion(repo, scope):
    import psycopg
    from uuid import uuid4
    admin_url = os.getenv('ADMIN_DATABASE_URL')
    if not admin_url:
        pytest.skip('Requires isolated administrative test connection')
    key = 'test-snapshot-' + uuid4().hex
    try:
        with repo._connection(scope) as connection:
            assert connection.execute('SELECT count(*) n FROM ingestion_batches WHERE batch_key=%s', (key,)).fetchone()['n'] == 0
            with psycopg.connect(admin_url) as writer:
                writer.execute('INSERT INTO ingestion_batches(batch_key,dataset_version,expected_rows) VALUES (%s,%s,0)', (key, 'test-only'))
            assert connection.execute('SELECT count(*) n FROM ingestion_batches WHERE batch_key=%s', (key,)).fetchone()['n'] == 0
        with repo._connection(scope) as connection:
            assert connection.execute('SELECT count(*) n FROM ingestion_batches WHERE batch_key=%s', (key,)).fetchone()['n'] == 1
    finally:
        with psycopg.connect(admin_url) as writer:
            writer.execute('DELETE FROM ingestion_batches WHERE batch_key=%s', (key,))
