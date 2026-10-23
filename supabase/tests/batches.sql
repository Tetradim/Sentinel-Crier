BEGIN;
DO $$
DECLARE token text; follower text; code text; event jsonb; r jsonb; first_cursor bigint; last_cursor bigint; i integer;
BEGIN
  token:=public.crier_dispatch('POST','/api/connect/host','','{"name":"Batch"}','{}','batch-host')->'body'->>'token';
  code:=public.crier_dispatch('POST','/api/connect/invite',token,'{}','{}','batch-invite')->'body'->>'code';
  follower:=public.crier_dispatch('POST','/api/connect/receive','',jsonb_build_object('code',code),'{}','batch-receive')->'body'->>'token';
  event:='{"trade_id":"22222222-2222-4222-8222-222222222222","sequence":1,"action":"enter","environment":"paper","symbol":"AAPL","asset":"stock","quantity":1,"limit_price":"1.25","created_at":"2026-10-23T12:00:00Z","expires_at":"2026-10-23T12:00:20Z"}'::jsonb;
  FOR i IN 1..501 LOOP
    event:=event||jsonb_build_object('event_id',gen_random_uuid()::text,'sequence',i);
    r:=public.crier_dispatch('POST','/api/sync/events',token,event);
    ASSERT r->>'status'='200';
    last_cursor:=(r->'body'->>'cursor')::bigint;
    IF i=1 THEN first_cursor:=last_cursor; END IF;
  END LOOP;
  r:=public.crier_dispatch('GET','/api/sync/events',follower);
  ASSERT r->>'status'='200' AND jsonb_array_length(r->'body'->'events')=500;
  ASSERT (r->'body'->'events'->0->>'cursor')::bigint=first_cursor;
  r:=public.crier_dispatch('GET','/api/sync/events',follower,'{}',jsonb_build_object('after',r->'body'->>'cursor'));
  ASSERT jsonb_array_length(r->'body'->'events')=1 AND (r->'body'->>'cursor')::bigint=last_cursor;
  r:=public.crier_dispatch('GET','/api/sync/events',follower,'{}',jsonb_build_object('after',last_cursor));
  ASSERT r->'body'->'events'='[]'::jsonb AND (r->'body'->>'cursor')::bigint=last_cursor;
END $$;
ROLLBACK;
