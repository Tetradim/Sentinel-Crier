-- Observational reports and server-only private wake hints. Durable rows remain truth.
CREATE TABLE crier_private.status_reports (
 channel uuid NOT NULL REFERENCES crier_private.channels(id) ON DELETE CASCADE,
 trade_id uuid NOT NULL, actor text NOT NULL, event_sequence integer NOT NULL,
 report jsonb NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(channel,trade_id,actor)
);
CREATE TABLE crier_private.presences (
 channel uuid NOT NULL REFERENCES crier_private.channels(id) ON DELETE CASCADE,
 actor text NOT NULL, presence jsonb NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(channel,actor)
);
ALTER TABLE crier_private.status_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE crier_private.presences ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON crier_private.status_reports,crier_private.presences FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION crier_private.valid_revision(v jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(v)='number' AND v::text ~ '^[1-9][0-9]{0,15}$' AND (v::text)::numeric<=9007199254740991,false)
$$;
CREATE FUNCTION crier_private.valid_decimal(v jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE s text;
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
 s:=v#>>'{}';
 RETURN length(s)<=120 AND s ~ '^(0|[1-9][0-9]*)(\.[0-9]+)?$' AND length(regexp_replace(rtrim(ltrim(replace(s,'.',''),'0'),'0'),'[^0-9]','','g'))<=80;
END $$;
CREATE FUNCTION crier_private.valid_status(s jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE k text; q jsonb;
BEGIN
 IF jsonb_typeof(s) IS DISTINCT FROM 'object' OR NOT s ?& ARRAY['version','event_id','revision','observed_at','state','bought','sold'] THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(s) key WHERE key<>ALL(ARRAY['version','event_id','revision','observed_at','broker_observed_at','state','target_quantity','bought','sold','buy_premium','sell_premium','currency','multiplier','fees','quote','reason'])) THEN RETURN false; END IF;
 IF s->'version'<>'1'::jsonb OR NOT crier_private.is_uuid(s->'event_id') OR NOT crier_private.valid_revision(s->'revision') OR NOT crier_private.is_stamp(s->'observed_at') THEN RETURN false; END IF;
 IF coalesce(s->'broker_observed_at','null')<>'null' AND NOT crier_private.is_stamp(s->'broker_observed_at') THEN RETURN false; END IF;
 IF jsonb_typeof(s->'state')<>'string' OR s->>'state' NOT IN ('received','submitted','working','partially_filled','filled','cancel_pending','canceled','closed','blocked','unknown','not_submitted') THEN RETURN false; END IF;
 IF coalesce(s->'reason','null')<>'null' AND (jsonb_typeof(s->'reason')<>'string' OR s->>'reason' NOT IN ('broker_unavailable','reconciliation_required','entries_paused','invalid_instruction','not_submitted','quantity_unavailable','expired','clock_uncertain','client_unavailable')) THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['bought','sold','target_quantity'] LOOP
  IF k='target_quantity' AND coalesce(s->k,'null')='null' THEN CONTINUE; END IF;
  IF jsonb_typeof(s->k)<>'number' OR (s->k)::text !~ '^[0-9]{1,7}$' OR (s->>k)::numeric>(CASE WHEN k='target_quantity' THEN 1000 ELSE 1000000 END) THEN RETURN false; END IF;
 END LOOP;
 IF (s->>'sold')::numeric>(s->>'bought')::numeric THEN RETURN false; END IF;
 FOREACH k IN ARRAY ARRAY['buy_premium','sell_premium','fees'] LOOP
  IF coalesce(s->k,'null')<>'null' AND NOT crier_private.valid_decimal(s->k) THEN RETURN false; END IF;
 END LOOP;
 IF (coalesce(s->'currency','null')='null')<>(coalesce(s->'multiplier','null')='null') THEN RETURN false; END IF;
 IF coalesce(s->'currency','null')<>'null' AND (s->'currency'<>'"USD"' OR s->'multiplier' NOT IN ('1'::jsonb,'100'::jsonb)) THEN RETURN false; END IF;
 IF s->>'buy_premium' IS NOT NULL AND (((s->>'bought')::numeric>0 AND (s->>'buy_premium')::numeric<=0) OR ((s->>'bought')::numeric=0 AND (s->>'buy_premium')::numeric<>0)) THEN RETURN false; END IF;
 IF s->>'sell_premium' IS NOT NULL AND (((s->>'sold')::numeric>0 AND (s->>'sell_premium')::numeric<=0) OR ((s->>'sold')::numeric=0 AND (s->>'sell_premium')::numeric<>0)) THEN RETURN false; END IF;
 IF coalesce(s->'fees','null')<>'null' AND coalesce(s->'currency','null')='null' THEN RETURN false; END IF;
 q:=s->'quote';
 IF coalesce(q,'null')<>'null' AND NOT crier_private.valid_observation(jsonb_build_object('stage','sender','observed_at',s->'observed_at','quote',q)) THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

-- New operations reauthenticate opaque pairing tokens under the same channel lock as publishing/revocation.
ALTER FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text) SET SCHEMA crier_private;
ALTER FUNCTION crier_private.crier_dispatch(text,text,text,jsonb,jsonb,text) RENAME TO dispatch_v1;
CREATE FUNCTION public.crier_dispatch(p_method text,p_path text,p_token text DEFAULT '',p_body jsonb DEFAULT '{}',p_query jsonb DEFAULT '{}',p_peer text DEFAULT '')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c crier_private.channels%ROWTYPE; r crier_private.receivers%ROWTYPE; e crier_private.events%ROWTYPE;
 a text; role_value text; start_at bigint:=0; old jsonb; normalized jsonb; revision numeric; k text; result jsonb; snapshot jsonb; n boolean; omitted boolean:=false;
