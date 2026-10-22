"""Bounded PostgreSQL queries with transaction-local tenant context and evidence."""
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
import secrets
from uuid import uuid4
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from data_mind.contracts import Scope, Evidence
from data_mind.synthetic import CATEGORIES, STATUSES

class Repository:
    def __init__(self, database_url=None, *, cursor_secret=None, timeout_ms=5000, max_connections=8):
        self.pool = ConnectionPool(database_url or os.environ['DATABASE_URL'], min_size=1, max_size=max_connections,
                                   kwargs={'row_factory':dict_row}, open=True)
        self.cursor_secret = (cursor_secret or os.getenv('CURSOR_SECRET') or secrets.token_hex(32)).encode()
        self.timeout_ms = max(100,min(int(timeout_ms),30000))
    def close(self):
        self.pool.close()
    @contextmanager
    def _connection(self, scope):
        with self.pool.connection() as connection:
            with connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                role = connection.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
                if role['rolsuper'] or role['rolbypassrls']:
                    raise PermissionError('Query login must not be superuser or BYPASSRLS; use a restricted reader login')
                connection.execute('SET LOCAL ROLE data_mind_reader')
                connection.execute("SELECT set_config('app.tenant_id',%s,true)",(str(scope.tenant_id),))
                connection.execute("SELECT set_config('statement_timeout',%s,true)",(str(self.timeout_ms),))
                yield connection
    @staticmethod
    def _filter(scope, category=None,status=None):
        start,end = scope.utc_bounds()
        clauses=['tenant_id=%s','event_at >= %s','event_at < %s']
        values=[scope.tenant_id,start,end]
        if category is not None:
            if category not in CATEGORIES: raise ValueError('Unknown category')
            clauses.append('category=%s'); values.append(category)
        if status is not None:
            if status not in STATUSES: raise ValueError('Unknown status')
            clauses.append('status=%s'); values.append(status)
        return ' AND '.join(clauses),values
    @staticmethod
    def _limit(limit,maximum=100):
        if isinstance(limit,bool) or not 1 <= int(limit) <= maximum: raise ValueError(f'Limit must be between 1 and {maximum}')
        return int(limit)
    def _envelope(self,connection,scope,rows,total,*,truncated=False,method='exact',sources=None,warnings=None,next_cursor=None):
        state=connection.execute("SELECT max(event_at) watermark FROM incidents WHERE tenant_id=%s",(scope.tenant_id,)).fetchone()
        batches=connection.execute("SELECT batch_key,dataset_version,checkpoint,status FROM ingestion_batches ORDER BY batch_key").fetchall()
        version=hashlib.sha256(json.dumps(batches,sort_keys=True,default=str).encode()).hexdigest()[:16]
        kwargs=dict(query_id=str(uuid4()),dataset_version=version,effective_scope=scope,as_of=datetime.now(timezone.utc),event_watermark=state['watermark'],total_matching=int(total),returned_rows=len(rows),truncated=truncated,rows=rows,aggregation_method=method,sources=sources or ['synthetic:incidents'],warnings=warnings or [])
        result=Evidence(**kwargs)
        # The shared contract owns this optional field. Older consumers still receive bounded rows.
        if next_cursor is not None:
            result = result.model_copy(update={'next_cursor':next_cursor})
        return result
    def dataset_status(self,scope):
        with self._connection(scope) as c:
            row=c.execute('SELECT count(*) count,min(event_at) first_event,max(event_at) last_event FROM incidents WHERE tenant_id=%s',(scope.tenant_id,)).fetchone()
            return self._envelope(c,scope,[row],row['count'],sources=['synthetic:dataset'])
    def incidents_summary(self,scope,group_by='category',limit=20,category=None,status=None):
        if group_by not in {'category','status','sector'}: raise ValueError('Unsupported grouping')
        limit=self._limit(limit)
        where,args=self._filter(scope,category,status)
        with self._connection(scope) as c:
            total=c.execute(f'SELECT count(*) n FROM incidents WHERE {where}',args).fetchone()['n']
            rows=c.execute(f'SELECT {group_by} AS label,count(*) AS count FROM incidents WHERE {where} GROUP BY {group_by} ORDER BY count(*) DESC,{group_by} LIMIT %s',args+[limit+1]).fetchall()
            return self._envelope(c,scope,rows[:limit],total,truncated=len(rows)>limit)
    def incidents_timeseries(self,scope,category=None,status=None):
        where,args=self._filter(scope,category,status)
        with self._connection(scope) as c:
            rows=c.execute(f"SELECT (event_at AT TIME ZONE %s)::date AS day,count(*) AS count FROM incidents WHERE {where} GROUP BY day ORDER BY day",[scope.timezone]+args).fetchall()
            return self._envelope(c,scope,rows,sum(r['count'] for r in rows))
    def _cursor_scope(self,scope,text,category,status):
        return hashlib.sha256(json.dumps([scope.model_dump(mode='json'),text,category,status],sort_keys=True).encode()).hexdigest()
    def _encode_cursor(self,scope_hash,row):
        payload=json.dumps({'scope':scope_hash,'time':row['event_at'].isoformat(),'id':row['id']},sort_keys=True).encode()
        signature=hmac.new(self.cursor_secret,payload,hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload+signature).decode()
    def _decode_cursor(self,cursor,scope_hash):
        try:
            if len(cursor)>2000: raise ValueError()
            decoded=base64.urlsafe_b64decode(cursor.encode()); payload,signature=decoded[:-32],decoded[-32:]
            if not hmac.compare_digest(signature,hmac.new(self.cursor_secret,payload,hashlib.sha256).digest()): raise ValueError()
            value=json.loads(payload)
            if value['scope']!=scope_hash: raise ValueError()
            return datetime.fromisoformat(value['time']),int(value['id'])
        except Exception as exc: raise ValueError('Invalid cursor or changed query scope') from exc
    def incidents_search(self,scope,text='',limit=20,cursor=None,category=None,status=None):
        limit=self._limit(limit)
        if len(text)>300: raise ValueError('Search text too long')
        where,args=self._filter(scope,category,status)
        if text.strip(): where+=" AND search_vector @@ plainto_tsquery('spanish', %s)"; args.append(text)
        scope_hash=self._cursor_scope(scope,text,category,status)
        with self._connection(scope) as c:
            total=c.execute(f'SELECT count(*) n FROM incidents WHERE {where}',args).fetchone()['n']
            if cursor:
                event_at,row_id=self._decode_cursor(cursor,scope_hash)
                where+=' AND (event_at,id) > (%s,%s)'; args += [event_at,row_id]
            rows=c.execute(f'SELECT id,synthetic_id,event_at,category,status,sector,resolved_at,description FROM incidents WHERE {where} ORDER BY event_at,id LIMIT %s',args+[limit+1]).fetchall()
            truncated=len(rows)>limit; rows=rows[:limit]
            next_cursor=self._encode_cursor(scope_hash,rows[-1]) if truncated else None
            return self._envelope(c,scope,rows,total,truncated=truncated,next_cursor=next_cursor)
    def incident_detail(self,scope,incident_id):
        if isinstance(incident_id,str) and incident_id.startswith('SYN-'): incident_id=int(incident_id[4:])
        incident_id=int(incident_id)
        where,args=self._filter(scope)
        with self._connection(scope) as c:
            rows=c.execute(f'SELECT id,synthetic_id,event_at,category,status,sector,resolved_at,description FROM incidents WHERE {where} AND id=%s',args+[incident_id]).fetchall()
            return self._envelope(c,scope,rows,len(rows),sources=[f'synthetic:incident:{incident_id}'] if rows else [])
    def resolution_statistics(self,scope,category=None,status=None):
        if (scope.to_date_exclusive-scope.from_date).days>366: raise ValueError('Exact resolution statistics are limited to 366 days')
        where,args=self._filter(scope,category,status)
        with self._connection(scope) as c:
            row=c.execute(f'''SELECT count(*) AS matched_count,count(resolved_at) AS resolved_count,
                avg(extract(epoch FROM resolved_at-event_at))::float8 AS mean_seconds,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM resolved_at-event_at)) AS median_seconds,
                min(extract(epoch FROM resolved_at-event_at))::float8 AS min_seconds,
                max(extract(epoch FROM resolved_at-event_at))::float8 AS max_seconds
                FROM incidents WHERE {where}''',args).fetchone()
            return self._envelope(c,scope,[row],row['matched_count'])
    def knowledge_search(self,scope,query,limit=5):
        limit=self._limit(limit,10)
        if not query.strip() or len(query)>500: raise ValueError('Query must have 1-500 characters')
        _,end=scope.utc_bounds()
        with self._connection(scope) as c:
            rows=c.execute("""SELECT id,title,content,version,section,effective_at,
              ts_rank(search_vector,plainto_tsquery('spanish',%s))::float8 AS score
              FROM documents WHERE tenant_id=%s AND effective_at < %s
              AND search_vector @@ plainto_tsquery('spanish',%s) ORDER BY score DESC,id LIMIT %s""",(query,scope.tenant_id,end,query,limit+1)).fetchall()
            total=c.execute("SELECT count(*) n FROM documents WHERE tenant_id=%s AND effective_at < %s AND search_vector @@ plainto_tsquery('spanish',%s)",(scope.tenant_id,end,query)).fetchone()['n']
            return self._envelope(c,scope,rows[:limit],total,truncated=len(rows)>limit,method='full_text',sources=[f"synthetic:document:{r['id']}:{r['version']}" for r in rows[:limit]],warnings=['Document retrieval uses PostgreSQL full-text search; vector reranking requires the optional embedding profile.'])

    def knowledge_search_hybrid(self, scope, query, limit=5, *, model_path):
        """Optional genuine local embeddings, never downloaded during a request.

        Exact cosine candidates plus lexical candidates are fused using RRF.
        SQL still applies tenant and effective-date constraints before ranking.
        """
        from pathlib import Path
        from sentence_transformers import SentenceTransformer
        limit = self._limit(limit, 10)
        if not query.strip() or len(query) > 500:
            raise ValueError('Query must have 1-500 characters')
        if not Path(model_path).is_dir():
            raise ValueError('A locally provisioned 384-dimensional embedding model is required')
        if not hasattr(self, '_embedding_model'):
            self._embedding_model = SentenceTransformer(model_path, local_files_only=True, trust_remote_code=False)
        embedding = self._embedding_model.encode(query, normalize_embeddings=True).tolist()
        if len(embedding) != 384:
            raise ValueError('Embedding model must produce 384 dimensions')
        vector = '[' + ','.join(str(float(x)) for x in embedding) + ']'
        _, end = scope.utc_bounds()
        with self._connection(scope) as c:
            total = c.execute('SELECT count(*) n FROM documents WHERE tenant_id=%s AND effective_at < %s AND embedding IS NOT NULL', (scope.tenant_id, end)).fetchone()['n']
            if not total:
                raise ValueError('No embedded documents; run the worker embed-documents command first')
            rows = c.execute('''WITH eligible AS (
                SELECT *, ts_rank(search_vector, plainto_tsquery('spanish', %s)) lexical_score,
                       embedding <=> %s::vector distance
                FROM documents WHERE tenant_id=%s AND effective_at < %s AND embedding IS NOT NULL
            ), ranked AS (
                SELECT *, row_number() OVER (ORDER BY distance,id) semantic_rank,
                          row_number() OVER (ORDER BY lexical_score DESC,id) lexical_rank
                FROM eligible
            ) SELECT id,title,content,version,section,effective_at,
                     (1.0/(60+semantic_rank) + CASE WHEN lexical_score>0 THEN 1.0/(60+lexical_rank) ELSE 0 END)::float8 score
              FROM ranked ORDER BY score DESC,id LIMIT %s''', (query, vector, scope.tenant_id, end, limit)).fetchall()
            return self._envelope(c, scope, rows, total, truncated=total > limit,
                method='hybrid_exact_cosine_rrf', sources=[f"synthetic:document:{r['id']}:{r['version']}" for r in rows],
                warnings=['Ranking similarity is not a factual confidence score.'])
