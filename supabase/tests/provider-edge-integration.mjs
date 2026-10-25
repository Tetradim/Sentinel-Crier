// Actual gateway + WebCrypto + candidate SQL; every external request is synthetic.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';
import { createHandler } from '../provider-connect/gateway.ts';
import { sha256 } from '../provider-connect/crypto.ts';

const project='https://abcdefghijklmnopqrst.supabase.co';
const base=project+'/functions/v1/crier-oauth';
const owner='10000000-0000-0000-0000-000000000001';
const other='10000000-0000-0000-0000-000000000002';
const account='20000000-0000-0000-0000-000000000001';
const role='server-role-fixture-1234567890';
const proof='P'.repeat(43);
const tokenA='aaa.bbb.signature-a', tokenB='aaa.bbb.signature-b';
const db=new PGlite();
const calls=[];
let ambiguous=false;
const fakeFetch=async(input,init)=>{
  const request=new Request(input,init); const url=new URL(request.url); calls.push(request);
  if(url.origin===project && url.pathname==='/rest/v1/rpc/crier_oauth_flow') {
    assert.equal(request.headers.get('apikey'),role);
    assert.equal(request.headers.get('authorization'),'Bearer '+role);
    const p=await request.json();
    const result=await db.query('SELECT public.crier_oauth_flow($1,$2::uuid,$3,$4::jsonb) AS result',
      [p.p_action,p.p_owner,p.p_flow,JSON.stringify(p.p_input)]);
    return Response.json(result.rows[0].result);
  }
  if(url.origin===project && url.pathname==='/auth/v1/user') {
    const token=request.headers.get('authorization');
    if(!['Bearer '+tokenA,'Bearer '+tokenB].includes(token)) return Response.json({}, {status:401});
    assert.equal(request.headers.get('apikey'),'sb_publishable_fixture');
    return Response.json({id:token==='Bearer '+tokenA?owner:other,is_anonymous:false});
  }
  if(url.origin===project && url.pathname==='/auth/v1/token') {
    const body=await request.json(); assert.equal(body.email,'customer@example.test');
    assert.equal(body.password,'customer-password');
    return Response.json({access_token:tokenA,refresh_token:'refresh-a',expires_in:3600,token_type:'bearer',user:{id:owner,is_anonymous:false}});
  }
  if(url.href==='https://api.alpaca.markets/oauth/token') {
    assert.equal(request.method,'POST');
    const form=await request.formData(); assert.equal(form.get('client_secret'),'provider-secret');
    if(ambiguous) throw new TypeError('Synthetic connection loss after potential token issuance');
    return Response.json({access_token:'broker-bearer',token_type:'Bearer',scope:''});
  }
  if(url.href==='https://discord.com/api/oauth2/token') {
    return Response.json({access_token:'discord-access',token_type:'Bearer',scope:'webhook.incoming',webhook:{
      id:'123456',type:1,token:'webhook-fixture',guild_id:'234567',channel_id:'345678',
      url:'https://discord.com/api/webhooks/123456/webhook-fixture'}});
  }
  if(url.href==='https://paper-api.alpaca.markets/v2/account') {
    assert.equal(request.headers.get('authorization'),'Bearer broker-bearer');
    assert.equal(request.headers.get('APCA-API-KEY-ID'),null);
    return Response.json({id:account,trading_blocked:true});
  }
  throw Error('Unexpected synthetic network route: '+url.pathname);
};
const handler=createHandler({projectUrl:project,publishableKey:'sb_publishable_fixture',serviceKey:role,
  encryptionKey:new Uint8Array(32).fill(7),keyId:'fixture',applications:[{provider:'alpaca',clientId:'fixture-client',clientSecret:'provider-secret'},
    {provider:'discord',clientId:'123456',clientSecret:'discord-secret'}],fetch:fakeFetch});
