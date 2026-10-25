BEGIN;
CREATE FUNCTION pg_temp.pb(o uuid,f text,c text DEFAULT repeat('a',64)) RETURNS jsonb LANGUAGE sql AS $$
 SELECT public.crier_oauth_flow('begin',o,f,jsonb_build_object('provider','alpaca','purpose','alerts','environment','paper','challenge',c,'ticket_hash',lpad(ascii(right(f,1))::text,64,'0'),'state_hash',lpad((ascii(right(f,1))+100)::text,64,'0'),'state_ciphertext',jsonb_build_object('version',1,'key_id','test','nonce',repeat('a',16),'ciphertext',repeat('b',22))))
$$;
DO $$
DECLARE o uuid:='10000000-0000-0000-0000-000000000001'; other uuid:='10000000-0000-0000-0000-000000000002'; f text:=repeat('A',42)||'a'; r jsonb; old jsonb; g jsonb; i integer;
BEGIN
 ASSERT NOT has_function_privilege('anon','public.crier_oauth_flow(text,uuid,text,jsonb)','EXECUTE');
 ASSERT NOT has_function_privilege('authenticated','public.crier_oauth_flow(text,uuid,text,jsonb)','EXECUTE');
 ASSERT has_function_privilege('service_role','public.crier_oauth_flow(text,uuid,text,jsonb)','EXECUTE');
 BEGIN
  SET LOCAL ROLE anon;
  PERFORM public.crier_oauth_flow('status',o,f,'{}');
  RAISE EXCEPTION 'anon unexpectedly invoked custody';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
  SET LOCAL ROLE authenticated;
  PERFORM public.crier_oauth_flow('status',o,f,'{}');
  RAISE EXCEPTION 'authenticated unexpectedly invoked custody';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 SET LOCAL ROLE service_role;
 ASSERT public.crier_oauth_flow('status',o,f,'{}')->>'ok'='false';
 RESET ROLE;
 ASSERT NOT has_schema_privilege('service_role','crier_provider','USAGE');
 ASSERT NOT has_table_privilege('service_role','crier_provider.flows','SELECT');
 ASSERT (SELECT relrowsecurity FROM pg_class WHERE oid='crier_provider.flows'::regclass);
 r:=pg_temp.pb(o,f); ASSERT r->>'ok'='true'; old:=r->'flow';
 ASSERT (old->>'expires_at')::bigint-(old->>'created_at')::bigint=300000;
 ASSERT public.crier_oauth_flow('status',other,f,'{}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('status',o,f,'{"extra":true}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('launch',other,NULL,jsonb_build_object('ticket_hash',old->>'ticket_hash','binding_hash',repeat('b',64)))->>'ok'='false';
 r:=public.crier_oauth_flow('launch',o,NULL,jsonb_build_object('ticket_hash',old->>'ticket_hash','binding_hash',repeat('b',64)));
 ASSERT r->>'ok'='true' AND r->'flow'->>'stage'='launched' AND r->'flow'->'state_ciphertext'=old->'state_ciphertext';
 ASSERT (SELECT state_ciphertext IS NULL AND ticket_hash IS NULL FROM crier_provider.flows WHERE flow_id=f);
 ASSERT public.crier_oauth_flow('launch',o,NULL,jsonb_build_object('ticket_hash',old->>'ticket_hash','binding_hash',repeat('b',64)))->>'ok'='false';
 ASSERT public.crier_oauth_flow('claim',o,NULL,jsonb_build_object('provider','alpaca','state_hash',old->>'state_hash','binding_hash',repeat('c',64)))->>'ok'='false';
 ASSERT public.crier_oauth_flow('claim',o,NULL,jsonb_build_object('provider','discord','state_hash',old->>'state_hash','binding_hash',repeat('b',64)))->>'ok'='false';
 r:=public.crier_oauth_flow('claim',o,NULL,jsonb_build_object('provider','alpaca','state_hash',old->>'state_hash','binding_hash',repeat('b',64)));
 ASSERT r->>'ok'='true' AND r->'flow'->>'stage'='exchanging';
 ASSERT (SELECT state_hash IS NULL AND binding_hash IS NULL FROM crier_provider.flows WHERE flow_id=f);
 g:=jsonb_build_object('version',1,'key_id','test','nonce',repeat('c',16),'ciphertext',repeat('d',22));
 ASSERT public.crier_oauth_flow('complete',o,f,'{"grant_ciphertext":null}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('complete',o,f,jsonb_build_object('grant_ciphertext',g||'{"secret":"bad"}'))->>'ok'='false';
 r:=public.crier_oauth_flow('complete',o,f,jsonb_build_object('grant_ciphertext',g));
 ASSERT r->>'ok'='true' AND r->'flow'->>'stage'='ready';
 ASSERT (r->'flow'->>'ready_until')::bigint<=(old->>'expires_at')::bigint;
 ASSERT public.crier_oauth_flow('redeem',o,f,jsonb_build_object('proof_hash',repeat('e',64)))->>'ok'='false';
 r:=public.crier_oauth_flow('redeem',o,f,jsonb_build_object('proof_hash',repeat('a',64)));
 ASSERT r->>'ok'='true' AND r->'flow'->'grant_ciphertext'=g AND r->'flow'->>'stage'='redeemed';
 ASSERT (SELECT grant_ciphertext IS NULL FROM crier_provider.flows WHERE flow_id=f);
 ASSERT public.crier_oauth_flow('redeem',o,f,jsonb_build_object('proof_hash',repeat('a',64)))->>'ok'='false';
 ASSERT public.crier_oauth_flow('cancel',o,f,jsonb_build_object('proof_hash',repeat('a',64)))->'flow'->>'stage'='redeemed';
 FOR i IN 1..8 LOOP
  f:=repeat('B',42)||chr(96+i);
  ASSERT pg_temp.pb(o,f,repeat(CASE WHEN i<=4 THEN 'a' ELSE 'b' END,64))->>'ok'='true';
  IF i=4 THEN ASSERT pg_temp.pb(o,repeat('B',42)||'x')->>'ok'='false','challenge quota'; END IF;
 END LOOP;
 ASSERT pg_temp.pb(o,repeat('B',42)||'z',repeat('c',64))->>'ok'='false','owner quota';
 f:=repeat('B',42)||'a';
 ASSERT public.crier_oauth_flow('cancel',o,f,jsonb_build_object('proof_hash',repeat('a',64)))->'flow'->>'stage'='cancelled';
 ASSERT (SELECT ticket_hash IS NULL AND state_ciphertext IS NULL AND state_hash IS NULL FROM crier_provider.flows WHERE flow_id=f);
 ASSERT pg_temp.pb(o,repeat('B',42)||'z',repeat('c',64))->>'ok'='true';
 f:=repeat('B',42)||'b';
 UPDATE crier_provider.flows SET created_at=0,expires_at=300000 WHERE flow_id=f;
 ASSERT public.crier_oauth_flow('status',other,f,'{}')->>'ok'='false';
 ASSERT (SELECT state_ciphertext IS NOT NULL FROM crier_provider.flows WHERE flow_id=f);
 ASSERT public.crier_oauth_flow('redeem',o,f,jsonb_build_object('proof_hash',repeat('a',64)))->>'ok'='false';
 ASSERT (SELECT stage='expired' AND state_ciphertext IS NULL AND ticket_hash IS NULL AND state_hash IS NULL FROM crier_provider.flows WHERE flow_id=f);
 ASSERT public.crier_oauth_flow('status',o,f,'{}')->'flow'->>'stage'='expired';
 ASSERT public.crier_oauth_flow('cleanup',o,NULL,'{"limit":1}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('cleanup',NULL,NULL,'{"limit":1001}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('cleanup',NULL,NULL,'{"limit":"1"}')->>'ok'='false';
 ASSERT public.crier_oauth_flow('cleanup',NULL,NULL,'{"limit":1}')->>'count'='1';
END $$;
DO $$
DECLARE o uuid:='30000000-0000-0000-0000-000000000001'; f text:=repeat('C',43); r jsonb; g jsonb; deadline bigint;
BEGIN
 g:=jsonb_build_object('version',1,'key_id','test','nonce',repeat('a',16),'ciphertext',repeat('b',22));
 r:=pg_temp.pb(o,f); ASSERT r->>'ok'='true';
 ASSERT public.crier_oauth_flow('fail',o,f,'{}')->>'ok'='false';
 UPDATE crier_provider.flows SET stage='exchanging',ticket_hash=NULL,state_hash=NULL,state_ciphertext=NULL WHERE flow_id=f;
 ASSERT public.crier_oauth_flow('fail',o,f,'{}')->'flow'->>'stage'='failed';
 ASSERT public.crier_oauth_flow('complete',o,f,jsonb_build_object('grant_ciphertext',g))->>'ok'='false';
 DELETE FROM crier_provider.flows WHERE flow_id=f;
 r:=pg_temp.pb(o,f);
 UPDATE crier_provider.flows SET stage='ready',ready_until=created_at,grant_ciphertext=g,ticket_hash=NULL,state_hash=NULL,state_ciphertext=NULL WHERE flow_id=f;
 ASSERT public.crier_oauth_flow('redeem',o,f,jsonb_build_object('proof_hash',repeat('a',64)))->>'ok'='false';
 ASSERT (SELECT stage='expired' AND grant_ciphertext IS NULL FROM crier_provider.flows WHERE flow_id=f);
 deadline:=floor(extract(epoch FROM clock_timestamp())*1000)::bigint+300000;
 ASSERT public.crier_oauth_flow('csrf_claim',NULL,NULL,jsonb_build_object('hash',repeat('f',64),'expires_at',deadline))->>'claimed'='true';
 ASSERT public.crier_oauth_flow('csrf_claim',NULL,NULL,jsonb_build_object('hash',repeat('f',64),'expires_at',deadline))->>'claimed'='false';
 ASSERT public.crier_oauth_flow('csrf_claim',o,NULL,jsonb_build_object('hash',repeat('f',64),'expires_at',deadline))->>'ok'='false';
 ASSERT public.crier_oauth_flow('csrf_claim',NULL,NULL,jsonb_build_object('hash',repeat('d',64),'expires_at',1))->>'ok'='false';
 ASSERT public.crier_oauth_flow('csrf_claim',NULL,NULL,jsonb_build_object('hash',repeat('d',64),'expires_at',deadline+999999))->>'ok'='false';
 ASSERT NOT has_table_privilege('service_role','crier_provider.csrf_used','SELECT');
END $$;
ROLLBACK;


