import {PGlite} from '@electric-sql/pglite';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
const owner='b013cf27-fbab-4425-9c6c-6c3236766514',hash='a'.repeat(64),state='b'.repeat(64);
async function database(){const db=new PGlite();try{await db.exec('create role anon;create role authenticated;create role service_role;');await db.exec(await readFile(new URL('../webull-host/browser_store.sql',import.meta.url),'utf8'));return db;}catch(error){await db.close();throw error;}}
async function rpc(db,name,values){return (await db.query(`select public.webull_host_${name}(${values.map((_,i)=>'$'+(i+1)).join(',')}) as value`,values)).rows[0].value;}
test('launch tickets are single-use; callback resolves stored owner and completes once',async()=>{
 const db=await database();try{
  const first=await rpc(db,'browser_issue',[owner,'sandbox',hash]);assert.equal(first.owner,owner);assert.equal(first.state_hash,null);
  assert.equal((await rpc(db,'browser_launch',[hash])).id,first.id);assert.equal(await rpc(db,'browser_launch',[hash]),null);
  assert.equal(await rpc(db,'browser_attach',[first.id,state,Date.now()+290000]),true);
  assert.equal((await rpc(db,'browser_resolve',[state])).owner,owner);
  assert.equal(await rpc(db,'browser_complete',[first.id]),true);assert.equal(await rpc(db,'browser_resolve',[state]),null);
 }finally{await db.close();}
});
test('revocation invalidates unused launch and pending callback state; expired tickets cannot launch',async()=>{
 const db=await database();try{
  await rpc(db,'browser_issue',[owner,'sandbox',hash]);await rpc(db,'browser_invalidate',[owner,'sandbox']);assert.equal(await rpc(db,'browser_launch',[hash]),null);
  await rpc(db,'browser_issue',[owner,'sandbox','c'.repeat(64)]);await db.exec("update webull_host_private.browser_flows set expires_at=clock_timestamp()-interval '1 second'");assert.equal(await rpc(db,'browser_launch',['c'.repeat(64)]),null);
 }finally{await db.close();}
});
test('durable admission separates customers and actual-broker/request scopes',async()=>{
 const db=await database();try{
  assert.equal(await rpc(db,'admit',[owner,'http',2]),true);assert.equal(await rpc(db,'admit',[owner,'http',2]),true);assert.equal(await rpc(db,'admit',[owner,'http',2]),false);
  assert.equal(await rpc(db,'admit',[owner,'webull',2]),true);
  assert.equal(await rpc(db,'admit',['00000000-0000-0000-0000-000000000001','http',2]),true);
  await db.exec("update webull_host_private.request_events set observed_at=clock_timestamp()-interval '61 seconds'");assert.equal(await rpc(db,'admit',[owner,'http',2]),true);
  await assert.rejects(()=>rpc(db,'admit',[owner,'http',1000]));
 }finally{await db.close();}
});
test('customer roles cannot read flow secrets or call browser RPCs',async()=>{
 const db=await database();try{for(const role of ['anon','authenticated']){await db.exec('set role '+role);await assert.rejects(()=>rpc(db,'browser_launch',[hash]),/permission denied/);await assert.rejects(()=>db.query('select * from webull_host_private.browser_flows'),/permission denied/);await db.exec('reset role');}}finally{await db.close();}
});
