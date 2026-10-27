/** Deployable composition. Approved OAuth may run independently of trading.
 * Only a concrete trusted resource adapter can enable real order capabilities. */
import {
  type Capabilities,
  createSupabaseVerifier,
  type Environment,
  type Provider,
} from "./gateway.ts";
import { createHostedGateway } from "./service.ts";
import { createAuthorizationHandler } from "./authorization.ts";
import { createAdmission, createBrowserFlows } from "./browser_store.ts";
import { createCustody } from "./custody.ts";
import { createRpcStore } from "../webull-connect/rpc_store.ts";
import {
  createTokenVault,
  importVaultKey,
} from "../webull-connect/token_vault.ts";
import { createSignedTokenTransport } from "./token_transport.ts";
interface AuthorizationConfig {
  environment: Environment;
  clientId: string;
  clientSecret: string;
  scope: string;
  appKey: string;
  appSecret: string;
  vaultKey: string;
  keyId: string;
  approved: boolean;
  previousVaultKeys?: Record<string, string>;
}
export interface ApplicationOptions {
  projectUrl: string;
  publishableKey: string;
  serviceRoleKey: string;
  fetch?: typeof fetch;
  authorization?: AuthorizationConfig;
  /** Trusted server integration points; never taken from an HTTP request. */
  bindTrading?: (
    custody: ReturnType<typeof createCustody>,
  ) => { provider: Provider; capabilities: Capabilities };
  admitRequest?: (owner: string) => Promise<boolean>;
}
const HEADERS = {
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};
function unavailable(): never {
  throw Error("Invalid Webull service configuration");
}
function vaultBytes(value: string) {
  if (!/^[A-Za-z0-9_-]{43}$/u.test(value)) unavailable();
  const bytes = Uint8Array.from(
    atob(value.replaceAll("-", "+").replaceAll("_", "/") + "="),
    (c) => c.charCodeAt(0),
  );
  if (
    bytes.length !== 32 ||
    btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll(
        "/",
        "_",
      ).replace(/=+$/u, "") !== value
  ) unavailable();
  return bytes;
}
export async function createApplication(
  options: ApplicationOptions,
): Promise<(r: Request) => Promise<Response>> {
  const fetcher = options.fetch ?? fetch, project = new URL(options.projectUrl);
  if (
    project.protocol !== "https:" || project.username || project.password ||
    project.port || project.search || project.hash ||
    project.pathname !== "/" || !options.serviceRoleKey ||
    /[\r\n]/u.test(options.serviceRoleKey)
  ) unavailable();
  const publicBase = project.origin + "/functions/v1/crier-webull-host";
  const verify = createSupabaseVerifier({
    url: project.origin,
    publishableKey: options.publishableKey,
    fetch: fetcher,
  });
  const rpc = async (
    name: string,
    args: Record<string, unknown>,
  ): Promise<unknown> => {
    if (!/^[a-z_]+$/u.test(name)) unavailable();
    const response = await fetcher(project.origin + "/rest/v1/rpc/" + name, {
      method: "POST",
      redirect: "error",
      headers: {
        apikey: options.serviceRoleKey,
        authorization: "Bearer " + options.serviceRoleKey,
        "content-type": "application/json",
      },
      body: JSON.stringify(args),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw Error("Webull storage unavailable");
    return await response.json();
  };
  const flows = createBrowserFlows(rpc), admission = createAdmission(rpc);
  let custody: ReturnType<typeof createCustody> | undefined;
  const config = options.authorization
    ? { ...options.authorization }
    : undefined;
  if (config) {
    if (
      config.approved !== true ||
      !["sandbox", "production"].includes(config.environment) ||
      !config.appKey || !config.appSecret ||
      !/^[A-Za-z0-9_-]{1,64}$/u.test(config.keyId)
    ) unavailable();
    const keys = new Map([[
      config.keyId,
      await importVaultKey(vaultBytes(config.vaultKey)),
    ]]);
    const previous = Object.entries(config.previousVaultKeys ?? {});
    if (previous.length > 8) unavailable();
    for (const [id, value] of previous) {
      if (
        id === config.keyId || !/^[A-Za-z0-9_-]{1,64}$/u.test(id) ||
        typeof value !== "string"
      ) unavailable();
      keys.set(id, await importVaultKey(vaultBytes(value)));
    }
    const vault = createTokenVault(config.keyId, keys);
    const store = createRpcStore(async (name, args) => ({
      data: await rpc(name, args),
      error: null,
    }));
    const transport = createSignedTokenTransport({
      environment: config.environment,
      appKey: config.appKey,
      appSecret: config.appSecret,
      fetch: fetcher,
    });
    custody = createCustody({
      store,
      vault,
      configs: {
        [config.environment]: {
          environment: config.environment,
          clientId: config.clientId,
          clientSecret: config.clientSecret,
          scope: config.scope,
          callback: publicBase + "/v1/connect/callback",
          approvedBrowserEntry: "https://passport.webull.com" +
            (config.environment === "sandbox"
              ? "/oauth2/sandbox/authenticate/login"
              : "/oauth2/authenticate/login"),
          integrationApproved: true,
          signingReady: true,
        },
      },
      transport: (_env, _owner, request, signal) => transport(request, signal),
      admitBroker: (owner) => admission(owner, "webull", 80),
    });
  }
  if (options.bindTrading && !custody) unavailable();
  const trading = options.bindTrading && custody
    ? options.bindTrading(custody)
    : undefined;
  const admit = options.admitRequest ??
    (custody
      ? (owner: string) => admission(owner, "http", 60)
      : () => Promise.resolve(true));
  return async (original) => {
    try {
      const source = new URL(original.url);
      let path = source.pathname;
      const prefix = ["/functions/v1/crier-webull-host", "/crier-webull-host"]
        .find((p) => path.startsWith(p + "/"));
      if (prefix) path = path.slice(prefix.length);
      else if (!path.startsWith("/v1/")) {
        return Response.json({ error: "not_found" }, {
          status: 404,
          headers: HEADERS,
        });
      }
      source.pathname = path;
      const request = new Request(source, original);
      // A request-local verified principal avoids duplicate Auth traffic, without a
      // process-wide bearer cache that could outlive sign-out or token expiry.
      let verification: Promise<string> | undefined;
      let verifiedToken: string | undefined;
      const verifyOnce = (token: string) => {
        if (verifiedToken !== undefined && token !== verifiedToken) {
          return Promise.reject(Error("Principal changed"));
        }
        verifiedToken = token;
        return verification ??= verify(token);
      };
      if (path.startsWith("/v1/connect/")) {
        if (!custody) {
          return Response.json({ error: "authorization_unavailable" }, {
            status: 503,
            headers: HEADERS,
          });
        }
        const response = await createAuthorizationHandler({
          publicBase,
          verify: verifyOnce,
          coordinators: custody.coordinators,
          flows,
          admit,
        })(request);
        return response ??
          Response.json({ error: "not_found" }, {
            status: 404,
            headers: HEADERS,
          });
      }
      const authorization = request.headers.get("authorization");
      if (
        !authorization || !/^Bearer [^\s]+$/u.test(authorization) ||
        authorization.length > 16384
      ) {
        return Response.json({ error: "unauthorized" }, {
          status: 401,
          headers: HEADERS,
        });
      }
      let owner: string;
      try {
        owner = await verifyOnce(authorization.slice(7));
      } catch {
        return Response.json({ error: "unauthorized" }, {
          status: 401,
          headers: HEADERS,
        });
      }
      if (!await admit(owner)) {
        return Response.json({ error: "request_limit" }, {
          status: 429,
          headers: HEADERS,
        });
      }
      if (path === "/v1/capabilities" && request.method === "GET") {
        return Response.json({
          ...trading?.capabilities,
          available: trading?.capabilities.available ?? false,
          environments: config ? [config.environment] : [],
          stocks: trading?.capabilities.stocks ?? [],
          options: trading?.capabilities.options ?? false,
          authorization_available: Boolean(custody),
        }, { headers: HEADERS });
      }
      if (!trading) {
        return Response.json({
          error: "trading_adapter_unavailable",
          ...(path === "/v1/connection"
            ? {
              state: "unavailable",
              environment: source.searchParams.get("environment") ?? "sandbox",
            }
            : {}),
        }, { status: path === "/v1/connection" ? 200 : 503, headers: HEADERS });
      }
      return await createHostedGateway({
        supabaseUrl: project.origin,
        publishableKey: options.publishableKey,
        serviceRoleKey: options.serviceRoleKey,
        fetch: fetcher,
        verify: verifyOnce,
        ...trading,
      })(request);
    } catch {
      return Response.json({ error: "service_unavailable" }, {
        status: 503,
        headers: HEADERS,
      });
    }
  };
}
