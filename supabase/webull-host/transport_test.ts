// deno-lint-ignore-file require-await -- synthetic HTTP and stream ports.
import { createConnectTransport } from "./transport.ts";
import { createSignedTokenTransport } from "./token_transport.ts";
import { createTokenRequest } from "../webull-connect/oauth_contract.ts";

function eq(actual: unknown, expected: unknown) {
  if (actual !== expected) throw Error(`Expected ${expected}, got ${actual}`);
}
async function rejected(operation: Promise<unknown>) {
  try {
    await operation;
  } catch (error) {
    if (!(error instanceof Error) || error.message.includes("PRIVATE")) {
      throw Error("Unsafe transport error");
    }
    return;
  }
  throw Error("Expected rejection");
}
function sender(kind: "resource" | "token", fetcher: typeof fetch) {
  const options = {
    environment: "sandbox" as const,
    appKey: "app",
    appSecret: "secret",
    fetch: fetcher,
  };
  if (kind === "resource") {
    const send = createConnectTransport(options);
    return (signal: AbortSignal) =>
      send({
        path: "/oauth-openapi/approved-path",
        method: "GET",
        accessToken: "PRIVATE",
        signal,
      });
  }
  const send = createSignedTokenTransport(options);
  const request = createTokenRequest("sandbox", {
    client_id: "client",
    client_secret: "PRIVATE",
    grant_type: "authorization_code",
    code: "code",
  });
  return (signal: AbortSignal) => send(request, signal);
}

for (const kind of ["resource", "token"] as const) {
  const limit = kind === "resource" ? 1048576 : 65536;
  Deno.test(`${kind} rejects streaming overflow before reading the remainder`, async () => {
    let pulls = 0, canceled = false, calls = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls++;
        if (pulls <= 5) controller.enqueue(new Uint8Array(limit / 4));
        else controller.close();
      },
      cancel() {
        canceled = true;
      },
    }, { highWaterMark: 0 });
    const send = sender(kind, async () => {
      calls++;
      return new Response(stream);
    });
    await rejected(send(new AbortController().signal));
    eq(pulls, 5);
    eq(canceled, true);
    eq(calls, 1);
    eq(stream.locked, false);
  });
  Deno.test(`${kind} accepts exact byte bound and rejects invalid UTF-8`, async () => {
    const value = "x".repeat(limit - 2);
    const send = sender(kind, async () => new Response(JSON.stringify(value)));
    eq(await send(new AbortController().signal), value);
    const invalid = sender(kind, async () =>
      new Response(new Uint8Array([34, 0xff, 34])));
    await rejected(invalid(new AbortController().signal));
  });
  Deno.test(`${kind} owns buffered bytes independently of reused stream chunks`, async () => {
    const bytes = new Uint8Array(1), content = [34, 120, 34];
    let index = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index === content.length) return controller.close();
        bytes[0] = content[index++];
        controller.enqueue(bytes);
      },
    }, { highWaterMark: 0 });
    const send = sender(kind, async () => new Response(stream));
    eq(await send(new AbortController().signal), "x");
  });
  Deno.test(`${kind} cancels HTTP error bodies without reading or waiting for cleanup`, async () => {
    let pulls = 0, canceled = false;
    const stream = new ReadableStream<Uint8Array>({
      pull() {
        pulls++;
      },
      cancel() {
        canceled = true;
        return new Promise(() => {});
      },
    }, { highWaterMark: 0 });
    const send = sender(kind, async () => new Response(stream, { status: 503 }));
    await rejected(send(new AbortController().signal));
    eq(pulls, 0);
    eq(canceled, true);
    eq(stream.locked, false);
  });
  Deno.test(`${kind} abort interrupts a stalled response even when cleanup stalls`, async () => {
    const abort = new AbortController();
    let canceled = false;
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(value) {
        controller = value;
      },
      pull() {
        abort.abort(Error("PRIVATE upstream cancellation reason"));
      },
      cancel() {
        canceled = true;
        return new Promise(() => {});
      },
    }, { highWaterMark: 0 });
    const send = sender(kind, async () => new Response(stream));
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        rejected(send(abort.signal)),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error("Body abort did not settle")), 500);
        }),
      ]);
      eq(canceled, true);
      eq(stream.locked, false);
    } finally {
      clearTimeout(timer);
      if (!canceled) controller.close();
    }
  });
  Deno.test(`${kind} already aborted calls never dispatch`, async () => {
    let calls = 0;
    const send = sender(kind, async () => {
      calls++;
      return new Response("{}");
    });
    const abort = new AbortController();
    abort.abort(Error("PRIVATE"));
    await rejected(send(abort.signal));
    eq(calls, 0);
  });
}

Deno.test("resource caller cancellation cannot replace the request deadline", async () => {
  const caller = new AbortController();
  const send = sender("resource", async (_url, init) => {
    if (!init?.signal || init.signal === caller.signal) {
      throw Error("Expected independent combined deadline signal");
    }
    return new Response("{}");
  });
  const value = await send(caller.signal) as Record<string, unknown>;
  eq(Object.keys(value).length, 0);
});

Deno.test("resource body size counts UTF-8 bytes before any dispatch", async () => {
  let calls = 0;
  const send = createConnectTransport({
    environment: "sandbox",
    appKey: "app",
    appSecret: "secret",
    fetch: async () => {
      calls++;
      return new Response("{}");
    },
  });
  await rejected(send({
    path: "/oauth-openapi/approved-path",
    method: "POST",
    accessToken: "PRIVATE",
    body: { value: "😀".repeat(17000) },
  }));
  eq(calls, 0);
});
