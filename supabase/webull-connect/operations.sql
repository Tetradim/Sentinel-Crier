-- CANDIDATE / TEST ONLY: outside migrations; load after authorization_flow.sql.
-- Rewrap changes encrypted custody only. The trusted codec authenticates the
-- same owner/environment/generation AAD; SQL can validate shape, not encryption.
BEGIN;
CREATE FUNCTION public.crier_webull_token_rewrap(
  p_owner text,p_environment text,p_expected_generation bigint,p_expected_envelope jsonb,p_envelope jsonb
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states;
BEGIN
  -- Shared scope lock and READ COMMITTED guard fence refresh, revoke and other
  -- rotations. Exact envelope CAS also fences rotations at the same generation.
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  SELECT * INTO r FROM crier_webull_private.token_states s
    WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND OR p_expected_generation IS NULL OR r.state<>'active'
    OR r.generation<>p_expected_generation OR r.envelope IS DISTINCT FROM p_expected_envelope THEN RETURN false; END IF;
  IF NOT crier_webull_private.valid_token_envelope(p_envelope)
    OR (p_envelope-ARRAY['key_id','nonce','ciphertext']) IS DISTINCT FROM (r.envelope-ARRAY['key_id','nonce','ciphertext']) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation';
  END IF;
  -- Check wall time after every lock; access may have expired while refresh is
  -- still usable. Neither lifetime nor generation can change during a rewrap.
  IF (r.envelope->>'refresh_expires_at_ms')::numeric<=extract(epoch FROM clock_timestamp())*1000 THEN RETURN false; END IF;
  UPDATE crier_webull_private.token_states s SET envelope=p_envelope
    WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN true;
END $$;

CREATE FUNCTION public.crier_webull_cleanup_expired_sessions(p_limit integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE removed integer;
BEGIN
  IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull cleanup operation';
  END IF;
  -- Row locks only: never take owner/token locks after session rows. This avoids
  -- reversing the authorization lock hierarchy and lets workers skip busy rows.
  WITH expired AS MATERIALIZED (
    SELECT s.state_hash FROM crier_webull_private.authorization_sessions s
    WHERE s.expires_at<=clock_timestamp()
    ORDER BY s.expires_at,s.state_hash LIMIT p_limit FOR UPDATE OF s SKIP LOCKED
  )
  DELETE FROM crier_webull_private.authorization_sessions s USING expired e
    WHERE s.state_hash=e.state_hash AND s.expires_at<=clock_timestamp();
  GET DIAGNOSTICS removed=ROW_COUNT;
  -- FK cascade removes associations; token states and tombstones are untouched.
  RETURN removed;
END $$;
REVOKE ALL ON FUNCTION public.crier_webull_token_rewrap(text,text,bigint,jsonb,jsonb),public.crier_webull_cleanup_expired_sessions(integer) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_token_rewrap(text,text,bigint,jsonb,jsonb),public.crier_webull_cleanup_expired_sessions(integer) TO service_role;
COMMIT;
