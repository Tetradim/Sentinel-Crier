/** Synthetic, in-memory acceptance only. No endpoint, credentials or network inputs. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { createCoordinator } from '../webull-connect/coordinator.ts';
import { createRpcStore } from '../webull-connect/rpc_store.ts';
import { createOperations } from '../webull-connect/operations.ts';
import { createTokenVault, importVaultKey } from '../webull-connect/token_vault.ts';

const folder = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(folder, '../..');
const scalar = new Set(['crier_webull_token_commit','crier_webull_token_mark_unknown',
  'crier_webull_authorization_revoke','crier_webull_token_rewrap','crier_webull_cleanup_expired_sessions']);
const table = new Set(['crier_webull_authorization_begin','crier_webull_authorization_consume',
  'crier_webull_token_read','crier_webull_token_claim_refresh']);
const config = Object.freeze({environment:'sandbox',clientId:'fixture-client',clientSecret:'fixture-client-secret',
  scope:'fixture-only',callback:'https://example.test/callback',
  approvedBrowserEntry:'https://passport.webull.com/oauth2/sandbox/authenticate/login',
  integrationApproved:true,signingReady:true});
function response(identity = 'fixture-identity') {
  return {access_token:'fixture-access',refresh_token:'fixture-refresh',identity_id:identity,
    token_type:'Bearer',created_at:new Date().toISOString(),expires_in:'60',rt_expires_in:'3600'};
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise,resolve};
}
async function within(promise, milliseconds = 2000) {
  let timer;
  try {
    return await Promise.race([promise,new Promise((_resolve,reject) => {
      timer = setTimeout(()=>reject(new Error('Synthetic scenario deadline exceeded')),milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
function callbackInput(auth) {
  return {state:new URL(auth.url()).searchParams.get('state'),browserBinding:auth.browserBinding(),code:'fixture-code'};
}

export async function runAcceptance() {
  const database = new PGlite({extensions:{pgcrypto}});
  const scenarios = [];
  try {
    await database.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA extensions;');
    for (const file of (await readdir(path.join(folder,'../migrations'))).filter(name => name.endsWith('.sql')).sort()) {
      await database.exec(await readFile(path.join(folder,'../migrations',file),'utf8'));
    }
    for (const file of ['session_store.sql','token_store.sql','authorization_flow.sql','operations.sql']) {
      await database.exec(await readFile(path.join(folder,'../webull-connect',file),'utf8'));
    }
    await database.exec('SET ROLE service_role');
    const store = createRpcStore(async (name, parameters) => {
      assert.ok(scalar.has(name) || table.has(name), 'Only fixed candidate RPCs may be invoked');
      const entries = Object.entries(parameters);
      // Identifiers originate only from the adapter's fixed maps; values are bound.
      assert.ok(entries.every(([key]) => /^p_[a-z_]+$/.test(key)));
      const args = entries.map(([key],index) => `${key} => $${index+1}`).join(',');
      const values = entries.map(([,value]) => value && typeof value === 'object' ? JSON.stringify(value) : value);
      try {
        const result = await database.query(`SELECT * FROM public.${name}(${args})`,values);
        const rows = JSON.parse(JSON.stringify(result.rows)); // Match PostgREST's timestamp serialization.
        return {data:scalar.has(name)?rows[0]?.[name]:rows,error:null};
      } catch { return {data:null,error:true}; }
    });
    const oldKey = await importVaultKey(new Uint8Array(32).fill(5));
    const newKey = await importVaultKey(new Uint8Array(32).fill(6));
    const oldVault = createTokenVault('old',new Map([['old',oldKey]]));
    const rotatedVault = createTokenVault('next',new Map([['old',oldKey],['next',newKey]]));
    function fixture(owner, dispatch = async () => response(), timeoutMs = 1000) {
      let calls = 0;
      const verifyPrincipal = async auth => { if (auth !== `auth:${owner}`) throw new Error('Denied synthetic principal'); return owner; };
      const coordinator = createCoordinator({config,store,vault:oldVault,verifyPrincipal,timeoutMs,
        transport:async (request,signal) => {
          calls++;
          assert.equal(request.endpoint,'https://oauth-open-api.sandbox.webull.com/oauth2/tokens/create');
          const form = new URLSearchParams(request.serializeForm());
          assert.equal(form.get('client_secret'),config.clientSecret);
          assert.ok(['authorization_code','refresh_token'].includes(form.get('grant_type')));
          return await dispatch(form,signal);
        }});
      return {coordinator,verifyPrincipal,calls:()=>calls,auth:`auth:${owner}`};
    }
    async function scenario(id, run) { await run(); scenarios.push({id,status:'passed'}); }

    await scenario('exchange-encrypted-persistence-refresh-replay',async () => {
      const f = fixture('offline-login'), c = f.coordinator;
      const auth = await c.begin(f.auth), input = callbackInput(auth);
      assert.equal((await c.callback(f.auth,input)).generation,1);
      const row = await store.read('offline-login','sandbox');
      assert.equal(row.state,'active');
      const opened = await oldVault.open({ownerRef:'offline-login',environment:'sandbox',generation:1},row.envelope,Date.now());
      assert.equal(opened.accessToken(),'fixture-access');
      assert.ok(!JSON.stringify(row).includes('fixture-access'));
      await assert.rejects(c.callback(f.auth,input)); assert.equal(f.calls(),1);
      assert.equal((await c.refresh(f.auth)).generation,2); assert.equal(f.calls(),2);
      await assert.rejects(oldVault.open({ownerRef:'offline-login',environment:'sandbox',generation:1},(await store.read('offline-login','sandbox')).envelope,Date.now()));
    });
    await scenario('forged-principal-and-browser-binding-rejected',async () => {
      const f = fixture('offline-binding'), input = callbackInput(await f.coordinator.begin(f.auth));
      await assert.rejects(f.coordinator.callback('forged',input));
      await assert.rejects(f.coordinator.callback(f.auth,{...input,browserBinding:'A'.repeat(43)}));
      assert.equal(f.calls(),0);
      assert.equal((await f.coordinator.callback(f.auth,input)).state,'active');
    });
    await scenario('revocation-fences-in-flight-exchange',async () => {
      const entered = deferred(), held = deferred();
      const f = fixture('offline-revoke',async () => { entered.resolve(); return await held.promise; });
      const input = callbackInput(await f.coordinator.begin(f.auth));
      const pending = f.coordinator.callback(f.auth,input);
      const rejected = assert.rejects(pending);
      await within(entered.promise);
      await f.coordinator.revoke(f.auth); held.resolve(response()); await rejected;
      const row = await store.read('offline-revoke','sandbox');
      assert.equal(row.state,'revoked'); assert.equal(row.envelope,null);
    });
    await scenario('lost-refresh-response-requires-new-authorization',async () => {
      let lose = false;
      const f = fixture('offline-loss',async () => { if (lose) throw new Error('Synthetic response lost'); return response(); });
      await f.coordinator.callback(f.auth,callbackInput(await f.coordinator.begin(f.auth)));
      lose = true; await assert.rejects(f.coordinator.refresh(f.auth));
      assert.equal((await store.read('offline-loss','sandbox')).state,'unknown');
      await assert.rejects(f.coordinator.refresh(f.auth)); assert.equal(f.calls(),2);
      lose = false;
      const auth = await f.coordinator.begin(f.auth);
      assert.equal(auth.generation,3);
      assert.equal((await f.coordinator.callback(f.auth,callbackInput(auth))).state,'active');
    });
    await scenario('timeout-ignoring-abort-never-commits-late',async () => {
      const held = deferred();
      const f = fixture('offline-timeout',async () => await held.promise,10);
      const input = callbackInput(await f.coordinator.begin(f.auth));
      await assert.rejects(f.coordinator.callback(f.auth,input));
      assert.equal((await store.read('offline-timeout','sandbox')).state,'unknown');
      held.resolve(response()); await new Promise(resolve => setTimeout(resolve,0));
      assert.equal((await store.read('offline-timeout','sandbox')).state,'unknown');
      assert.equal(f.calls(),1);
    });
    await scenario('key-rotation-preserves-expiry-and-redacts-audit',async () => {
      const f = fixture('offline-rotation');
      await f.coordinator.callback(f.auth,callbackInput(await f.coordinator.begin(f.auth)));
      const before = await store.read('offline-rotation','sandbox'), events = [];
      const ops = createOperations({environment:'sandbox',store,vault:rotatedVault,verifyPrincipal:f.verifyPrincipal,
        verifyOperator:async auth => auth === 'operator',audit:event=>events.push(event)});
      assert.equal(await ops.rotateKey(f.auth),'rotated');
      const after = await store.read('offline-rotation','sandbox');
      assert.equal(after.generation,before.generation);
      assert.equal(after.envelope.key_id,'next');
      assert.equal(after.envelope.access_expires_at_ms,before.envelope.access_expires_at_ms);
      const newOnly = createTokenVault('next',new Map([['next',newKey]]));
      assert.equal((await newOnly.open({ownerRef:'offline-rotation',environment:'sandbox',generation:after.generation},after.envelope,Date.now())).identityId(),'fixture-identity');
      assert.equal((await ops.status(f.auth)).state,'connected');
      assert.ok(!JSON.stringify(events).includes('offline-rotation'));
      assert.ok(!JSON.stringify(events).includes('ciphertext'));
    });
    await scenario('bounded-operator-cleanup-retains-tombstones',async () => {
      const f = fixture('offline-expire'), keep = fixture('offline-keep');
      const expired = callbackInput(await f.coordinator.begin(f.auth));
      const active = callbackInput(await keep.coordinator.begin(keep.auth));
      await database.exec("RESET ROLE; UPDATE crier_webull_private.authorization_sessions SET created_at=statement_timestamp()-interval '301 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE owner_ref='offline-expire'; SET ROLE service_role;");
      const ops = createOperations({environment:'sandbox',store,vault:oldVault,verifyPrincipal:f.verifyPrincipal,verifyOperator:async auth=>auth==='operator'});
      await assert.rejects(ops.cleanup(f.auth,5));
      assert.equal(await ops.cleanup('operator',1),1);
      await assert.rejects(f.coordinator.callback(f.auth,expired));
      assert.equal((await keep.coordinator.callback(keep.auth,active)).state,'active');
      await f.coordinator.revoke(f.auth); await ops.cleanup('operator',5);
      assert.equal((await store.read('offline-expire','sandbox')).state,'revoked');
    });
    await scenario('rotation-cas-loses-to-revocation',async () => {
      const f = fixture('offline-cas');
      await f.coordinator.callback(f.auth,callbackInput(await f.coordinator.begin(f.auth)));
      const row = await store.read('offline-cas','sandbox');
      const replacement = await rotatedVault.rewrap({ownerRef:'offline-cas',environment:'sandbox',generation:row.generation},row.envelope,Date.now());
      await f.coordinator.revoke(f.auth);
      assert.equal(await store.rewrap('offline-cas','sandbox',row.generation,row.envelope,replacement),false);
      assert.equal((await store.read('offline-cas','sandbox')).state,'revoked');
    });
    await scenario('unapproved-signing-configuration-fails-closed',async () => {
      const f = fixture('offline-unapproved');
      for (const patch of [{integrationApproved:false},{signingReady:false},{approvedBrowserEntry:'https://example.test/login'}]) {
        assert.throws(()=>createCoordinator({config:{...config,...patch},store,vault:oldVault,verifyPrincipal:f.verifyPrincipal,transport:async()=>response()}));
      }
      assert.equal(f.calls(),0);
    });
    const sourceTreeDirty = !!execFileSync('git',['status','--porcelain','--untracked-files=all','--',
      'supabase','.github/workflows/supabase-tests.yml'],{cwd:root,encoding:'utf8'}).trim();
    return {schema:'crier.webull-offline-acceptance.v1',sourceCommit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),
      sourceTreeDirty,evidenceAttribution:sourceTreeDirty?'working_tree':'commit',
      runtime:'Node 24 + PGlite',deployment:'not_deployed',brokerCalls:0,discordCalls:0,scenarios,
      capabilities:['authorization','exchange_refresh_coordinator','encrypted_custody','rotation_recovery','expiry_cleanup','safe_diagnostics'].map(name=>({name,implemented:true,integration:'synthetic_sql',deployed:false,brokerAccepted:false}))};
  } finally { await database.close(); }
}
if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { process.stdout.write(JSON.stringify(await runAcceptance(),null,2)+'\n'); }
  catch { process.stderr.write('Offline acceptance failed; run node --test supabase/tests/offline-acceptance.test.mjs for diagnostics.\n'); process.exitCode=1; }
}
