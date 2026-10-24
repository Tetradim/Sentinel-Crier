import { createOperations } from "./operations.ts";
import { createTokenVault, importVaultKey } from "./token_vault.ts";

function assert(value: unknown): asserts value {
  if (!value) throw new Error("assertion failed");
}
async function rejects(action: () => unknown | Promise<unknown>) {
  try {
    await action();
  } catch (error) {
    assert(
      error instanceof Error &&
        error.message === "Invalid Webull operational request",
    );
    assert(error.cause === undefined);
    return;
  }
  throw new Error("expected rejection");
}
const now = Date.parse("2026-10-24T12:00:00Z");
const context = {
  ownerRef: "fixture-owner",
  environment: "sandbox",
  generation: 1,
} as const;
async function fixture() {
  const old = await importVaultKey(new Uint8Array(32).fill(3));
  const next = await importVaultKey(new Uint8Array(32).fill(4));
  const vault = createTokenVault(
    "next",
    new Map([["old", old], ["next", next]]),
  );
  const envelope = await createTokenVault("old", new Map([["old", old]]))
    .sealReply(context, {
      access_token: "fixture-access",
      refresh_token: "fixture-refresh",
      identity_id: "fixture-identity",
      token_type: "Bearer",
      created_at: "2026-10-24T12:00:00Z",
      expires_in: "60",
      rt_expires_in: "3600",
    }, { nowMs: now });
  let row: { state: string; generation: number; envelope: unknown } | null = {
    state: "active",
    generation: 1,
    envelope,
  };
  let calls = 0, cleanup = 0, stale = false;
  const events: unknown[] = [];
  const store = {
    read: () => Promise.resolve(row),
    rewrap: (
      _owner: string,
      _env: string,
      generation: number,
      expected: unknown,
      replacement: unknown,
    ) => {
      calls++;
      assert(generation === 1 && expected === envelope);
      if (stale) return Promise.resolve(false);
      row = { state: "active", generation: 1, envelope: replacement };
      return Promise.resolve(true);
    },
    cleanupExpiredSessions: (limit: number) => {
      cleanup++;
      assert(limit === 5);
      return Promise.resolve(2);
    },
  };
  const options = {
    environment: "sandbox" as const,
    store,
    vault,
    verifyPrincipal: (auth: unknown) =>
      auth === "customer"
        ? Promise.resolve(context.ownerRef)
        : Promise.reject(new Error("fixture-secret")),
    verifyOperator: (auth: unknown) => Promise.resolve(auth === "operator"),
    nowMs: () => now,
    audit: (event: unknown) => {
      events.push(event);
    },
  };
  return {
    options,
    events,
    store,
    vault,
    envelope,
    calls: () => calls,
    cleanup: () => cleanup,
    setRow: (value: typeof row) => {
      row = value;
    },
    setStale: () => {
      stale = true;
    },
  };
}
Deno.test("operations rotate real encrypted envelope with CAS and safe audit", async () => {
  const f = await fixture(), ops = createOperations(f.options);
  assert(await ops.rotateKey("customer") === "rotated");
  assert(f.calls() === 1);
  const status = await ops.status("customer");
  assert(status.state === "connected" && status.generation === 1);
  const output = JSON.stringify([status, f.events, ops]);
  for (
    const secret of [
      "fixture-owner",
      "fixture-access",
      "fixture-refresh",
      "fixture-identity",
      "ciphertext",
      "nonce",
    ]
  ) assert(!output.includes(secret));
  assert(JSON.stringify(f.events).includes("rotation"));
});
Deno.test("rotation loses safely to newer refresh or revoke and expired tokens require auth", async () => {
  const f = await fixture(), ops = createOperations(f.options);
  f.setStale();
  assert(await ops.rotateKey("customer") === "stale");
  f.setRow({ state: "refresh_pending", generation: 2, envelope: null });
  assert(await ops.rotateKey("customer") === "reauthorize");
  assert((await ops.status("customer")).state === "refresh_pending");
  f.setRow({ state: "unknown", generation: 2, envelope: null });
  assert((await ops.status("customer")).state === "reauthorization_required");
  f.setRow(null);
  assert((await ops.status("customer")).state === "not_connected");
  assert(f.calls() === 1);
});
Deno.test("operator-only cleanup is bounded and customer identity cannot grant it", async () => {
  const f = await fixture(), ops = createOperations(f.options);
  await rejects(() => ops.cleanup("customer", 5));
  assert(f.cleanup() === 0);
  for (const limit of [0, 501, 1.5, NaN]) {
    await rejects(() => ops.cleanup("operator", limit));
  }
  assert(await ops.cleanup("operator", 5) === 2);
  assert(f.cleanup() === 1);
  await rejects(() => ops.rotateKey("forged"));
  await rejects(() => ops.status("forged"));
});
Deno.test("status honors deadlines and operational errors never echo raw backend values", async () => {
  const f = await fixture();
  const ops = createOperations({ ...f.options, nowMs: () => now + 60_000 });
  assert((await ops.status("customer")).state === "refresh_required");
  const expired = createOperations({
    ...f.options,
    nowMs: () => now + 3_600_000,
  });
  assert(
    (await expired.status("customer")).state === "reauthorization_required",
  );
  assert(await expired.rotateKey("customer") === "reauthorize");
  const bad = createOperations({
    ...f.options,
    store: {
      ...f.store,
      read: () => Promise.reject(new Error("fixture-access")),
    },
  });
  await rejects(() => bad.status("customer"));
  const auditFails = createOperations({
    ...f.options,
    audit: () => {
      throw new Error("fixture-access");
    },
  });
  assert(await auditFails.rotateKey("customer") === "rotated");
});

Deno.test("asynchronous audit sink rejection does not escape a completed operation", async () => {
  const f = await fixture();
  const ops = createOperations({
    ...f.options,
    audit: () => Promise.reject(new Error("fixture-access")),
  });
  assert(await ops.rotateKey("customer") === "rotated");
  await new Promise((resolve) => setTimeout(resolve, 0));
});
