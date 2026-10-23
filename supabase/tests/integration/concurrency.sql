-- Real PostgreSQL only: run in an isolated database as migration owner.
-- Configure an owner connection for two extra sessions without putting it in this
-- file: SELECT set_config('crier.test_dsn', '<test database connection>', false);
-- This test requires dblink and committed fixtures, and cleans up on success.
CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA extensions;
CREATE TEMP TABLE crier_concurrency_fixture(host text,follower text,channel uuid);
DO $$
DECLARE h text; f text; code text; channel_id uuid;
BEGIN
  IF nullif(current_setting('crier.test_dsn',true),'') IS NULL THEN RAISE EXCEPTION 'Set crier.test_dsn to an isolated owner test database'; END IF;
  h:=public.crier_dispatch('POST','/api/connect/host','','{"name":"Concurrency fixture"}','{}','concurrency-host')->'body'->>'token';
  code:=public.crier_dispatch('POST','/api/connect/invite',h,'{}','{}','concurrency-invite')->'body'->>'code';
  f:=public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',code),'{}','concurrency-receive')->'body'->>'token';
  SELECT id INTO channel_id FROM crier_private.channels WHERE host_digest=extensions.digest(h,'sha256');
  INSERT INTO crier_concurrency_fixture VALUES(h,f,channel_id);
END $$;
DO $$
DECLARE fixture record; event jsonb; query_a text; query_b text; a jsonb; b jsonb; c jsonb; seq_before bigint; seq_after bigint; code text;
BEGIN
  SELECT * INTO fixture FROM crier_concurrency_fixture;
  PERFORM extensions.dblink_connect('crier_a',current_setting('crier.test_dsn'));
  PERFORM extensions.dblink_connect('crier_b',current_setting('crier.test_dsn'));
  event:='{"version":1,"event_id":"11111111-1111-4111-8111-111111111111","trade_id":"22222222-2222-4222-8222-222222222222","sequence":1,"action":"enter","environment":"paper","symbol":"AAPL","asset":"stock","quantity":1,"limit_price":"1.25","created_at":"2026-10-23T12:00:00Z","expires_at":"2026-10-23T12:00:20Z"}'::jsonb;
  query_a:=format('SELECT public.crier_dispatch(''POST'',''/api/sync/events'',%L,%L::jsonb)',fixture.host,event::text);
  query_b:=format('SELECT public.crier_dispatch(''POST'',''/api/sync/events'',%L,%L::jsonb)',fixture.host,(event||'{"event_id":"33333333-3333-4333-8333-333333333333","sequence":2}')::text);
  PERFORM extensions.dblink_exec('crier_a','BEGIN');
  SELECT value INTO a FROM extensions.dblink('crier_a',query_a) AS t(value jsonb);
  ASSERT a->>'status'='200';
  SELECT last_value INTO seq_before FROM crier_private.events_cursor_seq;
  PERFORM extensions.dblink_send_query('crier_b',query_b);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('crier_b')=1,'Second publisher must wait for channel lock';
  SELECT last_value INTO seq_after FROM crier_private.events_cursor_seq;
  ASSERT seq_after=seq_before,'Waiting publisher must not allocate a cursor before channel lock';
  -- A reader snapshot cannot see an event whose publishing transaction is open.
  ASSERT NOT EXISTS(SELECT 1 FROM crier_private.events WHERE channel=fixture.channel);
  PERFORM extensions.dblink_exec('crier_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);
  ASSERT b->>'status'='200' AND (b->'body'->>'cursor')::bigint>(a->'body'->>'cursor')::bigint;
  PERFORM value FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);
  SELECT value INTO c FROM extensions.dblink('crier_a',format('SELECT public.crier_dispatch(''GET'',''/api/sync/events'',%L)',fixture.follower)) AS t(value jsonb);
  ASSERT jsonb_array_length(c->'body'->'events')=2;
  ASSERT c->'body'->'events'->0->'cursor'=a->'body'->'cursor';
  ASSERT c->'body'->'events'->1->'cursor'=b->'body'->'cursor';

  -- Concurrent retry is idempotent, even while the original publish is open.
  event:=event||'{"event_id":"44444444-4444-4444-8444-444444444444","sequence":3}';
  query_a:=format('SELECT public.crier_dispatch(''POST'',''/api/sync/events'',%L,%L::jsonb)',fixture.host,event::text);
  PERFORM extensions.dblink_exec('crier_a','BEGIN');
  SELECT value INTO a FROM extensions.dblink('crier_a',query_a) AS t(value jsonb);
  PERFORM extensions.dblink_send_query('crier_b',query_a);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('crier_b')=1;
  PERFORM extensions.dblink_exec('crier_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);
  ASSERT a=b;
  PERFORM value FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);

  -- Two simultaneous invitation claims issue exactly one receiver credential.
  -- The invitation is created remotely to commit independently of this DO block.
  SELECT value INTO a FROM extensions.dblink('crier_a',format('SELECT public.crier_dispatch(''POST'',''/api/connect/invite'',%L,''{}'',''{}'',''concurrency-invite'')',fixture.host)) AS t(value jsonb);
  code:=a->'body'->>'code';
  query_a:=format('SELECT public.crier_dispatch(''POST'',''/api/connect/receive'','''',%L::jsonb,''{}'',''concurrency-receive'')',jsonb_build_object('code',code)::text);
  PERFORM extensions.dblink_exec('crier_a','BEGIN');
  SELECT value INTO a FROM extensions.dblink('crier_a',query_a) AS t(value jsonb);
  ASSERT a->>'status'='200';
  PERFORM extensions.dblink_send_query('crier_b',query_a);
  PERFORM pg_sleep(0.2);
  ASSERT extensions.dblink_is_busy('crier_b')=1;
  PERFORM extensions.dblink_exec('crier_a','COMMIT');
  SELECT value INTO b FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);
  ASSERT b->>'status'='401';
  PERFORM value FROM extensions.dblink_get_result('crier_b') AS t(value jsonb);
  ASSERT (SELECT count(*) FROM crier_private.receivers WHERE channel=fixture.channel)=2;
  PERFORM extensions.dblink_disconnect('crier_a');
  PERFORM extensions.dblink_disconnect('crier_b');
EXCEPTION WHEN OTHERS THEN
  -- Closing a session rolls back its open transaction, releasing blocked peers.
  BEGIN PERFORM extensions.dblink_disconnect('crier_a'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM extensions.dblink_disconnect('crier_b'); EXCEPTION WHEN OTHERS THEN NULL; END;
  RAISE;
END $$;
DELETE FROM crier_private.channels WHERE id IN (SELECT channel FROM crier_concurrency_fixture);
DELETE FROM crier_private.rate_limits WHERE id IN (
  extensions.digest('host:concurrency-host','sha256'),
  extensions.digest('invite:concurrency-invite','sha256'),
  extensions.digest('receive:concurrency-receive','sha256')
);
DROP TABLE crier_concurrency_fixture;
