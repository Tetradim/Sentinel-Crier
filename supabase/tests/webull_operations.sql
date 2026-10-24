-- Synthetic encrypted-shape fixtures only; no cryptographic keys or broker calls.
BEGIN;
DO $$
DECLARE e jsonb:=jsonb_build_object('schema','crier.webull-token.v1','key_id','old-key','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
  rotated jsonb; bad jsonb; rejected boolean; r record; role_name text; fn text; bound integer;
  op uuid:='00000000-0000-4000-8000-000000000001';
BEGIN
  ASSERT to_regprocedure('public.crier_webull_token_rewrap(text,text,bigint,jsonb,jsonb)') IS NOT NULL,'Token rewrap RPC required';
  ASSERT to_regprocedure('public.crier_webull_cleanup_expired_sessions(integer)') IS NOT NULL,'Cleanup RPC required';
  rotated:=e||jsonb_build_object('key_id','new-key','nonce',repeat('B',16),'ciphertext',repeat('B',21)||'A');
  ASSERT public.crier_webull_token_reserve('operations','sandbox',0,op)=1;
  ASSERT public.crier_webull_token_commit('operations','sandbox',1,op,e);
  ASSERT NOT public.crier_webull_token_rewrap('operations','production',1,e,rotated);
  ASSERT NOT public.crier_webull_token_rewrap('operations','sandbox',2,e,rotated);
  ASSERT NOT public.crier_webull_token_rewrap('operations','sandbox',1,rotated,e);
  FOR bad IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
    rotated-'nonce',rotated||'{"schema":"wrong"}',rotated||jsonb_build_object('identity_hash',repeat('b',64)),
    rotated||jsonb_build_object('access_expires_at_ms',(e->>'access_expires_at_ms')::numeric+1),
    rotated||jsonb_build_object('access_expires_at_ms',(e->>'access_expires_at_ms')::numeric-1),
    rotated||jsonb_build_object('refresh_expires_at_ms',(e->>'refresh_expires_at_ms')::numeric+1),
    rotated||jsonb_build_object('refresh_expires_at_ms',(e->>'refresh_expires_at_ms')::numeric-1),NULL::jsonb
  )) LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_token_rewrap('operations','sandbox',1,e,bad);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull token operation'; END;
    ASSERT rejected,'Rewrap must reject malformed envelopes and metadata changes';
  END LOOP;
  ASSERT public.crier_webull_token_rewrap('operations','sandbox',1,e,rotated);
  ASSERT NOT public.crier_webull_token_rewrap('operations','sandbox',1,e,e),'Old envelope CAS must lose after rotation';
  SELECT * INTO r FROM public.crier_webull_token_read('operations','sandbox');
  ASSERT r.generation=1 AND r.state='active' AND r.envelope=rotated,'Rewrap preserves generation and lifetime';
  -- Access expiry does not destroy a still-refreshable token's custody.
  e:=e||jsonb_build_object('access_expires_at_ms',1);
  UPDATE crier_webull_private.token_states SET envelope=e WHERE owner_ref='operations';
  rotated:=e||jsonb_build_object('key_id','another-key');
  ASSERT public.crier_webull_token_rewrap('operations','sandbox',1,e,rotated);
  ASSERT EXISTS(SELECT FROM public.crier_webull_token_claim_refresh('operations','sandbox',1,op));
  ASSERT NOT public.crier_webull_token_rewrap('operations','sandbox',1,rotated,e);
  ASSERT public.crier_webull_token_revoke('operations','sandbox')=3;
  ASSERT NOT public.crier_webull_token_rewrap('operations','sandbox',3,rotated,e);
  -- An expired refresh token cannot be rewrapped even with an exact CAS.
  e:=e||jsonb_build_object('refresh_expires_at_ms',2);
  INSERT INTO crier_webull_private.token_states VALUES('expired-operation','sandbox',1,'active',NULL,e,e->>'identity_hash');
  ASSERT NOT public.crier_webull_token_rewrap('expired-operation','sandbox',1,e,e||'{"key_id":"new"}');
  FOREACH bound IN ARRAY ARRAY[NULL::integer,0,-1,501] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_cleanup_expired_sessions(bound);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull cleanup operation'; END;
    ASSERT rejected,'Cleanup bounds required';
  END LOOP;
  INSERT INTO crier_webull_private.authorization_sessions
    SELECT 'cleanup',repeat(i::text,64),repeat('b',64),'sandbox','https://example.test/callback',statement_timestamp()-interval '301 seconds',statement_timestamp()-interval '1 second' FROM generate_series(1,3) i;
  INSERT INTO crier_webull_private.authorization_reservations SELECT state_hash,1,op FROM crier_webull_private.authorization_sessions WHERE owner_ref='cleanup';
  PERFORM public.crier_webull_session_create('cleanup-active',repeat('4',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT public.crier_webull_cleanup_expired_sessions(1)=1;
  ASSERT NOT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('1',64)),'Expiry ties ordered by digest';
  ASSERT (SELECT count(*) FROM crier_webull_private.authorization_reservations)=2,'Association cascades';
  ASSERT public.crier_webull_cleanup_expired_sessions(500)=2;
  ASSERT public.crier_webull_cleanup_expired_sessions(500)=0;
  ASSERT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE owner_ref='cleanup-active');
  ASSERT EXISTS(SELECT FROM crier_webull_private.token_states WHERE owner_ref='operations' AND state='revoked' AND generation=3),'Cleanup retains tombstones';
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    ASSERT NOT has_schema_privilege(role_name,'crier_webull_private','USAGE');
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.authorization_sessions','SELECT,INSERT,UPDATE,DELETE');
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.authorization_reservations','SELECT,INSERT,UPDATE,DELETE');
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.token_states','SELECT,INSERT,UPDATE,DELETE');
    FOREACH fn IN ARRAY ARRAY['crier_webull_token_rewrap(text,text,bigint,jsonb,jsonb)','crier_webull_cleanup_expired_sessions(integer)'] LOOP
      ASSERT has_function_privilege(role_name,'public.'||fn,'EXECUTE')=(role_name='service_role');
      ASSERT NOT EXISTS(SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.oid=('public.'||fn)::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE');
    END LOOP;
  END LOOP;
  FOR r IN SELECT prosecdef,proconfig FROM pg_proc WHERE oid IN ('public.crier_webull_token_rewrap(text,text,bigint,jsonb,jsonb)'::regprocedure,'public.crier_webull_cleanup_expired_sessions(integer)'::regprocedure) LOOP
    ASSERT r.prosecdef AND r.proconfig=ARRAY['search_path=pg_catalog'];
  END LOOP;
END $$;
SET LOCAL ROLE service_role;
DO $$ BEGIN ASSERT public.crier_webull_cleanup_expired_sessions(1)=0; END $$;
RESET ROLE;
ROLLBACK;
BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $$ DECLARE rejected boolean:=false; BEGIN
  BEGIN PERFORM public.crier_webull_token_rewrap('isolation','sandbox',1,'{}','{}'); EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected,'Rewrap requires READ COMMITTED';
END $$;
ROLLBACK;
