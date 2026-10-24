-- CANDIDATE / TEST ONLY: deliberately outside migrations; db push must not deploy this.
-- Durable authorization state only: never store raw state, browser secrets,
-- broker credentials, or tokens here. The trusted gateway must derive owner_ref
-- from its authenticated customer and validate the exact configured callback.
-- These service-only RPCs do not themselves authenticate a customer.
-- Keep installation atomic, including removal of default PUBLIC execution.
BEGIN;
CREATE SCHEMA crier_webull_private;
REVOKE ALL ON SCHEMA crier_webull_private FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION crier_webull_private.valid_session_input(
  p_owner text, p_state_hash text, p_binding_hash text, p_environment text, p_callback text
) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
  SELECT coalesce(
    length(p_owner) BETWEEN 1 AND 200 AND p_owner ~ '[^[:space:]]'
    AND p_owner !~ '[[:cntrl:]]'
    AND p_state_hash ~ '^[0-9a-f]{64}$'
    AND p_binding_hash ~ '^[0-9a-f]{64}$'
    AND p_environment IN ('sandbox','production')
    AND length(p_callback) BETWEEN 9 AND 2048
    AND p_callback ~ '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?(/[^?#]*)?$'
    AND p_callback !~ '[[:space:][:cntrl:]@?#]'
    AND position(chr(92) IN p_callback)=0,
    false)
$$;
REVOKE ALL ON FUNCTION crier_webull_private.valid_session_input(text,text,text,text,text) FROM PUBLIC, anon, authenticated, service_role;

CREATE TABLE crier_webull_private.authorization_sessions (
  owner_ref text NOT NULL,
  state_hash text PRIMARY KEY,
  binding_hash text NOT NULL,
  environment text NOT NULL,
  callback text NOT NULL,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  CHECK (crier_webull_private.valid_session_input(owner_ref,state_hash,binding_hash,environment,callback)),
  CHECK (expires_at = created_at + interval '300 seconds')
);
CREATE INDEX authorization_sessions_owner_expiry ON crier_webull_private.authorization_sessions(owner_ref,expires_at);
REVOKE ALL ON crier_webull_private.authorization_sessions FROM PUBLIC, anon, authenticated, service_role;

-- Caller creates two independent 32-byte cryptographically random values and
-- submits only their lowercase SHA-256 hex digests. SQL cannot prove entropy.
CREATE FUNCTION public.crier_webull_session_create(
  p_owner text, p_state_hash text, p_binding_hash text, p_environment text, p_callback text
) RETURNS TABLE(created_at timestamptz, expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE issued timestamptz;
BEGIN
  -- PostgREST uses READ COMMITTED. Reject fixed transaction snapshots: they
  -- could miss a concurrent insert committed while waiting for the quota lock.
  IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
    OR NOT crier_webull_private.valid_session_input(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback) THEN
    RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Invalid authorization session';
  END IF;
  -- Serialize every create for an owner across both environments. A hash
  -- collision merely serializes unrelated owners; it cannot merge their data.
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('crier-webull-session:'||p_owner,0));
  DELETE FROM crier_webull_private.authorization_sessions AS s WHERE s.owner_ref=p_owner AND s.expires_at<=pg_catalog.clock_timestamp();
  IF (SELECT count(*) FROM crier_webull_private.authorization_sessions AS s WHERE s.owner_ref=p_owner)>=5 THEN
    RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Invalid authorization session';
  END IF;
  issued:=pg_catalog.clock_timestamp();
  INSERT INTO crier_webull_private.authorization_sessions(owner_ref,state_hash,binding_hash,environment,callback,created_at,expires_at)
    VALUES(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback,issued,issued+interval '300 seconds');
  RETURN QUERY SELECT issued,issued+interval '300 seconds';
EXCEPTION WHEN unique_violation THEN
  -- Never upsert or reveal the conflicting owner or digest.
  RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Invalid authorization session';
END $$;

CREATE FUNCTION public.crier_webull_session_consume(
  p_owner text, p_state_hash text, p_binding_hash text, p_environment text, p_callback text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE deadline timestamptz;
BEGIN
  IF NOT crier_webull_private.valid_session_input(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback) THEN RETURN false; END IF;
  SELECT s.expires_at INTO deadline FROM crier_webull_private.authorization_sessions AS s
    WHERE s.state_hash=p_state_hash AND s.owner_ref=p_owner AND s.binding_hash=p_binding_hash
      AND s.environment=p_environment AND s.callback=p_callback FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  -- Check wall time only AFTER obtaining the row lock. A waiting consumer
  -- must not authorize an already-expired session using an earlier snapshot.
  IF deadline<=pg_catalog.clock_timestamp() THEN
    DELETE FROM crier_webull_private.authorization_sessions AS s WHERE s.state_hash=p_state_hash;
    RETURN false;
  END IF;
  DELETE FROM crier_webull_private.authorization_sessions AS s WHERE s.state_hash=p_state_hash;
  RETURN true;
END $$;

CREATE FUNCTION public.crier_webull_session_revoke(p_owner text,p_environment text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE removed integer;
BEGIN
  -- Revocation must see creates committed while it waits for the owner lock.
  IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
    OR p_owner IS NULL OR length(p_owner) NOT BETWEEN 1 AND 200 OR p_owner !~ '[^[:space:]]'
    OR p_owner ~ '[[:cntrl:]]' OR p_environment IS NULL OR p_environment NOT IN ('sandbox','production') THEN
    RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Invalid authorization session';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('crier-webull-session:'||p_owner,0));
  DELETE FROM crier_webull_private.authorization_sessions AS s WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  GET DIAGNOSTICS removed=ROW_COUNT;
  RETURN removed;
END $$;

REVOKE ALL ON FUNCTION public.crier_webull_session_create(text,text,text,text,text) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.crier_webull_session_consume(text,text,text,text,text) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.crier_webull_session_revoke(text,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_session_create(text,text,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_session_consume(text,text,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_session_revoke(text,text) TO service_role;
COMMIT;
