/** Full synthetic HTTP/browser -> coordinator -> vault -> actual SQL composition. */
import {PGlite} from '@electric-sql/pglite';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import {createApplication} from '../webull-host/application.ts';
const owner='b013cf27-fbab-4425-9c6c-6c3236766514';
const project='https://abcdefghijklmnopqrst.supabase.co',base=project+'/functions/v1/crier-webull-host';
const tabular=new Set(['crier_webull_authorization_begin','crier_webull_authorization_consume','crier_webull_token_read','crier_webull_token_claim_refresh']);
test('complete browser consent, encrypted persistence, refresh and revocation through deployable application',async()=>{
 const db=new PGlite();let exchanges=0;
 try{
  await db.exec('create role anon;create role authenticated;create role service_role;');
  for(const file of ['session_store.sql','token_store.sql','authorization_flow.sql','operations.sql'])await db.exec(await readFile(new URL('../webull-connect/'+file,import.meta.url),'utf8'));
  for(const file of ['ledger.sql','browser_store.sql'])await db.exec(await readFile(new URL('../webull-host/'+file,import.meta.url),'utf8'));
  const fetcher=async(url,init)=>{
   const text=String(url);
   if(text===project+'/auth/v1/user')return Response.json({id:owner,is_anonymous:false});
   if(text.startsWith(project+'/rest/v1/rpc/')){
    const name=text.slice((project+'/rest/v1/rpc/').length);assert.match(name,/^(?:crier_webull_|webull_host_)[a-z_]+$/);
    const entries=Object.entries(JSON.parse(init.body));assert.ok(entries.every(([k])=>/^p_[a-z_]+$/.test(k)));
    const args=entries.map(([k],i)=>`${k} => $${i+1}`).join(',');
    const result=await db.query(`select * from public.${name}(${args})`,entries.map(([,v])=>v&&typeof v==='object'?JSON.stringify(v):v));
    return Response.json(tabular.has(name)?result.rows:result.rows[0]?.[name]??null);
   }
   assert.equal(text,'https://oauth-open-api.sandbox.webull.com/oauth2/tokens/create');
   assert.equal(init.redirect,'error');assert.ok(new Headers(init.headers).get('x-signature'));
   exchanges++;
   return Response.json({access_token:'fixture-access',refresh_token:'fixture-refresh',identity_id:'fixture-identity',token_type:'Bearer',created_at:new Date().toISOString(),expires_in:'1800',rt_expires_in:'86400'});
  };
  const options={projectUrl:project,publishableKey:'fixture-public',serviceRoleKey:'fixture-service',fetch:fetcher,authorization:{environment:'sandbox',approved:true,clientId:'fixture-client',clientSecret:'fixture-client-secret',scope:'fixture-only',appKey:'fixture-app',appSecret:'fixture-app-secret',vaultKey:Buffer.alloc(32,7).toString('base64url'),keyId:'fixture'}};
  let app=await createApplication(options);
  const request=(path,body,headers={})=>app(new Request(base+path,{method:body?'POST':'GET',headers:{...(body?{'content-type':'application/json'}:{}),...headers},...(body?{body:JSON.stringify(body)}:{})}));
  const auth={authorization:'Bearer fixture-customer'};
  const caps=await (await request('/v1/capabilities',undefined,auth)).json();assert.equal(caps.authorization_available,true);assert.equal(caps.available,false);
  const begin=await (await request('/v1/connect/begin',{environment:'sandbox'},auth)).json();assert.equal(exchanges,0);
  const launched=await app(new Request(begin.authorization_url));assert.equal(launched.status,303);
  const cookie=launched.headers.get('set-cookie').split(';')[0],state=new URL(launched.headers.get('location')).searchParams.get('state');
  const callback='/v1/connect/callback?state='+state+'&code=fixture-code';
  assert.equal((await request(callback)).status,400);assert.equal(exchanges,0);
  assert.equal((await request(callback,undefined,{cookie})).status,200);assert.equal(exchanges,1);
  assert.equal((await request(callback,undefined,{cookie})).status,400);assert.equal(exchanges,1);
  const stored=await db.query('select envelope from crier_webull_private.token_states');
  assert.ok(!JSON.stringify(stored.rows).includes('fixture-access'));
  assert.equal((await (await request('/v1/connect/status?environment=sandbox',undefined,auth)).json()).state,'active');
  assert.equal((await request('/v1/connect/refresh',{environment:'sandbox'},auth)).status,200);assert.equal(exchanges,2);
  app=await createApplication({...options,authorization:{...options.authorization,keyId:'next',vaultKey:Buffer.alloc(32,8).toString('base64url'),previousVaultKeys:{fixture:options.authorization.vaultKey}}});
  assert.equal((await request('/v1/connect/refresh',{environment:'sandbox'},auth)).status,200);assert.equal(exchanges,3);
  assert.equal((await db.query('select envelope from crier_webull_private.token_states')).rows[0].envelope.key_id,'next');
  const unused=await (await request('/v1/connect/begin',{environment:'sandbox'},auth)).json();
  assert.equal((await request('/v1/connect/revoke',{environment:'sandbox'},auth)).status,200);
  assert.equal((await app(new Request(unused.authorization_url))).status,400);
  assert.equal((await (await request('/v1/connect/status?environment=sandbox',undefined,auth)).json()).state,'revoked');
  assert.equal((await request('/v1/orders',{},auth)).status,503);
 }finally{await db.close();}
});
