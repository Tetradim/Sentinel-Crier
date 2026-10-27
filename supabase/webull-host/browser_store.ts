import type { BrowserFlow, BrowserFlows } from "./authorization.ts";
type Rpc = (name: string, args: Record<string, unknown>) => Promise<unknown>;
function invalid(): never {
  throw Error("Browser store unavailable");
}
function row(value: unknown): BrowserFlow | null {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const f = value as Record<string, unknown>,
    uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/u;
  if (
    Object.keys(f).length !== 5 || typeof f.id !== "string" ||
    !uuid.test(f.id) || typeof f.owner !== "string" || !uuid.test(f.owner) ||
    !["sandbox", "production"].includes(String(f.environment)) ||
    !Number.isSafeInteger(f.expires_at_ms) ||
    (f.state_hash !== null &&
      (typeof f.state_hash !== "string" ||
        !/^[a-f0-9]{64}$/u.test(f.state_hash)))
  ) invalid();
  return f as unknown as BrowserFlow;
}
function boolean(value: unknown) {
  if (typeof value !== "boolean") invalid();
  return value;
}
export function createBrowserFlows(rpc: Rpc): BrowserFlows {
  return {
    async issue(owner, env, hash) {
      const f = row(
        await rpc("webull_host_browser_issue", {
          p_owner: owner,
          p_environment: env,
          p_ticket_hash: hash,
        }),
      );
      if (!f) invalid();
      return f;
    },
    async launch(hash) {
      return row(
        await rpc("webull_host_browser_launch", { p_ticket_hash: hash }),
      );
    },
    async attach(id, hash, expires) {
      return boolean(
        await rpc("webull_host_browser_attach", {
          p_id: id,
          p_state_hash: hash,
          p_expires_at_ms: expires,
        }),
      );
    },
    async resolve(hash) {
      return row(
        await rpc("webull_host_browser_resolve", { p_state_hash: hash }),
      );
    },
    async complete(id) {
      return boolean(await rpc("webull_host_browser_complete", { p_id: id }));
    },
    async invalidate(owner, env) {
      if (
        !boolean(
          await rpc("webull_host_browser_invalidate", {
            p_owner: owner,
            p_environment: env,
          }),
        )
      ) invalid();
    },
  };
}
export function createAdmission(rpc: Rpc) {
  return async (
    owner: string,
    scope: "http" | "webull",
    limit: number,
  ): Promise<boolean> =>
    boolean(
      await rpc("webull_host_admit", {
        p_owner: owner,
        p_scope: scope,
        p_limit: limit,
      }),
    );
}
