-- REAL PostgreSQL only; load all four candidate SQL files first.
-- Synthetic envelope shapes, isolated owner database, no keys or broker calls.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
DO $$
DECLARE e jsonb; rotated jsonb; q text; ok boolean; n bigint; count_a integer; count_b integer; kind text; owner_name text;
  fixture text:='webull-operations-concurrency-fixture';
  op uuid:='00000000-0000-4000-8000-000000000001';
BEGIN
  IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN RAISE EXCEPTION 'Set crier.test_dsn to an isolated owner test database'; END IF;
  PERFORM extensions.dblink_connect('operations_a',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_connect('operations_b',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_exec('operations_a','SET statement_timeout=''5s''');
  PERFORM extensions.dblink_exec('operations_b','SET statement_timeout=''5s''');
  e:=jsonb_build_object('schema','crier.webull-token.v1','key_id','old-key','nonce',repeat('A',16),'ciphertext',repeat('A',22),'identity_hash',repeat('a',64),'access_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+60000,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+120000);
  rotated:=e||jsonb_build_object('key_id','new-key','nonce',repeat('B',16),'ciphertext',repeat('B',21)||'A');
  FOREACH kind IN ARRAY ARRAY['rotation','refresh','revoke'] LOOP
    owner_name:=fixture||'-'||kind;
    SELECT value INTO n FROM extensions.dblink('operations_a',format('SELECT public.crier_webull_token_reserve(%L,''sandbox'',0,%L::uuid)',owner_name,op)) AS t(value bigint);
    ASSERT n=1;
    SELECT value INTO ok FROM extensions.dblink('operations_a',format('SELECT public.crier_webull_token_commit(%L,''sandbox'',1,%L::uuid,%L::jsonb)',owner_name,op,e)) AS t(value boolean);
    ASSERT ok;
    PERFORM extensions.dblink_exec('operations_a','BEGIN');
    IF kind='rotation' THEN
      SELECT value INTO ok FROM extensions.dblink('operations_a',format('SELECT public.crier_webull_token_rewrap(%L,''sandbox'',1,%L::jsonb,%L::jsonb)',owner_name,e,rotated)) AS t(value boolean);
      ASSERT ok;
    ELSIF kind='refresh' THEN
      SELECT value INTO n FROM extensions.dblink('operations_a',format('SELECT new_generation FROM public.crier_webull_token_claim_refresh(%L,''sandbox'',1,%L::uuid)',owner_name,op)) AS t(value bigint);
      ASSERT n=2;
    ELSE
      SELECT value INTO n FROM extensions.dblink('operations_a',format('SELECT public.crier_webull_token_revoke(%L,''sandbox'')',owner_name)) AS t(value bigint);
      ASSERT n=2;
    END IF;
    q:=format('SELECT public.crier_webull_token_rewrap(%L,''sandbox'',1,%L::jsonb,%L::jsonb)',owner_name,e,rotated);
    PERFORM extensions.dblink_send_query('operations_b',q);
    PERFORM pg_sleep(0.2);
    ASSERT extensions.dblink_is_busy('operations_b')=1,'Rewrap must wait for competing token mutation';
    PERFORM extensions.dblink_exec('operations_a','COMMIT');
    SELECT value INTO ok FROM extensions.dblink_get_result('operations_b') AS t(value boolean);
    ASSERT NOT ok,'Only one rotation wins; refresh/revoke fence old rotation';
    PERFORM value FROM extensions.dblink_get_result('operations_b') AS t(value boolean);
    IF kind='rotation' THEN
      SELECT value INTO ok FROM extensions.dblink('operations_a',format('SELECT generation=1 AND envelope=%L::jsonb FROM public.crier_webull_token_read(%L,''sandbox'')',rotated,owner_name)) AS t(value boolean);
      ASSERT ok,'Rotation preserves generation and exact winning envelope';
      -- Rotation first: the refresh claimant must receive the winning envelope.
      SELECT value INTO ok FROM extensions.dblink('operations_b',format('SELECT envelope=%L::jsonb AND new_generation=2 FROM public.crier_webull_token_claim_refresh(%L,''sandbox'',1,%L::uuid)',rotated,owner_name,op)) AS t(value boolean);
      ASSERT ok,'Refresh must use rotated custody';
    END IF;
  END LOOP;
  -- Refresh expires while rewrap is blocked on a row lock. Wall time must be
  -- evaluated after that lock even when the advisory lock was uncontended.
  owner_name:=fixture||'-expiry';
  e:=e||jsonb_build_object('access_expires_at_ms',1,'refresh_expires_at_ms',floor(extract(epoch FROM clock_timestamp())*1000)+1000);
  PERFORM extensions.dblink_exec('operations_a',format('INSERT INTO crier_webull_private.token_states VALUES(%L,''sandbox'',1,''active'',NULL,%L::jsonb,%L)',owner_name,e,e->>'identity_hash'));
  PERFORM extensions.dblink_exec('operations_a','BEGIN');
  PERFORM value FROM extensions.dblink('operations_a',format('SELECT generation FROM crier_webull_private.token_states WHERE owner_ref=%L FOR UPDATE',owner_name)) AS t(value bigint);
  PERFORM extensions.dblink_send_query('operations_b',format('SELECT public.crier_webull_token_rewrap(%L,''sandbox'',1,%L::jsonb,%L::jsonb)',owner_name,e,e||'{"key_id":"new-key"}'));
  PERFORM pg_sleep(1.2);
  ASSERT extensions.dblink_is_busy('operations_b')=1;
  PERFORM extensions.dblink_exec('operations_a','COMMIT');
  SELECT value INTO ok FROM extensions.dblink_get_result('operations_b') AS t(value boolean);
  ASSERT NOT ok,'Rewrap cannot extend refresh custody past expiry during a lock wait';
  PERFORM value FROM extensions.dblink_get_result('operations_b') AS t(value boolean);
  -- First cleanup holds a deleted parent and its cascading association. The
  -- second worker must immediately skip that row and delete the other row.
  PERFORM extensions.dblink_exec('operations_a',format('INSERT INTO crier_webull_private.authorization_sessions SELECT %L,repeat(i::text,64),repeat(''b'',64),''sandbox'',''https://example.test/callback'',statement_timestamp()-interval ''301 seconds'',statement_timestamp()-interval ''1 second'' FROM generate_series(1,2) i',fixture));
  PERFORM extensions.dblink_exec('operations_a',format('INSERT INTO crier_webull_private.authorization_reservations SELECT state_hash,1,%L::uuid FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',op,fixture));
  PERFORM extensions.dblink_exec('operations_a','BEGIN');
  SELECT value INTO count_a FROM extensions.dblink('operations_a','SELECT public.crier_webull_cleanup_expired_sessions(1)') AS t(value integer);
  PERFORM extensions.dblink_exec('operations_b','SET statement_timeout=''2s''');
  SELECT value INTO count_b FROM extensions.dblink('operations_b','SELECT public.crier_webull_cleanup_expired_sessions(500)') AS t(value integer);
  ASSERT count_a=1 AND count_b=1,'Concurrent cleanup must skip locked rows without a lock stall';
  PERFORM extensions.dblink_exec('operations_a','COMMIT');
  SELECT value INTO n FROM extensions.dblink('operations_a',format('SELECT count(*) FROM crier_webull_private.authorization_reservations WHERE state_hash IN (repeat(''1'',64),repeat(''2'',64))')) AS t(value bigint);
  ASSERT n=0,'Both cleanup workers cascade associations';
  SELECT value INTO ok FROM extensions.dblink('operations_a',format('SELECT state=''revoked'' AND generation=2 FROM crier_webull_private.token_states WHERE owner_ref=%L',fixture||'-revoke')) AS t(value boolean);
  ASSERT ok,'Cleanup retains revoke tombstones';
  -- Only test-owner teardown deletes token states.
  PERFORM extensions.dblink_exec('operations_a',format('DELETE FROM crier_webull_private.authorization_sessions WHERE owner_ref=%L',fixture));
  PERFORM extensions.dblink_exec('operations_a',format('DELETE FROM crier_webull_private.token_states WHERE owner_ref LIKE %L',fixture||'%'));
  PERFORM extensions.dblink_disconnect('operations_a');
  PERFORM extensions.dblink_disconnect('operations_b');
EXCEPTION WHEN OTHERS THEN
  BEGIN PERFORM extensions.dblink_disconnect('operations_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM extensions.dblink_disconnect('operations_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
  RAISE;
END $$;
