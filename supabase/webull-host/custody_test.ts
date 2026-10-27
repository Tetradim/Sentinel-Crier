// deno-lint-ignore-file require-await -- asynchronous in-memory storage ports.
import { createCustody } from "./custody.ts";
import {
  createTokenVault,
  type EncryptedEnvelope,
  importVaultKey,
} from "../webull-connect/token_vault.ts";
import type {
  CoordinatorStore,
  TokenState,
} from "../webull-connect/coordinator.ts";
const owner = "b013cf27-fbab-4425-9c6c-6c3236766514";
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw Error("Unexpected result");
}
async function rejects(fn: () => Promise<unknown>) {
  let failed = false;
  try {
    await fn();
  } catch {
    failed = true;
  }
  if (!failed) throw Error("Expected rejection");
}
async function fixture() {
  let row: {
      state: TokenState;
      generation: number;
      envelope: EncryptedEnvelope | null;
    } | null = null,
    op = "",
    pending: { state: string; binding: string } | null = null;
  let calls = 0, admitted = true;
  let now = Date.now();
  const store: CoordinatorStore = {
    async read(who) {
      eq(who, owner);
      return row;
    },
    async begin(who, _env, expected, operation, state, binding) {
      eq(who, owner);
      if (expected !== (row?.generation ?? 0)) return null;
      row = {
        state: "authorization_pending",
        generation: expected + 1,
        envelope: null,
      };
      op = operation;
      pending = { state, binding };
      return {
        generation: row.generation,
        operationId: op,
        expiresAtMs: Date.now() + 300000,
      };
    },
    async consume(_who, _env, state, binding) {
      if (
        !pending || pending.state !== state || pending.binding !== binding ||
        row?.state !== "authorization_pending"
      ) return null;
      pending = null;
      return { generation: row.generation, operationId: op };
    },
    async commit(_who, _env, g, operation, envelope) {
      if (
        !row || row.generation !== g || op !== operation ||
        !["authorization_pending", "refresh_pending"].includes(row.state)
      ) return false;
      row = { state: "active", generation: g, envelope };
      return true;
    },
    async claimRefresh(_who, _env, expected, operation) {
      if (
        row?.state !== "active" || row.generation !== expected || !row.envelope
      ) return null;
      const envelope = row.envelope;
      op = operation;
      row = {
        state: "refresh_pending",
        generation: expected + 1,
        envelope: null,
      };
      return {
        priorGeneration: expected,
        newGeneration: expected + 1,
        envelope,
      };
    },
    async markUnknown(_who, _env, g, operation) {
      if (!row || row.generation !== g || op !== operation) return false;
      row = { state: "unknown", generation: g, envelope: null };
      return true;
    },
    async revoke() {
      row = {
        state: "revoked",
        generation: (row?.generation ?? 0) + 1,
        envelope: null,
      };
      pending = null;
      return row.generation;
    },
  };
  const vault = createTokenVault(
    "test",
    new Map([["test", await importVaultKey(new Uint8Array(32).fill(7))]]),
  );
  const custody = createCustody({
    store,
    vault,
    nowMs: () => now,
    configs: {
      sandbox: {
        environment: "sandbox",
        clientId: "id",
        clientSecret: "private-client",
        scope: "read trade",
        callback: "https://project.test/v1/connect/callback",
        approvedBrowserEntry:
          "https://passport.webull.com/oauth2/sandbox/authenticate/login",
        integrationApproved: true,
        signingReady: true,
      },
    },
    transport: async () => {
      calls++;
      return {
        access_token: "secret-access",
        refresh_token: "secret-refresh",
        identity_id: "webull-identity",
        token_type: "Bearer",
        created_at: new Date(now).toISOString(),
        expires_in: "1800",
        rt_expires_in: "86400",
      };
    },
    admitBroker: async () => admitted,
  });
  return {
    custody,
    store,
    get calls() {
      return calls;
    },
    setAdmitted(v: boolean) {
      admitted = v;
    },
    advance(ms: number) {
      now += ms;
    },
  };
}
Deno.test("real coordinator flow stores encrypted tokens and lends scoped server-only access", async () => {
  const f = await fixture(), c = f.custody.coordinators.sandbox!;
  const begun = await c.begin(owner);
  await c.callback(owner, {
    state: new URL(begun.url()).searchParams.get("state")!,
    browserBinding: begun.browserBinding(),
    code: "single-use",
  });
  const row = await f.store.read(owner, "sandbox");
  if (JSON.stringify(row).includes("secret-access")) {
    throw Error("Plaintext token persisted");
  }
  const result = await f.custody.withAccess(owner, "sandbox", async (lease) => {
    if (JSON.stringify(lease).includes("secret-access")) {
      throw Error("Lease serialized secret");
    }
    return await lease.request(async (token, identity) => {
      eq(token, "secret-access");
      eq(identity, "webull-identity");
      return "account-read";
    });
  });
  eq(result, "account-read");
  eq(f.calls, 1);
  await c.refresh(owner);
  eq(f.calls, 2);
  eq((await c.status(owner)).generation, 2);
});
Deno.test("revocation or admission failure blocks a previously obtained credential lease", async () => {
  const f = await fixture(),
    c = f.custody.coordinators.sandbox!,
    a = await c.begin(owner);
  await c.callback(owner, {
    state: new URL(a.url()).searchParams.get("state")!,
    browserBinding: a.browserBinding(),
    code: "code",
  });
  await f.custody.withAccess(owner, "sandbox", async (lease) => {
    f.setAdmitted(false);
    await rejects(() =>
      lease.request(async () => {
        throw Error("must not send");
      })
    );
    f.setAdmitted(true);
    await c.revoke(owner);
    let sent = false;
    await rejects(() =>
      lease.request(async () => {
        sent = true;
      })
    );
    eq(sent, false);
  });
});
Deno.test("near-expiry access refreshes once before lending credentials", async () => {
  const f = await fixture(),
    c = f.custody.coordinators.sandbox!,
    a = await c.begin(owner);
  await c.callback(owner, {
    state: new URL(a.url()).searchParams.get("state")!,
    browserBinding: a.browserBinding(),
    code: "code",
  });
  f.advance(1790000);
  await f.custody.withAccess(
    owner,
    "sandbox",
    async (lease) =>
      await lease.request(async (token) => eq(token, "secret-access")),
  );
  eq(f.calls, 2);
  eq((await c.status(owner)).generation, 2);
});
