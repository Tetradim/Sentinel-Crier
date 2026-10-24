-- CANDIDATE / TEST ONLY: outside migrations, loaded after both candidate stores.
-- Trusted server composition boundary. Callers supply fresh CSPRNG state/binding
-- digests; SQL stores no raw secrets and cannot prove entropy or customer identity.
BEGIN;
CREATE TABLE crier_webull_private.authorization_reservations (
  state_hash text PRIMARY KEY REFERENCES crier_webull_private.authorization_sessions(state_hash) ON DELETE CASCADE,
  generation bigint NOT NULL CHECK(generation BETWEEN 1 AND 9007199254740991),
  operation_id uuid NOT NULL
);
REVOKE ALL ON crier_webull_private.authorization_reservations FROM PUBLIC,anon,authenticated,service_role;

-- Every compound operation takes owner/session lock, then token scope lock.
-- Lower-level RPCs are building blocks; the server coordinator uses these RPCs.
CREATE FUNCTION crier_webull_private.authorization_lock(p_owner text,p_environment text)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF current_setting('transaction_isolation')<>'read committed'
    OR NOT crier_webull_private.valid_token_scope(p_owner,p_environment)
    OR p_owner !~ '[^[:space:]]' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('crier-webull-session:'||p_owner,0));
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
END $$;
REVOKE ALL ON FUNCTION crier_webull_private.authorization_lock(text,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.crier_webull_authorization_begin(
  p_owner text,p_environment text,p_expected_generation bigint,p_operation_id uuid,
  p_state_hash text,p_binding_hash text,p_callback text
) RETURNS TABLE(generation bigint,operation_id uuid,expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE reserved bigint; deadline timestamptz;
BEGIN
  IF NOT crier_webull_private.valid_session_input(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback)
    OR NOT crier_webull_private.valid_token_scope(p_owner,p_environment)
    OR p_expected_generation IS NULL OR p_expected_generation NOT BETWEEN 0 AND 9007199254740990
    OR p_operation_id IS NULL THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
  END IF;
  PERFORM crier_webull_private.authorization_lock(p_owner,p_environment);
  reserved:=public.crier_webull_token_reserve(p_owner,p_environment,p_expected_generation,p_operation_id);
  IF reserved IS NULL THEN RETURN; END IF;
  -- Check before supersession: the current digest must not become reusable just
  -- because its session is about to be deleted. Cross-owner races hit UNIQUE.
  IF EXISTS(SELECT FROM crier_webull_private.authorization_sessions s WHERE s.state_hash=p_state_hash) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
  END IF;
  PERFORM public.crier_webull_session_revoke(p_owner,p_environment);
  SELECT s.expires_at INTO deadline FROM public.crier_webull_session_create(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback) s;
  INSERT INTO crier_webull_private.authorization_reservations(state_hash,generation,operation_id) VALUES(p_state_hash,reserved,p_operation_id);
  RETURN QUERY SELECT reserved,p_operation_id,deadline;
EXCEPTION WHEN unique_violation OR SQLSTATE '22023' THEN
  -- PL/pgSQL exception block rolls back reservation and browser state together.
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
END $$;

CREATE FUNCTION public.crier_webull_authorization_consume(
  p_owner text,p_environment text,p_state_hash text,p_binding_hash text,p_callback text
) RETURNS TABLE(generation bigint,operation_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE linked record;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
  END IF;
  IF NOT crier_webull_private.valid_session_input(p_owner,p_state_hash,p_binding_hash,p_environment,p_callback)
    OR NOT crier_webull_private.valid_token_scope(p_owner,p_environment) THEN RETURN; END IF;
  PERFORM crier_webull_private.authorization_lock(p_owner,p_environment);
  SELECT a.generation,a.operation_id,s.expires_at INTO linked
    FROM crier_webull_private.authorization_sessions s
    JOIN crier_webull_private.authorization_reservations a ON a.state_hash=s.state_hash
    WHERE s.owner_ref=p_owner AND s.environment=p_environment AND s.state_hash=p_state_hash
      AND s.binding_hash=p_binding_hash AND s.callback=p_callback FOR UPDATE OF s;
  IF NOT FOUND THEN RETURN; END IF;
  -- Wall time is checked after owner/token/row locks, including lock waits.
  IF linked.expires_at<=clock_timestamp() THEN
    DELETE FROM crier_webull_private.authorization_sessions s WHERE s.state_hash=p_state_hash;
    RETURN;
  END IF;
  IF NOT EXISTS(SELECT FROM crier_webull_private.token_states t
    WHERE t.owner_ref=p_owner AND t.environment=p_environment
      AND t.state='authorization_pending' AND t.generation=linked.generation AND t.operation_id=linked.operation_id) THEN RETURN; END IF;
  DELETE FROM crier_webull_private.authorization_sessions s WHERE s.state_hash=p_state_hash;
  RETURN QUERY SELECT linked.generation,linked.operation_id;
END $$;

CREATE FUNCTION public.crier_webull_authorization_revoke(p_owner text,p_environment text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE next_generation bigint;
BEGIN
  PERFORM crier_webull_private.authorization_lock(p_owner,p_environment);
  next_generation:=public.crier_webull_token_revoke(p_owner,p_environment);
  PERFORM public.crier_webull_session_revoke(p_owner,p_environment);
  RETURN next_generation;
EXCEPTION WHEN SQLSTATE '22023' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull authorization operation';
END $$;
REVOKE ALL ON FUNCTION public.crier_webull_authorization_begin(text,text,bigint,uuid,text,text,text),public.crier_webull_authorization_consume(text,text,text,text,text),public.crier_webull_authorization_revoke(text,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_authorization_begin(text,text,bigint,uuid,text,text,text),public.crier_webull_authorization_consume(text,text,text,text,text),public.crier_webull_authorization_revoke(text,text) TO service_role;
COMMIT;
