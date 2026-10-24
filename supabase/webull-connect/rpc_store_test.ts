import { createRpcStore } from "./rpc_store.ts";

function assert(value: unknown): asserts value {
  if (!value) throw new Error("assertion failed");
}
function equal(a: unknown, b: unknown) {
  assert(JSON.stringify(a) === JSON.stringify(b));
}
async function rejects(action: () => unknown | Promise<unknown>) {
  try {
    await action();
  } catch (e) {
    assert(
      e instanceof Error &&
        e.message === "Invalid Webull RPC store operation" &&
        e.cause === undefined,
    );
    return;
  }
  throw new Error("expected rejection");
}
const owner = "trusted-owner",
  env = "sandbox",
  op = "00000000-0000-4000-8000-000000000001";
const hash = "a".repeat(64),
  binding = "b".repeat(64),
  callback = "https://fixture.example/callback";
const envelope = {
  schema: "crier.webull-token.v1" as const,
  key_id: "fixture-key",
  nonce: "A".repeat(16),
  ciphertext: "A".repeat(22),
  identity_hash: hash,
  access_expires_at_ms: 1800000000000,
  refresh_expires_at_ms: 1800000100000,
};
function fixture(data: unknown) {
  const calls: unknown[] = [];
  const store = createRpcStore((name, parameters) => {
    calls.push({ name, parameters });
    return Promise.resolve({ data, error: null });
  });
  return { store, calls };
}
Deno.test("RPC adapter maps compound authorization begin/consume/revoke and preserves scope", async () => {
  const expiry = "2026-10-24T12:10:00+00:00";
  const a = fixture([{
    generation: "1",
    operation_id: op,
    expires_at: expiry,
  }]);
  equal(await a.store.begin(owner, env, 0, op, hash, binding, callback), {
    generation: 1,
    operationId: op,
    expiresAtMs: Date.parse(expiry),
  });
  equal(a.calls, [{
    name: "crier_webull_authorization_begin",
    parameters: {
      p_owner: owner,
      p_environment: env,
      p_expected_generation: 0,
      p_operation_id: op,
      p_state_hash: hash,
      p_binding_hash: binding,
      p_callback: callback,
    },
  }]);
  const b = fixture([{ generation: 1, operation_id: op }]);
  equal(await b.store.consume(owner, env, hash, binding, callback), {
    generation: 1,
    operationId: op,
  });
  equal(b.calls, [{
    name: "crier_webull_authorization_consume",
    parameters: {
      p_owner: owner,
      p_environment: env,
      p_state_hash: hash,
      p_binding_hash: binding,
      p_callback: callback,
    },
  }]);
  const c = fixture("9007199254740991");
  assert(await c.store.revoke(owner, "production") === Number.MAX_SAFE_INTEGER);
  equal(c.calls, [{
    name: "crier_webull_authorization_revoke",
    parameters: { p_owner: owner, p_environment: "production" },
  }]);
});
Deno.test("RPC adapter maps token reads, refresh claims, commits and unknown transitions", async () => {
  const a = fixture([{ state: "active", generation: 1, envelope }]);
  equal(await a.store.read(owner, env), {
    state: "active",
    generation: 1,
    envelope,
  });
  equal(a.calls, [{
    name: "crier_webull_token_read",
    parameters: { p_owner: owner, p_environment: env },
  }]);
  const b = fixture([{ prior_generation: "1", new_generation: "2", envelope }]);
  equal(await b.store.claimRefresh(owner, env, 1, op), {
    priorGeneration: 1,
    newGeneration: 2,
    envelope,
  });
  equal(b.calls, [{
    name: "crier_webull_token_claim_refresh",
    parameters: {
      p_owner: owner,
      p_environment: env,
      p_expected_generation: 1,
      p_operation_id: op,
    },
  }]);
  for (
    const [method, name] of [["commit", "crier_webull_token_commit"], [
      "markUnknown",
      "crier_webull_token_mark_unknown",
    ]] as const
  ) {
    const f = fixture(false);
    const result = method === "commit"
      ? await f.store.commit(owner, env, 2, op, envelope)
      : await f.store.markUnknown(owner, env, 2, op);
    assert(result === false);
    equal(f.calls, [{
      name,
      parameters: {
        p_owner: owner,
        p_environment: env,
        p_generation: 2,
        p_operation_id: op,
        ...(method === "commit" ? { p_envelope: envelope } : {}),
      },
    }]);
  }
});
Deno.test("RPC adapter maps envelope CAS rewrap and bounded cleanup without exposing transport", async () => {
  const rotated = { ...envelope, key_id: "new-key" };
  const a = fixture(true);
  assert(await a.store.rewrap(owner, env, 1, envelope, rotated));
  equal(a.calls, [{
    name: "crier_webull_token_rewrap",
    parameters: {
      p_owner: owner,
      p_environment: env,
      p_expected_generation: 1,
      p_expected_envelope: envelope,
      p_envelope: rotated,
    },
  }]);
  const b = fixture(2);
  assert(await b.store.cleanupExpiredSessions(500) === 2);
  equal(b.calls, [{
    name: "crier_webull_cleanup_expired_sessions",
    parameters: { p_limit: 500 },
  }]);
  assert(JSON.stringify(a.store) === "{}");
});
Deno.test("zero rows represent absent rows and every nonactive state requires null custody", async () => {
  const { store } = fixture([]);
  assert(await store.read(owner, env) === null);
  assert(
    await store.begin(owner, env, 0, op, hash, binding, callback) === null,
  );
  assert(await store.consume(owner, env, hash, binding, callback) === null);
  assert(await store.claimRefresh(owner, env, 1, op) === null);
  for (
    const state of [
      "authorization_pending",
      "refresh_pending",
      "unknown",
      "revoked",
    ]
  ) {
    equal(
      await fixture([{ state, generation: 1, envelope: null }]).store.read(
        owner,
        env,
      ),
      { state, generation: 1, envelope: null },
    );
    await rejects(() =>
      fixture([{ state, generation: 1, envelope }]).store.read(owner, env)
    );
  }
});
Deno.test("malformed table cardinality, generations, operation IDs and expiry fail closed", async () => {
  const good = {
    generation: 1,
    operation_id: op,
    expires_at: "2026-10-24T12:10:00Z",
  };
  for (
    const data of [
      null,
      {},
      good,
      [good, good],
      [null],
      [{ ...good, extra: "secret" }],
      ...[
        0,
        -1,
        NaN,
        Infinity,
        1.2,
        Number.MAX_SAFE_INTEGER + 1,
        "01",
        "1e0",
        "9007199254740992",
      ].map((generation) => [{ ...good, generation }]),
      ...["secret", "", null].map(
        (operation_id) => [{ ...good, operation_id }],
      ),
      ...[
        null,
        123,
        "secret",
        "1970-01-01T00:00:00Z",
        "2026-02-31T00:00:00Z",
        "2026-10-24",
      ].map((expires_at) => [{ ...good, expires_at }]),
    ]
  ) {
    await rejects(() =>
      fixture(data).store.begin(owner, env, 0, op, hash, binding, callback)
    );
  }
  await rejects(() =>
    fixture([{ generation: 2, operation_id: op, expires_at: good.expires_at }])
      .store.begin(owner, env, 0, op, hash, binding, callback)
  );
  await rejects(() =>
    fixture([{ prior_generation: 1, new_generation: 3, envelope }]).store
      .claimRefresh(owner, env, 1, op)
  );
});
Deno.test("malformed state and envelope cannot release plaintext custody", async () => {
  for (
    const data of [
      [{ state: "secret", generation: 1, envelope: null }],
      [{ state: "active", generation: 1, envelope: null }],
      [{ state: "active", generation: 1 }],
      [{ state: "active", generation: 1, envelope, extra: true }],
    ]
  ) await rejects(() => fixture(data).store.read(owner, env));
  for (
    const bad of [
      "plaintext-secret",
      {},
      { ...envelope, access_token: "secret" },
      { ...envelope, schema: "wrong" },
      { ...envelope, nonce: "bad" },
      { ...envelope, ciphertext: "B".repeat(22) },
      { ...envelope, identity_hash: "wrong" },
      { ...envelope, key_id: "\nsecret" },
      { ...envelope, access_expires_at_ms: 0 },
      { ...envelope, refresh_expires_at_ms: envelope.access_expires_at_ms },
    ]
  ) {
    await rejects(() =>
      fixture([{ state: "active", generation: 1, envelope: bad }]).store.read(
        owner,
        env,
      )
    );
  }
});
Deno.test("transport errors and malformed scalar replies redact details", async () => {
  for (
    const rpc of [
      () => Promise.reject(new Error("secret")),
      () => Promise.resolve({ data: [], error: { message: "secret" } }),
      () => Promise.resolve(null as never),
    ]
  ) await rejects(() => createRpcStore(rpc).read(owner, env));
  for (const data of [null, "true", 1, [], {}, [true]]) {
    await rejects(() =>
      fixture(data).store.commit(owner, env, 1, op, envelope)
    );
  }
  for (const data of [null, 0, "01", Number.MAX_SAFE_INTEGER + 1, {}]) {
    await rejects(() => fixture(data).store.revoke(owner, env));
  }
  for (const data of [-1, 3, "2.0", null, {}]) {
    await rejects(() => fixture(data).store.cleanupExpiredSessions(2));
  }
});
Deno.test("invalid trusted inputs reject before dispatch", async () => {
  const { store, calls } = fixture(true);
  for (const limit of [0, 501, NaN, 1.5]) {
    await rejects(() => store.cleanupExpiredSessions(limit));
  }
  await rejects(() => store.read("", env));
  await rejects(() => store.read(owner, "wrong" as never));
  await rejects(() =>
    store.begin(
      owner,
      env,
      Number.MAX_SAFE_INTEGER,
      op,
      hash,
      binding,
      callback,
    )
  );
  await rejects(() => store.claimRefresh(owner, env, 0, op));
  await rejects(() => store.markUnknown(owner, env, 1, "bad"));
  await rejects(() =>
    store.consume(owner, env, "raw-state", binding, callback)
  );
  assert(calls.length === 0);
});
