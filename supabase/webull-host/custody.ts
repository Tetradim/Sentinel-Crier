/** Server-only bridge to the existing generation-fenced authorization vault. */
import {
  type CoordinatorConfig,
  type CoordinatorStore,
  createCoordinator,
} from "../webull-connect/coordinator.ts";
import type { createTokenVault } from "../webull-connect/token_vault.ts";
import type { createTokenRequest } from "../webull-connect/oauth_contract.ts";
import type { Environment } from "./gateway.ts";
import type { AuthorizationCoordinator } from "./authorization.ts";
export interface CredentialLease {
  request<T>(
    send: (accessToken: string, identityId: string) => Promise<T>,
  ): Promise<T>;
}
interface Options {
  configs: Partial<Record<Environment, CoordinatorConfig>>;
  store: CoordinatorStore;
  vault: ReturnType<typeof createTokenVault>;
  transport(
    environment: Environment,
    owner: string,
    request: ReturnType<typeof createTokenRequest>,
    signal: AbortSignal,
  ): Promise<unknown>;
  admitBroker(owner: string): Promise<boolean>;
  nowMs?: () => number;
}
export function createCustody(options: Options) {
  const { store, vault, transport, admitBroker } = options,
    configs = structuredClone(options.configs),
    now = options.nowMs ?? Date.now;
  function coordinator(owner: unknown, environment: Environment) {
    if (
      typeof owner !== "string" ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/u.test(
        owner,
      )
    ) throw Error("Invalid owner");
    const config = configs[environment];
    if (!config || config.environment !== environment) {
      throw Error("Authorization unavailable");
    }
    return createCoordinator({
      config,
      store,
      vault,
      nowMs: now,
      verifyPrincipal: (input) =>
        input === owner
          ? Promise.resolve(owner)
          : Promise.reject(Error("Invalid principal")),
      transport: async (request, signal) => {
        if (!await admitBroker(owner)) throw Error("Broker request limit");
        return await transport(environment, owner, request, signal);
      },
    });
  }
  const coordinators: Partial<Record<Environment, AuthorizationCoordinator>> =
    {};
  for (const env of ["sandbox", "production"] as const) {
    if (!configs[env]) continue;
    // Validate all config/ports now, without dispatching or touching storage.
    coordinator("00000000-0000-0000-0000-000000000000", env);
    coordinators[env] = {
      begin: (owner) => coordinator(owner, env).begin(owner),
      callback: (owner, input) =>
        coordinator(owner, env).callback(owner, input),
      status: (owner) => coordinator(owner, env).status(owner),
      refresh: (owner) => coordinator(owner, env).refresh(owner),
      revoke: (owner) => coordinator(owner, env).revoke(owner),
    };
  }
  return Object.freeze({
    coordinators: Object.freeze(coordinators),
    async withAccess<T>(
      owner: string,
      environment: Environment,
      action: (lease: CredentialLease) => Promise<T>,
    ): Promise<T> {
      const c = coordinator(owner, environment);
      let status = await c.status(owner);
      if (status.state !== "active") throw Error("Authorization required");
      if ((status.accessExpiresAtMs ?? 0) <= now() + 30000) {
        status = await c.refresh(owner);
      }
      const row = await store.read(owner, environment);
      if (
        !row || row.state !== "active" || !row.envelope ||
        row.generation !== status.generation
      ) throw Error("Authorization changed");
      const opened = await vault.open(
        { ownerRef: owner, environment, generation: row.generation },
        row.envelope,
        now(),
      );
      const lease = Object.freeze({
        async request<R>(
          send: (access: string, identity: string) => Promise<R>,
        ): Promise<R> {
          if (!await admitBroker(owner)) throw Error("Broker request limit");
          const fresh = await store.read(owner, environment);
          if (
            !fresh || fresh.state !== "active" ||
            fresh.generation !== row.generation ||
            opened.accessExpiresAtMs <= now()
          ) throw Error("Authorization changed");
          // The only explicit token exposure is this trusted server request callback.
          return await send(opened.accessToken(), opened.identityId());
        },
        toJSON: () => "WebullCredentialLease [REDACTED]",
        toString: () => "WebullCredentialLease [REDACTED]",
      });
      return await action(lease);
    },
  });
}
