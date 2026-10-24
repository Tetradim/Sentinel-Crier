-- CANDIDATE / TEST ONLY: outside migrations; no gateway or live broker access.
-- The trusted codec authenticates AES-GCM context (owner/environment/generation).
-- SQL validates envelope shape only, never plaintext or cryptographic authenticity.
BEGIN;
-- JS strings use UTF-16 lengths and trim the ECMAScript whitespace set.
CREATE FUNCTION crier_webull_private.valid_token_text(value text)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
  SELECT coalesce(length(value) BETWEEN 1 AND 200
    AND length(value)+(SELECT count(*) FROM generate_series(1,length(value)) AS t(i) WHERE ascii(substr(value,i,1))>65535)<=200
    AND value !~ '[[:cntrl:]]'
    AND NOT EXISTS(SELECT FROM generate_series(1,length(value)) AS t(i) WHERE ascii(substr(value,i,1)) BETWEEN 127 AND 159)
    AND length(btrim(value,chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(32)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288)||chr(65279)))>0,false)
$$;
CREATE FUNCTION crier_webull_private.valid_token_scope(p_owner text,p_environment text)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
  SELECT coalesce(crier_webull_private.valid_token_text(p_owner) AND p_environment IN ('sandbox','production'),false)
$$;
CREATE FUNCTION crier_webull_private.valid_token_envelope(e jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE raw bytea; encoded text; k text; v numeric;
BEGIN
  IF e IS NULL OR jsonb_typeof(e)<>'object' THEN RETURN false; END IF;
  IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(e) AS t(key)) IS DISTINCT FROM
    ARRAY['access_expires_at_ms','ciphertext','identity_hash','key_id','nonce','refresh_expires_at_ms','schema'] THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['schema','key_id','nonce','ciphertext','identity_hash'] LOOP
    IF jsonb_typeof(e->k)<>'string' THEN RETURN false; END IF;
  END LOOP;
  IF e->>'schema'<>'crier.webull-token.v1' OR NOT crier_webull_private.valid_token_text(e->>'key_id')
    OR e->>'identity_hash' !~ '^[0-9a-f]{64}$'
    OR e->>'nonce' !~ '^[A-Za-z0-9_-]{16}$'
    OR length(e->>'ciphertext') NOT BETWEEN 22 AND 65536
    OR e->>'ciphertext' !~ '^[A-Za-z0-9_-]+$' THEN RETURN false; END IF;
  -- Require canonical unpadded base64url, matching the codec's decode/re-encode.
  encoded:=translate(e->>'ciphertext','-_','+/');
  raw:=decode(encoded||repeat('=',(4-length(encoded)%4)%4),'base64');
  IF octet_length(raw) NOT BETWEEN 16 AND 32784
    OR translate(rtrim(replace(encode(raw,'base64'),E'\n',''),'='),'+/','-_')<>e->>'ciphertext' THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['access_expires_at_ms','refresh_expires_at_ms'] LOOP
    IF jsonb_typeof(e->k)<>'number' THEN RETURN false; END IF;
    v:=(e->>k)::numeric;
    IF v<>trunc(v) OR v<=0 OR v>8640000000000000 THEN RETURN false; END IF;
  END LOOP;
  RETURN coalesce((e->>'refresh_expires_at_ms')::numeric>(e->>'access_expires_at_ms')::numeric,false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE TABLE crier_webull_private.token_states (
  owner_ref text NOT NULL,
  environment text NOT NULL,
  generation bigint NOT NULL CHECK(generation BETWEEN 1 AND 9007199254740991),
  state text NOT NULL CHECK(state IN ('authorization_pending','active','refresh_pending','unknown','revoked')),
  operation_id uuid,
  envelope jsonb,
  expected_identity_hash text,
  PRIMARY KEY(owner_ref,environment),
  CHECK(crier_webull_private.valid_token_scope(owner_ref,environment)),
  CHECK((state IN ('authorization_pending','refresh_pending'))=(operation_id IS NOT NULL)),
  CHECK((state='active')=(envelope IS NOT NULL)),
  CHECK((state IN ('active','refresh_pending'))=(expected_identity_hash IS NOT NULL)),
  CHECK(expected_identity_hash IS NULL OR expected_identity_hash ~ '^[0-9a-f]{64}$'),
  CHECK(state<>'active' OR expected_identity_hash=envelope->>'identity_hash'),
  CHECK(envelope IS NULL OR crier_webull_private.valid_token_envelope(envelope))
);
REVOKE ALL ON SCHEMA crier_webull_private FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON crier_webull_private.token_states FROM PUBLIC,anon,authenticated,service_role;

-- Shared transaction lock serializes first insert/revoke as well as row mutations.
-- No leases or time-based stealing: an interrupted rotating refresh requires new auth.
CREATE FUNCTION crier_webull_private.token_lock(p_owner text,p_environment text)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF current_setting('transaction_isolation')<>'read committed'
    OR NOT crier_webull_private.valid_token_scope(p_owner,p_environment) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('crier-webull-token:'||length(p_owner)::text||':'||p_owner||':'||p_environment,0));
END $$;
CREATE FUNCTION public.crier_webull_token_reserve(p_owner text,p_environment text,p_expected_generation bigint,p_operation_id uuid)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states; next_generation bigint;
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  IF p_operation_id IS NULL OR p_expected_generation IS NULL OR p_expected_generation NOT BETWEEN 0 AND 9007199254740990 THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation'; END IF;
  SELECT * INTO r FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND THEN
    IF p_expected_generation<>0 THEN RETURN NULL; END IF;
    INSERT INTO crier_webull_private.token_states VALUES(p_owner,p_environment,1,'authorization_pending',p_operation_id,NULL,NULL);
    RETURN 1;
  END IF;
  IF r.generation<>p_expected_generation THEN RETURN NULL; END IF;
  next_generation:=r.generation+1;
  UPDATE crier_webull_private.token_states s SET generation=next_generation,state='authorization_pending',operation_id=p_operation_id,envelope=NULL,expected_identity_hash=NULL WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN next_generation;
