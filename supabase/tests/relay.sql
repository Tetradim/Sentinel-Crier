-- Run as the migration owner against an isolated test database after migrations.
-- Every assertion raises on failure; test data is rolled back.
BEGIN;
DO $$
DECLARE
  r jsonb; host_token text; host2 text; follower text; follower2 text; invite text;
  event jsonb; cursor1 bigint; cursor2 bigint; channel_id uuid; receiver_id text;
  observation jsonb; invalid jsonb; i integer;
BEGIN
  ASSERT NOT has_schema_privilege('anon','crier_private','USAGE');
  ASSERT NOT has_schema_privilege('authenticated','crier_private','USAGE');
  ASSERT NOT has_function_privilege('anon','public.crier_dispatch(text,text,text,jsonb,jsonb,text)','EXECUTE');
  ASSERT NOT has_function_privilege('authenticated','public.crier_dispatch(text,text,text,jsonb,jsonb,text)','EXECUTE');
  ASSERT has_function_privilege('service_role','public.crier_dispatch(text,text,text,jsonb,jsonb,text)','EXECUTE');
  ASSERT NOT has_function_privilege('service_role','crier_private.valid_event(jsonb)','EXECUTE');
  ASSERT NOT has_table_privilege('anon','crier_private.events','SELECT');
  ASSERT NOT has_table_privilege('authenticated','crier_private.events','SELECT');
  ASSERT NOT has_table_privilege('service_role','crier_private.events','INSERT');
  ASSERT (SELECT prosecdef AND proconfig=ARRAY['search_path=pg_catalog'] FROM pg_proc WHERE oid='public.crier_dispatch(text,text,text,jsonb,jsonb,text)'::regprocedure);

  r:=public.crier_dispatch('GET','/health');
  ASSERT r->>'status'='200' AND r->'body'='{"status":"ok","pairing_enabled":true,"protocol":1}'::jsonb;
  ASSERT public.crier_dispatch('GET','/api/sync/channels')->>'status'='404';
  ASSERT public.crier_dispatch('POST','/api/connect/host','','{"name":"A","environment":"paper"}','{}','test-host1')->>'status'='200';
  r:=public.crier_dispatch('POST','/api/connect/host','','{"name":"Host","environment":"paper"}','{}','test-host2');
  ASSERT r->>'status'='200';host_token:=r->'body'->>'token';
  ASSERT length(host_token)=43 AND host_token ~ '^[A-Za-z0-9_-]{43}$';
  ASSERT r->'body'->>'role'='host' AND r->'body'->>'environment'='paper';
  ASSERT (SELECT count(*) FROM jsonb_object_keys(r->'body'))=3;
  SELECT id INTO channel_id FROM crier_private.channels WHERE host_digest=extensions.digest(host_token,'sha256');
  r:=public.crier_dispatch('POST','/api/connect/host','','{"name":"Other","environment":"live"}','{}','test-host3');
  host2:=r->'body'->>'token';
  r:=public.crier_dispatch('POST','/api/connect/invite',host_token,'{}','{}','test-invite');
  ASSERT r->>'status'='200';invite:=r->'body'->>'code';
  ASSERT invite ~ '^[A-Z2-7]{16}$';
  ASSERT abs((r->'body'->>'expires_at')::numeric-extract(epoch FROM clock_timestamp())-600)<5;
  r:=public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',invite,'environment','live'),'{}','test-receive');
  ASSERT r->>'status'='422';
  r:=public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',lower(left(invite,8))||'-'||right(invite,8),'environment','paper'),'{}','test-receive');
  ASSERT r->>'status'='200';follower:=r->'body'->>'token';
  ASSERT length(follower)=43 AND follower<>host_token;
  ASSERT r->'body'->>'role'='follower';
  ASSERT public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',invite),'{}','test-receive')->>'status'='401';
  ASSERT NOT EXISTS(SELECT 1 FROM crier_private.invitations WHERE code_digest=extensions.digest(invite,'sha256'));
  ASSERT public.crier_dispatch('GET','/api/sync/clock','unknown')->>'status'='401';
  ASSERT public.crier_dispatch('GET','/api/sync/clock',host_token)->>'status'='200';
  ASSERT public.crier_dispatch('GET','/api/sync/events',host_token)->>'status'='401';

  event:='{"version":1,"event_id":"11111111-1111-4111-8111-111111111111","trade_id":"22222222-2222-4222-8222-222222222222","sequence":1,"action":"enter","environment":"paper","symbol":"AAPL","asset":"stock","quantity":1,"limit_price":"1.25","created_at":"2026-10-23T12:00:00Z","expires_at":"2026-10-23T12:00:20Z"}'::jsonb;
  ASSERT public.crier_dispatch('POST','/api/sync/events',follower,event)->>'status'='401';
  ASSERT public.crier_dispatch('POST','/api/sync/events',host2,event)->>'status'='409';
  r:=public.crier_dispatch('POST','/api/sync/events',host_token,event);
  ASSERT r->>'status'='200';cursor1:=(r->'body'->>'cursor')::bigint;
  r:=public.crier_dispatch('POST','/api/sync/events',host_token,event);
  ASSERT (r->'body'->>'cursor')::bigint=cursor1;
  ASSERT public.crier_dispatch('POST','/api/sync/events',host_token,event||'{"quantity":2}')->>'status'='409';
  ASSERT public.crier_dispatch('POST','/api/sync/events',host_token,event||'{"event_id":"33333333-3333-4333-8333-333333333333"}')->>'status'='409';
  ASSERT public.crier_dispatch('POST','/api/sync/events',host_token,event||'{"event_id":"33333333-3333-4333-8333-333333333333","sequence":2,"symbol":"MSFT"}')->>'status'='409';
  r:=public.crier_dispatch('GET','/api/sync/events',follower,'{}','{"after":"0","wait":"0"}');
  ASSERT jsonb_array_length(r->'body'->'events')=1;
  ASSERT r->'body'->'events'->0->'event'=event;
  ASSERT (r->'body'->>'cursor')::bigint=cursor1;
  ASSERT public.crier_dispatch('GET','/api/sync/events',follower,'{}','{"after":"-1"}')->>'status'='422';
  ASSERT public.crier_dispatch('GET','/api/sync/events',follower,'{}','{"after":"9223372036854775808"}')->>'status'='422';

  -- All contract fields are checked, without returning untrusted input in errors.
  FOR invalid IN SELECT value FROM jsonb_array_elements('[{"version":2},{"sequence":true},{"sequence":1.0},{"sequence":0},{"sequence":2147483648},{"quantity":"1"},{"quantity":0},{"quantity":1001},{"limit_price":"NaN"},{"limit_price":true},{"limit_price":"0"},{"limit_price":"100001"},{"limit_price":"0.123456789"},{"symbol":"aapl"},{"environment":"demo"},{"action":"buy"},{"asset":"future"},{"event_id":"INVALID"},{"trade_id":"22222222-2222-4222-8222-22222222222A"},{"created_at":"2026-10-23T12:00:00"},{"expires_at":"2026-10-23T12:00:31Z"},{"expires_at":"2026-10-23T11:59:59Z"},{"unexpected":"secret"},{"symbol":"AAPL261332C00001000","asset":"option"},{"symbol":"AAPL260230C00001000","asset":"option"},{"symbol":"AAPL261223C00000000","asset":"option"},{"symbol":"AAPL 261223C00001000","asset":"option"}]'::jsonb) LOOP
    ASSERT public.crier_dispatch('POST','/api/sync/events',host_token,event||invalid)->>'status'='422',invalid::text;
  END LOOP;
  ASSERT crier_private.valid_event(event||'{"symbol":"AAPL261223C00001000","asset":"option"}');

  -- Joining captures the committed high water mark, without replaying old trades.
  invite:=public.crier_dispatch('POST','/api/connect/invite',host_token,'{}','{}','test-invite')->'body'->>'code';
  follower2:=public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',invite),'{}','test-receive')->'body'->>'token';
  r:=public.crier_dispatch('GET','/api/sync/events',follower2);
  ASSERT r->'body'->'events'='[]'::jsonb AND (r->'body'->>'cursor')::bigint=cursor1;
  r:=public.crier_dispatch('POST','/api/sync/events',host_token,event||'{"event_id":"33333333-3333-4333-8333-333333333333","sequence":2}');
  cursor2:=(r->'body'->>'cursor')::bigint;
  ASSERT cursor2>cursor1;
  ASSERT jsonb_array_length(public.crier_dispatch('GET','/api/sync/events',follower2)->'body'->'events')=1;
  ASSERT public.crier_dispatch('GET','/api/sync/diagnostics',follower2,'{}',jsonb_build_object('event_id',event->>'event_id'))->>'status'='404';

  observation:=jsonb_build_object('event_id',event->>'event_id','observation',jsonb_build_object('stage','sender','observed_at','2026-10-23T12:00:01Z'));
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',host_token,observation)->>'status'='200';
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',host_token,observation)->>'status'='200';
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',follower,observation)->>'status'='403';
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',host_token,jsonb_set(observation,'{observation,observed_at}','"2026-10-23T12:00:02Z"'))->>'status'='409';
  observation:=jsonb_set(observation,'{observation,stage}','"receiver"');
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',follower,observation)->>'status'='200';
  r:=public.crier_dispatch('GET','/api/sync/diagnostics',host_token,'{}',jsonb_build_object('event_id',event->>'event_id'));
  ASSERT jsonb_array_length(r->'body'->'observations')=1;
  r:=public.crier_dispatch('GET','/api/sync/diagnostics',follower,'{}',jsonb_build_object('event_id',event->>'event_id'));
  ASSERT jsonb_array_length(r->'body'->'observations')=2;
  ASSERT public.crier_dispatch('GET','/api/sync/diagnostics',host2,'{}',jsonb_build_object('event_id',event->>'event_id'))->>'status'='404';
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',follower,jsonb_set(observation,'{observation,quote}','{"source":"test","quote_timestamp":"2026-10-23T12:00:01Z","bid":"2","ask":"1"}'))->>'status'='422';
  ASSERT public.crier_dispatch('POST','/api/sync/diagnostics',follower,jsonb_set(observation,'{observation,clock_offset_ms}','604800001'))->>'status'='422';

  -- Revocation survives subsequent requests; one receiver cannot revoke another.
  r:=public.crier_dispatch('GET','/api/connect/receivers',host_token,'{}','{}','test-list');
  ASSERT jsonb_array_length(r->'body')=2;
  SELECT id::text INTO receiver_id FROM crier_private.receivers WHERE token_digest=extensions.digest(follower,'sha256');
  ASSERT public.crier_dispatch('POST','/api/connect/receivers/'||receiver_id||'/revoke',follower,'{}','{}','test-revoke')->>'status'='401';
  ASSERT public.crier_dispatch('POST','/api/connect/receivers/'||receiver_id||'/revoke',host2,'{}','{}','test-revoke')->>'status'='200';
  ASSERT public.crier_dispatch('GET','/api/sync/clock',follower)->>'status'='200';
  ASSERT public.crier_dispatch('POST','/api/connect/receivers/'||receiver_id||'/revoke',host_token,'{}','{}','test-revoke')->>'status'='200';
  ASSERT public.crier_dispatch('GET','/api/sync/clock',follower)->>'status'='401';
  ASSERT public.crier_dispatch('GET','/api/sync/events',follower)->>'status'='401';
  ASSERT public.crier_dispatch('GET','/api/sync/clock',follower2)->>'status'='200';
  invite:=public.crier_dispatch('POST','/api/connect/invite',host_token,'{}','{}','test-invite')->'body'->>'code';
  UPDATE crier_private.invitations SET expires=clock_timestamp()-interval '1 second' WHERE code_digest=extensions.digest(invite,'sha256');
  ASSERT public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',invite),'{}','test-receive')->>'status'='401';
  UPDATE crier_private.channels SET revoked=true WHERE id=channel_id;
  ASSERT public.crier_dispatch('GET','/api/sync/clock',host_token)->>'status'='401';
  ASSERT public.crier_dispatch('GET','/api/sync/clock',follower2)->>'status'='401';

  FOR i IN 1..5 LOOP
    ASSERT public.crier_dispatch('POST','/api/connect/host','','{"name":"Rate test"}','{}','test-rate')->>'status'='200';
  END LOOP;
  ASSERT public.crier_dispatch('POST','/api/connect/host','','{"name":"Rate test"}','{}','test-rate')->>'status'='429';
END $$;
-- Exercise the SECURITY DEFINER boundary with the actual granted role.
SET LOCAL ROLE service_role;
DO $$ BEGIN ASSERT public.crier_dispatch('GET','/health')->>'status'='200'; END $$;
RESET ROLE;
ROLLBACK;
