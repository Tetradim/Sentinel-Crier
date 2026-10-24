import { createTokenVault, importVaultKey } from "./token_vault.ts";

function assert(value: unknown): asserts value {
  if (!value) throw new Error("assertion failed");
}
async function rejects(action: () => unknown | Promise<unknown>) {
  try {
    await action();
  } catch (error) {
    assert(error instanceof Error);
    assert(error.message === "Invalid Webull token vault operation");
    assert(error.cause === undefined);
    return;
  }
  throw new Error("expected rejection");
}
const now = Date.parse("2026-10-24T12:00:00Z");
const context = {
  ownerRef: "owner-fixture",
  environment: "sandbox",
  generation: 1,
} as const;
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
async function fixture() {
  const key = await importVaultKey(new Uint8Array(32).fill(7));
  const keys = new Map([["test-key-1", key]]);
  return { key, keys, vault: createTokenVault("test-key-1", keys) };
}

Deno.test("vault roundtrips only explicit secrets and fresh nonce envelopes", async () => {
  const { vault, key } = await fixture();
  const first = await vault.sealReply(context, reply({ extra: "discard-me" }), {
    nowMs: now,
  });
  const second = await vault.sealReply(context, reply(), { nowMs: now });
  assert(
    first.nonce !== second.nonce && first.ciphertext !== second.ciphertext,
  );
  assert(first.schema === "crier.webull-token.v1");
  assert(/^[a-f0-9]{64}$/.test(first.identity_hash));
  assert(/^[A-Za-z0-9_-]{16}$/.test(first.nonce));
  const opened = await vault.open(
    context,
    JSON.parse(JSON.stringify(first)),
    now,
  );
  assert(opened.accessToken() === "synthetic-access");
  assert(opened.refreshToken() === "synthetic-refresh");
  assert(opened.identityId() === "synthetic-identity");
  assert(opened.accessExpiresAtMs === now + 60_000);
  assert(opened.refreshExpiresAtMs === now + 3_600_000);
  assert(!opened.needsRefresh(now));
  assert(opened.needsRefresh(now + 60_000));
  assert(!JSON.stringify(first).includes("synthetic"));
  assert(Object.isFrozen(first) && Object.isFrozen(opened));
  const from64 = (value: string) =>
    Uint8Array.from(
      atob(
        value.replaceAll("-", "+").replaceAll("_", "/") +
          "=".repeat((4 - value.length % 4) % 4),
      ),
      (c) => c.charCodeAt(0),
    );
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: from64(first.nonce),
      tagLength: 128,
      additionalData: new TextEncoder().encode(
        JSON.stringify([
          first.schema,
          context.ownerRef,
          context.environment,
          context.generation,
          first.key_id,
          first.identity_hash,
          first.access_expires_at_ms,
          first.refresh_expires_at_ms,
        ]),
      ),
    },
    key,
    from64(first.ciphertext),
  );
  const decrypted = JSON.parse(new TextDecoder().decode(plaintext));
  assert(
    Object.keys(decrypted).sort().join(",") ===
      "access_token,identity_id,refresh_token",
  );
  assert(decrypted.identity_id === "synthetic-identity");
});

Deno.test("expired access remains available for refresh until refresh deadline", async () => {
  const { vault } = await fixture();
  const envelope = await vault.sealReply(context, reply(), { nowMs: now });
  const opened = await vault.open(context, envelope, now + 60_000);
  assert(opened.needsRefresh(now + 60_000));
  await rejects(() => vault.open(context, envelope, now + 3_600_000));
  await rejects(() =>
    vault.sealReply(context, reply(), { nowMs: now + 60_000 })
  );
  await rejects(() =>
    vault.sealReply(context, reply(), { nowMs: now, expectedIdentity: "wrong" })
  );
});

Deno.test("all context and envelope metadata are authenticated", async () => {
  const { vault } = await fixture();
  const envelope = await vault.sealReply(context, reply(), { nowMs: now });
  for (
    const change of [{ ownerRef: "other" }, { environment: "production" }, {
      generation: 2,
    }]
  ) {
    await rejects(() =>
      vault.open({ ...context, ...change } as never, envelope, now)
    );
  }
  const changes = {
    schema: "crier.webull-token.v2",
    key_id: "missing-key",
    nonce: "A".repeat(16),
    ciphertext: "A".repeat(envelope.ciphertext.length),
    identity_hash: "0".repeat(64),
    access_expires_at_ms: now + 60_001,
    refresh_expires_at_ms: now + 3_600_001,
  };
  for (const [key, value] of Object.entries(changes)) {
    await rejects(() =>
      vault.open(context, { ...envelope, [key]: value }, now)
    );
  }
  await rejects(() => vault.open(context, { ...envelope, extra: true }, now));
});

