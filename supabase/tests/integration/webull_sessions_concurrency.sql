-- REAL PostgreSQL only, isolated owner database, after session_store.sql.
-- SELECT set_config('crier.test_dsn','<isolated owner connection>',false);
-- dblink sessions need committed fixtures. All fixtures are removed on success;
-- the test database should be discarded after any failure.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
DO $$
DECLARE a boolean; b boolean; n integer; q text; i integer; fixture_owner text := 'webull-concurrency-fixture';
BEGIN
  IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN
    RAISE EXCEPTION 'Set crier.test_dsn to an isolated owner test database';
  END IF;
  PERFORM extensions.dblink_connect('webull_a',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_connect('webull_b',current_setting('crier.test_dsn'));
  -- Create and commit remotely so both worker snapshots can see the fixture.
  PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''sandbox'',''https://example.test/callback'')',fixture_owner,repeat('a',64),repeat('b',64))) AS t(value integer);
  q:=format('SELECT public.crier_webull_session_consume(%L,%L,%L,''sandbox'',''https://example.test/callback'')',fixture_owner,repeat('a',64),repeat('b',64));
  PERFORM extensions.dblink_exec('webull_a','BEGIN');
  SELECT value INTO a FROM extensions.dblink('webull_a',q) AS t(value boolean);
  PERFORM extensions.dblink_send_query('webull_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('webull_b')=1,'Second consume must wait for first transaction';
  PERFORM extensions.dblink_exec('webull_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('webull_b') AS t(value boolean);
  ASSERT a AND NOT b,'Exactly one concurrent consume must succeed';
  PERFORM value FROM extensions.dblink_get_result('webull_b') AS t(value boolean);

  -- Lock an otherwise valid row, then force the consumer to wait past expiry.
  PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''sandbox'',''https://example.test/callback'')',fixture_owner,repeat('a',64),repeat('b',64))) AS t(value integer);
  PERFORM extensions.dblink_exec('webull_a','BEGIN');
  PERFORM extensions.dblink_exec('webull_a',format('UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval ''298 seconds'',expires_at=statement_timestamp()+interval ''2 seconds'' WHERE state_hash=%L',repeat('a',64)));
  PERFORM extensions.dblink_send_query('webull_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('webull_b')=1,'Expiry test consumer must wait on the row lock';
  PERFORM pg_sleep(2.1);
  PERFORM extensions.dblink_exec('webull_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('webull_b') AS t(value boolean);
  ASSERT NOT b,'Expiry must use wall time after obtaining the row lock';
  PERFORM value FROM extensions.dblink_get_result('webull_b') AS t(value boolean);

  FOR i IN 1..4 LOOP
    PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''sandbox'',''https://example.test/callback'')',fixture_owner,lpad(i::text,64,'0'),repeat('b',64))) AS t(value integer);
  END LOOP;
  PERFORM extensions.dblink_exec('webull_a','BEGIN');
  PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''production'',''https://example.test/callback'')',fixture_owner,lpad('5',64,'0'),repeat('b',64))) AS t(value integer);
  q:=format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''sandbox'',''https://example.test/callback'')',fixture_owner,lpad('6',64,'0'),repeat('b',64));
  PERFORM extensions.dblink_send_query('webull_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('webull_b')=1,'Concurrent create must wait for owner quota lock';
  PERFORM extensions.dblink_exec('webull_a','COMMIT');
  -- false suppresses the expected generic quota error from the remote worker.
  SELECT count(*) INTO n FROM extensions.dblink_get_result('webull_b',false) AS t(value integer);
  ASSERT n=0,'Sixth pending session must be rejected';
  PERFORM value FROM extensions.dblink_get_result('webull_b') AS t(value integer);
  SELECT value INTO n FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture_owner)) AS t(value integer);
  ASSERT n=5,'Concurrent creates must not exceed the cross-environment owner cap';
  PERFORM extensions.dblink_exec('webull_a',format('DELETE FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture_owner));

  -- A READ COMMITTED revoke waits for the same owner lock, then sees and
  -- removes the creation committed while it was waiting.
  PERFORM extensions.dblink_exec('webull_a','BEGIN');
  PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''production'',''https://example.test/callback'')',fixture_owner,repeat('c',64),repeat('b',64))) AS t(value integer);
  q:=format('SELECT public.crier_webull_session_revoke(%L,''production'')',fixture_owner);
  PERFORM extensions.dblink_send_query('webull_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('webull_b')=1,'Revoke must wait for the owner create lock';
  PERFORM extensions.dblink_exec('webull_a','COMMIT');
  SELECT value INTO n FROM extensions.dblink_get_result('webull_b') AS t(value integer);
  ASSERT n=1,'Waiting revoke must remove the newly committed creation';
  PERFORM value FROM extensions.dblink_get_result('webull_b') AS t(value integer);
  SELECT value INTO n FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture_owner)) AS t(value integer);
  ASSERT n=0,'Revoke must leave no pending fixture';

  -- A fixed snapshot predating a committed creation must fail explicitly.
  -- The remote DO block verifies both SQLSTATE and generic error text.
  PERFORM extensions.dblink_exec('webull_b','BEGIN ISOLATION LEVEL REPEATABLE READ');
  PERFORM value FROM extensions.dblink('webull_b',format('SELECT count(*)::integer FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture_owner)) AS t(value integer);
  PERFORM value FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM public.crier_webull_session_create(%L,%L,%L,''production'',''https://example.test/callback'')',fixture_owner,repeat('d',64),repeat('b',64))) AS t(value integer);
  PERFORM extensions.dblink_exec('webull_b',format($remote$
    DO $test$
    DECLARE rejected boolean := false;
    BEGIN
      BEGIN PERFORM public.crier_webull_session_revoke(%L,'production');
      EXCEPTION WHEN SQLSTATE '22023' THEN
        rejected:=true;
        ASSERT SQLERRM='Invalid authorization session';
      END;
      ASSERT rejected,'Repeatable read revoke must fail explicitly';
    END $test$;
  $remote$,fixture_owner));
  PERFORM extensions.dblink_exec('webull_b','ROLLBACK');
  SELECT value INTO n FROM extensions.dblink('webull_a',format('SELECT count(*)::integer FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture_owner)) AS t(value integer);
  ASSERT n=1,'Rejected stale-snapshot revoke must preserve the pending row';
  SELECT value INTO n FROM extensions.dblink('webull_a',q) AS t(value integer);
  ASSERT n=1,'Read committed cleanup revoke must remove the pending row';
  PERFORM extensions.dblink_disconnect('webull_a');
  PERFORM extensions.dblink_disconnect('webull_b');
EXCEPTION WHEN OTHERS THEN
  BEGIN PERFORM extensions.dblink_disconnect('webull_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM extensions.dblink_disconnect('webull_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
  RAISE;
END $$;
