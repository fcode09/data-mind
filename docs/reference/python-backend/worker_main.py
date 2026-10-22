"""Administrative commands for the synthetic-only dataset.

Run `python -m apps.worker.main --help`. Requires a separate administrative URL.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from data_mind.synthetic import incident, fingerprint, Manifest, CATEGORIES

ROOT=Path(__file__).resolve().parents[2]
COLUMNS='id,synthetic_id,tenant_id,event_at,category,status,sector,resolved_at,description,batch_key'

def migrate(url, vectors=False):
    with psycopg.connect(url) as c:
        c.execute((ROOT/'db/migrations/001_initial.sql').read_text())
        if vectors: c.execute((ROOT/'db/migrations/002_optional_vectors.sql').read_text())

def seed(url, *, rows=1000000,seed=42,anchor=datetime(2026,10,23,tzinfo=timezone.utc),days=730,batch_size=10000,offset=0,batch_key=None):
    if not 1 <= rows <= 10000000 or not 1<=batch_size<=100000 or offset<0:
        raise ValueError('Invalid rows, batch size or offset')
    version=fingerprint(rows,seed,anchor,days,offset)
    key=batch_key or f'base-{version[:16]}'
    manifest=Manifest(); start=time.monotonic()
    with psycopg.connect(url,row_factory=dict_row) as c:
        # A lock per dataset prevents two concurrent loaders from racing checkpoints.
        c.execute('SELECT pg_advisory_lock(hashtext(%s))',(key,))
        c.commit()
        try:
            with c.transaction():
                c.execute('SET LOCAL ROLE data_mind_writer')
                c.execute('INSERT INTO ingestion_batches(batch_key,dataset_version,expected_rows) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(key,version,rows))
                record=c.execute('SELECT * FROM ingestion_batches WHERE batch_key=%s FOR UPDATE',(key,)).fetchone()
                if record['dataset_version']!=version: raise ValueError('Batch key already belongs to a different generation specification')
                checkpoint=record['checkpoint']
            # Recompute the independent manifest even on resume; batches bound RAM.
            for first in range(1,rows+1,batch_size):
                last=min(rows,first+batch_size-1)
                batch=[incident(offset+i,seed,anchor,days,key) for i in range(first,last+1)]
                for row in batch: manifest.add(row)
                if last<=checkpoint: continue
                with c.transaction():
                    c.execute('SET LOCAL ROLE data_mind_writer')
                    # PostgreSQL forbids COPY directly into an RLS table. A transaction-local
                    # staging table preserves bounded COPY performance and RLS on INSERT.
                    c.execute(f'CREATE TEMP TABLE seed_stage ON COMMIT DROP AS SELECT {COLUMNS} FROM incidents WITH NO DATA')
                    with c.cursor().copy(f'COPY seed_stage({COLUMNS}) FROM STDIN') as copy:
                        for row in batch:
                            if row[0]-offset>checkpoint: copy.write_row(row)
                    c.execute(f'INSERT INTO incidents({COLUMNS}) SELECT {COLUMNS} FROM seed_stage')
                    c.execute('UPDATE ingestion_batches SET checkpoint=%s,loaded_at=now() WHERE batch_key=%s',(last,key))
            result=manifest.as_dict()
            with c.transaction():
                c.execute('SET LOCAL ROLE data_mind_writer')
                c.execute("UPDATE ingestion_batches SET status='complete',manifest=%s,loaded_at=now() WHERE batch_key=%s",(Jsonb(result),key))
                for tenant in range(1,6):
                    for index,category in enumerate(CATEGORIES):
                        for section in range(1,5):
                            document_id=tenant*1000+index*10+section
                            content=f'Procedimiento ficticio para {category.lower()}. Paso {section}: registrar el incidente, validar el sector y documentar la atención. El cierre requiere evidencia y revisión del responsable. No sustituye procedimientos reales.'
                            c.execute('INSERT INTO documents(id,tenant_id,title,content,version,section,effective_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING',(document_id,tenant,f'SOP ficticio: {category}',content,'1.0',f'Sección {section}',anchor-timedelta(days=days)))
                refresh_daily(c)
            return dict(batch_key=key,dataset_version=version,manifest=result,elapsed_seconds=round(time.monotonic()-start,3))
        finally:
            c.rollback()
            c.execute('SELECT pg_advisory_unlock(hashtext(%s))',(key,)); c.commit()

def refresh_daily(c):
    c.execute('DELETE FROM daily_metrics')
    c.execute("""INSERT INTO daily_metrics
      SELECT tenant_id,(event_at AT TIME ZONE 'America/Lima')::date,category,count(*),
             coalesce(sum(extract(epoch FROM resolved_at-event_at)),0),count(resolved_at)
      FROM incidents GROUP BY tenant_id,2,category""")

def verify(url,batch_key):
    with psycopg.connect(url,row_factory=dict_row) as c:
        c.execute('SET LOCAL ROLE data_mind_writer')
        batch=c.execute('SELECT manifest,status FROM ingestion_batches WHERE batch_key=%s',(batch_key,)).fetchone()
        if not batch or batch['status']!='complete': raise ValueError('Batch is missing or incomplete')
        actual=c.execute('SELECT count(*) count,count(resolved_at) resolved_count,coalesce(sum(extract(epoch FROM resolved_at-event_at)),0)::bigint duration_sum_seconds FROM incidents WHERE batch_key=%s',(batch_key,)).fetchone()
        manifest=batch['manifest']
        errors=[key for key in actual if actual[key]!=manifest[key]]
        tenants=c.execute('SELECT tenant_id,count(*) n FROM incidents WHERE batch_key=%s GROUP BY tenant_id',(batch_key,)).fetchall()
        if {str(r['tenant_id']):r['n'] for r in tenants}!=manifest['tenants']: errors.append('tenants')
        categories=c.execute('SELECT category,count(*) n FROM incidents WHERE batch_key=%s GROUP BY category',(batch_key,)).fetchall()
        if {r['category']:r['n'] for r in categories}!=manifest['categories']: errors.append('categories')
        if errors: raise ValueError(f'Manifest mismatch: {errors}')
        return dict(verified=True,batch_key=batch_key,actual=actual)

def embed_documents(url, model_path):
    """Embed only synthetic SOP documents using a pre-provisioned local model."""
    from sentence_transformers import SentenceTransformer
    if not Path(model_path).is_dir():
        raise ValueError('Provide an existing local model directory; network downloads are disabled')
    model = SentenceTransformer(model_path, local_files_only=True, trust_remote_code=False)
    with psycopg.connect(url, row_factory=dict_row) as c:
        c.execute('SET LOCAL ROLE data_mind_writer')
        rows = c.execute('SELECT id,title,content FROM documents ORDER BY id').fetchall()
        vectors = model.encode([r['title'] + '\n' + r['content'] for r in rows], normalize_embeddings=True)
        for row, vector in zip(rows, vectors):
            if len(vector) != 384:
                raise ValueError('Embedding model must produce 384 dimensions')
            value = '[' + ','.join(str(float(x)) for x in vector) + ']'
            c.execute('UPDATE documents SET embedding=%s::vector WHERE id=%s', (value, row['id']))
    return {'embedded_documents': len(rows), 'dimensions': 384}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',default=os.getenv('DATABASE_ADMIN_URL'))
    subs=parser.add_subparsers(dest='command',required=True)
    migration=subs.add_parser('migrate'); migration.add_argument('--vectors',action='store_true')
    for command in ('seed','append-day'):
        p=subs.add_parser(command); p.add_argument('--rows',type=int,default=1000000 if command=='seed' else 10000); p.add_argument('--seed',type=int,default=42)
        p.add_argument('--anchor',default='2026-10-23T00:00:00+00:00'); p.add_argument('--batch-size',type=int,default=10000)
        p.add_argument('--offset',type=int,default=None)
        p.add_argument('--batch-key'); p.add_argument('--manifest-output')
    e=subs.add_parser('embed-documents'); e.add_argument('--model-path',required=True)
    v=subs.add_parser('verify'); v.add_argument('--batch-key',required=True)
    args=parser.parse_args()
    if not args.database_url: parser.error('DATABASE_ADMIN_URL or --database-url is required; never use a production database')
    if args.command=='migrate': migrate(args.database_url,args.vectors); result={'migrated':True}
    elif args.command=='embed-documents': result=embed_documents(args.database_url,args.model_path)
    elif args.command=='verify': result=verify(args.database_url,args.batch_key)
    else:
        anchor=datetime.fromisoformat(args.anchor)
        if anchor.tzinfo is None: parser.error('Anchor must include timezone offset')
        result=seed(args.database_url,rows=args.rows,seed=args.seed,anchor=anchor,days=1 if args.command=='append-day' else 730,batch_size=args.batch_size,offset=args.offset if args.offset is not None else (0 if args.command=='seed' else anchor.date().toordinal()*10000000),batch_key=args.batch_key)
        if args.manifest_output: Path(args.manifest_output).write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
