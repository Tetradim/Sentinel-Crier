type Options = {
  url: string;
  serviceKey: string;
  fetch?: typeof fetch;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

const LIMIT = 32_768;
const HEADERS = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy":
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
};
const PAGE =
  '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sentinel Crier invitation</title><h1>Open Sentinel Crier</h1><p>Copy the full invitation address, paste it into the app, and press Receive. Invitations are private, single use, and expire after ten minutes.</p></html>';

class RequestError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: HEADERS });
}

function pathOf(path: string): string {
  // Hosted and local Supabase runtimes may preserve different prefix lengths.
  if (path.startsWith("/functions/v1/crier/")) {
    return path.slice("/functions/v1/crier".length);
  }
  if (path.startsWith("/crier/")) return path.slice("/crier".length);
  return path;
}

function knownRoute(method: string, path: string): boolean {
  if (method === "GET") {
    return [
      "/health",
      "/connect",
      "/api/connect/receivers",
      "/api/sync/events",
      "/api/sync/clock",
      "/api/sync/diagnostics",
    ].includes(path);
  }
  if (method === "POST") {
    return [
      "/api/connect/host",
      "/api/connect/invite",
      "/api/connect/receive",
      "/api/sync/events",
      "/api/sync/diagnostics",
    ].includes(path) ||
      /^\/api\/connect\/receivers\/[0-9a-f-]{36}\/revoke$/.test(path);
  }
  return false;
}

async function readBody(request: Request): Promise<unknown> {
  const length = request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length) > LIMIT)) {
    throw new RequestError(413, "Request too large");
  }
  if (!request.body) return {};
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timeout = setTimeout(
      () => reject(new RequestError(408, "Request body timed out")),
      5_000,
    );
  });
  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), expired]);
      if (done) break;
      size += value.byteLength;
      if (size > LIMIT) throw new RequestError(413, "Request too large");
      chunks.push(value);
    }
    if (!size) return {};
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    try {
      const value = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        throw new Error();
      }
      return value;
    } catch {
      throw new RequestError(422, "Invalid JSON object");
    }
  } finally {
    clearTimeout(timeout);
    // Do not await an untrusted producer's cancellation callback.
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function createHandler(
  options: Options,
): (request: Request) => Promise<Response> {
  const fetchRpc = options.fetch ?? fetch;
  const now = options.now ?? Date.now;
  const sleep = options.sleep ??
    ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  return async (request) => {
    try {
      const url = new URL(request.url);
      const path = pathOf(url.pathname);
      const method = request.method.toUpperCase();
      if (!knownRoute(method, path)) return json({ detail: "Not found" }, 404);
      if (path === "/connect") {
        return new Response(PAGE, {
          headers: { ...HEADERS, "Content-Type": "text/html; charset=utf-8" },
        });
      }
      if (url.search.length > 2048) {
        throw new RequestError(422, "Invalid query");
      }
      const authorization = request.headers.get("authorization");
      if (
        authorization && !/^Bearer [A-Za-z0-9_-]{1,300}$/.test(authorization)
      ) throw new RequestError(401, "Pair first");
      const token = authorization?.slice(7) ?? null;
      const publicRoute = path === "/health" || path === "/api/connect/host" ||
        path === "/api/connect/receive";
      if (!publicRoute && !token) throw new RequestError(401, "Pair first");
      const body = await readBody(request);
      const query: Record<string, string> = {};
      for (const [key, value] of url.searchParams) {
        if (Object.hasOwn(query, key)) {
          throw new RequestError(422, "Duplicate query parameter");
        }
        Object.defineProperty(query, key, {
          value,
          enumerable: true,
          configurable: true,
        });
      }
      const polling = method === "GET" && path === "/api/sync/events";
      const wait = polling ? Number(query.wait ?? "20") : 0;
      if (polling && (!Number.isFinite(wait) || wait < 0 || wait > 25)) {
        throw new RequestError(422, "Wait must be between 0 and 25 seconds");
      }
      if (polling) {
        Object.defineProperty(query, "wait", {
          value: "0",
          enumerable: true,
          configurable: true,
        });
      }
      const deadline = now() + wait * 1000;
      for (;;) {
        if (request.signal.aborted) {
          throw new RequestError(408, "Request cancelled");
        }
        if (!options.url || !options.serviceKey) {
          throw new Error("Missing server configuration");
        }
        const timeout = polling && wait > 0
          ? Math.max(1, Math.min(8_000, deadline - now()))
          : 8_000;
        const response = await fetchRpc(
          options.url.replace(/\/$/, "") + "/rest/v1/rpc/crier_dispatch",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              apikey: options.serviceKey,
              authorization: "Bearer " + options.serviceKey,
            },
            body: JSON.stringify({
              p_method: method,
              p_path: path,
              p_token: token,
              p_body: body,
              p_query: query,
              p_peer: "global",
            }),
            signal: AbortSignal.any([
              request.signal,
              AbortSignal.timeout(timeout),
            ]),
          },
        );
        if (!response.ok) throw new Error("RPC unavailable");
        const result = await response.json();
        if (
          !result || !Number.isInteger(result.status) || result.status < 200 ||
          result.status > 599 || !Object.hasOwn(result, "body")
        ) throw new Error("Invalid RPC response");
        if (
          !polling || result.status !== 200 ||
          !Array.isArray(result.body?.events) || result.body.events.length ||
          now() >= deadline
        ) return json(result.body, result.status);
        await sleep(Math.min(1_000, Math.max(0, deadline - now())));
        if (now() >= deadline) return json(result.body, result.status);
      }
    } catch (error) {
      if (error instanceof RequestError) {
        return json({ detail: error.message }, error.status);
      }
      // Never reflect PostgREST errors, request bodies, tokens or configuration.
      return json({ detail: "Connection service unavailable" }, 503);
    }
  };
}
