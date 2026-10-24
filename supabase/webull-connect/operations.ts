/** Server-only recovery operations. No HTTP, environment reads or live deployment. */
import type { OAuthEnvironment } from "./oauth_contract.ts";
import type { createTokenVault, EncryptedEnvelope } from "./token_vault.ts";

interface OperationsStore {
  read(owner: string, environment: OAuthEnvironment): Promise<unknown>;
  rewrap(
    owner: string,
    environment: OAuthEnvironment,
    generation: number,
    expected: EncryptedEnvelope,
    replacement: EncryptedEnvelope,
  ): Promise<boolean>;
  cleanupExpiredSessions(limit: number): Promise<number>;
}
interface Options {
  environment: OAuthEnvironment;
  store: OperationsStore;
  vault: ReturnType<typeof createTokenVault>;
  verifyPrincipal(input: unknown): Promise<string>;
  verifyOperator(input: unknown): Promise<boolean>;
  nowMs?: () => number;
  audit?: (event: Readonly<AuditEvent>) => void | Promise<void>;
}
interface AuditEvent {
  schema: "crier.webull-operation.v1";
  action: "rotation" | "status" | "cleanup";
  outcome: "success" | "stale" | "reauthorize" | "failure";
  environment: OAuthEnvironment;
  atMs: number;
}
export interface SafeStatus {
  state:
    | "not_connected"
    | "connected"
    | "refresh_required"
    | "authorization_pending"
    | "refresh_pending"
    | "reauthorization_required";
  generation: number | null;
  accessExpiresAtMs?: number;
  refreshExpiresAtMs?: number;
}
function invalid(): never {
  throw new Error("Invalid Webull operational request");
}
function clock(value: unknown): number {
  if (
    typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 ||
    value > 8_640_000_000_000_000
  ) invalid();
  return value;
}
function owner(value: unknown): string {
  if (
    typeof value !== "string" || !value.trim() || value.length > 200 ||
    // deno-lint-ignore no-control-regex -- explicitly reject control characters.
    /[\u0000-\u001f\u007f-\u009f]/u.test(value)
  ) invalid();
  return value;
}
function record(
  value: unknown,
): { state: string; generation: number; envelope: unknown } | null {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const row = value as Record<string, unknown>;
  if (
    typeof row.state !== "string" ||
    ![
      "active",
      "authorization_pending",
      "refresh_pending",
      "unknown",
      "revoked",
    ].includes(row.state) ||
    typeof row.generation !== "number" ||
    !Number.isSafeInteger(row.generation) || row.generation < 1 ||
    (row.state === "active" ? !row.envelope : row.envelope !== null)
  ) invalid();
  return {
    state: row.state,
    generation: row.generation,
    envelope: row.envelope,
  };
}
export function createOperations(options: Options) {
  if (
    !options || !["sandbox", "production"].includes(options.environment) ||
    typeof options.verifyPrincipal !== "function" ||
    typeof options.verifyOperator !== "function" ||
    !options.store || !options.vault
  ) invalid();
  // Capture a private snapshot; caller mutations cannot change the security boundary.
  const { environment, store, vault, verifyPrincipal, verifyOperator, audit } =
    options;
  const nowMs = options.nowMs ?? Date.now;
  function emit(action: AuditEvent["action"], outcome: AuditEvent["outcome"]) {
    try {
      const pending = audit?.(
        Object.freeze({
          schema: "crier.webull-operation.v1",
          action,
          outcome,
          environment,
          atMs: clock(nowMs()),
        }),
      );
      // Attach a rejection handler immediately; audit delivery cannot undo a mutation.
      Promise.resolve(pending).catch(() => {});
    } catch {
      /* Audit sink failure must never cause a caller to repeat a completed mutation. */
    }
  }
  return Object.freeze({
    async rotateKey(
      authInput: unknown,
    ): Promise<"rotated" | "stale" | "reauthorize"> {
      try {
        const principal = owner(await verifyPrincipal(authInput));
        const row = record(await store.read(principal, environment));
        if (!row || row.state !== "active") {
          emit("rotation", "reauthorize");
          return "reauthorize";
        }
        const context = {
          ownerRef: principal,
          environment,
          generation: row.generation,
        };
        let replacement: Readonly<EncryptedEnvelope>;
        try {
          replacement = await vault.rewrap(
            context,
            row.envelope,
            clock(nowMs()),
          );
        } catch {
          emit("rotation", "reauthorize");
          return "reauthorize";
        }
        const committed = await store.rewrap(
          principal,
          environment,
          row.generation,
          row.envelope as EncryptedEnvelope,
          replacement,
        );
        if (typeof committed !== "boolean") invalid();
        emit("rotation", committed ? "success" : "stale");
        return committed ? "rotated" : "stale";
      } catch {
        emit("rotation", "failure");
        invalid();
      }
    },
    async status(authInput: unknown): Promise<Readonly<SafeStatus>> {
      try {
        const principal = owner(await verifyPrincipal(authInput));
        const row = record(await store.read(principal, environment));
        let status: SafeStatus;
        if (!row) status = { state: "not_connected", generation: null };
        else if (row.state !== "active") {
          status = {
            state: row.state === "unknown" || row.state === "revoked"
              ? "reauthorization_required"
              : row.state as "authorization_pending" | "refresh_pending",
            generation: row.generation,
          };
        } else {
          try {
            const now = clock(nowMs());
            const token = await vault.open(
              { ownerRef: principal, environment, generation: row.generation },
              row.envelope,
              now,
            );
            status = {
              state: token.needsRefresh(now) ? "refresh_required" : "connected",
              generation: row.generation,
              accessExpiresAtMs: token.accessExpiresAtMs,
              refreshExpiresAtMs: token.refreshExpiresAtMs,
            };
          } catch {
            status = {
              state: "reauthorization_required",
              generation: row.generation,
            };
          }
        }
        emit("status", "success");
        return Object.freeze(status);
      } catch {
        emit("status", "failure");
        invalid();
      }
    },
    async cleanup(authInput: unknown, limit: number): Promise<number> {
      try {
        if (
          !Number.isInteger(limit) || limit < 1 || limit > 500 ||
          await verifyOperator(authInput) !== true
        ) invalid();
        const count = await store.cleanupExpiredSessions(limit);
        if (!Number.isInteger(count) || count < 0 || count > limit) invalid();
        emit("cleanup", "success");
        return count;
      } catch {
        emit("cleanup", "failure");
        invalid();
      }
    },
  });
}
