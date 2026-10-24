-- REAL PostgreSQL only; load session, token and authorization candidates first.
-- crier.test_dsn must name an isolated owner database. No broker calls.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
DO $$
DECLARE n bigint; a integer; b integer; ok boolean; q text; e jsonb;
  fixture text:='webull-authorization-concurrency-fixture';
  op uuid:='00000000-0000-4000-8000-000000000001';
  op2 uuid:='00000000-0000-4000-8000-000000000002';
  cb text:='https://example.test/callback';
BEGIN
  IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN RAISE EXCEPTION 'Set crier.test_dsn to an isolated owner test database'; END IF;
  PERFORM extensions.dblink_connect('auth_a',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_connect('auth_b',current_setting('crier.test_dsn'));
  e:=jsonb_build_object('schema','crier.webull-token.v1','key_id','test-key','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
  -- First begin wins its CAS; contender blocks then must observe generation 1.
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  q:=format('SELECT generation FROM public.crier_webull_authorization_begin(%L,''sandbox'',0,%L::uuid,%L,%L,%L)',fixture,op,repeat('7',64),repeat('b',64),cb);
  SELECT value INTO n FROM extensions.dblink('auth_a',q) AS t(value bigint);
  ASSERT n=1;
  q:=format('SELECT count(*)::integer FROM public.crier_webull_authorization_begin(%L,''sandbox'',0,%L::uuid,%L,%L,%L)',fixture,op2,repeat('8',64),repeat('b',64),cb);
  PERFORM extensions.dblink_send_query('auth_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Competing begins must serialize';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  ASSERT b=0,'Only one initial reservation wins';
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  -- A successful supersession blocks an old callback, which cannot consume it.
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  SELECT value INTO n FROM extensions.dblink('auth_a',format('SELECT generation FROM public.crier_webull_authorization_begin(%L,''sandbox'',1,%L::uuid,%L,%L,%L)',fixture,op2,repeat('8',64),repeat('b',64),cb)) AS t(value bigint);
  ASSERT n=2;
  q:=format('SELECT count(*)::integer FROM public.crier_webull_authorization_consume(%L,''sandbox'',%L,%L,%L)',fixture,repeat('7',64),repeat('b',64),cb);
  PERFORM extensions.dblink_send_query('auth_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Old callback must wait for supersession';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  ASSERT b=0,'Superseded callback cannot consume new flow';
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  -- Exactly one consumer receives the bound operation metadata.
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  q:=format('SELECT count(*)::integer FROM public.crier_webull_authorization_consume(%L,''sandbox'',%L,%L,%L) WHERE generation=2 AND operation_id=%L::uuid',fixture,repeat('8',64),repeat('b',64),cb,op2);
  SELECT value INTO a FROM extensions.dblink('auth_a',q) AS t(value integer);
  PERFORM extensions.dblink_send_query('auth_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Duplicate consume must wait';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  ASSERT a=1 AND b=0,'Exactly one callback wins';
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  -- Consume already returned metadata; revoke beats its delayed token result.
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  SELECT value INTO n FROM extensions.dblink('auth_a',format('SELECT public.crier_webull_authorization_revoke(%L,''sandbox'')',fixture)) AS t(value bigint);
  ASSERT n=3;
  PERFORM extensions.dblink_send_query('auth_b',format('SELECT public.crier_webull_token_commit(%L,''sandbox'',2,%L::uuid,%L::jsonb)',fixture,op2,e));
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Late commit must wait for revoke';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO ok FROM extensions.dblink_get_result('auth_b') AS t(value boolean);
  ASSERT NOT ok,'Revoked callback result cannot restore custody';
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value boolean);
  -- Revoke before callback removes both pending state and association atomically.
  SELECT value INTO n FROM extensions.dblink('auth_a',format('SELECT generation FROM public.crier_webull_authorization_begin(%L,''sandbox'',3,%L::uuid,%L,%L,%L)',fixture,op,repeat('9',64),repeat('b',64),cb)) AS t(value bigint);
  ASSERT n=4;
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  SELECT value INTO n FROM extensions.dblink('auth_a',format('SELECT public.crier_webull_authorization_revoke(%L,''sandbox'')',fixture)) AS t(value bigint);
  ASSERT n=5;
  q:=format('SELECT count(*)::integer FROM public.crier_webull_authorization_consume(%L,''sandbox'',%L,%L,%L)',fixture,repeat('9',64),repeat('b',64),cb);
  PERFORM extensions.dblink_send_query('auth_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Callback must wait for revoke';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  ASSERT b=0;
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  -- Consumer starts before expiry, but waits on owner lock past its deadline.
  SELECT value INTO n FROM extensions.dblink('auth_a',format('SELECT generation FROM public.crier_webull_authorization_begin(%L,''sandbox'',5,%L::uuid,%L,%L,%L)',fixture,op,repeat('6',64),repeat('b',64),cb)) AS t(value bigint);
  ASSERT n=6;
  PERFORM extensions.dblink_exec('auth_a',format('UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval ''299 seconds'',expires_at=statement_timestamp()+interval ''1 second'' WHERE owner_ref=%L',fixture));
  PERFORM extensions.dblink_exec('auth_a','BEGIN');
  PERFORM value FROM extensions.dblink('auth_a',format('SELECT pg_advisory_xact_lock(hashtextextended(%L,0))::text','crier-webull-session:'||fixture)) AS t(value text);
  q:=format('SELECT count(*)::integer FROM public.crier_webull_authorization_consume(%L,''sandbox'',%L,%L,%L)',fixture,repeat('6',64),repeat('b',64),cb);
  PERFORM extensions.dblink_send_query('auth_b',q);
  PERFORM pg_sleep(1.2);
  ASSERT extensions.dblink_is_busy('auth_b')=1,'Consumer waits past expiry';
  PERFORM extensions.dblink_exec('auth_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  ASSERT b=0,'Expiry must be checked after lock wait';
  PERFORM value FROM extensions.dblink_get_result('auth_b') AS t(value integer);
  SELECT value INTO b FROM extensions.dblink('auth_a',format('SELECT count(*)::integer FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture)) AS t(value integer);
  ASSERT b=0,'Expired session deleted with association cascade';
  -- Owner-only test cleanup; production RPCs retain generation tombstones.
  PERFORM extensions.dblink_exec('auth_a',format('DELETE FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture));
  PERFORM extensions.dblink_exec('auth_a',format('DELETE FROM crier_webull_private.token_states WHERE owner_ref=%L',fixture));
  PERFORM extensions.dblink_disconnect('auth_a');
  PERFORM extensions.dblink_disconnect('auth_b');
EXCEPTION WHEN OTHERS THEN
  BEGIN PERFORM extensions.dblink_disconnect('auth_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM extensions.dblink_disconnect('auth_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
  RAISE;
END $$;
