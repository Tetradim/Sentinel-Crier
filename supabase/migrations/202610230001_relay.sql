-- The edge function is the sole caller. No broker credentials enter this schema.
CREATE SCHEMA IF NOT EXISTS crier_private;
REVOKE ALL ON SCHEMA crier_private FROM PUBLIC, anon, authenticated;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

CREATE TABLE crier_private.channels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 60 AND name ~ '[^[:space:]]'),
  environment text NOT NULL CHECK (environment IN ('paper','live')),
  host_digest bytea UNIQUE NOT NULL,
  revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE crier_private.invitations (
  code_digest bytea PRIMARY KEY,
  channel uuid NOT NULL REFERENCES crier_private.channels(id) ON DELETE CASCADE,
  expires timestamptz NOT NULL
);
CREATE INDEX invitations_expiry ON crier_private.invitations(expires);
CREATE TABLE crier_private.receivers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  channel uuid NOT NULL REFERENCES crier_private.channels(id) ON DELETE CASCADE,
  token_digest bytea UNIQUE NOT NULL,
  created timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked boolean NOT NULL DEFAULT false,
  start_cursor bigint NOT NULL DEFAULT 0
);
CREATE INDEX receivers_channel ON crier_private.receivers(channel,created);
CREATE TABLE crier_private.events (
  cursor bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  channel uuid NOT NULL REFERENCES crier_private.channels(id) ON DELETE CASCADE,
  event_id uuid NOT NULL,
  trade_id uuid NOT NULL,
  sequence integer NOT NULL,
  identity jsonb NOT NULL,
  payload jsonb NOT NULL,
  UNIQUE(channel,event_id), UNIQUE(channel,trade_id,sequence)
);
CREATE INDEX events_stream ON crier_private.events(channel,cursor);
CREATE TABLE crier_private.diagnostics (
  channel uuid NOT NULL,
  event_id uuid NOT NULL,
  actor text NOT NULL,
  observation jsonb NOT NULL,
  PRIMARY KEY(channel,event_id,actor),
  FOREIGN KEY(channel,event_id) REFERENCES crier_private.events(channel,event_id) ON DELETE CASCADE
);
CREATE TABLE crier_private.rate_limits (
  id bytea PRIMARY KEY, bucket bigint NOT NULL, count integer NOT NULL
);
-- RLS adds defense in depth even if grants are accidentally added later.
ALTER TABLE crier_private.channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.receivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.diagnostics ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.rate_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA crier_private FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA crier_private FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION crier_private.reply(code integer, value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
  SELECT jsonb_build_object('status',code,'body',value)
$$;
CREATE FUNCTION crier_private.fail(code integer, message text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
  SELECT crier_private.reply(code,jsonb_build_object('detail',message))
$$;
CREATE FUNCTION crier_private.is_uuid(value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
  SELECT coalesce(jsonb_typeof(value)='string' AND value #>> '{}' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',false)
$$;
CREATE FUNCTION crier_private.is_stamp(value jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
BEGIN
  IF jsonb_typeof(value) IS DISTINCT FROM 'string' OR length(value #>> '{}')>64
     OR (value #>> '{}') !~ '^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d{1,6})?([Zz]|[+-]\d{2}:\d{2})$' THEN RETURN false; END IF;
  PERFORM (value #>> '{}')::timestamptz;
  RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

CREATE FUNCTION crier_private.valid_event(e jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
DECLARE k text; stamp text; price numeric; lifetime interval;
BEGIN
  IF jsonb_typeof(e) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  IF NOT e ?& ARRAY['event_id','trade_id','sequence','action','environment','symbol','asset','quantity','limit_price','created_at','expires_at'] THEN RETURN false; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_object_keys(e) key WHERE key <> ALL(ARRAY['version','event_id','trade_id','sequence','action','environment','symbol','asset','quantity','limit_price','created_at','expires_at'])) THEN RETURN false; END IF;
  IF e ? 'version' AND (jsonb_typeof(e->'version') <> 'number' OR e->>'version' <> '1') THEN RETURN false; END IF;
  IF NOT crier_private.is_uuid(e->'event_id') OR NOT crier_private.is_uuid(e->'trade_id') THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['sequence','quantity'] LOOP
    IF jsonb_typeof(e->k) <> 'number' OR e->>k !~ '^[0-9]+$' THEN RETURN false; END IF;
  END LOOP;
  IF (e->>'sequence')::numeric NOT BETWEEN 1 AND 2147483647 OR (e->>'quantity')::numeric NOT BETWEEN 1 AND 1000 THEN RETURN false; END IF;
  IF jsonb_typeof(e->'action') <> 'string' OR e->>'action' NOT IN ('enter','replace','cancel','exit')
     OR jsonb_typeof(e->'environment') <> 'string' OR e->>'environment' NOT IN ('paper','live')
     OR jsonb_typeof(e->'asset') <> 'string' OR e->>'asset' NOT IN ('stock','option')
     OR jsonb_typeof(e->'symbol') <> 'string' OR length(e->>'symbol') > 32 THEN RETURN false; END IF;
  IF jsonb_typeof(e->'limit_price') NOT IN ('number','string') OR length(e->>'limit_price')>40
     OR e->>'limit_price' !~ '^[+]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN RETURN false; END IF;
  price := (e->>'limit_price')::numeric;
  IF price <= 0 OR price>100000 OR price <> round(price,8) THEN RETURN false; END IF;
  IF NOT crier_private.is_stamp(e->'created_at') OR NOT crier_private.is_stamp(e->'expires_at') THEN RETURN false; END IF;
  lifetime := (e->>'expires_at')::timestamptz - (e->>'created_at')::timestamptz;
  IF lifetime <= interval '0 seconds' OR (e->>'action' IN ('enter','replace') AND lifetime>interval '30 seconds') THEN RETURN false; END IF;
  IF e->>'asset'='stock' THEN RETURN e->>'symbol' ~ '^[A-Z][A-Z0-9.\-]{0,9}$'; END IF;
  IF e->>'symbol' !~ '^[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}$' OR right(e->>'symbol',8)::integer <= 0 THEN RETURN false; END IF;
  stamp := substring(e->>'symbol' FROM '[0-9]{6}');
  -- make_date rejects impossible option expiry dates instead of normalizing them.
  PERFORM make_date(2000+left(stamp,2)::integer,substring(stamp,3,2)::integer,right(stamp,2)::integer);
  RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

CREATE FUNCTION crier_private.valid_observation(o jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
DECLARE q jsonb; k text; n numeric; bid numeric; ask numeric; found_price boolean := false;
BEGIN
  IF jsonb_typeof(o) IS DISTINCT FROM 'object' OR NOT o ?& ARRAY['stage','observed_at'] THEN RETURN false; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_object_keys(o) key WHERE key <> ALL(ARRAY['stage','observed_at','clock_offset_ms','clock_uncertainty_ms','clock_sampled_at','quote','quote_error'])) THEN RETURN false; END IF;
  IF jsonb_typeof(o->'stage') <> 'string' OR o->>'stage' NOT IN ('sender','receiver') OR NOT crier_private.is_stamp(o->'observed_at') THEN RETURN false; END IF;
  IF o ? 'clock_sampled_at' AND o->'clock_sampled_at' <> 'null'::jsonb AND NOT crier_private.is_stamp(o->'clock_sampled_at') THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['clock_offset_ms','clock_uncertainty_ms'] LOOP
    IF o ? k AND o->k <> 'null'::jsonb THEN
      IF jsonb_typeof(o->k) <> 'number' THEN RETURN false; END IF;
      n := (o->>k)::numeric;
      IF (k='clock_offset_ms' AND abs(n)>604800000) OR (k='clock_uncertainty_ms' AND (n<0 OR n>30000)) THEN RETURN false; END IF;
    END IF;
  END LOOP;
  IF o ? 'quote_error' AND o->'quote_error' <> 'null'::jsonb AND (jsonb_typeof(o->'quote_error') <> 'string' OR length(o->>'quote_error')>160) THEN RETURN false; END IF;
  q:=o->'quote';
  IF q IS NULL OR q='null'::jsonb THEN RETURN true; END IF;
  IF jsonb_typeof(q) <> 'object' OR NOT q ?& ARRAY['source','quote_timestamp'] OR EXISTS(SELECT 1 FROM jsonb_object_keys(q) key WHERE key <> ALL(ARRAY['source','quote_timestamp','bid','ask','last'])) THEN RETURN false; END IF;
  IF jsonb_typeof(q->'source') <> 'string' OR (q->>'source') !~ '[^[:space:]]' OR length(q->>'source')>80 OR NOT crier_private.is_stamp(q->'quote_timestamp') THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['bid','ask','last'] LOOP
    IF q ? k AND q->k <> 'null'::jsonb THEN
      IF jsonb_typeof(q->k) <> 'string' OR length(q->>k)>40 OR q->>k !~ '^[+]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN RETURN false; END IF;
      n:=(q->>k)::numeric;
      IF n<0 OR n>1000000000000 THEN RETURN false; END IF;
      IF k='bid' THEN bid:=n; ELSIF k='ask' THEN ask:=n; END IF;
      found_price:=true;
    END IF;
  END LOOP;
  RETURN found_price AND (bid IS NULL OR ask IS NULL OR bid<=ask);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

CREATE FUNCTION public.crier_dispatch(p_method text,p_path text,p_token text DEFAULT '',p_body jsonb DEFAULT '{}'::jsonb,p_query jsonb DEFAULT '{}'::jsonb,p_peer text DEFAULT '')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
  channel_row crier_private.channels%ROWTYPE;
  receiver_row crier_private.receivers%ROWTYPE;
  invite_row crier_private.invitations%ROWTYPE;
  event_row crier_private.events%ROWTYPE;
  raw_token text; code text; v_actor text; role text; kind text; key text;
  digest_token bytea; limit_id bytea; limit_window bigint; limit_count integer; maximum integer; seconds integer:=3600;
  after_cursor bigint:=0; next_cursor bigint; start_cursor bigint:=0; event_uuid uuid; receiver_uuid uuid;
  result jsonb; normalized jsonb; identity_value jsonb; old_value jsonb;
BEGIN
  p_method:=upper(coalesce(p_method,''));
  p_body:=coalesce(p_body,'{}'::jsonb); p_query:=coalesce(p_query,'{}'::jsonb);
  IF octet_length(p_body::text)>16384 THEN RETURN crier_private.fail(413,'Request too large'); END IF;
  IF jsonb_typeof(p_body)<>'object' OR jsonb_typeof(p_query)<>'object' THEN RETURN crier_private.fail(422,'Invalid request'); END IF;
  IF p_method='GET' AND p_path='/health' THEN RETURN crier_private.reply(200,'{"status":"ok","pairing_enabled":true,"protocol":1}'); END IF;
  IF NOT ((p_method='POST' AND p_path IN ('/api/connect/host','/api/connect/invite','/api/connect/receive','/api/sync/events','/api/sync/diagnostics'))
    OR (p_method='GET' AND p_path IN ('/api/connect/receivers','/api/sync/events','/api/sync/clock','/api/sync/diagnostics'))
    OR (p_method='POST' AND p_path ~ '^/api/connect/receivers/[0-9a-f-]{36}/revoke$')) THEN RETURN crier_private.fail(404,'Not Found'); END IF;
  -- p_peer is supplied only by the trusted edge, never from request JSON/headers.
  IF p_path LIKE '/api/connect/%' THEN
    IF p_peer IS NULL OR length(p_peer) NOT BETWEEN 1 AND 200 THEN RETURN crier_private.fail(400,'Peer identity required'); END IF;
    CASE p_path
      WHEN '/api/connect/host' THEN kind:='host';maximum:=5;
      WHEN '/api/connect/invite' THEN kind:='invite';maximum:=60;
      WHEN '/api/connect/receive' THEN kind:='receive';maximum:=20;seconds:=60;
      WHEN '/api/connect/receivers' THEN kind:='list';maximum:=120;seconds:=60;
      ELSE kind:='revoke';maximum:=60;
    END CASE;
    limit_id:=extensions.digest(kind||':'||p_peer,'sha256');
    limit_window:=floor(extract(epoch FROM clock_timestamp())/seconds)::bigint;
    INSERT INTO crier_private.rate_limits AS rl VALUES(limit_id,limit_window,1)
    ON CONFLICT(id) DO UPDATE SET bucket=excluded.bucket,count=CASE WHEN rl.bucket=excluded.bucket THEN least(rl.count+1,1000000) ELSE 1 END
    RETURNING count INTO limit_count;
    IF limit_count>maximum THEN RETURN crier_private.fail(429,'Too many connection requests. Try again later.'); END IF;
  END IF;
  IF p_path='/api/connect/host' THEN
    IF jsonb_typeof(p_body->'name') IS DISTINCT FROM 'string' OR (length(p_body->>'name') NOT BETWEEN 1 AND 60 OR (p_body->>'name') !~ '[^[:space:]]')
      OR (p_body ? 'environment' AND (jsonb_typeof(p_body->'environment')<>'string' OR p_body->>'environment' NOT IN ('paper','live'))) THEN RETURN crier_private.fail(422,'Invalid channel'); END IF;
    -- A transaction lock makes the count-and-create capacity check atomic.
    PERFORM pg_advisory_xact_lock(731924001);
    IF (SELECT count(*) FROM crier_private.channels)>=10000 THEN RETURN crier_private.fail(503,'Connection service capacity reached.'); END IF;
    raw_token:=translate(rtrim(encode(extensions.gen_random_bytes(32),'base64'),'='),'+/','-_');
    INSERT INTO crier_private.channels(name,environment,host_digest) VALUES(p_body->>'name',coalesce(p_body->>'environment','paper'),extensions.digest(raw_token,'sha256')) RETURNING * INTO channel_row;
    RETURN crier_private.reply(200,jsonb_build_object('token',raw_token,'environment',channel_row.environment,'role','host'));
  END IF;
  IF p_path='/api/connect/receive' THEN
    IF jsonb_typeof(p_body->'code') IS DISTINCT FROM 'string' OR length(p_body->>'code') NOT BETWEEN 1 AND 128
       OR (p_body ? 'environment' AND p_body->'environment'<>'null'::jsonb AND (jsonb_typeof(p_body->'environment')<>'string' OR p_body->>'environment' NOT IN ('paper','live'))) THEN RETURN crier_private.fail(422,'Invalid invitation'); END IF;
    code:=upper(regexp_replace(p_body->>'code','[[:space:]-]','','g'));
    IF code !~ '^[A-Z2-7]{16}$' THEN RETURN crier_private.fail(422,'Enter the 16-character invitation code.'); END IF;
    -- Lock channel FIRST everywhere; serialize joining with publishing so the start cursor is exact.
    SELECT c.* INTO channel_row FROM crier_private.channels c JOIN crier_private.invitations i ON i.channel=c.id WHERE i.code_digest=extensions.digest(code,'sha256') FOR UPDATE OF c;
    IF NOT FOUND OR channel_row.revoked THEN RETURN crier_private.fail(401,'Invitation expired, already used or unavailable. Ask the host for a new one.'); END IF;
    SELECT * INTO invite_row FROM crier_private.invitations WHERE code_digest=extensions.digest(code,'sha256') AND expires>clock_timestamp() FOR UPDATE;
    IF NOT FOUND THEN RETURN crier_private.fail(401,'Invitation expired, already used or unavailable. Ask the host for a new one.'); END IF;
    IF p_body->>'environment' IS NOT NULL AND p_body->>'environment'<>channel_row.environment THEN RETURN crier_private.fail(422,'Select the invitation environment before receiving. The invitation has not been consumed.'); END IF;
    SELECT coalesce(max(cursor),0) INTO start_cursor FROM crier_private.events WHERE channel=channel_row.id;
    raw_token:=translate(rtrim(encode(extensions.gen_random_bytes(32),'base64'),'='),'+/','-_');
    INSERT INTO crier_private.receivers(channel,token_digest,start_cursor) VALUES(channel_row.id,extensions.digest(raw_token,'sha256'),start_cursor);
    DELETE FROM crier_private.invitations WHERE code_digest=invite_row.code_digest;
    RETURN crier_private.reply(200,jsonb_build_object('token',raw_token,'environment',channel_row.environment,'role','follower'));
  END IF;
  IF p_token IS NULL OR length(p_token) NOT BETWEEN 1 AND 300 THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
  digest_token:=extensions.digest(p_token,'sha256');
  -- This lock is acquired BEFORE the identity sequence is advanced by INSERT.
  -- Same-channel cursor visibility therefore follows commit order under concurrency.
  SELECT * INTO channel_row FROM crier_private.channels WHERE host_digest=digest_token FOR UPDATE;
  IF FOUND THEN role:='host';v_actor:='host';
  ELSE
    SELECT c.* INTO channel_row FROM crier_private.channels c JOIN crier_private.receivers r ON r.channel=c.id WHERE r.token_digest=digest_token FOR UPDATE OF c;
    IF FOUND THEN
      SELECT * INTO receiver_row FROM crier_private.receivers WHERE token_digest=digest_token AND NOT revoked;
      IF FOUND THEN role:='follower';v_actor:=receiver_row.id::text;start_cursor:=receiver_row.start_cursor; END IF;
    END IF;
  END IF;
  IF role IS NULL OR channel_row.revoked THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
  IF p_path LIKE '/api/connect/%' OR (p_path='/api/sync/events' AND p_method='POST') THEN
    IF role<>'host' THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
  END IF;
  IF p_path='/api/connect/invite' THEN
    -- 80 random bits encoded with the same 16-character base32 alphabet as legacy invitations.
    code:='';
    FOR next_cursor IN 1..16 LOOP code:=code||substr('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567',1+(get_byte(extensions.gen_random_bytes(1),0)%32),1); END LOOP;
    DELETE FROM crier_private.invitations WHERE channel=channel_row.id AND expires<=clock_timestamp();
    INSERT INTO crier_private.invitations VALUES(extensions.digest(code,'sha256'),channel_row.id,clock_timestamp()+interval '10 minutes') RETURNING * INTO invite_row;
    RETURN crier_private.reply(200,jsonb_build_object('code',code,'expires_at',extract(epoch FROM invite_row.expires)));
  ELSIF p_path='/api/connect/receivers' THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'created',extract(epoch FROM created),'revoked',CASE WHEN revoked THEN 1 ELSE 0 END) ORDER BY created,id),'[]'::jsonb) INTO result FROM crier_private.receivers WHERE channel=channel_row.id;
    RETURN crier_private.reply(200,result);
  ELSIF p_path LIKE '/api/connect/receivers/%/revoke' THEN
    UPDATE crier_private.receivers SET revoked=true WHERE channel=channel_row.id AND id::text=split_part(p_path,'/',5);
    RETURN crier_private.reply(200,'{"revoked":true}');
  ELSIF p_path='/api/sync/clock' THEN RETURN crier_private.reply(200,jsonb_build_object('server_time_ms',extract(epoch FROM clock_timestamp())*1000));
  ELSIF p_path='/api/sync/events' AND p_method='POST' THEN
    IF NOT crier_private.valid_event(p_body) THEN RETURN crier_private.fail(422,'Invalid intent event'); END IF;
    IF p_body->>'environment'<>channel_row.environment THEN RETURN crier_private.fail(409,'Channel environment mismatch'); END IF;
    -- Canonical representation mirrors IntentEvent.to_dict() defaults and Decimal JSON string.
    normalized:=p_body||jsonb_build_object('version',1,'limit_price',p_body->>'limit_price');
    SELECT * INTO event_row FROM crier_private.events WHERE channel=channel_row.id AND event_id=(p_body->>'event_id')::uuid;
    IF FOUND THEN
      IF event_row.payload<>normalized THEN RETURN crier_private.fail(409,'Event ID already used with different contents'); END IF;
      RETURN crier_private.reply(200,jsonb_build_object('cursor',event_row.cursor));
    END IF;
    identity_value:=jsonb_build_array(p_body->>'environment',p_body->>'symbol',p_body->>'asset');
    SELECT identity INTO old_value FROM crier_private.events WHERE channel=channel_row.id AND trade_id=(p_body->>'trade_id')::uuid LIMIT 1;
    IF FOUND AND old_value<>identity_value THEN RETURN crier_private.fail(409,'Trade identity cannot change'); END IF;
    IF EXISTS(SELECT 1 FROM crier_private.events WHERE channel=channel_row.id AND trade_id=(p_body->>'trade_id')::uuid AND sequence=(p_body->>'sequence')::integer) THEN RETURN crier_private.fail(409,'Trade sequence already used'); END IF;
    INSERT INTO crier_private.events(channel,event_id,trade_id,sequence,identity,payload) VALUES(channel_row.id,(p_body->>'event_id')::uuid,(p_body->>'trade_id')::uuid,(p_body->>'sequence')::integer,identity_value,normalized) RETURNING cursor INTO next_cursor;
    RETURN crier_private.reply(200,jsonb_build_object('cursor',next_cursor));
  ELSIF p_path='/api/sync/events' THEN
    IF role<>'follower' THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
    IF p_query ? 'after' THEN
      IF jsonb_typeof(p_query->'after') NOT IN ('string','number') OR p_query->>'after' !~ '^[0-9]{1,19}$' OR (p_query->>'after')::numeric>9223372036854775807 THEN RETURN crier_private.fail(422,'Invalid cursor'); END IF;
      after_cursor:=(p_query->>'after')::bigint;
    END IF;
    IF p_query ? 'wait' AND (jsonb_typeof(p_query->'wait') NOT IN ('string','number') OR p_query->>'wait' !~ '^[0-9]+(\.[0-9]+)?$' OR (p_query->>'wait')::numeric>25) THEN RETURN crier_private.fail(422,'Invalid wait'); END IF;
    after_cursor:=greatest(after_cursor,start_cursor);
    SELECT coalesce(jsonb_agg(jsonb_build_object('cursor',cursor,'event',payload) ORDER BY cursor),'[]'::jsonb),coalesce(max(cursor),after_cursor) INTO result,next_cursor FROM (SELECT cursor,payload FROM crier_private.events WHERE channel=channel_row.id AND cursor>after_cursor ORDER BY cursor LIMIT 500) batch;
    RETURN crier_private.reply(200,jsonb_build_object('events',result,'cursor',next_cursor));
  ELSIF p_path='/api/sync/diagnostics' THEN
    IF p_method='POST' THEN
      IF octet_length(p_body::text)>8192 THEN RETURN crier_private.fail(413,'Diagnostic observation too large'); END IF;
      IF NOT p_body ?& ARRAY['event_id','observation'] OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_body) k WHERE k NOT IN ('event_id','observation')) OR NOT crier_private.is_uuid(p_body->'event_id') OR NOT crier_private.valid_observation(p_body->'observation') THEN RETURN crier_private.fail(422,'Invalid diagnostic observation'); END IF;
      event_uuid:=(p_body->>'event_id')::uuid;
    ELSE
      IF NOT crier_private.is_uuid(p_query->'event_id') THEN RETURN crier_private.fail(422,'Invalid event ID'); END IF;
      event_uuid:=(p_query->>'event_id')::uuid;
    END IF;
    SELECT * INTO event_row FROM crier_private.events WHERE channel=channel_row.id AND event_id=event_uuid AND (role='host' OR cursor>start_cursor);
    IF NOT FOUND THEN RETURN crier_private.fail(404,'Event unavailable'); END IF;
    IF p_method='GET' THEN
      SELECT coalesce(jsonb_agg(jsonb_build_object('actor',d.actor,'observation',d.observation) ORDER BY d.actor),'[]'::jsonb) INTO result FROM crier_private.diagnostics d WHERE d.channel=channel_row.id AND d.event_id=event_uuid AND d.actor IN ('host',v_actor);
      RETURN crier_private.reply(200,jsonb_build_object('observations',result));
    END IF;
    IF p_body->'observation'->>'stage'<>(CASE WHEN role='host' THEN 'sender' ELSE 'receiver' END) THEN RETURN crier_private.fail(403,'Observation stage does not match device role'); END IF;
    normalized:=jsonb_build_object('clock_offset_ms',null,'clock_uncertainty_ms',null,'clock_sampled_at',null,'quote',null,'quote_error',null)||(p_body->'observation');
    IF jsonb_typeof(normalized->'quote')='object' THEN normalized:=jsonb_set(normalized,'{quote}',jsonb_build_object('bid',null,'ask',null,'last',null)||(normalized->'quote')); END IF;
    SELECT d.observation INTO old_value FROM crier_private.diagnostics d WHERE d.channel=channel_row.id AND d.event_id=event_uuid AND d.actor=v_actor;
    IF FOUND AND old_value<>normalized THEN RETURN crier_private.fail(409,'Diagnostic evidence is immutable'); END IF;
    INSERT INTO crier_private.diagnostics VALUES(channel_row.id,event_uuid,v_actor,normalized) ON CONFLICT DO NOTHING;
    RETURN crier_private.reply(200,'{"stored":true}');
  END IF;
  RETURN crier_private.fail(404,'Not Found');
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA crier_private FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text) TO service_role;
COMMENT ON FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text) IS 'Trusted relay edge only. Raw bearer token; p_peer must come from platform peer metadata. Returns {status,body}. No table access or tokens for browser clients.';