BEGIN
 IF NOT ((upper(p_method)='POST' AND p_path IN ('/api/sync/status','/api/sync/presence')) OR (upper(p_method)='GET' AND p_path='/api/sync/dashboard')) THEN
  RETURN crier_private.dispatch_v1(p_method,p_path,p_token,p_body,p_query,p_peer);
 END IF;
 IF p_token IS NULL OR length(p_token) NOT BETWEEN 1 AND 300 THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
 SELECT * INTO c FROM crier_private.channels WHERE host_digest=extensions.digest(p_token,'sha256') FOR UPDATE;
 IF FOUND THEN a:='host';role_value:='host'; ELSE
  SELECT ch.* INTO c FROM crier_private.channels ch JOIN crier_private.receivers re ON re.channel=ch.id WHERE re.token_digest=extensions.digest(p_token,'sha256') FOR UPDATE OF ch;
  IF FOUND THEN
   SELECT * INTO r FROM crier_private.receivers WHERE token_digest=extensions.digest(p_token,'sha256') AND NOT revoked;
   IF FOUND THEN a:=r.id::text;role_value:='follower';start_at:=r.start_cursor; END IF;
  END IF;
 END IF;
 IF a IS NULL OR c.revoked THEN RETURN crier_private.fail(401,'Pairing invalid or revoked'); END IF;
 IF jsonb_typeof(p_body) IS DISTINCT FROM 'object' OR jsonb_typeof(p_query) IS DISTINCT FROM 'object' OR p_query<>'{}' OR octet_length(p_body::text)>16384 THEN RETURN crier_private.fail(422,'Invalid request'); END IF;
 IF p_path='/api/sync/presence' THEN
  IF NOT p_body ?& ARRAY['version','revision','observed_at','platform','transport','entries_enabled'] OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_body) key WHERE key<>ALL(ARRAY['version','revision','observed_at','platform','transport','entries_enabled']))
   OR p_body->'version'<>'1'::jsonb OR NOT crier_private.valid_revision(p_body->'revision') OR NOT crier_private.is_stamp(p_body->'observed_at')
   OR jsonb_typeof(p_body->'entries_enabled')<>'boolean' OR jsonb_typeof(p_body->'platform')<>'string' OR p_body->>'platform' NOT IN ('windows','android','ios','python') OR jsonb_typeof(p_body->'transport')<>'string' OR p_body->>'transport' NOT IN ('push','poll','connecting') THEN RETURN crier_private.fail(422,'Invalid presence'); END IF;
  SELECT presence INTO old FROM crier_private.presences WHERE channel=c.id AND actor=a;
  IF FOUND AND (p_body->>'revision')::numeric<=(old->>'revision')::numeric THEN
   IF p_body=old THEN RETURN crier_private.reply(200,'{"stored":true}'); END IF;
   RETURN crier_private.fail(409,'Presence revision conflict');
  END IF;
  INSERT INTO crier_private.presences VALUES(c.id,a,p_body,clock_timestamp()) ON CONFLICT(channel,actor) DO UPDATE SET presence=excluded.presence,received_at=excluded.received_at;
  RETURN crier_private.reply(200,'{"stored":true}');
 ELSIF p_path='/api/sync/status' THEN
  IF NOT crier_private.valid_status(p_body) THEN RETURN crier_private.fail(422,'Invalid status report'); END IF;
  SELECT * INTO e FROM crier_private.events WHERE channel=c.id AND event_id=(p_body->>'event_id')::uuid AND cursor>start_at;
  IF NOT FOUND THEN RETURN crier_private.fail(404,'Event unavailable'); END IF;
  IF p_body->>'multiplier' IS NOT NULL AND (p_body->>'multiplier')::numeric<>(CASE WHEN e.payload->>'asset'='stock' THEN 1 ELSE 100 END) THEN RETURN crier_private.fail(422,'Invalid asset metadata'); END IF;
  normalized:=jsonb_build_object('broker_observed_at',null,'target_quantity',null,'buy_premium',null,'sell_premium',null,'currency',null,'multiplier',null,'fees',null,'quote',null,'reason',null)||p_body;
  IF jsonb_typeof(normalized->'quote')='object' THEN normalized:=jsonb_set(normalized,'{quote}',jsonb_build_object('bid',null,'ask',null,'last',null)||normalized->'quote'); END IF;
  SELECT report INTO old FROM crier_private.status_reports WHERE channel=c.id AND trade_id=e.trade_id AND actor=a;
  IF FOUND THEN
   IF normalized=old THEN RETURN crier_private.reply(200,'{"stored":true}'); END IF;
   IF (normalized->>'revision')::numeric<=(old->>'revision')::numeric OR (normalized->>'bought')::numeric<(old->>'bought')::numeric OR (normalized->>'sold')::numeric<(old->>'sold')::numeric
    OR e.sequence<(SELECT event_sequence FROM crier_private.status_reports WHERE channel=c.id AND trade_id=e.trade_id AND actor=a) THEN RETURN crier_private.fail(409,'Status revision conflict'); END IF;
  END IF;
  INSERT INTO crier_private.status_reports VALUES(c.id,e.trade_id,a,e.sequence,normalized,clock_timestamp()) ON CONFLICT(channel,trade_id,actor) DO UPDATE SET event_sequence=excluded.event_sequence,report=excluded.report,received_at=excluded.received_at;
  RETURN crier_private.reply(200,'{"stored":true}');
 END IF;
 -- Flat snapshot: bounded independently, and every report remains tied to its source event ID.
 WITH eligible AS (SELECT DISTINCT ON (trade_id) payload,cursor,trade_id FROM crier_private.events WHERE channel=c.id AND cursor>start_at ORDER BY trade_id,sequence DESC), bounded AS (SELECT * FROM eligible ORDER BY cursor DESC LIMIT 50)
 SELECT coalesce(jsonb_agg(payload ORDER BY cursor DESC),'[]'),(SELECT count(*)>50 FROM eligible) INTO result,omitted FROM bounded;
 snapshot:=jsonb_build_object('version',1,'channel_id',c.id,'environment',c.environment,'role',role_value,'actor',a,'generated_at',clock_timestamp(),'events',result);
 WITH eligible AS (SELECT 'host'::text actor,'host'::text role,false revoked UNION ALL SELECT id::text,'follower',revoked FROM crier_private.receivers WHERE channel=c.id AND (role_value='host' OR id::text=a)), bounded AS (SELECT * FROM eligible ORDER BY actor LIMIT 200)
 SELECT coalesce(jsonb_agg(jsonb_build_object('actor',m.actor,'role',m.role,'revoked',m.revoked,'last_seen_at',p.received_at,'presence',p.presence) ORDER BY m.actor),'[]'),(SELECT count(*)>200 FROM eligible) INTO result,n FROM bounded m LEFT JOIN crier_private.presences p ON p.channel=c.id AND p.actor=m.actor;
 snapshot:=snapshot||jsonb_build_object('members',result); omitted:=omitted OR n;
 WITH trades AS (SELECT (v->>'trade_id')::uuid id FROM jsonb_array_elements(snapshot->'events') v), eligible AS (SELECT s.* FROM crier_private.status_reports s JOIN crier_private.events source ON source.channel=s.channel AND source.event_id=(s.report->>'event_id')::uuid WHERE s.channel=c.id AND s.trade_id IN (SELECT id FROM trades) AND source.cursor>start_at AND (role_value='host' OR s.actor IN ('host',a))), bounded AS (SELECT * FROM eligible ORDER BY received_at DESC,actor,trade_id LIMIT 200)
 SELECT coalesce(jsonb_agg(jsonb_build_object('actor',actor,'received_at',received_at,'report',report) ORDER BY received_at DESC,actor,trade_id),'[]'),(SELECT count(*)>200 FROM eligible) INTO result,n FROM bounded;
 snapshot:=snapshot||jsonb_build_object('statuses',result); omitted:=omitted OR n;
 WITH trades AS (SELECT (v->>'trade_id')::uuid id FROM jsonb_array_elements(snapshot->'events') v), eligible AS (SELECT d.* FROM crier_private.diagnostics d JOIN crier_private.events source ON source.channel=d.channel AND source.event_id=d.event_id WHERE d.channel=c.id AND source.trade_id IN (SELECT id FROM trades) AND source.cursor>start_at AND (role_value='host' OR d.actor IN ('host',a))), bounded AS (SELECT * FROM eligible ORDER BY event_id,actor LIMIT 200)
 SELECT coalesce(jsonb_agg(jsonb_build_object('event_id',event_id,'actor',actor,'observation',observation) ORDER BY event_id,actor),'[]'),(SELECT count(*)>200 FROM eligible) INTO result,n FROM bounded;
 RETURN crier_private.reply(200,snapshot||jsonb_build_object('diagnostics',result,'truncated',omitted OR n));
