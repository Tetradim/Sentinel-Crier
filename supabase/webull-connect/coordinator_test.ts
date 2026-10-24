// deno-lint-ignore-file require-await -- in-memory asynchronous ports complete atomically.
import {
  type CoordinatorConfig,
  type CoordinatorStore,
  createCoordinator,
  type TokenState,
} from "./coordinator.ts";
import {
  createTokenVault,
  type EncryptedEnvelope,
  importVaultKey,
} from "./token_vault.ts";

function assert(value: unknown): asserts value {
  if (!value) throw new Error("assertion failed");
}
async function rejects(action: () => unknown | Promise<unknown>) {
  try {
    await action();
  } catch (e) {
    assert(
      e instanceof Error &&
        e.message === "Invalid Webull coordinator operation" &&
        e.cause === undefined,
    );
    return;
  }
  throw new Error("expected rejection");
}
const now = Date.parse("2026-10-24T12:00:00Z");
function reply(overrides = {}) {
  return {
    access_token: "synthetic-access",
    refresh_token: "synthetic-refresh",
    identity_id: "synthetic-identity",
    token_type: "Bearer",
    created_at: "2026-10-24T12:00:00Z",
    expires_in: "60",
    rt_expires_in: "3600",
    ...overrides,
  };
}
const config: CoordinatorConfig = {
  environment: "sandbox",
  clientId: "synthetic-client",
  clientSecret: "synthetic-secret",
  scope: "synthetic-scope",
  callback: "https://fixture.example/callback",
  approvedBrowserEntry:
    "https://passport.webull.com/oauth2/sandbox/authenticate/login",
  integrationApproved: true,
  signingReady: true,
};
class MemoryStore implements CoordinatorStore {
  row: {
    state: TokenState;
    generation: number;
    envelope: EncryptedEnvelope | null;
  } | null = null;
  operationId = "";
  pending:
    | { owner: string; state: string; binding: string; callback: string }
    | null = null;
  owners: string[] = [];
  async read(owner: string) {
    this.owners.push(owner);
    return this.row;
  }
  async begin(
    owner: string,
    _env: string,
    expected: number,
    op: string,
    state: string,
    binding: string,
    callback: string,
  ) {
    if (expected !== (this.row?.generation ?? 0)) return null;
    this.row = {
      state: "authorization_pending",
      generation: expected + 1,
      envelope: null,
    };
    this.operationId = op;
    this.pending = { owner, state, binding, callback };
    return {
      generation: expected + 1,
      operationId: op,
      expiresAtMs: now + 600_000,
    };
  }
  async consume(
    owner: string,
    _env: string,
    state: string,
    binding: string,
    callback: string,
  ) {
    const p = this.pending;
    if (
      !p || p.owner !== owner || p.state !== state || p.binding !== binding ||
      p.callback !== callback || this.row?.state !== "authorization_pending"
    ) return null;
    this.pending = null;
    return { generation: this.row.generation, operationId: this.operationId };
  }
  async commit(
    _owner: string,
    _env: string,
    generation: number,
    op: string,
    envelope: EncryptedEnvelope,
  ) {
    if (
      this.row?.generation !== generation || op !== this.operationId ||
      !["authorization_pending", "refresh_pending"].includes(this.row.state)
    ) return false;
    this.row = { state: "active", generation, envelope };
    return true;
  }
  async claimRefresh(
    _owner: string,
    _env: string,
    expected: number,
    op: string,
  ) {
    if (
      this.row?.state !== "active" || this.row.generation !== expected ||
      !this.row.envelope
    ) return null;
    const envelope = this.row.envelope;
    this.operationId = op;
    this.row = {
      state: "refresh_pending",
      generation: expected + 1,
      envelope: null,
    };
    return { priorGeneration: expected, newGeneration: expected + 1, envelope };
  }
  async markUnknown(
    _owner: string,
    _env: string,
    generation: number,
    op: string,
  ) {
    if (
      this.row?.generation !== generation || op !== this.operationId ||
      !["authorization_pending", "refresh_pending"].includes(this.row.state)
    ) return false;
    this.row = { state: "unknown", generation, envelope: null };
    return true;
  }
  async revoke() {
    const generation = (this.row?.generation ?? 0) + 1;
    this.row = { state: "revoked", generation, envelope: null };
    this.pending = null;
    return generation;
  }
}
async function fixture(
  transport: Parameters<typeof createCoordinator>[0]["transport"] = async () =>
    reply(),
  overrides = {},
) {
  const vault = createTokenVault(
    "fixture-key",
    new Map([[
      "fixture-key",
      await importVaultKey(new Uint8Array(32).fill(7)),
    ]]),
  );
  const store = new MemoryStore();
  const options = {
    config,
    store,
    vault,
    transport,
    verifyPrincipal: async (auth: unknown) => {
      if (auth !== "verified") throw new Error("secret auth failure");
      return "trusted-owner";
    },
    nowMs: () => now,
    timeoutMs: 20,
    ...overrides,
  };
  return { coordinator: createCoordinator(options), store, vault, options };
}
function callbackInput(a: { url(): string; browserBinding(): string }) {
  return {
    state: new URL(a.url()).searchParams.get("state")!,
    browserBinding: a.browserBinding(),
    code: "synthetic-code",
  };
}

