/** Production assembly; missing approved Connect resource adapter fails closed. */
import {
  type Capabilities,
  createGateway,
  createSupabaseVerifier,
  type Ledger,
  parseOrder,
  type Provider,
  type StoredOrder,
  validateReceipt,
} from "./gateway.ts";
type Rpc = (name: string, args: Record<string, unknown>) => Promise<unknown>;
function invalid(): never {
  throw Error("Invalid Webull ledger response");
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function row(value: unknown, owner: string, id: string): StoredOrder {
  const f = record(value), order = parseOrder(f.order);
  if (
    f.owner !== owner || order.client_order_id !== id ||
    typeof f.fingerprint !== "string" || !f.fingerprint ||
    f.fingerprint.length > 4096 || !Number.isSafeInteger(f.revision) ||
    Number(f.revision) < 1 || typeof f.cancel_claimed !== "boolean" ||
    typeof f.cancel_pending !== "boolean" ||
    (f.cancel_revision !== null &&
      (!Number.isSafeInteger(f.cancel_revision) ||
        Number(f.cancel_revision) < 1))
  ) invalid();
  return {
    owner,
    order,
    fingerprint: f.fingerprint,
    receipt: validateReceipt(f.receipt, order),
    revision: f.revision as number,
    cancel_claimed: f.cancel_claimed,
    cancel_pending: f.cancel_pending,
    cancel_revision: f.cancel_revision as number | null,
  };
}
/** RPC errors are never retried: a failed response can follow a committed claim. */
export function createRpcLedger(rpc: Rpc): Ledger {
  return {
    async reserve(owner, order, fingerprint) {
      const result = record(
        await rpc("webull_host_reserve", {
          p_owner: owner,
          p_order: order,
          p_fingerprint: fingerprint,
        }),
      );
      if (typeof result.created !== "boolean") invalid();
      if (
        result.created === false && result.row === null &&
        (result.reason === "insufficient_tracked_long_position" ||
          result.reason === "source_inventory_reconciliation_required") &&
        Object.keys(result).length === 3
      ) {
        return { created: false, row: null, reason: result.reason };
      }
      return {
        created: result.created,
        row: row(result.row, owner, order.client_order_id),
      };
    },
    async blockInventory(owner, id) {
      const result = await rpc("webull_host_block_inventory", {
        p_owner: owner,
        p_id: id,
      });
      if (result !== true) invalid();
    },
    async read(owner, id) {
      const result = await rpc("webull_host_read", {
        p_owner: owner,
        p_id: id,
      });
      return result === null ? null : row(result, owner, id);
    },
    async claimCancel(owner, id, revision) {
      const result = await rpc("webull_host_claim_cancel", {
        p_owner: owner,
        p_id: id,
        p_revision: revision,
      });
      return result === null ? null : row(result, owner, id);
    },
    async settleCancel(owner, id, cancelRevision) {
      const result = await rpc("webull_host_settle_cancel", {
        p_owner: owner,
        p_id: id,
        p_cancel_revision: cancelRevision,
      });
      if (typeof result !== "boolean") invalid();
    },
    async save(owner, id, revision, receipt, action = "submit") {
      const result = await rpc("webull_host_save", {
        p_owner: owner,
        p_id: id,
        p_revision: revision,
        p_receipt: receipt,
        p_action: action,
      });
      if (typeof result !== "boolean") invalid();
      return result;
    },
  };
}
export interface HostedOptions {
  supabaseUrl: string;
  publishableKey: string;
  serviceRoleKey: string;
  fetch?: typeof fetch;
  /** Trusted service assembly may reuse its already verified request principal. */
  verify?: (token: string) => Promise<string>;
  /** Only set together after approved Connect resource paths, mappings, exact
   * contract resolution, account/token binding and no-short enforcement validate. */
  provider?: Provider;
  capabilities?: Capabilities;
}
export function createHostedGateway(
  options: HostedOptions,
): (r: Request) => Promise<Response> {
  const fetcher = options.fetch ?? fetch,
    verify = options.verify ?? createSupabaseVerifier({
      url: options.supabaseUrl,
      publishableKey: options.publishableKey,
      fetch: fetcher,
    }),
    origin = new URL(options.supabaseUrl).origin,
    key = options.serviceRoleKey;
  if (!key || /[\r\n]/u.test(key)) {
    throw Error("Missing server service-role key");
  }
  const rpc: Rpc = async (name, args) => {
    const response = await fetcher(origin + "/rest/v1/rpc/" + name, {
      method: "POST",
      redirect: "error",
      headers: {
        apikey: key,
        authorization: "Bearer " + key,
        "content-type": "application/json",
      },
      body: JSON.stringify(args),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw Error("Webull ledger unavailable");
    return await response.json();
  };
  const unavailable = (): Promise<never> =>
    Promise.reject(Error("Webull integration unavailable"));
  const provider = options.provider ??
    {
      connection: unavailable,
      begin: unavailable,
      position: unavailable,
      submit: unavailable,
      lookup: unavailable,
      cancel: unavailable,
    };
  const capabilities = options.provider && options.capabilities
    ? options.capabilities
    : { available: false, environments: [], stocks: [], options: false };
  return createGateway({
    verify,
    ledger: createRpcLedger(rpc),
    provider,
    capabilities,
  });
}
