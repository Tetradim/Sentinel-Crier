/** Service-only PostgREST port. Public callers never receive these internal rows. */
import type { Envelope, FlowContext } from "./crypto.ts";

export type FlowRow = FlowContext & {
  stage: string;
  created_at: number;
  expires_at: number;
  ready_until: number | null;
  state_ciphertext: Envelope | null;
  grant_ciphertext: Envelope | null;
};
export interface FlowPort {
  call(
    action: string,
    owner: string | null,
    flow: string | null,
    input: Record<string, unknown>,
  ): Promise<FlowRow>;
  claimCsrf(hash: string, expiresAtSeconds: number): Promise<boolean>;
}
export class StoreRejected extends Error {
  constructor() {
    super("Provider flow rejected");
    this.name = "StoreRejected";
  }
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const STAGES = [
  "pending",
  "launched",
  "exchanging",
  "ready",
  "redeemed",
  "cancelled",
  "failed",
  "expired",
];

export function checkedRow(
  value: unknown,
  owner: string | null,
  flow: string | null,
): FlowRow {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new StoreRejected();
  }
  const row = value as FlowRow;
  if (
    !TOKEN.test(row.flow_id) || !UUID.test(row.owner_id) ||
    owner && row.owner_id !== owner || flow && row.flow_id !== flow ||
    !["alpaca", "discord"].includes(row.provider) ||
    !["alerts", "trade"].includes(row.purpose) ||
    row.provider === "discord" && row.purpose !== "alerts" ||
    !["paper", "live"].includes(row.environment) ||
    typeof row.challenge !== "string" ||
    !/^[0-9a-f]{64}$/.test(row.challenge) || !STAGES.includes(row.stage) ||
    !Number.isSafeInteger(row.created_at) || row.created_at < 0 ||
    !Number.isSafeInteger(row.expires_at) ||
    row.expires_at !== row.created_at + 300000 || row.ready_until !== null &&
      (!Number.isSafeInteger(row.ready_until) ||
        row.ready_until < row.created_at || row.ready_until > row.expires_at)
  ) {
    throw new StoreRejected();
  }
  return row;
}

export function metadata(row: FlowRow): Record<string, unknown> {
  return {
    flow: row.flow_id,
    provider: row.provider,
    purpose: row.purpose,
    environment: row.environment,
    stage: row.stage,
    expires_at: row.expires_at / 1000,
    ready_until: row.ready_until === null ? null : row.ready_until / 1000,
  };
}

export class RpcFlowStore implements FlowPort {
  private endpoint: string;
  private serviceKey: string;
  private fetcher: typeof fetch;
  constructor(
    projectUrl: string,
    serviceKey: string,
    fetcher: typeof fetch = fetch,
  ) {
    if (
      !/^https:\/\/[a-z]{20}\.supabase\.co$/.test(projectUrl) ||
      !/^[A-Za-z0-9._-]{20,8192}$/.test(serviceKey)
    ) throw new StoreRejected();
    this.endpoint = projectUrl + "/rest/v1/rpc/crier_oauth_flow";
    this.serviceKey = serviceKey;
    this.fetcher = fetcher;
  }
  private async rpc(
    action: string,
    owner: string | null,
    flow: string | null,
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await this.fetcher(this.endpoint, {
        method: "POST",
        redirect: "error",
        signal: controller.signal,
        headers: {
          "apikey": this.serviceKey,
          "Authorization": "Bearer " + this.serviceKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          p_action: action,
          p_owner: owner,
          p_flow: flow,
          p_input: input,
        }),
      });
      if (!response.ok || !response.body) throw new StoreRejected();
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        size += item.value.length;
        if (size > 131072) {
          await reader.cancel();
          throw new StoreRejected();
        }
        chunks.push(item.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      const result = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
      if (!result || typeof result !== "object" || result.ok !== true) {
        throw new StoreRejected();
      }
      return result;
    } catch {
      throw new StoreRejected();
    } finally {
      clearTimeout(timeout);
    }
  }
  async call(
    action: string,
    owner: string | null,
    flow: string | null,
    input: Record<string, unknown>,
  ): Promise<FlowRow> {
    return checkedRow(
      (await this.rpc(action, owner, flow, input)).flow,
      owner,
      flow,
    );
  }
  async claimCsrf(hash: string, expiresAtSeconds: number): Promise<boolean> {
    const result = await this.rpc("csrf_claim", null, null, {
      hash,
      expires_at: expiresAtSeconds * 1000,
    });
    if (typeof result.claimed !== "boolean") throw new StoreRejected();
    return result.claimed;
  }
}
