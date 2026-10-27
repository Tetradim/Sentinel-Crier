// deno-lint-ignore-file require-await -- Async test doubles implement asynchronous ports.
import {
  createGateway,
  createSupabaseVerifier,
  type Ledger,
  type Order,
  type Receipt,
  type StoredOrder,
} from "./gateway.ts";
import { createConnectTransport, signWebullRequest } from "./transport.ts";
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
}
const order: Order = {
  client_order_id: "b013cf27-fbab-4425-9c6c-6c3236766514",
  account_id: "account-a",
  environment: "sandbox",
  asset: "stock",
  symbol: "AAPL",
  quantity: 2,
  limit_price: "100.25",
  side: "buy",
};
function fixture(overrides?: Partial<Ledger>) {
  let cancelImpl: ((o: Order) => Promise<Receipt>) | undefined,
    lookupImpl: ((o: Order) => Promise<Receipt>) | undefined;
  const rows = new Map<string, StoredOrder>();
  let posts = 0, cancels = 0;
  let principal = "owner-a";
  let submit: (o: Order) => Promise<Receipt> = async (o) => ({
    client_order_id: o.client_order_id,
    status: "accepted",
    filled_quantity: 0,
    broker_order_id: "broker-a",
  });
  const key = (owner: string, id: string) => owner + id;
  const ledger: Ledger = {
    async blockInventory() {},
    async reserve(owner, o, fingerprint) {
      const k = key(owner, o.client_order_id), old = rows.get(k);
      if (old) return { created: false, row: structuredClone(old) };
      const row: StoredOrder = {
        owner,
        order: o,
        fingerprint,
        receipt: {
          client_order_id: o.client_order_id,
          status: "unknown",
          filled_quantity: 0,
        },
        revision: 1,
        cancel_claimed: false,
        cancel_pending: false,
        cancel_revision: null,
      };
      rows.set(k, row);
      return { created: true, row: structuredClone(row) };
    },
    async settleCancel(owner, id, cancelRevision) {
      const row = rows.get(key(owner, id));
      if (row && row.cancel_revision === cancelRevision) {
        row.cancel_pending = false;
      }
    },
    async read(owner, id) {
      return structuredClone(rows.get(key(owner, id)) ?? null);
    },
    async claimCancel(owner, id, revision) {
      const row = rows.get(key(owner, id));
      if (!row || row.revision !== revision || row.cancel_claimed) return null;
      row.cancel_claimed = true;
      row.cancel_pending = true;
      row.revision++;
      row.cancel_revision = row.revision;
      return structuredClone(row);
    },
    async save(owner, id, revision, receipt, action) {
      const row = rows.get(key(owner, id));
      if (!row || row.revision !== revision) return false;
      row.receipt = receipt;
      if (action === "cancel") row.cancel_pending = false;
      if (
        action === "lookup" && !row.cancel_pending &&
        ["accepted", "partially_filled"].includes(receipt.status)
      ) row.cancel_claimed = false;
      row.revision++;
      return true;
    },
  };
  Object.assign(ledger, overrides);
  const provider = {
    async connection(_owner: string, environment: "sandbox" | "production") {
      return {
        state: "connected" as const,
        environment,
        account_id: "account-a",
      };
    },
    async begin() {
      return {
        authorization_url:
          "https://passport.webull.com/oauth2/sandbox/authenticate/login?state=opaque",
        flow_id: "flow-a",
      };
    },
    async position() {
      return { symbol: "AAPL", quantity: 2 };
    },
    async submit(_owner: string, o: Order) {
      posts++;
      return await submit(o);
    },
    async lookup(_owner: string, o: Order) {
      if (lookupImpl) return await lookupImpl(o);
      return {
        client_order_id: o.client_order_id,
        status: "filled" as const,
        filled_quantity: 2,
        average_fill_price: "100.25",
        broker_order_id: "broker-a",
      };
    },
    async cancel(_owner: string, o: Order) {
      cancels++;
      if (cancelImpl) return await cancelImpl(o);
      return {
        client_order_id: o.client_order_id,
        status: "accepted" as const,
        filled_quantity: 0,
        broker_order_id: "broker-a",
      };
    },
  };
  const handle = createGateway({
    verify: async (token) => {
      if (token !== "verified") throw Error("invalid");
      return principal;
    },
    provider,
    ledger,
    capabilities: {
      available: true,
      environments: ["sandbox"],
      stocks: ["AAPL"],
      options: true,
    },
    timeoutMs: 20,
  });
  const request = (
    path: string,
    body?: unknown,
    method = body ? "POST" : "GET",
    token = "verified",
  ) =>
    handle(
      new Request("https://host.test/v1" + path, {
        method,
        headers: {
          authorization: "Bearer " + token,
          "content-type": "application/json",
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      }),
    );
  return {
    request,
    rows,
    get posts() {
      return posts;
    },
    get cancels() {
      return cancels;
    },
    setCancel(fn: (o: Order) => Promise<Receipt>) {
      cancelImpl = fn;
    },
    setLookup(fn: (o: Order) => Promise<Receipt>) {
      lookupImpl = fn;
    },
    setSubmit(fn: typeof submit) {
      submit = fn;
    },
    setOwner(o: string) {
      principal = o;
    },
  };
}
Deno.test("requires verified customer bearer before any gateway capability", async () => {
  const f = fixture();
  eq(
    (await f.request("/capabilities", undefined, "GET", "forged")).status,
    401,
  );
  eq(f.posts, 0);
});
Deno.test("inventory refusal is a conflict and never dispatches a source order", async () => {
  for (
    const reason of [
      "insufficient_tracked_long_position",
      "source_inventory_reconciliation_required",
    ] as const
  ) {
    const f = fixture({
      reserve: async () => ({ created: false, row: null, reason }),
    });
    const response = await f.request("/orders", { ...order, side: "sell" });
    eq(response.status, 409);
    eq((await response.json()).error, reason);
    eq(f.posts, 0);
  }
});
Deno.test("contradictory authoritative identity fences inventory before rejecting lookup", async () => {
  const fences: string[] = [];
  const f = fixture({
    blockInventory: async (owner, id) => {
      fences.push(owner + ":" + id);
    },
  });
  await f.request("/orders", order);
  f.setLookup(async () => ({
    client_order_id: order.client_order_id,
    broker_order_id: "changed-broker-id",
    status: "accepted",
    filled_quantity: 0,
  }));
  const response = await f.request(
    "/orders/" + order.client_order_id +
      "?environment=sandbox&account_id=account-a",
  );
  eq(response.status, 503);
  eq(fences, ["owner-a:" + order.client_order_id]);
});
Deno.test("reserves concurrent duplicate submits once and rejects changed intent", async () => {
  const f = fixture();
  const responses = await Promise.all([
    f.request("/orders", order),
    f.request("/orders", order),
  ]);
  eq(responses.map((r) => r.status), [200, 200]);
  eq(f.posts, 1);
  eq((await f.request("/orders", { ...order, quantity: 3 })).status, 409);
  eq(f.posts, 1);
});
Deno.test("uncertain submit is never posted again and GET reconciles", async () => {
  const f = fixture();
  f.setSubmit(async () => {
    throw Error("secret provider timeout");
  });
  const a = await f.request("/orders", order);
  eq((await a.json()).status, "unknown");
  eq((await (await f.request("/orders", order)).json()).status, "unknown");
  eq(f.posts, 1);
  const r = await f.request(
    "/orders/" + order.client_order_id +
      "?environment=sandbox&account_id=account-a",
  );
  eq((await r.json()).status, "filled");
  eq(f.posts, 1);
});
Deno.test("rejects account/environment mismatch and noncanonical contracts", async () => {
  const f = fixture();
  eq(
    (await f.request("/orders", { ...order, account_id: "other" })).status,
    403,
  );
  eq(
    (await f.request("/orders", { ...order, environment: "production" }))
      .status,
    503,
  );
  for (
    const patch of [
      { symbol: "aapl" },
      { quantity: 1.2 },
      { limit_price: "1e2" },
      { asset: "option", symbol: "AAPL  261230C00100000" },
      { extra: "field" },
    ]
  ) eq((await f.request("/orders", { ...order, ...patch })).status, 400);
  eq(f.posts, 0);
});
Deno.test("customer cannot reconcile another customer order", async () => {
  const f = fixture();
  await f.request("/orders", order);
  f.setOwner("other-owner");
  eq(
    (await f.request(
      "/orders/" + order.client_order_id +
        "?environment=sandbox&account_id=account-a",
    )).status,
    404,
  );
});
Deno.test("cancel acknowledgement is not assumed canceled; duplicate cancels dispatch once", async () => {
  const f = fixture();
  await f.request("/orders", order);
  const body = { environment: "sandbox", account_id: "account-a" };
  for (let i = 0; i < 2; i++) {
    eq(
      (await (await f.request(
        "/orders/" + order.client_order_id + "/cancel",
        body,
      )).json()).status,
      "accepted",
    );
  }
  eq(f.cancels, 1);
});
Deno.test("provider malformed receipt remains unknown without leaking errors", async () => {
  const f = fixture();
  f.setSubmit(
    async () => ({
      ...order,
      status: "accepted",
      filled_quantity: 9,
    } as unknown as Receipt),
  );
  const response = await f.request("/orders", order);
  const body = await response.json();
  eq(body.status, "unknown");
  eq(body.filled_quantity, 0);
});
Deno.test("Supabase verifier checks remote user, never accepts decoded claims", async () => {
  let authorization = "";
  const verify = createSupabaseVerifier({
    url: "https://project.supabase.co",
    publishableKey: "public",
    fetch: async (_url, init) => {
      authorization = new Headers(init?.headers).get("authorization")!;
      return Response.json({
        id: "b013cf27-fbab-4425-9c6c-6c3236766514",
        is_anonymous: false,
      });
    },
  });
  eq(await verify("jwt"), order.client_order_id);
  eq(authorization, "Bearer jwt");
});
Deno.test("official signature worked example matches documentation", async () => {
  const result = await signWebullRequest({
    host: "api.webull.com",
    path: "/trade/place_order",
    query: { a1: "webull", a2: "123", a3: "xxx", q1: "yyy" },
    body:
      '{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}',
    appKey: "776da210ab4a452795d74e726ebd74b6",
    appSecret: "0f50a2e853334a9aae1a783bee120c1f",
    timestamp: "2022-01-04T03:55:31Z",
    nonce: "48ef5afed43d4d91ae514aaeafbc29ba",
  });
  eq(result["x-signature"], "kvlS6opdZDhEBo5jq40nHYXaLvM=");
});
Deno.test("Connect transport pins host and never retries mutation or follows redirects", async () => {
  let calls = 0;
  const transport = createConnectTransport({
    environment: "sandbox",
    appKey: "app",
    appSecret: "secret",
    fetch: async (url, init) => {
      calls++;
      eq(new URL(String(url)).hostname, "oauth-open-api.sandbox.webull.com");
      eq(init?.redirect, "error");
      throw Error("ambiguous");
    },
  });
  try {
    await transport({
      path: "/oauth-openapi/approved-path",
      method: "POST",
      body: { a: 1 },
      accessToken: "private",
    });
  } catch { /* Expected transport refusal; request count is asserted below. */ }
  eq(calls, 1);
  try {
    await transport({
      path: "//evil.test/secret",
      method: "GET",
      accessToken: "private",
    });
  } catch { /* Expected transport refusal; request count is asserted below. */ }
  eq(calls, 1);
});

Deno.test("timed out submit cannot overwrite later reconciliation", async () => {
  const f = fixture();
  let resolve!: (value: Receipt) => void;
  f.setSubmit(() =>
    new Promise((r) => {
      resolve = r;
    })
  );
  const response = await f.request("/orders", order);
  eq((await response.json()).status, "unknown");
  const lookup = await f.request(
    "/orders/" + order.client_order_id +
      "?environment=sandbox&account_id=account-a",
  );
  eq((await lookup.json()).status, "filled");
  resolve({
    client_order_id: order.client_order_id,
    status: "accepted",
    filled_quantity: 0,
  });
  await Promise.resolve();
  eq((await (await f.request("/orders", order)).json()).status, "filled");
  eq(f.posts, 1);
});
Deno.test("sell preflight refuses to exceed observed long position", async () => {
  const f = fixture();
  eq(
    (await f.request("/orders", { ...order, quantity: 3, side: "sell" }))
      .status,
    409,
  );
  eq(f.posts, 0);
});
Deno.test("32 character native client ids accepted", async () => {
  const f = fixture();
  const response = await f.request("/orders", {
    ...order,
    client_order_id: order.client_order_id.replaceAll("-", ""),
  });
  eq(response.status, 200);
  eq((await response.json()).status, "accepted");
});
Deno.test("stock and option are distinct and exact OCC dates required", async () => {
  const f = fixture();
  eq(
    (await f.request("/orders", {
      ...order,
      asset: "option",
      symbol: "AAPL261230C00100000",
    })).status,
    200,
  );
  eq(
    (await f.request("/orders", {
      ...order,
      client_order_id: "a".repeat(32),
      asset: "option",
      symbol: "AAPL260230C00100000",
    })).status,
    400,
  );
});
Deno.test("Supabase verifier rejects unauthorized and anonymous user replies", async () => {
  for (
    const response of [
      new Response(null, { status: 401 }),
      Response.json({ id: order.client_order_id, is_anonymous: true }),
      Response.json({ id: "forged" }),
    ]
  ) {
    const verify = createSupabaseVerifier({
      url: "https://project.supabase.co",
      publishableKey: "public",
      fetch: () => Promise.resolve(response),
    });
    let rejected = false;
    try {
      await verify("jwt");
    } catch {
      rejected = true;
    }
    eq(rejected, true);
  }
});
Deno.test("fresh authoritative GET rearms an uncertain cancellation for explicit retry", async () => {
  const f = fixture();
  await f.request("/orders", order);
  const cancel = "/orders/" + order.client_order_id + "/cancel",
    scope = { environment: "sandbox", account_id: "account-a" };
  f.setCancel(async () => {
    throw Error("ambiguous cancel");
  });
  await f.request(cancel, scope);
  await f.request(cancel, scope);
  eq(f.cancels, 1);
  f.setLookup(async (o) => ({
    client_order_id: o.client_order_id,
    status: "accepted",
    filled_quantity: 0,
  }));
  await f.request(
    "/orders/" + order.client_order_id +
      "?environment=sandbox&account_id=account-a",
  );
  await f.request(cancel, scope);
  eq(f.cancels, 2);
});
Deno.test("GET during in-flight cancellation cannot rearm duplicate cancel", async () => {
  const f = fixture();
  await f.request("/orders", order);
  let resolve!: (value: Receipt) => void;
  let entered!: () => void;
  const started = new Promise<void>((r) => {
    entered = r;
  });
  f.setCancel(() => {
    entered();
    return new Promise((r) => {
      resolve = r;
    });
  });
  f.setLookup(async (o) => ({
    client_order_id: o.client_order_id,
    status: "accepted",
    filled_quantity: 0,
  }));
  const scope = { environment: "sandbox", account_id: "account-a" },
    path = "/orders/" + order.client_order_id;
  const cancel = f.request(path + "/cancel", scope);
  await started;
  await f.request(path + "?environment=sandbox&account_id=account-a");
  await f.request(path + "/cancel", scope);
  eq(f.cancels, 1);
  resolve({
    client_order_id: order.client_order_id,
    status: "accepted",
    filled_quantity: 0,
  });
  await cancel;
});

Deno.test("rejected receipt cannot contain fills and poison later reconciliation", async () => {
  const f = fixture();
  f.setSubmit(async (o) => ({
    client_order_id: o.client_order_id,
    status: "rejected",
    filled_quantity: 1,
  }));
  eq((await (await f.request("/orders", order)).json()).status, "unknown");
  eq(
    (await (await f.request(
      "/orders/" + order.client_order_id +
        "?environment=sandbox&account_id=account-a",
    )).json()).status,
    "filled",
  );
});
Deno.test("broker identity cannot change during reconciliation", async () => {
  const f = fixture();
  await f.request("/orders", order);
  f.setLookup(async (o) => ({
    client_order_id: o.client_order_id,
    broker_order_id: "different-order",
    status: "filled",
    filled_quantity: 2,
  }));
  const response = await f.request(
    "/orders/" + order.client_order_id +
      "?environment=sandbox&account_id=account-a",
  );
  eq(response.status, 503);
  const stored = await (await f.request("/orders", order)).json();
  eq(stored.status, "accepted");
  eq(stored.broker_order_id, "broker-a");
});

Deno.test("lookup failure cannot masquerade as fresh cached terminal evidence", async () => {
  const f = fixture();
  await f.request("/orders", order);
  const path = "/orders/" + order.client_order_id +
    "?environment=sandbox&account_id=account-a";
  await f.request(path);
  f.setLookup(async () => {
    throw Error("broker offline");
  });
  eq((await f.request(path)).status, 503);
  eq(f.posts, 1);
});
