-- Administrative migration. Never executed by a request handler.
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='data_mind_reader') THEN CREATE ROLE data_mind_reader NOLOGIN; END IF;
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='data_mind_writer') THEN CREATE ROLE data_mind_writer NOLOGIN; END IF;
END $$;
CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS tenants(id smallint PRIMARY KEY, name text NOT NULL);
INSERT INTO tenants SELECT n, 'Organización ficticia ' || n FROM generate_series(1,5) n ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ingestion_batches (
 batch_key text PRIMARY KEY, dataset_version text NOT NULL, expected_rows bigint NOT NULL,
 checkpoint bigint NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'loading',
 manifest jsonb NOT NULL DEFAULT '{}', loaded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS incidents (
 id bigint PRIMARY KEY, synthetic_id text UNIQUE NOT NULL, tenant_id smallint NOT NULL REFERENCES tenants(id),
 event_at timestamptz NOT NULL, category text NOT NULL, status text NOT NULL,
 sector text NOT NULL, resolved_at timestamptz, description text NOT NULL,
 batch_key text NOT NULL REFERENCES ingestion_batches(batch_key), loaded_at timestamptz NOT NULL DEFAULT now(),
 search_vector tsvector GENERATED ALWAYS AS (to_tsvector('spanish', description)) STORED,
 CHECK (resolved_at IS NULL OR resolved_at >= event_at)
);
CREATE INDEX IF NOT EXISTS incidents_tenant_time_id ON incidents(tenant_id,event_at,id);
CREATE INDEX IF NOT EXISTS incidents_tenant_status_time ON incidents(tenant_id,status,event_at);
CREATE INDEX IF NOT EXISTS incidents_search ON incidents USING gin(search_vector);
CREATE TABLE IF NOT EXISTS documents (
 id bigint PRIMARY KEY, tenant_id smallint NOT NULL REFERENCES tenants(id), title text NOT NULL,
 content text NOT NULL, version text NOT NULL, section text NOT NULL,
 effective_at timestamptz NOT NULL,
 search_vector tsvector GENERATED ALWAYS AS (to_tsvector('spanish', title || ' ' || content)) STORED
);
CREATE INDEX IF NOT EXISTS documents_search ON documents USING gin(search_vector);
CREATE INDEX IF NOT EXISTS documents_tenant ON documents(tenant_id,effective_at);
CREATE TABLE IF NOT EXISTS daily_metrics (
 tenant_id smallint NOT NULL, event_day date NOT NULL, category text NOT NULL,
 incident_count bigint NOT NULL, duration_sum_seconds numeric NOT NULL, resolved_count bigint NOT NULL,
 PRIMARY KEY(tenant_id,event_day,category)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['incidents','documents','daily_metrics'] LOOP
 EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
 IF NOT EXISTS (SELECT FROM pg_policies WHERE tablename=t AND policyname='reader_tenant') THEN
 EXECUTE format('CREATE POLICY reader_tenant ON %I FOR SELECT TO data_mind_reader USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::smallint)',t);
 END IF;
 IF NOT EXISTS (SELECT FROM pg_policies WHERE tablename=t AND policyname='writer_all') THEN
 EXECUTE format('CREATE POLICY writer_all ON %I TO data_mind_writer USING (true) WITH CHECK (true)',t);
 END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO data_mind_reader,data_mind_writer;
GRANT SELECT ON tenants,incidents,documents,daily_metrics,ingestion_batches TO data_mind_reader;
GRANT SELECT,INSERT,UPDATE,DELETE ON tenants,incidents,documents,daily_metrics,ingestion_batches TO data_mind_writer;
INSERT INTO schema_migrations(version) VALUES ('001_initial') ON CONFLICT DO NOTHING;