Deno.test("coordinator reserves before redirect, exchanges once and refreshes encrypted custody", async () => {
  const forms: string[] = [];
  const { coordinator: c, store, vault } = await fixture(async (request) => {
    forms.push(request.serializeForm());
    return reply();
  });
  const a = await c.begin("verified");
  assert(store.row?.state === "authorization_pending");
  assert(!JSON.stringify([a, c]).includes("synthetic"));
  assert(!Deno.inspect(a).includes(a.browserBinding()));
  const input = callbackInput(a);
  assert((await c.callback("verified", input)).state === "active");
  await rejects(() => c.callback("verified", input));
  assert(forms.length === 1);
  assert((await c.refresh("verified")).generation === 2);
  assert(Number(forms.length) === 2);
  assert(
    new URLSearchParams(forms[1]).get("refresh_token") === "synthetic-refresh",
  );
  assert(
    store.row?.envelope &&
      !JSON.stringify(await c.status("verified")).includes("ciphertext"),
  );
  const opened = await vault.open(
    { ownerRef: "trusted-owner", environment: "sandbox", generation: 2 },
    store.row!.envelope,
    now,
  );
  assert(opened.accessToken() === "synthetic-access");
  assert(store.owners.every((o) => o === "trusted-owner"));
});
Deno.test("coordinator rejects forged auth for every method before storage or transport", async () => {
  let calls = 0;
  const { coordinator: c, store } = await fixture(async () => {
    calls++;
    return reply();
  });
  for (
    const action of [
      () => c.begin({ owner: "trusted-owner" }),
      () => c.status(null),
      () => c.revoke(null),
      () => c.refresh(null),
      () => c.callback(null, { state: "", browserBinding: "", code: "" }),
    ]
  ) await rejects(action);
  assert(calls === 0 && store.row === null && store.owners.length === 0);
});
Deno.test("invalid code and wrong binding cannot consume pending authorization", async () => {
  let calls = 0;
  const { coordinator: c } = await fixture(async () => {
    calls++;
    return reply();
  });
  const a = await c.begin("verified"), input = callbackInput(a);
  await rejects(() => c.callback("verified", { ...input, code: "bad\ncode" }));
  await rejects(() =>
    c.callback("verified", { ...input, browserBinding: "A".repeat(43) })
  );
  assert(calls === 0);
  await c.callback("verified", input);
  assert(Number(calls) === 1);
});
Deno.test("timeout settles with ignored abort and late response never commits", async () => {
  let finish!: (value: unknown) => void;
  let signal!: AbortSignal;
  const { coordinator: c, store } = await fixture((_r, s) => {
    signal = s;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const a = await c.begin("verified");
  await rejects(() => c.callback("verified", callbackInput(a)));
  assert(signal.aborted && store.row?.state === "unknown");
  finish(reply());
  await new Promise((r) => setTimeout(r, 5));
  assert(store.row?.state === "unknown");
});
Deno.test("revoke fences an in-flight exchange", async () => {
  let finish!: (value: unknown) => void;
  let started!: () => void;
  const ready = new Promise<void>((r) => {
    started = r;
  });
  const { coordinator: c, store } = await fixture(() => {
    started();
    return new Promise((r) => {
      finish = r;
    });
  }, { timeoutMs: 1000 });
  const a = await c.begin("verified");
  const attempt = c.callback("verified", callbackInput(a));
  await ready;
  await c.revoke("verified");
  finish(reply());
  await rejects(() => attempt);
  assert(store.row?.state === "revoked");
});
Deno.test("wrong refresh identity, malformed reply and response loss require fresh authorization", async () => {
  for (
    const bad of [
      () => reply({ identity_id: "wrong" }),
      () => ({ access_token: "secret" }),
      () => {
        throw new Error("secret failure");
      },
    ]
  ) {
    let calls = 0;
    const { coordinator: c, store } = await fixture(async () => {
      calls++;
      return calls === 1 ? reply() : bad();
    });
    const a = await c.begin("verified");
    await c.callback("verified", callbackInput(a));
    await rejects(() => c.refresh("verified"));
    assert(store.row?.state === "unknown");
    await rejects(() => c.refresh("verified"));
    assert(calls === 2);
  }
});
Deno.test("configuration fails closed and errors redact all supplied values", async () => {
  const { options } = await fixture();
  for (
    const patch of [
      { signingReady: false },
      { integrationApproved: false },
      { approvedBrowserEntry: "https://evil.example/" },
      { callback: "http://fixture.example/" },
      { extra: "synthetic-secret" },
      { environment: "invalid" },
    ]
  ) {
    await rejects(() =>
      createCoordinator({
        ...options,
        config: { ...config, ...patch } as CoordinatorConfig,
      })
    );
  }
  for (const timeoutMs of [0, 30001, NaN]) {
    await rejects(() => createCoordinator({ ...options, timeoutMs }));
  }
  await rejects(() =>
    createCoordinator(
      { ...options, config: undefined } as unknown as Parameters<
        typeof createCoordinator
      >[0],
    )
  );
  await rejects(() =>
    createCoordinator(
      { ...options, extra: "secret" } as Parameters<
        typeof createCoordinator
      >[0],
    )
  );
});

Deno.test("concurrent refresh attempts dispatch a rotating grant only once", async () => {
  let calls = 0;
  let finish!: (value: unknown) => void;
  let started!: () => void;
  const ready = new Promise<void>((r) => {
    started = r;
  });
  const { coordinator: c } = await fixture(() => {
    calls++;
    if (calls === 1) return Promise.resolve(reply());
    started();
    return new Promise((r) => {
      finish = r;
    });
  }, { timeoutMs: 1000 });
  const a = await c.begin("verified");
  await c.callback("verified", callbackInput(a));
  const first = c.refresh("verified");
  await ready;
  await rejects(() => c.refresh("verified"));
  finish(reply());
  await first;
  assert(calls === 2);
});

Deno.test("reply shape and size are bounded before vault decode without running getters", async () => {
  let getterCalls = 0;
  const accessor = Object.defineProperty(reply(), "access_token", {
    get() {
      getterCalls++;
      return "secret";
    },
  });
  for (
    const malformed of [
      accessor,
      reply({ access_token: "x".repeat(32769) }),
      reply({ extra: { nested: "secret" } }),
      new Array(100).fill("secret"),
    ]
  ) {
    const { coordinator: c, store } = await fixture(async () => malformed);
    const a = await c.begin("verified");
    await rejects(() => c.callback("verified", callbackInput(a)));
    assert(store.row?.state === "unknown");
  }
  assert(getterCalls === 0);
});

Deno.test("new authorization explicitly recovers uncertainty and old pending redirects expire on supersession", async () => {
  let calls = 0;
  const { coordinator: c, store } = await fixture(async () => {
    calls++;
    if (calls === 1) throw new Error("lost synthetic reply");
    return reply();
  });
  const a = await c.begin("verified"), b = await c.begin("verified");
  await rejects(() => c.callback("verified", callbackInput(a)));
  assert(calls === 0);
  await rejects(() => c.callback("verified", callbackInput(b)));
  assert(store.row?.state === "unknown");
  const recovery = await c.begin("verified");
  assert(recovery.generation === 3);
  await c.callback("verified", callbackInput(recovery));
  assert((await c.status("verified")).state === "active");
});
