/** Structural RPC boundary only; the vault authenticates encrypted custody. */
import type { CoordinatorStore, TokenState } from "./coordinator.ts";
import type { EncryptedEnvelope } from "./token_vault.ts";
import type { OAuthEnvironment } from "./oauth_contract.ts";

export type Rpc = (
  name: string,
  parameters: Record<string, unknown>,
) => Promise<{ data: unknown; error: unknown }>;
export interface RpcStoreOperations {
  rewrap(
    owner: string,
    env: OAuthEnvironment,
    generation: number,
    expectedEnvelope: EncryptedEnvelope,
    envelope: EncryptedEnvelope,
  ): Promise<boolean>;
  cleanupExpiredSessions(limit: number): Promise<number>;
}
function invalid(): never {
  throw new Error("Invalid Webull RPC store operation");
}
function fields(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object") invalid();
  const proto = Object.getPrototypeOf(value);
  if (
    proto !== null && proto !== Object.prototype ||
    Reflect.ownKeys(value).length !== keys.length
  ) invalid();
  const result: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !Object.hasOwn(d, "value")) invalid();
    result[key] = d.value;
  }
  return result;
}
function integer(
  value: unknown,
  min = 1,
  max = Number.MAX_SAFE_INTEGER,
): number {
  if (typeof value === "string" && /^(?:0|[1-9][0-9]*)$/u.test(value)) {
    value = Number(value);
  }
  if (
    typeof value !== "number" || !Number.isSafeInteger(value) || value < min ||
    value > max
  ) invalid();
  return value;
}
function text(value: unknown, max: number): string {
  if (
    typeof value !== "string" || !value.trim() || value.length > max ||
    // deno-lint-ignore no-control-regex -- reject C0, DEL and C1 controls.
    /[\u0000-\u001f\u007f-\u009f]/u.test(value)
  ) invalid();
  return value;
}
function uuid(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(
      value,
    )
  ) invalid();
  return value;
}
function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/u.test(value)) invalid();
  return value;
}
function scope(owner: string, env: OAuthEnvironment) {
  text(owner, 200);
  if (env !== "sandbox" && env !== "production") invalid();
  return { p_owner: owner, p_environment: env };
}
function session(state: string, binding: string, callback: string) {
  digest(state);
  digest(binding);
  text(callback, 2048);
  let url: URL;
  try {
    url = new URL(callback);
  } catch {
    invalid();
  }
  if (url.protocol !== "https:" || url.username || url.password || url.hash) {
    invalid();
  }
  return { p_state_hash: state, p_binding_hash: binding, p_callback: callback };
}
function timestamp(value: unknown): number {
  if (typeof value !== "string") invalid();
  const m =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))$/u
      .exec(value);
  if (!m) invalid();
  const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (
    month < 1 || month > 12 || day < 1 || day > days || Number(m[4]) > 23 ||
    Number(m[5]) > 59 || Number(m[6]) > 59 || Number(m[8] ?? 0) > 23 ||
    Number(m[9] ?? 0) > 59
  ) invalid();
  return integer(Date.parse(value), 1, 8_640_000_000_000_000);
}
function base64(value: unknown, min: number, max: number): string {
  if (
    typeof value !== "string" || value.length > 65536 ||
    !/^[A-Za-z0-9_-]+$/u.test(value)
  ) invalid();
  const bytes = atob(
    value.replaceAll("-", "+").replaceAll("_", "/") +
      "=".repeat((4 - value.length % 4) % 4),
  );
  if (
    bytes.length < min || bytes.length > max ||
    btoa(bytes).replaceAll("+", "-").replaceAll("/", "_").replace(
        /=+$/u,
        "",
      ) !== value
  ) invalid();
  return value;
}
function envelope(value: unknown): EncryptedEnvelope {
  const f = fields(value, [
    "schema",
    "key_id",
    "nonce",
    "ciphertext",
    "identity_hash",
    "access_expires_at_ms",
    "refresh_expires_at_ms",
  ]);
  if (f.schema !== "crier.webull-token.v1") invalid();
  if (
    typeof f.access_expires_at_ms !== "number" ||
    typeof f.refresh_expires_at_ms !== "number"
  ) invalid();
  const access = integer(f.access_expires_at_ms, 1, 8_640_000_000_000_000),
    refresh = integer(f.refresh_expires_at_ms, 1, 8_640_000_000_000_000);
  if (refresh <= access) invalid();
  return {
    schema: "crier.webull-token.v1",
    key_id: text(f.key_id, 200),
    nonce: base64(f.nonce, 12, 12),
    ciphertext: base64(f.ciphertext, 16, 32784),
    identity_hash: digest(f.identity_hash),
    access_expires_at_ms: access,
    refresh_expires_at_ms: refresh,
  };
}
function row(value: unknown, keys: string[]) {
  if (!Array.isArray(value) || value.length > 1) invalid();
  return value.length === 0 ? null : fields(value[0], keys);
}
function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") invalid();
  return value;
}

