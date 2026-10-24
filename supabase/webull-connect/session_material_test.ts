import { createSessionMaterial, hashSessionToken } from "./session_material.ts";

function assert(value: unknown): asserts value {
  if (!value) throw new Error("assertion failed");
}

Deno.test("generates fresh independent 32-byte state and browser binding", async () => {
  const tokens = new Set<string>();
  for (let i = 0; i < 4; i++) {
    const material = await createSessionMaterial();
    for (const token of [material.state(), material.browserBinding()]) {
      assert(/^[A-Za-z0-9_-]{43}$/.test(token));
      assert(
        atob(token.replaceAll("-", "+").replaceAll("_", "/") + "=").length ===
          32,
      );
      assert(!tokens.has(token));
      tokens.add(token);
    }
    assert(material.stateHash === await hashSessionToken(material.state()));
    assert(
      material.bindingHash ===
        await hashSessionToken(material.browserBinding()),
    );
    assert(material.stateHash !== material.bindingHash);
  }
  assert(tokens.size === 8);
});

Deno.test("hashes UTF-8 token text consistently with Python sessions", async () => {
  assert(
    await hashSessionToken("A".repeat(43)) ===
      "0f007385b6f9d4b7eeb2748605afe1a984a0a3bfa3f014d09e2a784ce9e5cd1a",
  );
});

Deno.test("ordinary inspection never exposes browser or state values", async () => {
  const material = await createSessionMaterial();
  const output = [
    JSON.stringify(material),
    Deno.inspect(material),
    String(material),
    JSON.stringify({ ...material }),
  ].join(" ");
  assert(!output.includes(material.state()));
  assert(!output.includes(material.browserBinding()));
  assert(output.includes("REDACTED"));
  assert(Object.isFrozen(material));
});

Deno.test("invalid callback token material is rejected without echo", async () => {
  for (
    const value of [
      null,
      [],
      3,
      "",
      "x".repeat(1000),
      " ".repeat(43),
      "secret\n".repeat(7),
    ]
  ) {
    let rejected = false;
    try {
      await hashSessionToken(value as never);
    } catch (error) {
      assert(
        error instanceof Error &&
          error.message === "Invalid Webull session token",
      );
      rejected = true;
    }
    assert(rejected);
  }
});
