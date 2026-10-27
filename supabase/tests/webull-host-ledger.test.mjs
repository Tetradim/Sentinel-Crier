import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createGateway } from '../webull-host/gateway.ts';
import { createRpcLedger } from '../webull-host/service.ts';

const owner='b013cf27-fbab-4425-9c6c-6c3236766514';
const order={client_order_id:'a'.repeat(32),account_id:'account-a',environment:'sandbox',asset:'stock',symbol:'AAPL',quantity:2,limit_price:'1.25',side:'buy'};
const receipt=(status='accepted',quantity=0)=>({client_order_id:order.client_order_id,status,filled_quantity:quantity,broker_order_id:'broker-a'});
async function filledBuy(db, changes={}) {
  const buy={...order,...changes};
  await rpc(db,'reserve',{owner,order:buy,fingerprint:JSON.stringify(buy)});
  assert.equal(await rpc(db,'save',{owner,id:buy.client_order_id,revision:1,receipt:{client_order_id:buy.client_order_id,status:'filled',filled_quantity:buy.quantity,broker_order_id:'buy-'+buy.client_order_id},action:'lookup'}),true);
  return buy;
}
const sale=(id='b',quantity=2,changes={})=>({...order,side:'sell',client_order_id:id.repeat(32),quantity,...changes});
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

test('owned fills permit one uncertain sale; duplicates retain reservation and others refuse',async()=>{
  const db=await database();
  try {
    const sell=sale();
    assert.equal((await rpc(db,'reserve',{owner,order:sell,fingerprint:'sell'})).reason,'insufficient_tracked_long_position');
    await filledBuy(db);
    assert.equal((await rpc(db,'reserve',{owner,order:sell,fingerprint:'sell'})).created,true);
    assert.equal((await rpc(db,'reserve',{owner,order:sell,fingerprint:'sell'})).created,false);
    const denied=await rpc(db,'reserve',{owner,order:sale('c',1),fingerprint:'second'});
    assert.deepEqual(denied,{created:false,row:null,reason:'insufficient_tracked_long_position'});
    assert.equal(await rpc(db,'read',{owner,id:'c'.repeat(32)}),null);
  } finally {await db.close();}
});

test('cancel acknowledgement retains quantity; terminal partial cancellation releases only remainder',async()=>{
  const db=await database();
  try {
    await filledBuy(db);
    const sell=sale();
    await rpc(db,'reserve',{owner,order:sell,fingerprint:'sell'});
    const update=(status,filled)=>({client_order_id:sell.client_order_id,status,filled_quantity:filled,broker_order_id:'sell-a'});
    await rpc(db,'save',{owner,id:sell.client_order_id,revision:1,receipt:update('accepted',0),action:'submit'});
    assert.equal((await rpc(db,'reserve',{owner,order:sale('c',1),fingerprint:'second'})).created,false);
    await rpc(db,'save',{owner,id:sell.client_order_id,revision:2,receipt:update('canceled',1),action:'lookup'});
    assert.equal((await rpc(db,'reserve',{owner,order:sale('c',1),fingerprint:'second'})).created,true);
    assert.equal((await rpc(db,'reserve',{owner,order:sale('d',1),fingerprint:'third'})).created,false);
    // A raced revision must not discard contradictory authoritative quantity.
    assert.equal(await rpc(db,'save',{owner,id:sell.client_order_id,revision:1,receipt:update('canceled',2),action:'lookup'}),false);
    const blocked=await rpc(db,'reserve',{owner,order:sale('e',1),fingerprint:'fourth'});
    assert.equal(blocked.reason,'source_inventory_reconciliation_required');
    assert.equal((await rpc(db,'reserve',{owner,order:{...order,client_order_id:'f'.repeat(32)},fingerprint:'new-buy'})).reason,'source_inventory_reconciliation_required');
    assert.equal((await rpc(db,'read',{owner,id:sell.client_order_id})).receipt.filled_quantity,1);
  } finally {await db.close();}
});

