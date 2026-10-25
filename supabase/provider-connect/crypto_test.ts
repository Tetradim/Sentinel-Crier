import {
  type FlowContext,
  GrantCipher,
  randomToken,
  sha256,
} from "./crypto.ts";
const context: FlowContext = {
  flow_id: "a".repeat(43),
  owner_id: "customer",
  provider: "alpaca",
  purpose: "alerts",
  environment: "paper",
  challenge: "b".repeat(64),
};
function assert(v: unknown): asserts v {
  if (!v) throw new Error("assertion failed");
}
async function rejects(f: () => unknown) {
  try {
    await f();
  } catch (e) {
    assert(e instanceof Error && e.message === "Authorization flow rejected");
    return;
  }
  throw new Error("expected rejection");
}
Deno.test("crypto roundtrip, random nonces, context and kind binding", async () => {
  const cipher = new GrantCipher(
    { current: new Uint8Array(32).fill(7) },
    "current",
  );
  const a = await cipher.seal(context, "grant", { credential: "secret" });
  const b = await cipher.seal(context, "grant", { credential: "secret" });
  assert(a.nonce !== b.nonce && !JSON.stringify(a).includes("secret"));
  assert(
    JSON.stringify(await cipher.open(context, "grant", a)) ===
      '{"credential":"secret"}',
  );
  const changes = {
    flow_id: "c".repeat(43),
    owner_id: "other-customer",
    provider: "discord",
    purpose: "trade",
    environment: "live",
    challenge: "c".repeat(64),
  };
  for (const key of Object.keys(context)) {
    await rejects(() =>
      cipher.open(
        { ...context, [key]: changes[key as keyof FlowContext] },
        "grant",
        a,
      )
    );
  }
  await rejects(() => cipher.open(context, "state", a));
});
Deno.test("crypto rotation, malformed envelopes, tampering, explicit keys and bounds", async () => {
  const keys = {
    old: new Uint8Array(32).fill(1),
    current: new Uint8Array(32).fill(2),
  };
  const envelope = await new GrantCipher(keys, "old").seal(
    context,
    "state",
    "state",
  );
  assert(
    await new GrantCipher(keys, "current").open(context, "state", envelope) ===
      "state",
  );
  await rejects(() => new GrantCipher({ bad: new Uint8Array(31) }, "bad"));
  await rejects(() => new GrantCipher(keys, "missing"));
  for (
    const patch of [
      { version: 2 },
      { key_id: "missing" },
      { nonce: envelope.nonce + "=" },
      { ciphertext: "A".repeat(24) },
      { extra: true },
    ]
  ) {
    await rejects(() =>
      new GrantCipher(keys, "current").open(context, "state", {
        ...envelope,
        ...patch,
      })
    );
  }
  await rejects(() =>
    new GrantCipher(keys, "old").seal(context, "grant", "x".repeat(65537))
  );
  await rejects(() =>
    new GrantCipher(keys, "old").seal(context, "grant", { n: NaN })
  );
  await rejects(() =>
    new GrantCipher(keys, "old").seal(context, "grant", undefined)
  );
  await rejects(() =>
    new GrantCipher({ current: keys.current }, "current").open(
      context,
      "state",
      envelope,
    )
  );
});
Deno.test("random tokens and SHA256 match protocol", async () => {
  assert(/^[A-Za-z0-9_-]{43}$/.test(randomToken()));
  assert(randomToken() !== randomToken());
  assert(
    await sha256("abc") ===
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});
