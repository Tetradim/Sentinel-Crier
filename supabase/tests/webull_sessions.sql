-- Isolated, rolled-back fixtures; execute as the SQL installation owner.
BEGIN;
DO $$
DECLARE r record; bad text; i integer; rejected boolean;
BEGIN
  ASSERT to_regprocedure('public.crier_webull_session_create(text,text,text,text,text)') IS NOT NULL,
    'Pending authorization session RPC is required';
  SELECT * INTO r FROM public.crier_webull_session_create('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT r.expires_at-r.created_at=interval '300 seconds';
  ASSERT NOT public.crier_webull_session_consume('other-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('c',64),'sandbox','https://example.test/callback');
  ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),'production','https://example.test/callback');
  ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://other.test/callback');
  ASSERT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  rejected:=false;
  BEGIN
    PERFORM public.crier_webull_session_create('other-owner',repeat('a',64),repeat('c',64),'production','https://other.test/callback');
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid authorization session'; END;
  ASSERT rejected,'Duplicate state must never replace a valid row';
  ASSERT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  -- Every malformed callback gets the same non-reflective error.
  FOREACH bad IN ARRAY ARRAY['http://example.test/cb','https://user@example.test/cb','https://example.test/cb?x=1','https://example.test/cb#x','https://example.test/ cb',E'https://example.test/\\cb','https:///cb','https://'] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('a',64),repeat('b',64),'sandbox',bad);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid authorization session'; END;
    ASSERT rejected,'Malformed callback accepted';
  END LOOP;
  FOREACH bad IN ARRAY ARRAY['',repeat('x',64),repeat('a',63),repeat('A',64),NULL] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_create('sessions-test-owner',bad,repeat('b',64),'sandbox','https://example.test/callback');
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
    ASSERT rejected,'Malformed state digest accepted';
    ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',bad,repeat('b',64),'sandbox','https://example.test/callback');
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('a',64),bad,'sandbox','https://example.test/callback');
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
    ASSERT rejected,'Malformed binding digest accepted';
  END LOOP;
  FOREACH bad IN ARRAY ARRAY['',repeat('x',201),'   ',E'owner\n',NULL] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_create(bad,repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid authorization session'; END;
    ASSERT rejected,'Malformed owner accepted';
  END LOOP;
  FOREACH bad IN ARRAY ARRAY['','paper','live','prod','Sandbox',NULL] LOOP
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('a',64),repeat('b',64),bad,'https://example.test/callback');
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
    ASSERT rejected,'Malformed environment accepted';
    ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',repeat('a',64),repeat('b',64),bad,'https://example.test/callback');
    rejected:=false;
    BEGIN PERFORM public.crier_webull_session_revoke('sessions-test-owner',bad);
    EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
    ASSERT rejected,'Malformed revoke environment accepted';
  END LOOP;
  FOR i IN 1..5 LOOP
    PERFORM public.crier_webull_session_create('sessions-test-owner',lpad(i::text,64,'0'),repeat('b',64),CASE WHEN i%2=0 THEN 'production' ELSE 'sandbox' END,'https://example.test/callback');
  END LOOP;
  rejected:=false;
  BEGIN PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('f',64),repeat('b',64),'production','https://example.test/callback');
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; END;
  ASSERT rejected,'Quota must include both environments';
  PERFORM public.crier_webull_session_create('other-owner',repeat('f',64),repeat('b',64),'production','https://example.test/callback');
  UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval '301 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE state_hash=lpad('1',64,'0');
  ASSERT NOT public.crier_webull_session_consume('sessions-test-owner',lpad('1',64,'0'),repeat('b',64),'sandbox','https://example.test/callback');
  PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('e',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT NOT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=lpad('1',64,'0'));
  ASSERT public.crier_webull_session_revoke('sessions-test-owner','production')=2;
  ASSERT public.crier_webull_session_revoke('sessions-test-owner','production')=0;
  ASSERT (SELECT count(*) FROM crier_webull_private.authorization_sessions WHERE owner_ref='sessions-test-owner')=3;
  ASSERT public.crier_webull_session_consume('other-owner',repeat('f',64),repeat('b',64),'production','https://example.test/callback');
  -- Pruning on create frees an expired slot even without a consume attempt.
  UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval '301 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE state_hash=repeat('e',64);
  PERFORM public.crier_webull_session_create('sessions-test-owner',repeat('f',64),repeat('b',64),'sandbox','https://example.test/callback');
  ASSERT NOT EXISTS(SELECT FROM crier_webull_private.authorization_sessions WHERE state_hash=repeat('e',64));
  ASSERT (SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='crier_webull_private' AND table_name='authorization_sessions') = ARRAY['owner_ref','state_hash','binding_hash','environment','callback','created_at','expires_at'], 'Store must have no raw state or token columns';
END $$;
DO $$
DECLARE role_name text; fn text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    ASSERT NOT has_schema_privilege(role_name,'crier_webull_private','USAGE');
    ASSERT NOT has_table_privilege(role_name,'crier_webull_private.authorization_sessions','SELECT,INSERT,UPDATE,DELETE');
    FOREACH fn IN ARRAY ARRAY['public.crier_webull_session_create(text,text,text,text,text)','public.crier_webull_session_consume(text,text,text,text,text)','public.crier_webull_session_revoke(text,text)'] LOOP
      ASSERT has_function_privilege(role_name,fn,'EXECUTE')=(role_name='service_role');
    END LOOP;
  END LOOP;
END $$;
SET LOCAL ROLE service_role;
SELECT * FROM public.crier_webull_session_create('service-owner',repeat('d',64),repeat('b',64),'production','https://example.test/callback');
DO $$ BEGIN
  ASSERT public.crier_webull_session_consume('service-owner',repeat('d',64),repeat('b',64),'production','https://example.test/callback');
  BEGIN PERFORM 1 FROM crier_webull_private.authorization_sessions; RAISE EXCEPTION 'Direct access allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN
  BEGIN PERFORM public.crier_webull_session_revoke('service-owner','production'); RAISE EXCEPTION 'Anon RPC allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE authenticated;
DO $$ BEGIN
  BEGIN PERFORM public.crier_webull_session_revoke('service-owner','production'); RAISE EXCEPTION 'Authenticated RPC allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $$
DECLARE rejected boolean := false;
BEGIN
  BEGIN PERFORM public.crier_webull_session_revoke('isolation-owner','sandbox');
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid authorization session'; END;
  ASSERT rejected,'Revoke must reject stale-snapshot transaction isolation';
END $$;
ROLLBACK;
-- Count-based quotas require a fresh snapshot after the advisory lock wait.
BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $$
DECLARE rejected boolean := false;
BEGIN
  BEGIN PERFORM public.crier_webull_session_create('isolation-owner',repeat('a',64),repeat('b',64),'sandbox','https://example.test/callback');
  EXCEPTION WHEN SQLSTATE '22023' THEN rejected:=true; ASSERT SQLERRM='Invalid authorization session'; END;
  ASSERT rejected,'Create must reject stale-snapshot transaction isolation';
END $$;
ROLLBACK;
