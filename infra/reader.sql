-- Only the synthetic local stack uses this login. The runtime never gets admin credentials.
\getenv reader_password READER_PASSWORD
SELECT 'CREATE ROLE data_mind_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'data_mind_app') \gexec
ALTER ROLE data_mind_app PASSWORD :'reader_password';
ALTER ROLE data_mind_app INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT data_mind_reader TO data_mind_app;
ALTER ROLE data_mind_app SET default_transaction_read_only = on;
