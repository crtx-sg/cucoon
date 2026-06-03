-- =============================================================================
--  mcp-readonly.sql — least-privilege read-only role for the Postgres MCP.
--  Apply AFTER the apps have created their schemas, once, per database:
--
--    docker compose exec -T postgres psql -U "$PG_SUPERUSER" -d odysseus \
--      -v mcp_user="$MCP_RO_DB_USER" -v mcp_pass="'$MCP_RO_DB_PASSWORD'" \
--      -f - < postgres/mcp-readonly.sql
--
--  Pair this with the server's own `--access-mode=restricted` flag: the role
--  is the hard wall (can't write), restricted mode is the soft wall (won't try).
-- =============================================================================

-- Create the role if it doesn't exist (idempotent-ish).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'mcp_user') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', :'mcp_user', :'mcp_pass');
  END IF;
END
$$;

-- Read-only on the current database's public schema.
GRANT CONNECT ON DATABASE current_database() TO :"mcp_user" ;  -- noop guard
GRANT USAGE ON SCHEMA public TO :"mcp_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"mcp_user";
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO :"mcp_user";

-- Ensure future tables are readable too (so new app migrations don't lock it out).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"mcp_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO :"mcp_user";

-- Explicitly deny write paths (belt and suspenders; role has no grants anyway).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM :"mcp_user";
