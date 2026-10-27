// deno-lint-ignore-file require-await -- asynchronous test ports.
import {
  type BrowserFlows,
  createAuthorizationHandler,
} from "./authorization.ts";
const owner = "b013cf27-fbab-4425-9c6c-6c3236766514";
const base = "https://project.test/functions/v1/crier-webull-host";
const state = "s".repeat(43), binding = "b".repeat(43);
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw Error(`Expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
}
function fixture() {
  let flow: Record<string, unknown> | null = null,
    exchange = 0,
    begins = 0,
    refreshes = 0,
    revokes = 0,
    admitted = true;
  const flows: BrowserFlows = {
    async issue(who, environment, hash) {
      flow = {
        id: crypto.randomUUID(),
        owner: who,
        environment,
        expires_at_ms: Date.now() + 300000,
        state_hash: null,
        ticket: hash,
        used: false,
      };
      return { ...flow } as never;
    },
    async launch(hash) {
      if (!flow || flow.ticket !== hash || flow.used) return null;
      flow.used = true;
      return { ...flow } as never;
    },
    async attach(id, hash, expires) {
      if (flow?.id !== id) return false;
      flow.state_hash = hash;
      flow.expires_at_ms = expires;
      return true;
    },
    async resolve(hash) {
      return flow?.state_hash === hash && !flow.complete
        ? { ...flow } as never
        : null;
    },
    async complete(id) {
      if (flow?.id !== id) return false;
      flow.complete = true;
      return true;
    },
    async invalidate() {
      flow = null;
    },
  };
  const coordinator = {
    async begin(who: unknown) {
      eq(who, owner);
      begins++;
      return {
        url: () =>
          `https://passport.webull.com/oauth2/sandbox/authenticate/login?state=${state}`,
        browserBinding: () => binding,
        expiresAtMs: Date.now() + 300000,
        generation: 1,
        toJSON: () => "[REDACTED]",
      };
    },
    async callback(
      who: unknown,
      input: { state: string; browserBinding: string; code: string },
    ) {
      eq(who, owner);
      if (
        input.state !== state || input.browserBinding !== binding || exchange
      ) throw Error("Rejected");
      exchange++;
      return {
        state: "active" as const,
        generation: 1,
        accessExpiresAtMs: Date.now() + 1800000,
        refreshExpiresAtMs: Date.now() + 86400000,
      };
    },
    async status() {
      return { state: "active" as const, generation: 1 };
    },
    async refresh() {
      refreshes++;
      return { state: "active" as const, generation: 2 };
    },
    async revoke() {
      revokes++;
      return { state: "revoked" as const, generation: 3 };
    },
  };
  const handle = createAuthorizationHandler({
    publicBase: base,
    verify: async (token) => {
      if (token !== "customer") throw Error("invalid");
      return owner;
    },
    coordinators: { sandbox: coordinator },
    flows,
    admit: async () => admitted,
  });
  const request = (
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ) =>
    handle(
      new Request("https://internal.test" + path, {
        method: body ? "POST" : "GET",
        headers: {
          ...(body ? { "content-type": "application/json" } : {}),
          ...headers,
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      }),
    );
  return {
    request,
    get exchange() {
      return exchange;
    },
    get begins() {
      return begins;
    },
    get refreshes() {
      return refreshes;
    },
    get revokes() {
      return revokes;
    },
    setAdmitted(v: boolean) {
      admitted = v;
    },
  };
}
async function launch(f: ReturnType<typeof fixture>) {
  const begun = await f.request(
    "/v1/connect/begin",
    { environment: "sandbox" },
    { authorization: "Bearer customer" },
  );
  eq(begun!.status, 200);
  const value = await begun!.json();
  const url = new URL(value.authorization_url);
  eq(url.origin + url.pathname, base + "/v1/connect/launch");
  const response = await f.request("/v1/connect/launch" + url.search);
  eq(response!.status, 303);
  return {
    ticket: url.search,
    cookie: response!.headers.get("set-cookie")!,
    redirect: response!.headers.get("location")!,
  };
}
Deno.test("native begin never exchanges a code or exposes browser binding; browser launch sets cookie", async () => {
  const f = fixture();
  const a = await launch(f);
  eq(f.begins, 1);
  eq(f.exchange, 0);
  if (
    !a.cookie.includes("Secure") || !a.cookie.includes("HttpOnly") ||
    !a.cookie.includes("SameSite=Lax") || !a.cookie.includes("Path=/")
  ) throw Error("Missing cookie security");
  eq(new URL(a.redirect).origin, "https://passport.webull.com");
  eq((await f.request("/v1/connect/launch" + a.ticket))!.status, 400);
});
Deno.test("callback binds stored owner and browser cookie; code replay never re-exchanges", async () => {
  const f = fixture();
  const a = await launch(f);
  const query = "?state=" + state + "&code=secret-code";
  eq((await f.request("/v1/connect/callback" + query))!.status, 400);
  eq(f.exchange, 0);
  const response = await f.request("/v1/connect/callback" + query, undefined, {
    cookie: a.cookie.split(";")[0],
  });
  eq(response!.status, 200);
  eq(f.exchange, 1);
  if ((await response!.text()).includes("secret-code")) {
    throw Error("Code leaked");
  }
  eq(
    (await f.request("/v1/connect/callback" + query, undefined, {
      cookie: a.cookie.split(";")[0],
    }))!.status,
    400,
  );
  eq(f.exchange, 1);
});
Deno.test("forged principal, unknown body fields and duplicate callback fields are rejected", async () => {
  const f = fixture();
  eq(
    (await f.request("/v1/connect/begin", { environment: "sandbox" }))!.status,
    401,
  );
  eq(
    (await f.request("/v1/connect/begin", {
      environment: "sandbox",
      owner: "attacker",
    }, { authorization: "Bearer customer" }))!.status,
    400,
  );
  const a = await launch(f);
  eq(
    (await f.request(
      "/v1/connect/callback?state=" + state + "&state=" + state + "&code=x",
      undefined,
      { cookie: a.cookie.split(";")[0] },
    ))!.status,
    400,
  );
  eq(f.exchange, 0);
});
Deno.test("refresh and revoke require bearer and admission; no token appears in status", async () => {
  const f = fixture();
  eq(
    (await f.request("/v1/connect/refresh", { environment: "sandbox" }))!
      .status,
    401,
  );
  const headers = { authorization: "Bearer customer" };
  eq(
    (await f.request(
      "/v1/connect/refresh",
      { environment: "sandbox" },
      headers,
    ))!.status,
    200,
  );
  eq(f.refreshes, 1);
  eq(
    (await f.request(
      "/v1/connect/revoke",
      { environment: "sandbox" },
      headers,
    ))!.status,
    200,
  );
  eq(f.revokes, 1);
  f.setAdmitted(false);
  eq(
    (await f.request("/v1/connect/begin", { environment: "sandbox" }, headers))!
      .status,
    429,
  );
  const status = await f.request(
    "/v1/connect/status?environment=sandbox",
    undefined,
    headers,
  );
  eq(status!.status, 429);
});
