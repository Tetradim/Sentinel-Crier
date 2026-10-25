-- Real PostgreSQL only; isolated owner database, configured crier.test_dsn.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
CREATE TEMP TABLE provider_race_fixture(owner_id uuid,flow_id text);
INSERT INTO provider_race_fixture VALUES('40000000-0000-0000-0000-000000000001',repeat('R',43));
-- Committed rows are visible to independent sessions.
WITH stamp AS MATERIALIZED (SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms)
INSERT INTO crier_provider.flows(flow_id,owner_id,provider,purpose,environment,challenge,stage,created_at,expires_at,ready_until,grant_ciphertext)
SELECT flow_id,owner_id,'alpaca','alerts','paper',repeat('a',64),'ready',
 stamp.ms,stamp.ms+300000,stamp.ms+60000,
 jsonb_build_object('version',1,'key_id','test','nonce',repeat('a',16),'ciphertext',repeat('b',22)) FROM provider_race_fixture CROSS JOIN stamp;
-- Seven committed active rows leave one owner slot; unique challenges avoid
-- accidentally exercising the independent per-challenge quota here.
WITH stamp AS MATERIALIZED (SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms)
INSERT INTO crier_provider.flows(flow_id,owner_id,provider,purpose,environment,challenge,stage,created_at,expires_at)
SELECT repeat('Q',42)||i::text,'40000000-0000-0000-0000-000000000001','alpaca','alerts','paper',md5(i::text)||md5(i::text),'pending',stamp.ms,stamp.ms+300000
FROM generate_series(1,7) i CROSS JOIN stamp;
DO $$
DECLARE fixture record; q text; a jsonb; b jsonb; deadline bigint; quota_input jsonb;
BEGIN
 IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN RAISE EXCEPTION 'Set crier.test_dsn'; END IF;
 SELECT * INTO fixture FROM provider_race_fixture;
 PERFORM extensions.dblink_connect('provider_a',current_setting('crier.test_dsn'));
 PERFORM extensions.dblink_connect('provider_b',current_setting('crier.test_dsn'));
 q:=format('SELECT public.crier_oauth_flow(''redeem'',%L,%L,%L::jsonb)',fixture.owner_id,fixture.flow_id,jsonb_build_object('proof_hash',repeat('a',64))::text);
 PERFORM extensions.dblink_exec('provider_a','BEGIN');
 SELECT value INTO a FROM extensions.dblink('provider_a',q) AS t(value jsonb);
 ASSERT a->>'ok'='true' AND a->'flow'->'grant_ciphertext'<>'null'::jsonb;
 PERFORM extensions.dblink_send_query('provider_b',q);
 PERFORM pg_sleep(0.1);
 ASSERT extensions.dblink_is_busy('provider_b')=1,'Concurrent redemption must wait';
 PERFORM extensions.dblink_exec('provider_a','COMMIT');
 SELECT value INTO b FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 ASSERT b='{"ok":false}'::jsonb,'Exactly one redeemer receives ciphertext';
 PERFORM value FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 -- Shared durable CSRF tombstone also excludes concurrent process replay.
 deadline:=floor(extract(epoch FROM clock_timestamp())*1000)::bigint+300000;
 q:=format('SELECT public.crier_oauth_flow(''csrf_claim'',NULL,NULL,%L::jsonb)',jsonb_build_object('hash',repeat('e',64),'expires_at',deadline)::text);
 PERFORM extensions.dblink_exec('provider_a','BEGIN');
 SELECT value INTO a FROM extensions.dblink('provider_a',q) AS t(value jsonb);
 ASSERT a->>'claimed'='true';
 PERFORM extensions.dblink_send_query('provider_b',q);
 PERFORM pg_sleep(0.1);
 ASSERT extensions.dblink_is_busy('provider_b')=1;
 PERFORM extensions.dblink_exec('provider_a','COMMIT');
 SELECT value INTO b FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 ASSERT b->>'ok'='true' AND b->>'claimed'='false';
 PERFORM value FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 -- A clock sampled before waiting on a row would incorrectly redeem this row.
 PERFORM extensions.dblink_exec('provider_a','BEGIN');
 PERFORM extensions.dblink_exec('provider_a',format('UPDATE crier_provider.flows SET stage=''ready'',ready_until=floor(extract(epoch FROM clock_timestamp())*1000)::bigint+300,grant_ciphertext=%L::jsonb WHERE flow_id=%L',jsonb_build_object('version',1,'key_id','test','nonce',repeat('a',16),'ciphertext',repeat('b',22))::text,fixture.flow_id));
 q:=format('SELECT public.crier_oauth_flow(''redeem'',%L,%L,%L::jsonb)',fixture.owner_id,fixture.flow_id,jsonb_build_object('proof_hash',repeat('a',64))::text);
 PERFORM extensions.dblink_send_query('provider_b',q);
 PERFORM pg_sleep(0.45);
 ASSERT extensions.dblink_is_busy('provider_b')=1;
 PERFORM extensions.dblink_exec('provider_a','COMMIT');
 SELECT value INTO b FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 ASSERT b='{"ok":false}'::jsonb,'Deadline must be sampled after lock acquisition';
 PERFORM value FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 ASSERT (SELECT stage='expired' AND grant_ciphertext IS NULL FROM crier_provider.flows WHERE flow_id=fixture.flow_id),'Rejected expired redemption persists scrub';
 -- Owner quota serializes across different flow/challenge keys.
 quota_input:=jsonb_build_object('provider','alpaca','purpose','alerts','environment','paper','challenge',repeat('c',64),'ticket_hash',repeat('1',64),'state_hash',repeat('2',64),'state_ciphertext',jsonb_build_object('version',1,'key_id','test','nonce',repeat('a',16),'ciphertext',repeat('b',22)));
 q:=format('SELECT public.crier_oauth_flow(''begin'',%L,%L,%L::jsonb)',fixture.owner_id,repeat('S',43),quota_input::text);
 PERFORM extensions.dblink_exec('provider_a','BEGIN');
 SELECT value INTO a FROM extensions.dblink('provider_a',q) AS t(value jsonb);
 ASSERT a->>'ok'='true';
 quota_input:=quota_input||jsonb_build_object('challenge',repeat('d',64),'ticket_hash',repeat('3',64),'state_hash',repeat('4',64));
 q:=format('SELECT public.crier_oauth_flow(''begin'',%L,%L,%L::jsonb)',fixture.owner_id,repeat('T',43),quota_input::text);
 PERFORM extensions.dblink_send_query('provider_b',q);
 PERFORM pg_sleep(0.1);
 ASSERT extensions.dblink_is_busy('provider_b')=1,'Owner quota must wait for prior create';
 PERFORM extensions.dblink_exec('provider_a','COMMIT');
 SELECT value INTO b FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 ASSERT b='{"ok":false}'::jsonb,'Concurrent owner create may not exceed eight active';
 PERFORM value FROM extensions.dblink_get_result('provider_b') AS t(value jsonb);
 PERFORM extensions.dblink_disconnect('provider_a');
 PERFORM extensions.dblink_disconnect('provider_b');
EXCEPTION WHEN OTHERS THEN
 BEGIN PERFORM extensions.dblink_disconnect('provider_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
 BEGIN PERFORM extensions.dblink_disconnect('provider_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
 RAISE;
END $$;
DELETE FROM crier_provider.flows WHERE owner_id IN (SELECT owner_id FROM provider_race_fixture);
DELETE FROM crier_provider.csrf_used WHERE hash=repeat('e',64);
DROP TABLE provider_race_fixture;



