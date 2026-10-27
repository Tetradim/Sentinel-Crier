// deno-lint-ignore-file require-await -- injected HTTP test ports.
import { createSignedTokenTransport } from "./token_transport.ts";
import { createTokenRequest } from "../webull-connect/oauth_contract.ts";
function eq(a: unknown, b: unknown) {
  if (a !== b) throw Error("Unexpected value");
}
const request = createTokenRequest("sandbox", {
  client_id: "client",
  client_secret: "private",
  grant_type: "authorization_code",
  code: "code",
});
Deno.test("token exchange is signed, pinned, form encoded and never automatically retried", async () => {
  let calls = 0;
  const send = createSignedTokenTransport({
    environment: "sandbox",
    appKey: "app",
    appSecret: "secret",
    fetch: async (url, init) => {
      calls++;
      eq(
        String(url),
        "https://oauth-open-api.sandbox.webull.com/oauth2/tokens/create",
      );
      eq(init?.redirect, "error");
      eq(
        new Headers(init?.headers).get("content-type"),
        "application/x-www-form-urlencoded",
      );
      if (!new Headers(init?.headers).get("x-signature")) {
        throw Error("Unsigned");
      }
      throw Error("ambiguous");
    },
  });
  let failed = false;
  try {
    await send(request, new AbortController().signal);
  } catch {
    failed = true;
  }
  eq(failed, true);
  eq(calls, 1);
});
Deno.test("cross-environment token dispatch and oversized replies are rejected", async () => {
  let calls = 0;
  const send = createSignedTokenTransport({
    environment: "production",
    appKey: "app",
    appSecret: "secret",
    fetch: async () => {
      calls++;
      return new Response("x".repeat(70000));
    },
  });
  try {
    await send(request, new AbortController().signal);
  } catch {
    /* A sandbox request must be refused before production dispatch. */
  }
  eq(calls, 0);
  const prod = createTokenRequest("production", {
    client_id: "client",
    client_secret: "private",
    grant_type: "authorization_code",
    code: "code",
  });
  let failed = false;
  try {
    await send(prod, new AbortController().signal);
  } catch {
    failed = true;
  }
  eq(failed, true);
  eq(calls, 1);
});
