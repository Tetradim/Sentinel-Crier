-- REAL PostgreSQL only; isolated owner database after both candidate stores.
-- Set crier.test_dsn to its owner connection. Committed fixtures cleaned on success.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
DO $$
DECLARE n bigint; a integer; b integer; ok boolean; q text; e jsonb;
  fixture text:='webull-token-concurrency-fixture';
  op uuid:='00000000-0000-4000-8000-000000000001';
  op2 uuid:='00000000-0000-4000-8000-000000000002';
BEGIN
  IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN RAISE EXCEPTION 'Set crier.test_dsn to an isolated owner test database'; END IF;
  PERFORM extensions.dblink_connect('tokens_a',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_connect('tokens_b',current_setting('crier.test_dsn'));
  e:=jsonb_build_object('schema','crier.webull-token.v1','key_id','test-key','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
  -- Concurrent first inserts: second waits, then observes CAS miss.
  PERFORM extensions.dblink_exec('tokens_a','BEGIN');
  q:=format('SELECT public.crier_webull_token_reserve(%L,''sandbox'',0,%L::uuid)',fixture,op);
  SELECT value INTO n FROM extensions.dblink('tokens_a',q) AS t(value bigint);
  ASSERT n=1;
  PERFORM extensions.dblink_send_query('tokens_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('tokens_b')=1,'First insert race must serialize';
  PERFORM extensions.dblink_exec('tokens_a','COMMIT');
  SELECT value INTO n FROM extensions.dblink_get_result('tokens_b') AS t(value bigint);
  ASSERT n IS NULL,'Only one initial CAS wins';
  PERFORM value FROM extensions.dblink_get_result('tokens_b') AS t(value bigint);
  SELECT value INTO ok FROM extensions.dblink('tokens_a',format('SELECT public.crier_webull_token_commit(%L,''sandbox'',1,%L::uuid,%L::jsonb)',fixture,op,e)) AS t(value boolean);
  ASSERT ok;
  -- Hold winner's claim transaction; contender must wait and then return no row.
  PERFORM extensions.dblink_exec('tokens_a','BEGIN');
  q:=format('SELECT count(*)::integer FROM public.crier_webull_token_claim_refresh(%L,''sandbox'',1,%L::uuid)',fixture,op2);
  SELECT value INTO a FROM extensions.dblink('tokens_a',q) AS t(value integer);
  PERFORM extensions.dblink_send_query('tokens_b',q);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('tokens_b')=1,'Second refresh must wait';
  PERFORM extensions.dblink_exec('tokens_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('tokens_b') AS t(value integer);
  ASSERT a=1 AND b=0,'Exactly one refresh winner';
  PERFORM value FROM extensions.dblink_get_result('tokens_b') AS t(value integer);
  -- Revoke holds lock before the old refresh completion arrives.
  PERFORM extensions.dblink_exec('tokens_a','BEGIN');
  SELECT value INTO n FROM extensions.dblink('tokens_a',format('SELECT public.crier_webull_token_revoke(%L,''sandbox'')',fixture)) AS t(value bigint);
  ASSERT n=3;
  PERFORM extensions.dblink_send_query('tokens_b',format('SELECT public.crier_webull_token_commit(%L,''sandbox'',2,%L::uuid,%L::jsonb)',fixture,op2,e));
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('tokens_b')=1,'Stale completion must wait for revoke';
  PERFORM extensions.dblink_exec('tokens_a','COMMIT');
  SELECT value INTO ok FROM extensions.dblink_get_result('tokens_b') AS t(value boolean);
  ASSERT NOT ok,'Revoked refresh result must not resurrect credentials';
  PERFORM value FROM extensions.dblink_get_result('tokens_b') AS t(value boolean);
  SELECT value INTO n FROM extensions.dblink('tokens_a',format('SELECT generation FROM public.crier_webull_token_read(%L,''sandbox'') WHERE state=''revoked'' AND envelope IS NULL',fixture)) AS t(value bigint);
  ASSERT n=3,'Tombstone survives stale completion';
  -- Only test owner cleanup may delete tombstones; RPCs never do.
  PERFORM extensions.dblink_exec('tokens_a',format('DELETE FROM crier_webull_private.token_states WHERE owner_ref=%L',fixture));
  PERFORM extensions.dblink_disconnect('tokens_a');
  PERFORM extensions.dblink_disconnect('tokens_b');
EXCEPTION WHEN OTHERS THEN
  BEGIN PERFORM extensions.dblink_disconnect('tokens_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM extensions.dblink_disconnect('tokens_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
  RAISE;
END $$;