END $$;
CREATE FUNCTION public.crier_webull_token_commit(p_owner text,p_environment text,p_generation bigint,p_operation_id uuid,p_envelope jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states;
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  SELECT * INTO r FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND OR p_generation IS NULL OR p_operation_id IS NULL OR r.generation<>p_generation OR r.operation_id IS DISTINCT FROM p_operation_id OR r.state NOT IN ('authorization_pending','refresh_pending') THEN RETURN false; END IF;
  IF NOT crier_webull_private.valid_token_envelope(p_envelope) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation'; END IF;
  IF r.state='refresh_pending' AND r.expected_identity_hash IS DISTINCT FROM p_envelope->>'identity_hash' THEN RETURN false; END IF;
  -- Wall time after lock; never extend token lifetimes or accept expired results.
  IF (p_envelope->>'access_expires_at_ms')::numeric<=extract(epoch FROM clock_timestamp())*1000 THEN RETURN false; END IF;
  UPDATE crier_webull_private.token_states s SET state='active',operation_id=NULL,envelope=p_envelope,expected_identity_hash=p_envelope->>'identity_hash' WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN true;
END $$;
CREATE FUNCTION public.crier_webull_token_claim_refresh(p_owner text,p_environment text,p_expected_generation bigint,p_operation_id uuid)
RETURNS TABLE(prior_generation bigint,new_generation bigint,envelope jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states;
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  IF p_operation_id IS NULL OR p_expected_generation IS NULL OR p_expected_generation NOT BETWEEN 1 AND 9007199254740990 THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation'; END IF;
  SELECT * INTO r FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND OR r.generation<>p_expected_generation OR r.state<>'active' THEN RETURN; END IF;
  IF (r.envelope->>'refresh_expires_at_ms')::numeric<=extract(epoch FROM clock_timestamp())*1000 THEN RETURN; END IF;
  UPDATE crier_webull_private.token_states s SET generation=r.generation+1,state='refresh_pending',operation_id=p_operation_id,envelope=NULL,expected_identity_hash=r.envelope->>'identity_hash' WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN QUERY SELECT r.generation,r.generation+1,r.envelope;
END $$;
CREATE FUNCTION public.crier_webull_token_read(p_owner text,p_environment text)
RETURNS TABLE(state text,generation bigint,envelope jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  RETURN QUERY SELECT s.state,s.generation,CASE WHEN s.state='active' THEN s.envelope ELSE NULL::jsonb END FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment;
END $$;
CREATE FUNCTION public.crier_webull_token_mark_unknown(p_owner text,p_environment text,p_generation bigint,p_operation_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states;
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  SELECT * INTO r FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND OR p_generation IS NULL OR p_operation_id IS NULL OR r.generation<>p_generation OR r.operation_id IS DISTINCT FROM p_operation_id OR r.state NOT IN ('authorization_pending','refresh_pending') THEN RETURN false; END IF;
  UPDATE crier_webull_private.token_states s SET state='unknown',operation_id=NULL,envelope=NULL,expected_identity_hash=NULL WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN true;
END $$;
-- First revoke creates generation 1 tombstone; every later revoke increments.
-- Tombstones are never deleted, preventing generation reuse and stale completion.
CREATE FUNCTION public.crier_webull_token_revoke(p_owner text,p_environment text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r crier_webull_private.token_states;
BEGIN
  PERFORM crier_webull_private.token_lock(p_owner,p_environment);
  SELECT * INTO r FROM crier_webull_private.token_states s WHERE s.owner_ref=p_owner AND s.environment=p_environment FOR UPDATE;
  IF NOT FOUND THEN
    INSERT INTO crier_webull_private.token_states VALUES(p_owner,p_environment,1,'revoked',NULL,NULL,NULL); RETURN 1;
  END IF;
  IF r.generation=9007199254740991 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid Webull token operation'; END IF;
  UPDATE crier_webull_private.token_states s SET generation=r.generation+1,state='revoked',operation_id=NULL,envelope=NULL,expected_identity_hash=NULL WHERE s.owner_ref=p_owner AND s.environment=p_environment;
  RETURN r.generation+1;
END $$;
REVOKE ALL ON FUNCTION crier_webull_private.valid_token_text(text),crier_webull_private.valid_token_scope(text,text),crier_webull_private.valid_token_envelope(jsonb),crier_webull_private.token_lock(text,text) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.crier_webull_token_reserve(text,text,bigint,uuid),public.crier_webull_token_commit(text,text,bigint,uuid,jsonb),public.crier_webull_token_claim_refresh(text,text,bigint,uuid),public.crier_webull_token_read(text,text),public.crier_webull_token_mark_unknown(text,text,bigint,uuid),public.crier_webull_token_revoke(text,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.crier_webull_token_reserve(text,text,bigint,uuid),public.crier_webull_token_commit(text,text,bigint,uuid,jsonb),public.crier_webull_token_claim_refresh(text,text,bigint,uuid),public.crier_webull_token_read(text,text),public.crier_webull_token_mark_unknown(text,text,bigint,uuid),public.crier_webull_token_revoke(text,text) TO service_role;
COMMIT;