Deno.test("rotation preserves identity and deadlines and fails without old key", async () => {
  const { vault, key } = await fixture();
  const old = await vault.sealReply(context, reply(), { nowMs: now });
  const next = await importVaultKey(new Uint8Array(32).fill(9));
  const rotated = createTokenVault(
    "test-key-2",
    new Map([["test-key-1", key], ["test-key-2", next]]),
  );
  const envelope = await rotated.rewrap(context, old, now + 60_000);
  assert(envelope.key_id === "test-key-2");
  assert(envelope.identity_hash === old.identity_hash);
  assert(envelope.access_expires_at_ms === old.access_expires_at_ms);
  assert(envelope.refresh_expires_at_ms === old.refresh_expires_at_ms);
  const newOnly = createTokenVault(
    "test-key-2",
    new Map([["test-key-2", next]]),
  );
  assert(
    (await newOnly.open(context, envelope, now + 60_000)).identityId() ===
      "synthetic-identity",
  );
  await rejects(() => newOnly.open(context, old, now));
  const alias = createTokenVault("alias", new Map([["alias", key]]));
  await rejects(() => alias.open(context, { ...old, key_id: "alias" }, now));
});

Deno.test("keys are nonextractable and ordinary secret inspection is redacted", async () => {
  const { vault, key, keys } = await fixture();
  assert(!key.extractable && key.algorithm.name === "AES-GCM");
  keys.clear(); // Constructor must copy its caller's keyring.
  const envelope = await vault.sealReply(context, reply(), { nowMs: now });
  const token = await vault.open(context, envelope, now);
  const nodeInspect = (token as unknown as Record<symbol, () => string>)[
    Symbol.for("nodejs.util.inspect.custom")
  ];
  const inspected = [
    String(token),
    JSON.stringify(token),
    Deno.inspect(token),
    nodeInspect.call(token),
    JSON.stringify({ ...token }),
    Deno.inspect(vault),
  ].join(" ");
  for (
    const secret of [
      "synthetic-access",
      "synthetic-refresh",
      "synthetic-identity",
    ]
  ) assert(!inspected.includes(secret));
  assert(inspected.includes("REDACTED"));
  let denied = false;
  try {
    await crypto.subtle.exportKey("raw", key);
  } catch {
    denied = true;
  }
  assert(denied);
});

Deno.test("malformed input size and timestamp bounds fail closed with generic errors", async () => {
  const { vault } = await fixture();
  const envelope = await vault.sealReply(context, reply(), { nowMs: now });
  for (const ownerRef of ["", " ", "a\n", "a".repeat(201)]) {
    await rejects(() =>
      vault.sealReply({ ...context, ownerRef }, reply(), { nowMs: now })
    );
  }
  for (const generation of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    await rejects(() => vault.open({ ...context, generation }, envelope, now));
  }
  for (const value of [NaN, Infinity, 8_640_000_000_000_001, 1.5]) {
    await rejects(() => vault.open(context, envelope, value));
    await rejects(() =>
      vault.open(context, { ...envelope, access_expires_at_ms: value }, now)
    );
  }
  for (
    const ciphertext of [
      "",
      "A".repeat(21),
      "A".repeat(65537),
      envelope.ciphertext + "=",
      "A".repeat(23),
    ]
  ) {
    await rejects(() => vault.open(context, { ...envelope, ciphertext }, now));
  }
  for (const nonce of ["A".repeat(15), "A".repeat(17), "!".repeat(16)]) {
    await rejects(() => vault.open(context, { ...envelope, nonce }, now));
  }
  await rejects(() =>
    vault.sealReply(context, reply({ access_token: "a".repeat(32768) }), {
      nowMs: now,
    })
  );
  await rejects(() =>
    vault.sealReply(context, reply({ refresh_token: "☃".repeat(12000) }), {
      nowMs: now,
    })
  );
  await rejects(() => importVaultKey(new Uint8Array(31)));
  await rejects(() => createTokenVault("missing", new Map()));
  await rejects(() => createTokenVault("", new Map()));
  const extractable = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
  await rejects(() => createTokenVault("key", new Map([["key", extractable]])));
  const short = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 128 },
    false,
    ["encrypt", "decrypt"],
  );
  await rejects(() => createTokenVault("key", new Map([["key", short]])));
  const encryptOnly = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  await rejects(() => createTokenVault("key", new Map([["key", encryptOnly]])));
  await rejects(() => vault.open(context, null, now));
  await rejects(() =>
    vault.open(
      context,
      Object.assign(Object.create({ inherited: true }), envelope),
      now,
    )
  );
  await rejects(() =>
    vault.open({ ...context, extra: true } as never, envelope, now)
  );
  await rejects(() =>
    vault.open({ ...context, environment: "other" } as never, envelope, now)
  );
  await rejects(() =>
    vault.open(context, { ...envelope, identity_hash: "A".repeat(64) }, now)
  );
  await rejects(() =>
    vault.open(context, { ...envelope, refresh_expires_at_ms: "3600" }, now)
  );
  await rejects(() =>
    vault.sealReply(context, reply({ refresh_token: "secret\n" }), {
      nowMs: now,
    })
  );
  await rejects(() =>
    vault.sealReply(context, reply(), { nowMs: now, unexpected: true } as never)
  );
  await rejects(() => createTokenVault("bad\nkey", new Map()));
  const wrongAlgorithm = await crypto.subtle.generateKey(
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  await rejects(() =>
    createTokenVault("key", new Map([["key", wrongAlgorithm]]))
  );
  const opened = await vault.open(context, envelope, now);
  await rejects(() => opened.needsRefresh(NaN));
});

