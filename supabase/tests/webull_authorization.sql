-- Candidate compound authorization contract; synthetic fixtures, rolled back.
BEGIN;
DO $$
DECLARE r record; rejected boolean; bad text; role_name text; fn text;
  op uuid:='00000000-0000-4000-8000-000000000001';
  op2 uuid:='00000000-0000-4000-8000-000000000002';
  cb text:='https://example.test/callback';
  e jsonb:=jsonb_build_object('schema','crier.webull-token.v1','key_id','test','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
BEGIN
  ASSERT to_regprocedure('public.crier_webull_authorization_begin(text,text,bigint,uuid,text,text,text)') IS NOT NULL,'Atomic authorization begin RPC required';
  SELECT * INTO r FROM public.crier_webull_authorization_begin('auth-test','sandbox',0,op,repeat('a',64),repeat('b',64),cb);
  ASSERT r.generation=1 AND r.operation_id=op AND r.expires_at>clock_timestamp() AND r.expires_at<=clock_timestamp()+interval '300 seconds';
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('other','sandbox',repeat('a',64),repeat('b',64),cb));
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','production',repeat('a',64),repeat('b',64),cb));
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('a',64),repeat('c',64),cb));
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('a',64),repeat('b',64),'https://other.test/callback'));
  -- Failed CAS must preserve even expired state; mutation starts only after reserve.
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_begin('auth-test','sandbox',0,op2,repeat('c',64),repeat('b',64),cb));
  ASSERT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('a',64));
  SELECT * INTO r FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('a',64),repeat('b',64),cb);
  ASSERT r.generation=1 AND r.operation_id=op;
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('a',64),repeat('b',64),cb));
  ASSERT NOT EXISTS(SELECT FROM crier_webull_private.authorization_reservations WHERE state_hash=repeat('a',64)),'Consume cascades private association';
  ASSERT public.crier_webull_token_commit('auth-test','sandbox',1,op,e);
  PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',1,op2,repeat('c',64),repeat('b',64),cb);
  PERFORM public.crier_webull_authorization_begin('auth-test','production',0,op,repeat('d',64),repeat('b',64),cb);
  PERFORM public.crier_webull_authorization_begin('auth-other','sandbox',0,op,repeat('e',64),repeat('b',64),cb);
  -- A globally duplicate digest rolls back both reservation and supersession.
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',2,op,repeat('e',64),repeat('b',64),cb);
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull authorization operation'; END;
  ASSERT rejected;
  ASSERT (SELECT generation FROM public.crier_webull_token_read('auth-test','sandbox'))=2;
  ASSERT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('c',64));
  -- Duplicate of this very scope must also fail before its old session is erased.
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',2,op,repeat('c',64),repeat('b',64),cb);
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected;
  PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',2,op,repeat('f',64),repeat('b',64),cb);
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('c',64),repeat('b',64),cb));
  ASSERT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('f',64));
  ASSERT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','production',repeat('d',64),repeat('b',64),cb));
  -- Lower-level reservation changes cannot let an old linked callback authorize it.
  ASSERT public.crier_webull_token_reserve('auth-test','sandbox',3,op2)=4;
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('f',64),repeat('b',64),cb));
  PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',4,op,repeat('1',64),repeat('b',64),cb);
  UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval '301 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE state_hash=repeat('1',64);
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_begin('auth-test','sandbox',4,op2,repeat('2',64),repeat('b',64),cb));
  ASSERT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('1',64));
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('1',64),repeat('b',64),cb));
  ASSERT NOT EXISTS(SELECT FROM crier_webull_private.authorization_reservations WHERE state_hash=repeat('1',64));
  PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',5,op2,repeat('2',64),repeat('b',64),cb);
  SELECT * INTO r FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('2',64),repeat('b',64),cb);
  ASSERT r.generation=6 AND r.operation_id=op2;
  ASSERT public.crier_webull_authorization_revoke('auth-test','sandbox')=7;
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',repeat('2',64),repeat('b',64),cb));
  ASSERT NOT public.crier_webull_token_commit('auth-test','sandbox',6,op2,e);
  ASSERT (SELECT state='revoked' AND envelope IS NULL FROM public.crier_webull_token_read('auth-test','sandbox'));
  ASSERT public.crier_webull_authorization_revoke('auth-new','sandbox')=1;
  -- Existing low-level sessions in the other environment can exhaust owner
  -- quota. Creation failure must roll back the newly reserved token generation.
  FOR r IN SELECT i FROM generate_series(1,5) t(i) LOOP
    PERFORM public.crier_webull_session_create('auth-quota',lpad(r.i::text,64,'0'),repeat('b',64),'production',cb);
  END LOOP;
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_begin('auth-quota','sandbox',0,op,repeat('3',64),repeat('b',64),cb);
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull authorization operation'; END;
  ASSERT rejected;
  ASSERT NOT EXISTS(SELECT FROM public.crier_webull_token_read('auth-quota','sandbox'));
  ASSERT (SELECT count(*) FROM crier_webull_private.authorization_sessions WHERE owner_ref='auth-quota')=5;
  FOREACH bad IN ARRAY ARRAY['',NULL,repeat('A',64),repeat('a',63)] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_authorization_begin('auth-test','sandbox',7,op,bad,repeat('b',64),cb);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid Webull authorization operation'; END;
    ASSERT rejected;
    ASSERT NOT EXISTS(SELECT FROM public.crier_webull_authorization_consume('auth-test','sandbox',bad,repeat('b',64),cb));
  END LOOP;
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.authorization_reservations','SELECT,INSERT,UPDATE,DELETE');
    ASSERT NOT has_function_privilege(role_name,'crier_webull_private.authorization_lock(text,text)','EXECUTE');
    FOREACH fn IN ARRAY ARRAY['begin(text,text,bigint,uuid,text,text,text)','consume(text,text,text,text,text)','revoke(text,text)'] LOOP
      ASSERT has_function_privilege(role_name,'public.crier_webull_authorization_'||fn,'EXECUTE')=(role_name='service_role');
    END LOOP;
  END LOOP;
  FOR r IN SELECT p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'crier_webull_authorization_%' LOOP
    ASSERT r.prosecdef AND r.proconfig=ARRAY['search_path=pg_catalog'];
  END LOOP;
END $$;
SET LOCAL ROLE service_role;
DO $$ BEGIN
  ASSERT EXISTS(SELECT FROM public.crier_webull_authorization_begin('service-auth','sandbox',0,'00000000-0000-4000-8000-000000000001',repeat('9',64),repeat('b',64),'https://example.test/callback'));
  ASSERT EXISTS(SELECT FROM public.crier_webull_authorization_consume('service-auth','sandbox',repeat('9',64),repeat('b',64),'https://example.test/callback'));
  ASSERT public.crier_webull_authorization_revoke('service-auth','sandbox')=2;
  BEGIN PERFORM 1 FROM crier_webull_private.authorization_reservations; RAISE EXCEPTION 'Direct access allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN
  BEGIN PERFORM public.crier_webull_authorization_revoke('denied','sandbox'); RAISE EXCEPTION 'Anon RPC allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $$ DECLARE rejected boolean; BEGIN
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_begin('isolation-auth','sandbox',0,'00000000-0000-4000-8000-000000000001',repeat('a',64),repeat('b',64),'https://example.test/callback'); EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected;
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_consume('isolation-auth','sandbox',repeat('a',64),repeat('b',64),'https://example.test/callback'); EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected;
  rejected:=false;
  BEGIN PERFORM public.crier_webull_authorization_revoke('isolation-auth','sandbox'); EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected;
END $$;
ROLLBACK;