function post(path,value,token=tokenA) {
  return handler(new Request(base+path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(value)}));
}
function cookie(response,name) {
  return response.headers.getSetCookie().find(value=>value.startsWith(name+'=')).split(';')[0];
}
const passed=[];
async function scenario(name,operation) { await operation(); passed.push({name,status:'passed'}); }
try {
  await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;');
  await db.exec(await readFile(new URL('../provider-connect/flow_store.sql',import.meta.url),'utf8'));
  await scenario('capabilities and internal prefix use pinned public base',async()=>{
    const response=await handler(new Request('http://internal:9000/crier-oauth/oauth/capabilities'));
    assert.equal(response.status,200); assert.equal((await response.json()).service_url,base);
    assert.equal((await post('/oauth/begin',{},'invalid')).status,401);
  });
  await scenario('customer login does not install browser cookies',async()=>{
    const response=await post('/auth/login',{email:'customer@example.test',password:'customer-password'});
    assert.equal((await response.json()).user.id,owner); assert.equal(response.headers.get('set-cookie'),null);
    assert.equal(response.headers.get('cache-control'),'no-store');
  });
  const start=async(provider='alpaca')=>{
    const response=await post('/oauth/begin',{provider,purpose:'alerts',environment:'paper',challenge:await sha256(proof)});
    assert.equal(response.status,200); return await response.json();
  };
  await scenario('login form durable CSRF and same-owner consent to one-use receipt',async()=>{
    const flow=await start();
    const needsLogin=await handler(new Request(flow.launch_url)); assert.equal(needsLogin.status,303);
    const login=await handler(new Request(needsLogin.headers.get('location')));
    const html=await login.text(); const csrf=/name="csrf" value="([^"]+)"/.exec(html)[1];
    const ticket=new URL(flow.launch_url).searchParams.get('ticket');
    const loginCookie=cookie(login,'__Host-crier-login');
    const form=new URLSearchParams({csrf,ticket,email:'customer@example.test',password:'customer-password'});
    const signIn=()=>handler(new Request(base+'/auth/browser',{method:'POST',headers:{Origin:project,'Content-Type':'application/x-www-form-urlencoded',Cookie:loginCookie},body:form}));
    const signed=await signIn(); assert.equal(signed.status,303);
    assert.equal((await signIn()).status,401); // durable CSRF claim prevents simultaneous/repeated use
    const sessionCookie=cookie(signed,'__Host-crier-session');
    const launched=await handler(new Request(flow.launch_url,{headers:{Cookie:sessionCookie}}));
    assert.equal(launched.status,303); const authorize=new URL(launched.headers.get('location'));
    assert.equal(authorize.origin,'https://app.alpaca.markets'); assert.equal(authorize.searchParams.has('scope'),false);
    const state=authorize.searchParams.get('state');
    const flowCookie=launched.headers.getSetCookie()[0].split(';')[0];
    const callbackUrl=base+'/oauth/callback/alpaca?state='+state+'&code=synthetic-code';
    const callback=await handler(new Request(callbackUrl,{headers:{Cookie:sessionCookie+'; '+flowCookie}}));
    assert.equal(callback.status,303); assert.equal(callback.headers.get('location'),'sentinelcrier://oauth/complete?flow='+flow.flow);
    assert.equal(JSON.stringify([...callback.headers]).includes('broker-bearer'),false);
    const status=await (await post('/oauth/status',{flow:flow.flow})).json(); assert.equal(status.stage,'ready');
    assert.equal(JSON.stringify(status).includes('ciphertext'),false); assert.equal(JSON.stringify(status).includes('challenge'),false);
    assert.equal((await post('/oauth/redeem',{flow:flow.flow,proof},tokenB)).status,400);
    const receipt=await (await post('/oauth/redeem',{flow:flow.flow,proof})).json();
    assert.equal(receipt.credential,'broker-bearer'); assert.equal(receipt.account_id,account);
    assert.equal((await post('/oauth/redeem',{flow:flow.flow,proof})).status,400);
    const stored=await db.query('SELECT grant_ciphertext,state_ciphertext,stage FROM crier_provider.flows WHERE flow_id=$1',[flow.flow]);
    assert.equal(stored.rows[0].grant_ciphertext,null); assert.equal(stored.rows[0].stage,'redeemed');
  });
  await scenario('shared launch ticket cannot bind a different browser customer',async()=>{
    const flow=await start();
    const foreign=await handler(new Request(flow.launch_url,{headers:{Cookie:'__Host-crier-session='+tokenB}}));
    assert.equal(foreign.status,400);
    assert.equal((await (await post('/oauth/status',{flow:flow.flow})).json()).stage,'pending');
  });
  await scenario('ambiguous exchange remains nonretryable; cancel removes custody',async()=>{
    const flow=await start(); const session='__Host-crier-session='+tokenA;
    const launched=await handler(new Request(flow.launch_url,{headers:{Cookie:session}}));
    const state=new URL(launched.headers.get('location')).searchParams.get('state');
    ambiguous=true;
    const callback=()=>handler(new Request(base+'/oauth/callback/alpaca?state='+state+'&code=lost',{headers:{Cookie:session+'; '+launched.headers.getSetCookie()[0].split(';')[0]}}));
    assert.equal((await callback()).status,303); assert.equal((await callback()).status,400);
    assert.equal((await (await post('/oauth/status',{flow:flow.flow})).json()).stage,'exchanging');
    assert.equal((await post('/oauth/cancel',{flow:flow.flow,proof})).status,200);
    assert.equal((await (await post('/oauth/status',{flow:flow.flow})).json()).stage,'cancelled');
  });
  await scenario('Discord issuer/cookie denial and verified channel receipt use actual SQL',async()=>{
    const session='__Host-crier-session='+tokenA;
    const launch=async()=>{
      const flow=await start('discord'); const response=await handler(new Request(flow.launch_url,{headers:{Cookie:session}}));
      const target=new URL(response.headers.get('location'));
      assert.equal(target.origin,'https://discord.com'); assert.equal(target.searchParams.get('scope'),'webhook.incoming');
      return {flow,state:target.searchParams.get('state'),cookie:session+'; '+response.headers.getSetCookie()[0].split(';')[0]};
    };
    const denied=await launch();
    const callback=(entry,query)=>handler(new Request(base+'/oauth/callback/discord?state='+entry.state+query,{headers:{Cookie:entry.cookie}}));
    assert.equal((await callback(denied,'&code=code')).status,400);
    assert.equal((await callback(denied,'&code=code&iss=https%3A%2F%2Fevil.test')).status,400);
    assert.equal((await (await post('/oauth/status',{flow:denied.flow.flow})).json()).stage,'launched');
    assert.equal((await callback(denied,'&error=access_denied&iss=https%3A%2F%2Fdiscord.com')).status,303);
    assert.equal((await (await post('/oauth/status',{flow:denied.flow.flow})).json()).stage,'failed');
    const accepted=await launch();
    assert.equal((await callback(accepted,'&code=code&iss=https%3A%2F%2Fdiscord.com')).status,303);
    const receipt=await (await post('/oauth/redeem',{flow:accepted.flow.flow,proof})).json();
    assert.equal(receipt.credential,'https://discord.com/api/webhooks/123456/webhook-fixture');
    assert.equal(receipt.channel_id,'345678'); assert.deepEqual(receipt.scopes,['webhook.incoming']);
    assert.equal((await post('/oauth/redeem',{flow:accepted.flow.flow,proof})).status,400);
  });
  const snapshot=await db.query('SELECT to_jsonb(f) AS row FROM crier_provider.flows f');
  const serialized=JSON.stringify(snapshot.rows);
  for(const secret of ['customer-password',tokenA,'broker-bearer','synthetic-code','provider-secret']) assert.equal(serialized.includes(secret),false);
  const report={schema:'crier.provider-edge-acceptance.v1',scenarios:passed,external_calls:'synthetic_only',broker_orders:0,discord_messages:0,deployed:false};
  console.log(JSON.stringify(report,null,2));
} finally { await db.close(); }
