import { createHandler } from "./gateway.ts";

function assert(value: unknown, message = "assertion failed"): asserts value {
  if (!value) throw new Error(message);
}

function fixture(
  results: { status: number; body: unknown }[] = [{
    status: 200,
    body: { ok: true },
  }],
) {
  const calls: Record<string, unknown>[] = [];
  let time = 0;
  const handler = createHandler({
    url: "https://example.supabase.co",
    serviceKey: "server-secret",
    fetch: (input, init) => {
      assert(
        String(input) ===
          "https://example.supabase.co/rest/v1/rpc/crier_dispatch",
      );
      assert(new Headers(init?.headers).get("apikey") === "server-secret");
      calls.push(JSON.parse(String(init?.body)));
      return Promise.resolve(Response.json(
        results[Math.min(calls.length - 1, results.length - 1)],
      ));
    },
    now: () => time,
    sleep: (ms) => {
      time += ms;
      return Promise.resolve();
    },
  });
  return { handler, calls, time: () => time };
}

Deno.test("routes deployed paths and passes only opaque token to RPC", async () => {
  const { handler, calls } = fixture();
  const response = await handler(
    new Request("https://relay.test/functions/v1/crier/api/connect/invite", {
      method: "POST",
      headers: {
        authorization: "Bearer device-token",
        "x-forwarded-for": "spoofed",
      },
    }),
  );
  assert(response.status === 200);
  assert(calls[0].p_path === "/api/connect/invite");
  assert(calls[0].p_token === "device-token");
  assert(calls[0].p_peer === "global");
  assert(response.headers.get("cache-control") === "no-store");
  assert(!response.headers.has("access-control-allow-origin"));
  assert(!(await response.text()).includes("server-secret"));
});

Deno.test("health checks database and invitation page is static", async () => {
  const { handler, calls } = fixture([{
    status: 503,
    body: { status: "unavailable" },
  }]);
  assert(
    (await handler(new Request("https://relay.test/crier/health"))).status ===
      503,
  );
  assert(calls[0].p_path === "/health");
  const page = await handler(
    new Request("https://relay.test/functions/v1/crier/connect"),
  );
  assert((await page.text()).includes("Copy the full invitation"));
  assert(calls.length === 1);
});

Deno.test("rejects streamed oversized bodies before JSON parsing or RPC", async () => {
  const { handler, calls } = fixture();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(20_000));
      controller.enqueue(new Uint8Array(20_000));
      controller.close();
    },
  });
  const response = await handler(
    new Request("https://relay.test/crier/api/connect/host", {
      method: "POST",
      body,
    }),
  );
  assert(response.status === 413);
  assert(calls.length === 0);
});

Deno.test("rejects malformed JSON and malformed authorization", async () => {
  const { handler, calls } = fixture();
  assert(
    (await handler(
      new Request("https://relay.test/crier/api/connect/host", {
        method: "POST",
        body: "{",
      }),
    )).status === 422,
  );
  assert(
    (await handler(
      new Request("https://relay.test/crier/api/sync/events", {
        headers: { authorization: "Basic secret" },
      }),
    )).status === 401,
  );
  assert(calls.length === 0);
});

Deno.test("invalid event credentials fail immediately without waiting", async () => {
  const { handler, calls, time } = fixture([{
    status: 401,
    body: { detail: "Pair first" },
  }]);
  const response = await handler(
    new Request("https://relay.test/crier/api/sync/events?wait=25", {
      headers: { authorization: "Bearer invalid" },
    }),
  );
  assert(response.status === 401 && calls.length === 1 && time() === 0);
});

Deno.test("long poll reads durable events and rechecks revocation", async () => {
  const { handler, calls, time } = fixture([
    { status: 200, body: { events: [], cursor: 7 } },
    { status: 401, body: { detail: "Pair first" } },
  ]);
  const response = await handler(
    new Request("https://relay.test/crier/api/sync/events?after=7&wait=25", {
      headers: { authorization: "Bearer receiver" },
    }),
  );
  assert(response.status === 401 && calls.length === 2 && time() === 1000);
  assert((calls[0].p_query as Record<string, string>).wait === "0");
});

Deno.test("long poll stops on events and bounds an empty wait", async () => {
  const request = () =>
    new Request("https://relay.test/crier/api/sync/events?wait=25", {
      headers: { authorization: "Bearer receiver" },
    });
  const ready = fixture([{
    status: 200,
    body: { events: [{ cursor: 1 }], cursor: 1 },
  }]);
  assert(
    (await ready.handler(request())).status === 200 && ready.calls.length === 1,
  );
  const empty = fixture([{ status: 200, body: { events: [], cursor: 0 } }]);
  assert((await empty.handler(request())).status === 200);
  assert(empty.time() === 25_000 && empty.calls.length === 25);
});

Deno.test("invalid waits and duplicate query parameters never reach database", async () => {
  const { handler, calls } = fixture();
  for (const query of ["wait=26", "wait=-1", "wait=NaN", "wait=1&wait=2"]) {
    const response = await handler(
      new Request("https://relay.test/crier/api/sync/events?" + query, {
        headers: { authorization: "Bearer receiver" },
      }),
    );
    assert(response.status === 422);
  }
  assert(calls.length === 0);
});

Deno.test("missing credentials do not query protected routes", async () => {
  const { handler, calls } = fixture();
  assert(
    (await handler(
      new Request("https://relay.test/crier/api/sync/events?wait=25"),
    )).status === 401,
  );
  assert(calls.length === 0);
});

Deno.test("RPC failures hide backend details and invalid routes never reach RPC", async () => {
  const handler = createHandler({
    url: "https://example.supabase.co",
    serviceKey: "server-secret",
    fetch: () =>
      Promise.resolve(
        new Response("server-secret SQL details", { status: 500 }),
      ),
  });
  const response = await handler(
    new Request("https://relay.test/crier/health"),
  );
  assert(
    response.status === 503 && !(await response.text()).includes("secret"),
  );
  assert(
    (await handler(new Request("https://relay.test/crier/admin"))).status ===
      404,
  );
});
