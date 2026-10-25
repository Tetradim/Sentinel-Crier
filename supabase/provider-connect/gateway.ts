/** Separate provider custody endpoint; the existing instruction relay is unchanged. */
import { AuthRejected, CustomerAuth } from "./auth.ts";
import { GrantCipher, randomToken, sha256 } from "./crypto.ts";
import type { FlowContext } from "./crypto.ts";
import { ProviderApplication } from "./providers.ts";
import type { Grant } from "./providers.ts";
import { metadata, RpcFlowStore, StoreRejected } from "./store.ts";
import type { FlowPort, FlowRow } from "./store.ts";

export interface Options {
  projectUrl: string;
  publishableKey: string;
  serviceKey: string;
  encryptionKey: Uint8Array;
  keyId: string;
  applications: Array<
    { provider: "alpaca" | "discord"; clientId: string; clientSecret: string }
  >;
  fetch?: typeof fetch;
  store?: FlowPort;
}
const HEADERS = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy":
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
};
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const MESSAGE = "Provider connection request rejected.";
function json(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: HEADERS });
}
function redirect(location: string): Response {
  return new Response(null, {
    status: 303,
    headers: { ...HEADERS, Location: location },
  });
}
function record(value: unknown, fields: string[]): Record<string, unknown> {
  if (
    !value || typeof value !== "object" || Array.isArray(value) ||
    Object.keys(value).length !== fields.length ||
    fields.some((field) => !Object.hasOwn(value, field))
  ) throw new StoreRejected();
  return value as Record<string, unknown>;
}
async function body(request: Request): Promise<unknown> {
  if (
    request.headers.get("content-type")?.split(";", 1)[0] !==
      "application/json" || !request.body
  ) throw new StoreRejected();
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new StoreRejected()), 5000);
  });
  try {
    while (true) {
      const item = await Promise.race([reader.read(), deadline]);
      if (item.done) break;
      size += item.value.length;
      if (size > 8192) throw new StoreRejected();
      chunks.push(item.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => {});
  }
}
function query(
  url: URL,
  allowed: string[],
  required: string[],
): Record<string, string> {
  if (
    url.search.length > 8192 ||
    [...url.searchParams.keys()].some((key) =>
      !allowed.includes(key) || url.searchParams.getAll(key).length !== 1
    ) ||
    required.some((key) => !url.searchParams.has(key))
  ) throw new StoreRejected();
  return Object.fromEntries(url.searchParams);
}
function cookie(request: Request, name: string): string {
  const values = (request.headers.get("cookie") ?? "").split(";").map((part) =>
    part.trim()
  ).filter((part) => part.startsWith(name + "="));
  if (values.length !== 1 || !TOKEN.test(values[0].slice(name.length + 1))) {
    throw new StoreRejected();
  }
  return values[0].slice(name.length + 1);
}
function context(row: FlowRow): FlowContext {
  return {
    flow_id: row.flow_id,
    owner_id: row.owner_id,
    provider: row.provider,
    purpose: row.purpose,
    environment: row.environment,
    challenge: row.challenge,
  };
}
function grant(value: unknown, row: FlowRow): Grant {
  const fields = [
    "provider",
    "purpose",
    "environment",
    "credential",
    "account_id",
    "guild_id",
    "channel_id",
    "scopes",
  ];
  const data = record(value, fields);
  if (
    data.provider !== row.provider || data.purpose !== row.purpose ||
    data.environment !== row.environment ||
    !["credential", "account_id", "guild_id", "channel_id"].every((key) =>
      typeof data[key] === "string"
    ) ||
    typeof data.credential !== "string" || !data.credential ||
    data.credential.length > 8192 || !Array.isArray(data.scopes) ||
    data.scopes.some((scope) => typeof scope !== "string")
  ) throw new StoreRejected();
  return data as Grant;
}