Deno.test("authenticated invalid plaintext and mismatched identity hash fail closed", async () => {
  const { key, vault } = await fixture();
  const template = await vault.sealReply(context, reply(), { nowMs: now });
  for (
    const plaintext of [
      "not JSON",
      JSON.stringify({
        access_token: "synthetic-access",
        refresh_token: "synthetic-refresh",
        identity_id: "different-identity",
      }),
      JSON.stringify({
        access_token: "synthetic-access",
        refresh_token: "synthetic-refresh",
        identity_id: "synthetic-identity",
        unexpected: true,
      }),
      JSON.stringify({
        access_token: "",
        refresh_token: "synthetic-refresh",
        identity_id: "synthetic-identity",
      }),
    ]
  ) {
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const to64 = (value: Uint8Array) =>
      btoa(String.fromCharCode(...value)).replaceAll("+", "-").replaceAll(
        "/",
        "_",
      ).replace(/=+$/u, "");
    const additionalData = new TextEncoder().encode(
      JSON.stringify([
        template.schema,
        context.ownerRef,
        context.environment,
        context.generation,
        template.key_id,
        template.identity_hash,
        template.access_expires_at_ms,
        template.refresh_expires_at_ms,
      ]),
    );
    const ciphertext = new Uint8Array(
      await crypto.subtle.encrypt(
        { name: "AES-GCM", iv: nonce, additionalData, tagLength: 128 },
        key,
        new TextEncoder().encode(plaintext),
      ),
    );
    await rejects(() =>
      vault.open(context, {
        ...template,
        nonce: to64(nonce),
        ciphertext: to64(ciphertext),
      }, now)
    );
  }
});

Deno.test("plaintext UTF-8 size boundary is exact", async () => {
  const { vault } = await fixture();
  const overhead = new TextEncoder().encode(
    JSON.stringify({
      access_token: "",
      refresh_token: "r",
      identity_id: "i",
    }),
  ).length;
  const access = "a".repeat(32768 - overhead);
  const envelope = await vault.sealReply(
    context,
    reply({ access_token: access, refresh_token: "r", identity_id: "i" }),
    { nowMs: now },
  );
  assert((await vault.open(context, envelope, now)).accessToken() === access);
  await rejects(() =>
    vault.sealReply(
      context,
      reply({
        access_token: access + "a",
        refresh_token: "r",
        identity_id: "i",
      }),
      { nowMs: now },
    )
  );
});

Deno.test("custody requires positive deadlines with refresh strictly after access", async () => {
  const { vault, key } = await fixture();
  for (const rt_expires_in of ["59", "60"]) {
    await rejects(() =>
      vault.sealReply(context, reply({ rt_expires_in }), { nowMs: now })
    );
  }
  await rejects(() =>
    vault.sealReply(context, reply({ created_at: "1969-12-31T23:00:00Z" }), {
      nowMs: -3_600_000,
    })
  );
  const original = await vault.sealReply(context, reply(), { nowMs: now });
  for (
    const [access, refresh] of [
      [now + 5000, now + 5000],
      [now + 6000, now + 5000],
      [0, now + 5000],
      [-1, now + 5000],
    ]
  ) {
    const value = {
      ...original,
      access_expires_at_ms: access,
      refresh_expires_at_ms: refresh,
    };
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const to64 = (bytes: Uint8Array) =>
      btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll(
        "/",
        "_",
      ).replace(/=+$/u, "");
    const additionalData = new TextEncoder().encode(
      JSON.stringify([
        value.schema,
        context.ownerRef,
        context.environment,
        context.generation,
        value.key_id,
        value.identity_hash,
        access,
        refresh,
      ]),
    );
    const ciphertext = new Uint8Array(
      await crypto.subtle.encrypt(
        { name: "AES-GCM", iv: nonce, additionalData, tagLength: 128 },
        key,
        new TextEncoder().encode(
          JSON.stringify({
            access_token: "synthetic-access",
            refresh_token: "synthetic-refresh",
            identity_id: "synthetic-identity",
          }),
        ),
      ),
    );
    await rejects(() =>
      vault.open(context, {
        ...value,
        nonce: to64(nonce),
        ciphertext: to64(ciphertext),
      }, now)
    );
  }
});
