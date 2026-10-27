/** Browser/native authorization boundary. All owner identity comes from Auth or
 * a service-only durable flow record, never callback/body identity parameters. */
import type {
  CallbackInput,
  CoordinatorStatus,
} from "../webull-connect/coordinator.ts";
import type { Environment } from "./gateway.ts";
import {
  createSessionMaterial,
  hashSessionToken,
} from "../webull-connect/session_material.ts";

export interface BrowserFlow {
  id: string;
  owner: string;
  environment: Environment;
  expires_at_ms: number;
  state_hash: string | null;
}
export interface BrowserFlows {
  issue(
    owner: string,
    environment: Environment,
    ticketHash: string,
  ): Promise<BrowserFlow>;
  launch(ticketHash: string): Promise<BrowserFlow | null>;
  attach(id: string, stateHash: string, expiresAtMs: number): Promise<boolean>;
  resolve(stateHash: string): Promise<BrowserFlow | null>;
  complete(id: string): Promise<boolean>;
  invalidate(owner: string, environment: Environment): Promise<void>;
}
export interface AuthorizationCoordinator {
  begin(
    owner: unknown,
  ): Promise<{ url(): string; browserBinding(): string; expiresAtMs: number }>;
  callback(owner: unknown, input: CallbackInput): Promise<CoordinatorStatus>;
  status(owner: unknown): Promise<CoordinatorStatus>;
  refresh(owner: unknown): Promise<CoordinatorStatus>;
  revoke(owner: unknown): Promise<CoordinatorStatus>;
}
interface Options {
  publicBase: string;
  verify(token: string): Promise<string>;
  coordinators: Partial<Record<Environment, AuthorizationCoordinator>>;
  flows: BrowserFlows;
  admit(owner: string): Promise<boolean>;
}
const TOKEN = /^[A-Za-z0-9_-]{43}$/u;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/u;
const HEADERS = {
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "content-security-policy":
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
};
class Rejected extends Error {
  readonly status: number;
  constructor(status = 400) {
    super("Authorization request rejected");
    this.status = status;
  }
}
function reject(status = 400): never {
  throw new Rejected(status);
}
function environment(value: unknown): Environment {
  if (value !== "sandbox" && value !== "production") reject();
  return value;
}
function flow(value: BrowserFlow | null): BrowserFlow {
  if (
    !value || !UUID.test(value.id) || !UUID.test(value.owner) ||
    !["sandbox", "production"].includes(value.environment) ||
    !Number.isSafeInteger(value.expires_at_ms) ||
    value.expires_at_ms <= Date.now()
  ) reject();
  return value;
}
function json(value: unknown, status = 200) {
  return Response.json(value, { status, headers: HEADERS });
}
function html(ok: boolean, status: number, cookie?: string) {
  return new Response(
    ok
      ? "<!doctype html><title>Webull connected</title><p>Authorization completed. Return to Crier and check the connection.</p>"
      : "<!doctype html><title>Webull connection incomplete</title><p>Authorization could not be completed. Return to Crier, check connection status and start a new authorization if needed.</p>",
    {
      status,
      headers: {
        ...HEADERS,
        "content-type": "text/html; charset=utf-8",
        ...(cookie ? { "set-cookie": cookie } : {}),
      },
    },
  );
}
function cookieName(id: string) {
  return "__Host-crier_webull_" + id.replaceAll("-", "");
}
function cookieValue(request: Request, name: string) {
  const found = (request.headers.get("cookie") ?? "").split(";").map((v) =>
    v.trim()
  ).filter((v) => v.startsWith(name + "="));
  if (found.length !== 1 || !TOKEN.test(found[0].slice(name.length + 1))) {
    reject();
  }
  return found[0].slice(name.length + 1);
}
function cookie(name: string, value: string, seconds: number) {
  return `${name}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${seconds}`;
}
function query(url: URL, keys: string[]) {
  if (
    url.search.length > 4096 ||
    keys.some((k) => url.searchParams.getAll(k).length !== 1) ||
    [...url.searchParams.keys()].some((k) => !keys.includes(k))
  ) reject();
  return Object.fromEntries(url.searchParams);
}
async function bodyEnvironment(request: Request) {
  if (
    request.headers.get("content-type")?.split(";")[0] !== "application/json" ||
    !request.body
  ) reject(415);
  const reader = request.body.getReader();
  let text = "";
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, r) => {
    timer = setTimeout(() => r(new Rejected(408)), 5000);
  });
  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), timeout]);
      if (done) break;
      size += value.length;
      if (size > 1024) reject(413);
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    const f = JSON.parse(text);
    if (!f || Object.keys(f).length !== 1 || !Object.hasOwn(f, "environment")) {
      reject();
    }
    return environment(f.environment);
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
function safeStatus(value: CoordinatorStatus) {
  if (
    ![
      "active",
      "unlinked",
      "authorization_pending",
      "refresh_pending",
      "unknown",
      "revoked",
    ].includes(value.state) || !Number.isSafeInteger(value.generation) ||
    value.generation < 0
  ) reject(503);
  return {
    state: value.state,
    generation: value.generation,
    ...(value.accessExpiresAtMs !== undefined
      ? { access_expires_at_ms: value.accessExpiresAtMs }
      : {}),
    ...(value.refreshExpiresAtMs !== undefined
      ? { refresh_expires_at_ms: value.refreshExpiresAtMs }
      : {}),
  };
}
export function createAuthorizationHandler(
  options: Options,
): (r: Request) => Promise<Response | null> {
  const publicURL = new URL(options.publicBase);
  if (
    publicURL.protocol !== "https:" || publicURL.username ||
    publicURL.password || publicURL.search || publicURL.hash ||
    publicURL.port || publicURL.href.endsWith("/")
  ) throw Error("Invalid public service base");
  const { verify, flows, admit } = options,
    coordinators = { ...options.coordinators };
  return async (request) => {
    const url = new URL(request.url), path = url.pathname;
    if (!path.startsWith("/v1/connect/")) return null;
    let current: BrowserFlow | undefined;
    try {
      if (path === "/v1/connect/launch" && request.method === "GET") {
        const q = query(url, ["ticket"]);
        if (!TOKEN.test(q.ticket)) reject();
        current = flow(await flows.launch(await hashSessionToken(q.ticket)));
        if (!await admit(current.owner)) reject(429);
        const coordinator = coordinators[current.environment];
        if (!coordinator) reject(503);
        const started = await coordinator.begin(current.owner),
          target = new URL(started.url());
        const expected = current.environment === "sandbox"
          ? "/oauth2/sandbox/authenticate/login"
          : "/oauth2/authenticate/login";
        if (
          target.origin !== "https://passport.webull.com" ||
          target.pathname !== expected || target.hash || target.username ||
          target.password ||
          !TOKEN.test(target.searchParams.get("state") ?? "") ||
          !TOKEN.test(started.browserBinding())
        ) reject(503);
        if (
          !await flows.attach(
            current.id,
            await hashSessionToken(target.searchParams.get("state")!),
            started.expiresAtMs,
          )
        ) reject(503);
        const seconds = Math.min(
          300,
          Math.floor((started.expiresAtMs - Date.now()) / 1000),
        );
        if (seconds <= 0) reject();
        return new Response(null, {
          status: 303,
          headers: {
            ...HEADERS,
            location: target.href,
            "set-cookie": cookie(
              cookieName(current.id),
              started.browserBinding(),
              seconds,
            ),
          },
        });
      }
      if (path === "/v1/connect/callback" && request.method === "GET") {
        const q = query(url, ["state", "code"]);
        if (
          !TOKEN.test(q.state) || !q.code || q.code.length > 2048 ||
          /[\r\n]/u.test(q.code)
        ) reject();
        current = flow(await flows.resolve(await hashSessionToken(q.state)));
        const binding = cookieValue(request, cookieName(current.id));
        if (!await admit(current.owner)) reject(429);
        const coordinator = coordinators[current.environment];
        if (!coordinator) reject(503);
        const result = await coordinator.callback(current.owner, {
          state: q.state,
          browserBinding: binding,
          code: q.code,
        });
        if (result.state !== "active") reject(503);
        if (!await flows.complete(current.id)) reject(503);
        return html(true, 200, cookie(cookieName(current.id), "", 0));
      }
      const token = request.headers.get("authorization");
      if (!token || !/^Bearer [^\s]+$/u.test(token) || token.length > 16384) {
        reject(401);
      }
      let owner: string;
      try {
        owner = await verify(token.slice(7));
        if (!UUID.test(owner)) reject(401);
      } catch {
        reject(401);
      }
      if (!await admit(owner)) reject(429);
      if (path === "/v1/connect/status" && request.method === "GET") {
        const env = environment(query(url, ["environment"]).environment),
          coordinator = coordinators[env];
        if (!coordinator) reject(503);
        return json(safeStatus(await coordinator.status(owner)));
      }
      if (
        ["/v1/connect/begin", "/v1/connect/refresh", "/v1/connect/revoke"]
          .includes(path) && request.method === "POST"
      ) {
        if (url.search) reject();
        const env = await bodyEnvironment(request),
          coordinator = coordinators[env];
        if (!coordinator) reject(503);
        if (path.endsWith("/begin")) {
          const material = await createSessionMaterial();
          const f = flow(await flows.issue(owner, env, material.stateHash));
          if (
            f.owner !== owner || f.environment !== env ||
            f.expires_at_ms > Date.now() + 301000
          ) reject(503);
          const launch = new URL(publicURL.href + "/v1/connect/launch");
          launch.searchParams.set("ticket", material.state());
          return json({ authorization_url: launch.href, flow_id: f.id });
        }
        if (path.endsWith("/revoke")) await flows.invalidate(owner, env);
        return json(
          safeStatus(
            await (path.endsWith("/refresh")
              ? coordinator.refresh(owner)
              : coordinator.revoke(owner)),
          ),
        );
      }
      return json({ error: "not_found" }, 404);
    } catch (error) {
      const status = error instanceof Rejected ? error.status : 400;
      if (path === "/v1/connect/callback") {
        return html(
          false,
          status,
          current ? cookie(cookieName(current.id), "", 0) : undefined,
        );
      }
      return json({
        error: status === 429
          ? "request_limit"
          : status === 401
          ? "unauthorized"
          : "authorization_unavailable",
      }, status);
    }
  };
}
