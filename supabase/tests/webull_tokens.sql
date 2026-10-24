-- Isolated fixtures; all changes rolled back.
BEGIN;
DO $$
DECLARE e jsonb := jsonb_build_object('schema','crier.webull-token.v1','key_id','test-key','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
  r record; bad jsonb; rejected boolean; role_name text; fn text;
  op uuid := '00000000-0000-4000-8000-000000000001';
  op2 uuid := '00000000-0000-4000-8000-000000000002';
BEGIN
  ASSERT to_regprocedure('public.crier_webull_token_reserve(text,text,bigint,uuid)') IS NOT NULL,'Token reservation RPC required';
  ASSERT public.crier_webull_token_reserve('token-test','sandbox',0,op)=1;
  ASSERT public.crier_webull_token_reserve('token-test','sandbox',0,op2) IS NULL;
  ASSERT NOT public.crier_webull_token_commit('other','sandbox',1,op,e);
  ASSERT NOT public.crier_webull_token_commit('token-test','production',1,op,e);
  ASSERT NOT public.crier_webull_token_commit('token-test','sandbox',1,op2,e);
  FOR bad IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
    e||'{"access_token":"plaintext"}',e-'nonce',e||'{"schema":"wrong"}',
    e||'{"key_id":" "}',e||jsonb_build_object('key_id',repeat(chr(128512),101)),e||jsonb_build_object('key_id',chr(160)),e||jsonb_build_object('key_id',E'bad\n'),e||jsonb_build_object('key_id',repeat('a',201)),
    e||'{"nonce":"AAAAAAAAAAAAAAA="}',e||'{"ciphertext":"AAAAAAAAAAAAAAAAAAAAAB"}',
    e||jsonb_build_object('ciphertext',repeat('A',43714)),e||'{"identity_hash":"A"}',
    e||'{"access_expires_at_ms":"123"}',e||'{"access_expires_at_ms":1.5}',
    e||'{"access_expires_at_ms":0}',e||'{"refresh_expires_at_ms":8640000000000001}',
    e||'{"refresh_expires_at_ms":1}', '{}'::jsonb,'[]'::jsonb,'null'::jsonb
  )) LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_token_commit('token-test','sandbox',1,op,bad);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull token operation'; END;
    ASSERT rejected,'Malformed envelope accepted';
  END LOOP;
  ASSERT public.crier_webull_token_commit('token-test','sandbox',1,op,e);
  SELECT * INTO r FROM public.crier_webull_token_read('token-test','sandbox');
  ASSERT r.state='active' AND r.generation=1 AND r.envelope=e;
  SELECT * INTO r FROM public.crier_webull_token_claim_refresh('token-test','sandbox',1,op2);
  ASSERT r.prior_generation=1 AND r.new_generation=2 AND r.envelope=e;
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_token_claim_refresh('token-test','sandbox',1,op));
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_token_claim_refresh('token-test','sandbox',2,op));
  SELECT * INTO r FROM public.crier_webull_token_read('token-test','sandbox');
  ASSERT r.state='refresh_pending' AND r.generation=2 AND r.envelope IS NULL;
  -- No time-based lease or automatic refresh retry exists; only explicit auth can supersede.
  ASSERT NOT public.crier_webull_token_commit('token-test','sandbox',2,op2,e||jsonb_build_object('identity_hash',repeat('b',64))),'Refresh identity must remain bound';
  ASSERT NOT public.crier_webull_token_mark_unknown('token-test','sandbox',2,op);
  ASSERT public.crier_webull_token_mark_unknown('token-test','sandbox',2,op2);
  ASSERT NOT public.crier_webull_token_commit('token-test','sandbox',2,op2,e);
  ASSERT public.crier_webull_token_reserve('token-test','sandbox',2,op)=3;
  ASSERT public.crier_webull_token_revoke('token-test','sandbox')=4;
  ASSERT NOT public.crier_webull_token_commit('token-test','sandbox',3,op,e);
  ASSERT public.crier_webull_token_reserve('token-test','sandbox',0,op) IS NULL;
  ASSERT public.crier_webull_token_reserve('token-test','sandbox',4,op2)=5;
  ASSERT NOT public.crier_webull_token_commit('token-test','sandbox',3,op,e);
  ASSERT public.crier_webull_token_commit('token-test','sandbox',5,op2,e);
  ASSERT public.crier_webull_token_revoke('token-test','production')=1;
  ASSERT public.crier_webull_token_revoke('token-test','production')=2;
  SELECT * INTO r FROM public.crier_webull_token_read('token-test','production');
  ASSERT r.state='revoked' AND r.generation=2 AND r.envelope IS NULL;
  ASSERT public.crier_webull_token_reserve('token-test','production',2,op)=3;
  ASSERT public.crier_webull_token_reserve('token-test','production',3,op2)=4;
  ASSERT NOT public.crier_webull_token_commit('token-test','production',3,op,e);
  -- A successful refresh commits the next generation and cannot commit twice.
  ASSERT public.crier_webull_token_reserve('refresh-success','sandbox',0,op)=1;
  ASSERT public.crier_webull_token_commit('refresh-success','sandbox',1,op,e);
  SELECT * INTO r FROM public.crier_webull_token_claim_refresh('refresh-success','sandbox',1,op2);
  ASSERT r.prior_generation=1 AND r.new_generation=2;
  ASSERT public.crier_webull_token_commit('refresh-success','sandbox',2,op2,e);
  ASSERT NOT public.crier_webull_token_commit('refresh-success','sandbox',2,op2,e);
  SELECT * INTO r FROM public.crier_webull_token_read('refresh-success','sandbox');
  ASSERT r.state='active' AND r.generation=2 AND r.envelope=e;
  -- Expired commit is rejected after locking, without extending metadata.
  ASSERT NOT public.crier_webull_token_commit('token-test','production',4,op2,
    e||jsonb_build_object('access_expires_at_ms',1,'refresh_expires_at_ms',2));
  ASSERT public.crier_webull_token_mark_unknown('token-test','production',4,op2);
  ASSERT NOT public.crier_webull_token_mark_unknown('token-test','production',4,op2);
  FOR bad IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
    jsonb_build_array('', 'sandbox'), jsonb_build_array('   ','sandbox'),
    jsonb_build_array(repeat('x',201),'sandbox'),jsonb_build_array(repeat(chr(128512),101),'sandbox'),jsonb_build_array(chr(160),'sandbox'),jsonb_build_array(E'bad\n','sandbox'),
    jsonb_build_array('valid','prod'),jsonb_build_array(NULL,'sandbox'),jsonb_build_array('valid',NULL)
  )) LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_token_reserve(bad->>0,bad->>1,0,op);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
    ASSERT rejected,'Malformed scope accepted';
  END LOOP;
  -- Boundary generation exhaustion cannot wrap, erase or recycle the tombstone.
  UPDATE crier_webull_private.token_states SET generation=9007199254740991 WHERE owner_ref='token-test' AND environment='production';
  rejected:=false;
  BEGIN PERFORM public.crier_webull_token_revoke('token-test','production');
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected;
  ASSERT (SELECT generation FROM public.crier_webull_token_read('token-test','production'))=9007199254740991;
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    ASSERT NOT has_schema_privilege(role_name,'crier_webull_private','USAGE');
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.token_states','SELECT,INSERT,UPDATE,DELETE');
    FOREACH fn IN ARRAY ARRAY['reserve(text,text,bigint,uuid)','commit(text,text,bigint,uuid,jsonb)','claim_refresh(text,text,bigint,uuid)','read(text,text)','mark_unknown(text,text,bigint,uuid)','revoke(text,text)'] LOOP
      ASSERT has_function_privilege(role_name,'public.crier_webull_token_'||fn,'EXECUTE')=(role_name='service_role');
    END LOOP;
  END LOOP;
END $$;
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='public' AND p.proname LIKE 'crier_webull_token_%' LOOP
    ASSERT r.prosecdef AND r.proconfig=ARRAY['search_path=pg_catalog'];
  END LOOP;
END $$;
SET LOCAL ROLE anon;
DO $$ BEGIN
  BEGIN PERFORM public.crier_webull_token_revoke('denied','sandbox'); RAISE EXCEPTION 'Anon RPC allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE authenticated;
DO $$ BEGIN
  BEGIN PERFORM public.crier_webull_token_read('denied','sandbox'); RAISE EXCEPTION 'Authenticated RPC allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE service_role;
DO $$ BEGIN
  ASSERT public.crier_webull_token_revoke('service-token','sandbox')=1;
  BEGIN PERFORM 1 FROM crier_webull_private.token_states; RAISE EXCEPTION 'Direct access allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $$ DECLARE rejected boolean:=false; BEGIN
  BEGIN PERFORM public.crier_webull_token_revoke('isolation-token','sandbox'); EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected,'Fixed snapshots must fail';
END $$;
ROLLBACK;
