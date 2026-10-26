import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const owner='b013cf27-fbab-4425-9c6c-6c3236766514';
const order={client_order_id:'a'.repeat(32),account_id:'account-a',environment:'sandbox',asset:'stock',symbol:'AAPL',quantity:2,limit_price:'1.25',side:'buy'};
const receipt=(status='accepted',quantity=0)=>({client_order_id:order.client_order_id,status,filled_quantity:quantity,broker_order_id:'broker-a'});
async function database() {
  const db=new PGlite();
  await db.exec('create role anon; create role authenticated; create role service_role;');
  await db.exec(await readFile(new URL('../webull-host/ledger.sql',import.meta.url),'utf8'));
  return db;
}
async function rpc(db,name,args) {
  const values=Object.values(args),parameters=values.map((_,i)=>'$'+(i+1)).join(',');
  const result=await db.query(`select public.webull_host_${name}(${parameters}) as result`,values);
  return result.rows[0].result;
}
test('durable ledger reserves once, isolates owners and CAS-protects receipts',async()=>{
  const db=await database();
  try {
    const first=await rpc(db,'reserve',{owner,order,fingerprint:JSON.stringify(order)});
    assert.equal(first.created,true);
    assert.equal((await rpc(db,'reserve',{owner,order,fingerprint:JSON.stringify(order)})).created,false);
    assert.equal(await rpc(db,'read',{owner:'00000000-0000-0000-0000-000000000001',id:order.client_order_id}),null);
    assert.equal(await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt(),action:'submit'}),true);
    assert.equal(await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt('filled',2),action:'lookup'}),false);
    assert.equal((await rpc(db,'read',{owner,id:order.client_order_id})).receipt.status,'accepted');
  } finally {await db.close();}
});
test('cancel lease cannot rearm during dispatch; completed attempt requires fresh lookup',async()=>{
  const db=await database();
  try {
    await rpc(db,'reserve',{owner,order,fingerprint:JSON.stringify(order)});
    await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt(),action:'submit'});
    const claimed=await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:2});
    assert.equal(claimed.cancel_pending,true);
    await rpc(db,'save',{owner,id:order.client_order_id,revision:claimed.revision,receipt:receipt(),action:'lookup'});
    let row=await rpc(db,'read',{owner,id:order.client_order_id});
    assert.equal(await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:row.revision}),null);
    await rpc(db,'settle_cancel',{owner,id:order.client_order_id,cancelRevision:claimed.cancel_revision});
    row=await rpc(db,'read',{owner,id:order.client_order_id});
    assert.equal(await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:row.revision}),null);
    await rpc(db,'save',{owner,id:order.client_order_id,revision:row.revision,receipt:receipt(),action:'lookup'});
    row=await rpc(db,'read',{owner,id:order.client_order_id});
    assert.ok(await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:row.revision}));
  } finally {await db.close();}
});
test('ledger rejects contradictory fills and changed broker identity',async()=>{
  const db=await database();
  try {
    await rpc(db,'reserve',{owner,order,fingerprint:JSON.stringify(order)});
    await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt(),action:'submit'});
    assert.equal(await rpc(db,'save',{owner,id:order.client_order_id,revision:2,receipt:{...receipt(),broker_order_id:'other'},action:'lookup'}),false);
    await assert.rejects(()=>rpc(db,'save',{owner,id:order.client_order_id,revision:2,receipt:receipt('rejected',1),action:'lookup'}));
  } finally {await db.close();}
});
test('fresh lookup recovers expired cancel lease while old completion cannot settle new attempt',async()=>{
  const db=await database();
  try {
    await rpc(db,'reserve',{owner,order,fingerprint:JSON.stringify(order)});
    await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt(),action:'submit'});
    const first=await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:2});
    await db.exec("update webull_host_private.orders set cancel_started_at=clock_timestamp()-interval '61 seconds'");
    await rpc(db,'save',{owner,id:order.client_order_id,revision:first.revision,receipt:receipt(),action:'lookup'});
    const current=await rpc(db,'read',{owner,id:order.client_order_id});
    const second=await rpc(db,'claim_cancel',{owner,id:order.client_order_id,revision:current.revision});
    assert.equal(second.cancel_pending,true);
    assert.equal(await rpc(db,'settle_cancel',{owner,id:order.client_order_id,cancelRevision:first.cancel_revision}),false);
    assert.equal((await rpc(db,'read',{owner,id:order.client_order_id})).cancel_pending,true);
  } finally {await db.close();}
});
test('customer and anonymous roles cannot invoke privileged ledger RPCs',async()=>{
  const db=await database();
  try {
    for(const role of ['anon','authenticated']) {
      await db.exec('set role '+role);
      await assert.rejects(()=>rpc(db,'read',{owner,id:order.client_order_id}),/permission denied/);
      await db.exec('reset role');
    }
  } finally {await db.close();}
});