export function createHandler(
  options: Options,
): (request: Request) => Promise<Response> {
  const auth = new CustomerAuth({
    projectUrl: options.projectUrl,
    publishableKey: options.publishableKey,
    fetch: options.fetch,
  });
  const base = options.projectUrl + "/functions/v1/crier-oauth";
  const basePath = "/functions/v1/crier-oauth";
  const cipher = new GrantCipher(
    { [options.keyId]: options.encryptionKey },
    options.keyId,
  );
  const store = options.store ??
    new RpcFlowStore(options.projectUrl, options.serviceKey, options.fetch);
  const applications = new Map(
    options.applications.map((
      application,
    ) => [
      application.provider,
      new ProviderApplication({
        ...application,
        callback: base + "/oauth/callback/" + application.provider,
      }),
    ]),
  );
  if (!applications.size || applications.size !== options.applications.length) {
    throw new StoreRejected();
  }
  const fetcher = options.fetch ?? fetch;
  return async (incoming) => {
    try {
      const source = new URL(incoming.url);
      // Supabase may remove /functions/v1 from its internal request URL.
      // Every public URL/Origin check still derives from pinned configuration.
      const prefix = source.pathname.startsWith(basePath + "/")
        ? basePath
        : source.pathname.startsWith("/crier-oauth/")
        ? "/crier-oauth"
        : null;
      if (!prefix || source.hash) return json({ detail: MESSAGE }, 400);
      const path = source.pathname.slice(prefix.length);
      const request = new Request(base + path + source.search, incoming);
      const url = new URL(request.url);
      if (request.method === "GET" && path === "/oauth/capabilities") {
        query(url, [], []);
        return json({
          version: 1,
          service_url: base,
          providers: [...applications.keys()],
          auth_project_url: options.projectUrl,
        });
      }
      if (
        path === "/auth/browser" && ["GET", "POST"].includes(request.method)
      ) {
        const values = query(url, ["ticket"], []);
        return await auth.browserLogin(request, {
          baseUrl: base,
          nextTicket: values.ticket,
          claimCsrf: (hash, expiresAt) => store.claimCsrf(hash, expiresAt),
        });
      }
      if (
        request.method === "POST" &&
        ["/auth/login", "/auth/signup", "/auth/refresh"].includes(path)
      ) {
        query(url, [], []);
        const data = record(
          await body(request),
          path === "/auth/refresh" ? ["refresh_token"] : ["email", "password"],
        );
        if (path === "/auth/refresh") {
          return json(await auth.refresh(data.refresh_token as string));
        }
        if (path === "/auth/signup") {
          return json(
            await auth.signUp(data.email as string, data.password as string),
          );
        }
        return json(
          await auth.signIn(data.email as string, data.password as string),
        );
      }
      if (request.method === "GET" && path === "/oauth/browser") {
        const values = query(url, ["ticket"], ["ticket"]);
        if (!TOKEN.test(values.ticket)) throw new StoreRejected();
        let owner: string;
        try {
          owner = await auth.browserOwner(request);
        } catch {
          return redirect(base + "/auth/browser?ticket=" + values.ticket);
        }
        const binding = randomToken();
        const row = await store.call("launch", owner, null, {
          ticket_hash: await sha256(values.ticket),
          binding_hash: await sha256(binding),
        });
        const state = await cipher.open(
          context(row),
          "state",
          row.state_ciphertext!,
        );
        if (typeof state !== "string" || !TOKEN.test(state)) {
          throw new StoreRejected();
        }
        const application = applications.get(row.provider);
        if (!application) throw new StoreRejected();
        const response = redirect(
          application.authorize(state, row.purpose, row.environment),
        );
        const name = "__Host-crier-oauth-" + (await sha256(state)).slice(0, 24);
        response.headers.append(
          "Set-Cookie",
          `${name}=${binding}; Path=/; Max-Age=300; Secure; HttpOnly; SameSite=Lax`,
        );
        return response;
      }
      if (request.method === "GET" && path.startsWith("/oauth/callback/")) {
        const provider = path.slice("/oauth/callback/".length);
        const application = applications.get(provider as "alpaca" | "discord");
        if (!application) throw new StoreRejected();
        const values = query(url, ["state", "code", "error", "iss"], ["state"]);
        if (
          !TOKEN.test(values.state) ||
          Boolean(values.code) === Boolean(values.error) ||
          provider === "discord" && values.iss !== "https://discord.com" ||
          provider === "alpaca" && values.iss !== undefined
        ) throw new StoreRejected();
        const owner = await auth.browserOwner(request);
        const name = "__Host-crier-oauth-" +
          (await sha256(values.state)).slice(0, 24);
        const row = await store.call("claim", owner, null, {
          provider,
          state_hash: await sha256(values.state),
          binding_hash: await sha256(cookie(request, name)),
        });
        try {
          if (values.error) await store.call("fail", owner, row.flow_id, {});
          else {
            const controller = new AbortController();
            let timer: ReturnType<typeof setTimeout> | undefined;
            const deadline = new Promise<never>((_, reject) => {
              timer = setTimeout(() => {
                controller.abort();
                reject(new StoreRejected());
              }, 30000);
            });
            const boundedFetch: typeof fetch = (input, init) => {
              if (controller.signal.aborted) {
                return Promise.reject(new StoreRejected());
              }
              return fetcher(input, {
                ...init,
                signal: init?.signal
                  ? AbortSignal.any([controller.signal, init.signal])
                  : controller.signal,
              });
            };
            let result: Grant;
            try {
              result = await Promise.race([
                application.exchange(
                  values.code,
                  row.purpose,
                  row.environment,
                  boundedFetch,
                ),
                deadline,
              ]);
            } finally {
              clearTimeout(timer);
            }
            const sealed = await cipher.seal(
              context(row),
              "grant",
              grant(result, row),
            );
            await store.call("complete", owner, row.flow_id, {
              grant_ciphertext: sealed,
            });
          }
        } catch {
          /* Claimed exchanges stay uncertain; cancellation/expiry wins over late replies. */
        }
        const response = redirect(
          "sentinelcrier://oauth/complete?flow=" + row.flow_id,
        );
        response.headers.append(
          "Set-Cookie",
          `${name}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax`,
        );
        return response;
      }
      if (
        request.method !== "POST" ||
        !["/oauth/begin", "/oauth/status", "/oauth/redeem", "/oauth/cancel"]
          .includes(path)
      ) return json({ detail: MESSAGE }, 404);
      query(url, [], []);
      const owner = await auth.owner(
        request.headers.get("authorization") ?? "",
      );
      if (path === "/oauth/begin") {
        const data = record(await body(request), [
          "provider",
          "purpose",
          "environment",
          "challenge",
        ]);
        if (
          !applications.has(data.provider as "alpaca" | "discord") ||
          typeof data.challenge !== "string" ||
          !/^[0-9a-f]{64}$/.test(data.challenge) ||
          !["alerts", "trade"].includes(data.purpose as string) ||
          !["paper", "live"].includes(data.environment as string) ||
          data.provider === "discord" && data.purpose !== "alerts"
        ) throw new StoreRejected();
        const flow: FlowContext = {
          flow_id: randomToken(),
          owner_id: owner,
          provider: data.provider as "alpaca" | "discord",
          purpose: data.purpose as "alerts" | "trade",
          environment: data.environment as "paper" | "live",
          challenge: data.challenge,
        };
        const state = randomToken(), ticket = randomToken();
        const row = await store.call("begin", owner, flow.flow_id, {
          provider: flow.provider,
          purpose: flow.purpose,
          environment: flow.environment,
          challenge: flow.challenge,
          state_hash: await sha256(state),
          ticket_hash: await sha256(ticket),
          state_ciphertext: await cipher.seal(flow, "state", state),
        });
        return json({
          flow: row.flow_id,
          expires_at: row.expires_at / 1000,
          launch_url: base + "/oauth/browser?ticket=" + ticket,
        });
      }
      const fields = path === "/oauth/status" ? ["flow"] : ["flow", "proof"];
      const data = record(await body(request), fields);
      if (typeof data.flow !== "string" || !TOKEN.test(data.flow)) {
        throw new StoreRejected();
      }
      if (path === "/oauth/status") {
        return json(metadata(await store.call("status", owner, data.flow, {})));
      }
      if (typeof data.proof !== "string" || !TOKEN.test(data.proof)) {
        throw new StoreRejected();
      }
      const row = await store.call(
        path === "/oauth/cancel" ? "cancel" : "redeem",
        owner,
        data.flow,
        { proof_hash: await sha256(data.proof) },
      );
      if (path === "/oauth/cancel") return json({ cancelled: true });
      return json(
        grant(
          await cipher.open(context(row), "grant", row.grant_ciphertext!),
          row,
        ),
      );
    } catch (error) {
      return json({ detail: MESSAGE }, error instanceof AuthRejected ? 401 : 400);
    }
  };
}