END $$;

CREATE FUNCTION public.crier_stream_scope(p_token text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE d jsonb;
BEGIN
 d:=public.crier_dispatch('GET','/api/sync/dashboard',p_token);
 IF d->>'status'<>'200' THEN RETURN d; END IF;
 RETURN crier_private.reply(200,jsonb_build_object('channel_id',d->'body'->'channel_id','role',d->'body'->'role'));
END $$;

CREATE FUNCTION crier_private.wake() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE channel_id uuid;
BEGIN
 IF TG_TABLE_NAME='channels' THEN channel_id:=NEW.id; ELSE channel_id:=NEW.channel; END IF;
 -- Supabase delivers transactional broadcast only after commit. Failure to publish a hint
 -- must never roll back an accepted trading instruction or revocation.
 BEGIN
  PERFORM realtime.send(jsonb_build_object('version',1),'wake','crier:'||channel_id::text,true);
 EXCEPTION WHEN OTHERS THEN NULL;
 END;
 RETURN NEW;
END $$;
CREATE TRIGGER push_event AFTER INSERT ON crier_private.events FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
CREATE TRIGGER push_status AFTER INSERT OR UPDATE ON crier_private.status_reports FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
CREATE TRIGGER push_presence AFTER INSERT OR UPDATE ON crier_private.presences FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
CREATE TRIGGER push_diagnostic AFTER INSERT ON crier_private.diagnostics FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
CREATE TRIGGER push_receiver AFTER INSERT OR UPDATE ON crier_private.receivers FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
CREATE TRIGGER push_channel AFTER UPDATE ON crier_private.channels FOR EACH ROW EXECUTE FUNCTION crier_private.wake();
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA crier_private FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text),public.crier_stream_scope(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crier_dispatch(text,text,text,jsonb,jsonb,text),public.crier_stream_scope(text) TO service_role;


