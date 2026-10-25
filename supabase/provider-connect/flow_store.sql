-- CANDIDATE / TEST ONLY. Deliberately outside migrations; do not deploy implicitly.
-- The Edge gateway authenticates the owner and encrypts with an external key.
-- No plaintext secrets or encryption keys enter this RPC or these tables.
BEGIN;
CREATE SCHEMA crier_provider;
REVOKE ALL ON SCHEMA crier_provider FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION crier_provider.envelope_valid(value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(value)='object'
  AND value ?& ARRAY['version','key_id','nonce','ciphertext']
  AND (value - ARRAY['version','key_id','nonce','ciphertext'])='{}'::jsonb
  AND value->'version'='1'::jsonb
  AND jsonb_typeof(value->'key_id')='string' AND value->>'key_id' ~ '^[A-Za-z0-9_-]{1,64}$'
  AND jsonb_typeof(value->'nonce')='string' AND value->>'nonce' ~ '^[A-Za-z0-9_-]{16}$'
  AND jsonb_typeof(value->'ciphertext')='string'
  AND length(value->>'ciphertext') BETWEEN 22 AND 90000
  AND value->>'ciphertext' ~ '^[A-Za-z0-9_-]+$'
  AND length(value->>'ciphertext') % 4 <> 1, false)
$$;
REVOKE ALL ON FUNCTION crier_provider.envelope_valid(jsonb) FROM PUBLIC, anon, authenticated, service_role;

CREATE TABLE crier_provider.flows (
 flow_id text PRIMARY KEY CHECK (flow_id ~ '^[A-Za-z0-9_-]{43}$'),
 owner_id uuid NOT NULL,
 provider text NOT NULL CHECK (provider IN ('alpaca','discord')),
 purpose text NOT NULL CHECK (purpose IN ('alerts','trade') AND (provider<>'discord' OR purpose='alerts')),
 environment text NOT NULL CHECK (environment IN ('paper','live')),
 challenge text NOT NULL CHECK (challenge ~ '^[0-9a-f]{64}$'),
 stage text NOT NULL CHECK (stage IN ('pending','launched','exchanging','ready','redeemed','cancelled','failed','expired')),
 created_at bigint NOT NULL,
 expires_at bigint NOT NULL CHECK (expires_at=created_at+300000),
 ready_until bigint CHECK (ready_until<=expires_at AND ready_until>=created_at),
 ticket_hash text UNIQUE CHECK (ticket_hash ~ '^[0-9a-f]{64}$'),
 state_hash text UNIQUE CHECK (state_hash ~ '^[0-9a-f]{64}$'),
 binding_hash text CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
 state_ciphertext jsonb CHECK (state_ciphertext IS NULL OR crier_provider.envelope_valid(state_ciphertext)),
 grant_ciphertext jsonb CHECK (grant_ciphertext IS NULL OR crier_provider.envelope_valid(grant_ciphertext)),
 CHECK (stage NOT IN ('redeemed','cancelled','failed','expired') OR
  (ticket_hash IS NULL AND state_hash IS NULL AND binding_hash IS NULL AND state_ciphertext IS NULL AND grant_ciphertext IS NULL))
);
CREATE INDEX flows_owner_active ON crier_provider.flows(owner_id,challenge,expires_at)
 WHERE stage IN ('pending','launched','exchanging','ready');
CREATE INDEX flows_expiry ON crier_provider.flows(expires_at);
ALTER TABLE crier_provider.flows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON crier_provider.flows FROM PUBLIC, anon, authenticated, service_role;