test('gateway and real SQL ledger refuse competing source sales before broker dispatch',async()=>{
  const db=await database();let sales=0;
  try {
    const gateway=createGateway({verify:async()=>owner,ledger:createRpcLedger((name,args)=>rpc(db,name.replace('webull_host_',''),args)),
      capabilities:{available:true,environments:['sandbox'],stocks:['AAPL'],options:false},
      provider:{connection:async()=>({state:'connected',environment:'sandbox',account_id:order.account_id}),
        position:async()=>({symbol:'AAPL',quantity:2}),
        submit:async(_owner,o)=>{if(o.side==='sell')sales++;return {client_order_id:o.client_order_id,status:o.side==='buy'?'filled':'accepted',filled_quantity:o.side==='buy'?2:0,broker_order_id:'broker-'+o.client_order_id};},
        begin:async()=>{throw Error('not used');},lookup:async()=>{throw Error('not used');},cancel:async()=>{throw Error('not used');}},timeoutMs:10000});
    const submit=o=>gateway(new Request('https://gateway.test/v1/orders',{method:'POST',headers:{authorization:'Bearer customer','content-type':'application/json'},body:JSON.stringify(o)}));
    assert.equal((await submit(order)).status,200);
    const replies=await Promise.all([submit(sale()),submit(sale('c'))]);
    assert.deepEqual(replies.map(r=>r.status).sort(),[200,409]);
    assert.equal(sales,1);
  } finally {await db.close();}
});

test('unfilled buy quantities never fund sales; rejected sell releases reservation',async()=>{
  const db=await database();
  try {
    await rpc(db,'reserve',{owner,order,fingerprint:'buy'});
    assert.equal((await rpc(db,'reserve',{owner,order:sale('b',1),fingerprint:'sell'})).created,false);
    await rpc(db,'save',{owner,id:order.client_order_id,revision:1,receipt:receipt('partially_filled',1),action:'lookup'});
    assert.equal((await rpc(db,'reserve',{owner,order:sale('b',1),fingerprint:'sell'})).created,true);
    const rejected={client_order_id:'b'.repeat(32),status:'rejected',filled_quantity:0};
    assert.equal(await rpc(db,'save',{owner,id:rejected.client_order_id,revision:1,receipt:rejected,action:'lookup'}),true);
    assert.equal((await rpc(db,'reserve',{owner,order:sale('c',1),fingerprint:'new-sell'})).created,true);
    await db.exec('begin isolation level repeatable read');
    await assert.rejects(()=>rpc(db,'reserve',{owner,order:sale('d',1),fingerprint:'unsafe-snapshot'}),/READ COMMITTED required/);
    await db.exec('rollback');
    await db.exec('set role authenticated');
    await assert.rejects(()=>rpc(db,'block_inventory',{owner,id:order.client_order_id}),/permission denied/);
  } finally {await db.close();}
});

test('inventory does not cross owner/environment/account/asset/symbol boundaries',async()=>{
  const db=await database();
  try {
    await filledBuy(db);
    for(const changes of [{environment:'production'},{account_id:'other'},{symbol:'MSFT'},{asset:'option',symbol:'AAPL261218C00100000'}]) {
      assert.equal((await rpc(db,'reserve',{owner,order:sale('b',1,changes),fingerprint:'sell'})).reason,'insufficient_tracked_long_position');
    }
    assert.equal((await rpc(db,'reserve',{owner:'00000000-0000-4000-8000-000000000001',order:sale(),fingerprint:'sell'})).reason,'insufficient_tracked_long_position');
    assert.equal((await rpc(db,'reserve',{owner,order:sale(),fingerprint:'sell'})).created,true);
    await db.exec('set role authenticated');
    await assert.rejects(()=>db.query('select * from webull_host_private.quantity_scopes'),/permission denied/);
  } finally {await db.close();}
});