export function createRpcStore(
  rpc: Rpc,
): CoordinatorStore & RpcStoreOperations {
  if (typeof rpc !== "function") invalid();
  // Catch transport, parsing, and runtime validation failures without retaining causes.
  async function safe<T>(action: () => Promise<T>): Promise<T> {
    try {
      return await action();
    } catch {
      invalid();
    }
  }
  async function call(
    name: string,
    parameters: Record<string, unknown>,
  ): Promise<unknown> {
    const response = await rpc(name, parameters);
    if (!response || response.error !== null) invalid();
    return response.data;
  }
  return {
    begin: (owner, env, expected, op, state, binding, callback) =>
      safe(async () => {
        const parameters = {
          ...scope(owner, env),
          p_expected_generation: integer(
            expected,
            0,
            Number.MAX_SAFE_INTEGER - 1,
          ),
          p_operation_id: uuid(op),
          ...session(state, binding, callback),
        };
        const r = row(
          await call("crier_webull_authorization_begin", parameters),
          ["generation", "operation_id", "expires_at"],
        );
        if (!r) return null;
        const generation = integer(r.generation),
          operationId = uuid(r.operation_id);
        if (
          generation !== expected + 1 ||
          operationId.toLowerCase() !== op.toLowerCase()
        ) invalid();
        return {
          generation,
          operationId,
          expiresAtMs: timestamp(r.expires_at),
        };
      }),
    consume: (owner, env, state, binding, callback) =>
      safe(async () => {
        const r = row(
          await call("crier_webull_authorization_consume", {
            ...scope(owner, env),
            ...session(state, binding, callback),
          }),
          ["generation", "operation_id"],
        );
        return r
          ? {
            generation: integer(r.generation),
            operationId: uuid(r.operation_id),
          }
          : null;
      }),
    read: (owner, env) =>
      safe(async () => {
        const r = row(
          await call("crier_webull_token_read", scope(owner, env)),
          ["state", "generation", "envelope"],
        );
        if (!r) return null;
        if (
          ![
            "authorization_pending",
            "active",
            "refresh_pending",
            "unknown",
            "revoked",
          ].includes(r.state as string)
        ) invalid();
        if (r.state !== "active" && r.envelope !== null) invalid();
        return {
          state: r.state as TokenState,
          generation: integer(r.generation),
          envelope: r.state === "active" ? envelope(r.envelope) : null,
        };
      }),
    commit: (owner, env, generation, op, value) =>
      safe(async () =>
        boolean(
          await call("crier_webull_token_commit", {
            ...scope(owner, env),
            p_generation: integer(generation),
            p_operation_id: uuid(op),
            p_envelope: envelope(value),
          }),
        )
      ),
    claimRefresh: (owner, env, expected, op) =>
      safe(async () => {
        const r = row(
          await call("crier_webull_token_claim_refresh", {
            ...scope(owner, env),
            p_expected_generation: integer(
              expected,
              1,
              Number.MAX_SAFE_INTEGER - 1,
            ),
            p_operation_id: uuid(op),
          }),
          ["prior_generation", "new_generation", "envelope"],
        );
        if (!r) return null;
        const priorGeneration = integer(r.prior_generation),
          newGeneration = integer(r.new_generation);
        if (
          priorGeneration !== expected || newGeneration !== priorGeneration + 1
        ) invalid();
        return {
          priorGeneration,
          newGeneration,
          envelope: envelope(r.envelope),
        };
      }),
    markUnknown: (owner, env, generation, op) =>
      safe(async () =>
        boolean(
          await call("crier_webull_token_mark_unknown", {
            ...scope(owner, env),
            p_generation: integer(generation),
            p_operation_id: uuid(op),
          }),
        )
      ),
    revoke: (owner, env) =>
      safe(async () =>
        integer(
          await call("crier_webull_authorization_revoke", scope(owner, env)),
        )
      ),
    rewrap: (owner, env, generation, expectedEnvelope, value) =>
      safe(async () =>
        boolean(
          await call("crier_webull_token_rewrap", {
            ...scope(owner, env),
            p_expected_generation: integer(generation),
            p_expected_envelope: envelope(expectedEnvelope),
            p_envelope: envelope(value),
          }),
        )
      ),
    cleanupExpiredSessions: (limit) =>
      safe(async () => {
        integer(limit, 1, 500);
        return integer(
          await call("crier_webull_cleanup_expired_sessions", {
            p_limit: limit,
          }),
          0,
          limit,
        );
      }),
  };
}
