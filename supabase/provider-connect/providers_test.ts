// Injected fetch ports intentionally return resolved promises without network I/O.
// deno-lint-ignore-file require-await
import { ProviderApplication, ProviderRejected } from "./providers.ts";
function assert(v: unknown): asserts v {
  if (!v) throw new Error("assertion failed");
}
async function rejects(f: () => unknown) {
  try {
    await f();
  } catch (e) {
    assert(
      e instanceof ProviderRejected &&
        e.message === "Provider authorization was rejected.",
    );
    return;
  }
  throw new Error("expected rejection");
}
const app = (provider: "alpaca" | "discord") =>
  new ProviderApplication({
    provider,
    clientId: "client",
    clientSecret: "secret",
    callback: "https://crier.example/callback",
  });
const id = "12345678-1234-1234-1234-123456789abc";
const token = { token_type: "Bearer", access_token: "token" };
const reply = (v: unknown) => new Response(JSON.stringify(v));
Deno.test("authorize pinned URLs and minimum scopes", async () => {
  const a = new URL(app("alpaca").authorize("state", "alerts", "paper"));
  assert(
    a.origin === "https://app.alpaca.markets" && !a.searchParams.has("scope") &&
      a.searchParams.get("env") === "paper",
  );
  assert(
    new URL(app("alpaca").authorize("state", "trade", "live")).searchParams.get(
      "scope",
    ) === "trading",
  );
  assert(
    new URL(app("discord").authorize("state", "alerts", "live")).searchParams
      .get("scope") === "webhook.incoming",
  );
  await rejects(() => app("discord").authorize("state", "trade", "paper"));
  await rejects(() =>
    new ProviderApplication({
      provider: "alpaca",
      clientId: "client",
      clientSecret: "secret",
      callback: "http://bad/",
    })
  );
});
Deno.test("Alpaca exchange form and selected identity produce exact grant", async () => {
  const calls: string[] = [];
  const grant = await app("alpaca").exchange(
    "code",
    "trade",
    "paper",
    async (url, init) => {
      calls.push(String(url));
      assert(init?.redirect === "error" && init.signal instanceof AbortSignal);
      if (calls.length === 1) {
        const form = new URLSearchParams(String(init?.body));
        assert(
          form.get("client_secret") === "secret" && form.get("code") === "code",
        );
        return reply({ ...token, scope: "trading", account_id: id });
      }
      assert(
        new Headers(init?.headers).get("authorization") === "Bearer token",
      );
      return reply({ id });
    },
  );
  assert(
    calls.join("|") ===
      "https://api.alpaca.markets/oauth/token|https://paper-api.alpaca.markets/v2/account",
  );
  assert(
    JSON.stringify(grant) ===
      JSON.stringify({
        provider: "alpaca",
        environment: "paper",
        purpose: "trade",
        account_id: id,
        credential: "token",
        guild_id: "",
        channel_id: "",
        scopes: ["trading"],
      }),
  );
});
const webhook = {
  type: 1,
  id: "123",
  guild_id: "456",
  channel_id: "789",
  token: "hook-token",
  url: "https://discord.com/api/webhooks/123/hook-token",
};
Deno.test("Discord only returns validated canonical webhook credential", async () => {
  const grant = await app("discord").exchange(
    "code",
    "alerts",
    "paper",
    async () => reply({ ...token, scope: "webhook.incoming", webhook }),
  );
  assert(
    grant.credential === webhook.url && grant.guild_id === "456" &&
      grant.account_id === "",
  );
  for (
    const patch of [
      { type: "1" },
      { id: "01" },
      { guild_id: "18446744073709551616" },
      { token: "bad token" },
      { url: "https://evil.example/hook" },
    ]
  ) {
    await rejects(() =>
      app("discord").exchange("code", "alerts", "paper", async () =>
        reply({
          ...token,
          scope: "webhook.incoming",
          webhook: { ...webhook, ...patch },
        }))
    );
  }
});
Deno.test("reject excessive scopes, duplicate JSON, redirects, malformed and oversized decoded bodies", async () => {
  for (
    const body of [
      '{"token_type":"Bearer","token_type":"Bearer","access_token":"token"}',
      '{"token_type":"Bearer","token_\\u0074ype":"Bearer","access_token":"token"}',
      ...[null, [], {}, "trading", "trading trading"].map((scope) =>
        JSON.stringify({ ...token, scope })
      ),
      "[]",
      "not json",
      " ".repeat(65537),
    ]
  ) {
    await rejects(() =>
      app("alpaca").exchange(
        "code",
        "alerts",
        "live",
        async () => new Response(body),
      )
    );
  }
  await rejects(() =>
    app("alpaca").exchange(
      "code",
      "alerts",
      "live",
      async () => new Response("", { status: 302 }),
    )
  );
  await rejects(() =>
    app("alpaca").exchange("code", "alerts", "live", async () => {
      throw new Error("sensitive");
    })
  );
  let call = 0;
  await rejects(() =>
    app("alpaca").exchange(
      "code",
      "alerts",
      "live",
      async () =>
        ++call === 1
          ? reply({ ...token, account_id: id })
          : reply({ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" }),
    )
  );
});
Deno.test("decoded stream cap cancels body before reading unbounded input", async () => {
  let cancelled = false;
  await rejects(() =>
    app("alpaca").exchange(
      "code",
      "alerts",
      "paper",
      async () =>
        new Response(
          new ReadableStream({
            pull(controller) {
              controller.enqueue(new Uint8Array(32769));
            },
            cancel() {
              cancelled = true;
            },
          }),
        ),
    )
  );
  assert(cancelled);
});
Deno.test("explicit null scope is rejected before account lookup", async () => {
  let calls = 0;
  await rejects(() =>
    app("alpaca").exchange(
      "code",
      "alerts",
      "paper",
      async () =>
        ++calls === 1 ? reply({ ...token, scope: null }) : reply({ id }),
    )
  );
  assert(calls === 1);
});
Deno.test("callback requires an explicit HTTPS authority", async () => {
  await rejects(() =>
    new ProviderApplication({
      provider: "alpaca",
      clientId: "client",
      clientSecret: "secret",
      callback: "https:callback.example/path",
    })
  );
});
Deno.test("operation deadline covers a stalled response body", async () => {
  let cancelled = false;
  const start = Date.now();
  await rejects(() =>
    app("alpaca").exchange(
      "code",
      "alerts",
      "paper",
      async () =>
        new Response(
          new ReadableStream({
            cancel() {
              cancelled = true;
            },
          }),
        ),
    )
  );
  assert(
    cancelled && Date.now() - start >= 14000 && Date.now() - start < 20000,
  );
});