CREATE TABLE crier_provider.csrf_used (
 hash text PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{64}$'),
 expires_at bigint NOT NULL,
 retain_until bigint NOT NULL CHECK (retain_until>=expires_at)
);
CREATE INDEX csrf_used_expiry ON crier_provider.csrf_used(retain_until);
ALTER TABLE crier_provider.csrf_used ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON crier_provider.csrf_used FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION public.crier_oauth_flow(p_action text,p_owner uuid,p_flow text,p_input jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
 f crier_provider.flows%ROWTYPE;
 prior jsonb;
 now_ms bigint;
 keys text[];
 n integer;
 deadline bigint;
 csrf_count integer;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed'
   OR p_action IS NULL OR p_input IS NULL OR jsonb_typeof(p_input)<>'object'
   OR octet_length(p_input::text)>92000 THEN RETURN '{"ok":false}'; END IF;
 keys:=CASE p_action
  WHEN 'begin' THEN ARRAY['provider','purpose','environment','challenge','ticket_hash','state_hash','state_ciphertext']
  WHEN 'launch' THEN ARRAY['ticket_hash','binding_hash']
  WHEN 'claim' THEN ARRAY['provider','state_hash','binding_hash']
  WHEN 'complete' THEN ARRAY['grant_ciphertext']
  WHEN 'redeem' THEN ARRAY['proof_hash']
  WHEN 'cancel' THEN ARRAY['proof_hash']
  WHEN 'cleanup' THEN ARRAY['limit']
  WHEN 'csrf_claim' THEN ARRAY['hash','expires_at']
  WHEN 'status' THEN ARRAY[]::text[]
  WHEN 'fail' THEN ARRAY[]::text[] END;
 IF keys IS NULL OR NOT (p_input ?& keys) OR (p_input-keys)<>'{}'::jsonb THEN RETURN '{"ok":false}'; END IF;
 -- All non-envelope scalar inputs have exact JSON string types.
 IF EXISTS (SELECT 1 FROM jsonb_each(p_input) e WHERE e.key NOT IN ('state_ciphertext','grant_ciphertext','limit','expires_at') AND jsonb_typeof(e.value)<>'string') THEN RETURN '{"ok":false}'; END IF;
 IF p_action='csrf_claim' THEN
  IF p_owner IS NOT NULL OR p_flow IS NOT NULL OR NOT coalesce(p_input->>'hash' ~ '^[0-9a-f]{64}$',false)
   OR jsonb_typeof(p_input->'expires_at')<>'number' OR p_input->>'expires_at' !~ '^[0-9]{1,16}$' THEN RETURN '{"ok":false}'; END IF;
  -- Serialize equal hashes before sampling time, including a concurrent replay.
  PERFORM pg_advisory_xact_lock(hashtextextended('crier-provider-csrf:'||(p_input->>'hash'),0));
  now_ms:=floor(extract(epoch FROM clock_timestamp())*1000)::bigint;
  deadline:=(p_input->>'expires_at')::bigint;
  IF deadline<=now_ms OR deadline>now_ms+360000 THEN RETURN '{"ok":false}'; END IF;
  INSERT INTO crier_provider.csrf_used(hash,expires_at,retain_until) VALUES(p_input->>'hash',least(deadline,now_ms+300000),deadline) ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS n=ROW_COUNT;
  RETURN jsonb_build_object('ok',true,'claimed',n=1);
 END IF;
 IF p_action='cleanup' THEN
  IF p_owner IS NOT NULL OR p_flow IS NOT NULL OR jsonb_typeof(p_input->'limit')<>'number'
   OR p_input->>'limit' !~ '^[0-9]{1,4}$' THEN RETURN '{"ok":false}'; END IF;
  n:=(p_input->>'limit')::integer;
  IF n<1 OR n>1000 THEN RETURN '{"ok":false}'; END IF;
  -- SKIP LOCKED avoids interfering with an in-flight handoff.
  WITH doomed AS (SELECT flow_id FROM crier_provider.flows
    WHERE expires_at<=floor(extract(epoch FROM clock_timestamp())*1000)::bigint
    ORDER BY expires_at,flow_id LIMIT n FOR UPDATE SKIP LOCKED)
  DELETE FROM crier_provider.flows target USING doomed d WHERE target.flow_id=d.flow_id;
  GET DIAGNOSTICS n=ROW_COUNT;
  WITH doomed AS (SELECT hash FROM crier_provider.csrf_used
    WHERE retain_until<=floor(extract(epoch FROM clock_timestamp())*1000)::bigint
    ORDER BY retain_until,hash LIMIT (p_input->>'limit')::integer FOR UPDATE SKIP LOCKED)
  DELETE FROM crier_provider.csrf_used target USING doomed d WHERE target.hash=d.hash;
  GET DIAGNOSTICS csrf_count=ROW_COUNT;
  RETURN jsonb_build_object('ok',true,'count',n,'csrf_count',csrf_count);
 END IF;
 IF p_owner IS NULL OR (p_flow IS NOT NULL AND p_flow !~ '^[A-Za-z0-9_-]{43}$') THEN RETURN '{"ok":false}'; END IF;
 IF p_action='begin' THEN
  IF p_flow IS NULL OR NOT coalesce(p_input->>'provider' IN ('alpaca','discord')
   AND p_input->>'purpose' IN ('alerts','trade')
   AND (p_input->>'provider'<>'discord' OR p_input->>'purpose'='alerts')
   AND p_input->>'environment' IN ('paper','live')
   AND p_input->>'challenge' ~ '^[0-9a-f]{64}$'
   AND p_input->>'ticket_hash' ~ '^[0-9a-f]{64}$'
   AND p_input->>'state_hash' ~ '^[0-9a-f]{64}$'
   AND crier_provider.envelope_valid(p_input->'state_ciphertext'),false) THEN RETURN '{"ok":false}'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('crier-provider:'||p_owner::text,0));
  now_ms:=floor(extract(epoch FROM clock_timestamp())*1000)::bigint;
  IF (SELECT count(*) FROM crier_provider.flows WHERE owner_id=p_owner
    AND stage IN ('pending','launched','exchanging','ready') AND expires_at>now_ms
    AND (ready_until IS NULL OR ready_until>now_ms))>=8
   OR (SELECT count(*) FROM crier_provider.flows WHERE owner_id=p_owner AND challenge=p_input->>'challenge'
    AND stage IN ('pending','launched','exchanging','ready') AND expires_at>now_ms
    AND (ready_until IS NULL OR ready_until>now_ms))>=4 THEN RETURN '{"ok":false}'; END IF;
  -- Only insertion has an exception subtransaction. Expiry scrubbing below must
  -- survive semantic rejection; never wrap the complete function in EXCEPTION.
  BEGIN
   INSERT INTO crier_provider.flows(flow_id,owner_id,provider,purpose,environment,challenge,stage,created_at,expires_at,ticket_hash,state_hash,state_ciphertext)
   VALUES(p_flow,p_owner,p_input->>'provider',p_input->>'purpose',p_input->>'environment',p_input->>'challenge','pending',now_ms,now_ms+300000,p_input->>'ticket_hash',p_input->>'state_hash',p_input->'state_ciphertext') RETURNING * INTO f;
  EXCEPTION WHEN unique_violation THEN RETURN '{"ok":false}'; END;
  RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f));
 END IF;
 IF p_action='launch' THEN
  IF NOT coalesce(p_input->>'ticket_hash' ~ '^[0-9a-f]{64}$' AND p_input->>'binding_hash' ~ '^[0-9a-f]{64}$',false) THEN RETURN '{"ok":false}'; END IF;
  SELECT * INTO f FROM crier_provider.flows WHERE owner_id=p_owner AND ticket_hash=p_input->>'ticket_hash'
   AND (p_flow IS NULL OR flow_id=p_flow) FOR UPDATE;
 ELSIF p_action='claim' THEN
  IF NOT coalesce(p_input->>'provider' IN ('alpaca','discord') AND p_input->>'state_hash' ~ '^[0-9a-f]{64}$' AND p_input->>'binding_hash' ~ '^[0-9a-f]{64}$',false) THEN RETURN '{"ok":false}'; END IF;
  SELECT * INTO f FROM crier_provider.flows WHERE owner_id=p_owner AND state_hash=p_input->>'state_hash'
   AND (p_flow IS NULL OR flow_id=p_flow) FOR UPDATE;
 ELSE
  IF p_flow IS NULL THEN RETURN '{"ok":false}'; END IF;
  SELECT * INTO f FROM crier_provider.flows WHERE owner_id=p_owner AND flow_id=p_flow FOR UPDATE;
 END IF;
 IF NOT FOUND THEN RETURN '{"ok":false}'; END IF;
 -- Clock sampled AFTER the row lock; lock wait never extends a deadline.
 now_ms:=floor(extract(epoch FROM clock_timestamp())*1000)::bigint;
 IF f.expires_at<=now_ms OR (f.stage='ready' AND f.ready_until<=now_ms) THEN
  IF f.stage IN ('pending','launched','exchanging','ready') THEN
   UPDATE crier_provider.flows SET stage='expired',ticket_hash=NULL,state_hash=NULL,binding_hash=NULL,state_ciphertext=NULL,grant_ciphertext=NULL WHERE flow_id=f.flow_id RETURNING * INTO f;
  END IF;
  IF p_action='status' THEN RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f)); END IF;
  RETURN '{"ok":false}';
 END IF;
 CASE p_action
 WHEN 'status' THEN RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f));
 WHEN 'launch' THEN
  IF f.stage<>'pending' THEN RETURN '{"ok":false}'; END IF;
  prior:=f.state_ciphertext;
  UPDATE crier_provider.flows SET stage='launched',ticket_hash=NULL,state_ciphertext=NULL,binding_hash=p_input->>'binding_hash' WHERE flow_id=f.flow_id RETURNING * INTO f;
  RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f)||jsonb_build_object('state_ciphertext',prior));
 WHEN 'claim' THEN
  IF f.stage<>'launched' OR f.provider<>p_input->>'provider' OR f.binding_hash IS DISTINCT FROM p_input->>'binding_hash' THEN RETURN '{"ok":false}'; END IF;
  UPDATE crier_provider.flows SET stage='exchanging',state_hash=NULL,binding_hash=NULL WHERE flow_id=f.flow_id RETURNING * INTO f;
 WHEN 'complete' THEN
  IF f.stage<>'exchanging' OR NOT crier_provider.envelope_valid(p_input->'grant_ciphertext') THEN RETURN '{"ok":false}'; END IF;
  UPDATE crier_provider.flows SET stage='ready',ready_until=least(expires_at,now_ms+60000),grant_ciphertext=p_input->'grant_ciphertext' WHERE flow_id=f.flow_id RETURNING * INTO f;
 WHEN 'redeem' THEN
  IF f.stage<>'ready' OR f.challenge IS DISTINCT FROM p_input->>'proof_hash' THEN RETURN '{"ok":false}'; END IF;
  prior:=f.grant_ciphertext;
  UPDATE crier_provider.flows SET stage='redeemed',grant_ciphertext=NULL,ticket_hash=NULL,state_hash=NULL,binding_hash=NULL,state_ciphertext=NULL WHERE flow_id=f.flow_id RETURNING * INTO f;
  RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f)||jsonb_build_object('grant_ciphertext',prior));
 WHEN 'cancel' THEN
  IF f.challenge IS DISTINCT FROM p_input->>'proof_hash' THEN RETURN '{"ok":false}'; END IF;
  IF f.stage IN ('pending','launched','exchanging','ready') THEN
   UPDATE crier_provider.flows SET stage='cancelled',grant_ciphertext=NULL,ticket_hash=NULL,state_hash=NULL,binding_hash=NULL,state_ciphertext=NULL WHERE flow_id=f.flow_id RETURNING * INTO f;
  END IF;
 WHEN 'fail' THEN
  IF f.stage<>'exchanging' THEN RETURN '{"ok":false}'; END IF;
  UPDATE crier_provider.flows SET stage='failed',grant_ciphertext=NULL,ticket_hash=NULL,state_hash=NULL,binding_hash=NULL,state_ciphertext=NULL WHERE flow_id=f.flow_id RETURNING * INTO f;
 ELSE RETURN '{"ok":false}';
 END CASE;
 RETURN jsonb_build_object('ok',true,'flow',to_jsonb(f));
END $$;
REVOKE ALL ON FUNCTION public.crier_oauth_flow(text,uuid,text,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.crier_oauth_flow(text,uuid,text,jsonb) TO service_role;
COMMIT;




