/** Pinned, server-only authorization-code exchanges. Never sends or trades. */
import type { FlowContext } from "./crypto.ts";
export type Grant =
  & Pick<FlowContext, "provider" | "purpose" | "environment">
  & {
    account_id: string;
    credential: string;
    guild_id: string;
    channel_id: string;
    scopes: string[];
  };
export class ProviderRejected extends Error {
  constructor() {
    super("Provider authorization was rejected.");
    this.name = "ProviderRejected";
  }
}
function reject(): never {
  throw new ProviderRejected();
}
function text(value: unknown, limit = 4096): string {
  if (
    typeof value !== "string" || !value.length || value.length > limit ||
    /[^\x21-\x7e]/.test(value)
  ) reject();
  return value;
}
const AUTHORIZE = {
  alpaca: "https://app.alpaca.markets/oauth/authorize",
  discord: "https://discord.com/oauth2/authorize",
};
const TOKEN = {
  alpaca: "https://api.alpaca.markets/oauth/token",
  discord: "https://discord.com/api/oauth2/token",
};
const ACCOUNT = {
  paper: "https://paper-api.alpaca.markets/v2/account",
  live: "https://api.alpaca.markets/v2/account",
};
type ObjectValue = Record<string, unknown>;
/** Parse JSON while rejecting duplicate keys, including escaped aliases. */
function parseObject(source: string): ObjectValue {
  let offset = 0;
  const whitespace = () => {
    while (
      /[\x20\t\r\n]/.test(source[offset] ?? "") && offset < source.length
    ) offset++;
  };
  function string(): string {
    const start = offset++;
    while (offset < source.length) {
      const c = source[offset++];
      if (c === "\\") offset++;
      else if (c === '"') return JSON.parse(source.slice(start, offset));
    }
    return reject();
  }
  function value(depth: number): unknown {
    if (depth > 64) reject();
    whitespace();
    if (source[offset] === '"') return string();
    if (source[offset] === "{" || source[offset] === "[") {
      const object = source[offset++] === "{";
      const close = object ? "}" : "]";
      const result: ObjectValue = Object.create(null), list: unknown[] = [];
      whitespace();
      if (source[offset] === close) {
        offset++;
        return object ? result : list;
      }
      while (offset < source.length) {
        whitespace();
        if (object) {
          if (source[offset] !== '"') reject();
          const key = string();
          whitespace();
          if (Object.hasOwn(result, key) || source[offset++] !== ":") reject();
          result[key] = value(depth + 1);
        } else list.push(value(depth + 1));
        whitespace();
        const delimiter = source[offset++];
        if (delimiter === close) return object ? result : list;
        if (delimiter !== ",") reject();
      }
      reject();
    }
    const match =
      /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(
        source.slice(offset),
      );
    if (!match) reject();
    offset += match[0].length;
    const parsed = JSON.parse(match[0]);
    if (typeof parsed === "number" && !Number.isFinite(parsed)) reject();
    return parsed;
  }
  const result = value(0);
  whitespace();
  if (
    offset !== source.length || !result || typeof result !== "object" ||
    Array.isArray(result)
  ) reject();
  return result as ObjectValue;
}
async function requestJson(
  fetcher: typeof fetch,
  url: string,
  init: RequestInit,
): Promise<ObjectValue> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const timeout = new Promise<never>((_resolve, fail) => {
    timer = setTimeout(() => {
      controller.abort();
      fail(new ProviderRejected());
    }, 15000);
  });
  try {
    return await Promise.race([
      timeout,
      (async () => {
        const response = await fetcher(url, {
          ...init,
          redirect: "error",
          signal: controller.signal,
        });
        if (controller.signal.aborted) {
          void response.body?.cancel().catch(() => {});
          reject();
        }
        if (
          response.status !== 200 || response.redirected || !response.body
        ) reject();
        reader = response.body.getReader();
        const chunks: Uint8Array[] = [];
        let size = 0;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 65536) reject();
          chunks.push(value);
        }
        const bytes = new Uint8Array(size);
        let position = 0;
        for (const chunk of chunks) {
          bytes.set(chunk, position);
          position += chunk.length;
        }
        return parseObject(
          new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        );
      })(),
    ]);
  } finally {
    clearTimeout(timer);
    controller.abort();
    if (reader) void reader.cancel().catch(() => {});
  }
}
function accountId(v: unknown): string {
  const s = text(v, 36);
  if (
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(s)
  ) reject();
  return s;
}
function snowflake(v: unknown): string {
  if (
    typeof v !== "string" || !/^[1-9][0-9]{0,19}$/.test(v) ||
    BigInt(v) >= 2n ** 64n
  ) reject();
  return v;
}
export class ProviderApplication {
  #provider: FlowContext["provider"];
  #clientId: string;
  #clientSecret: string;
  #callback: string;
  constructor(
    config: {
      provider: FlowContext["provider"];
      clientId: string;
      clientSecret: string;
      callback: string;
    },
  ) {
    try {
      if (!config || !Object.hasOwn(AUTHORIZE, config.provider)) reject();
      this.#provider = config.provider;
      this.#clientId = text(config.clientId, 256);
      this.#clientSecret = text(config.clientSecret);
      this.#callback = text(config.callback, 2048);
      const url = new URL(this.#callback);
      if (
        !this.#callback.startsWith("https://") || url.protocol !== "https:" ||
        !url.hostname || url.username ||
        url.password || /[?#\\]/.test(this.#callback)
      ) reject();
    } catch {
      reject();
    }
  }
  #scopes(purpose: string, environment: string): string[] {
    if (
      !["alerts", "trade"].includes(purpose) ||
      !Object.hasOwn(ACCOUNT, environment) ||
      this.#provider === "discord" && purpose !== "alerts"
    ) reject();
    return this.#provider === "discord"
      ? ["webhook.incoming"]
      : purpose === "trade"
      ? ["trading"]
      : [];
  }
  authorize(
    state: string,
    purpose: FlowContext["purpose"],
    environment: FlowContext["environment"],
  ): string {
    try {
      const scopes = this.#scopes(purpose, environment);
      const query = new URLSearchParams({
        response_type: "code",
        client_id: this.#clientId,
        redirect_uri: this.#callback,
        state: text(state, 1024),
      });
      if (this.#provider === "alpaca") query.set("env", environment);
      if (scopes.length) query.set("scope", scopes.join(" "));
      return AUTHORIZE[this.#provider] + "?" + query;
    } catch {
      reject();
    }
  }
  async exchange(
    code: string,
    purpose: FlowContext["purpose"],
    environment: FlowContext["environment"],
    fetcher: typeof fetch = fetch,
  ): Promise<Grant> {
    try {
      const expected = this.#scopes(purpose, environment);
      const response = await requestJson(fetcher, TOKEN[this.#provider], {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          client_id: this.#clientId,
          client_secret: this.#clientSecret,
          redirect_uri: this.#callback,
          code: text(code),
        }).toString(),
      });
      if (
        response.error != null || typeof response.token_type !== "string" ||
        response.token_type.toLowerCase() !== "bearer"
      ) reject();
      const token = text(response.access_token),
        scope = response.scope === undefined ? "" : response.scope;
      if (typeof scope !== "string" || scope.length > 1024) reject();
      const scopes = scope.trim() ? scope.trim().split(/\s+/).sort() : [];
      if (
        scopes.length !== new Set(scopes).size ||
        scopes.join(" ") !== expected.join(" ")
      ) reject();
      let account_id = "", guild_id = "", channel_id = "", credential = token;
      if (this.#provider === "alpaca") {
        const identity = await requestJson(fetcher, ACCOUNT[environment], {
          method: "GET",
          headers: {
            Accept: "application/json",
            Authorization: "Bearer " + token,
          },
        });
        account_id = accountId(identity.id);
        if (
          Object.hasOwn(response, "account_id") &&
          accountId(response.account_id) !== account_id
        ) reject();
      } else {
        const w = response.webhook as ObjectValue;
        if (!w || typeof w !== "object" || Array.isArray(w) || w.type !== 1) {
          reject();
        }
        const id = snowflake(w.id);
        guild_id = snowflake(w.guild_id);
        channel_id = snowflake(w.channel_id);
        const hookToken = text(w.token, 256);
        if (!/^[A-Za-z0-9._-]+$/.test(hookToken)) reject();
        credential = `https://discord.com/api/webhooks/${id}/${hookToken}`;
        if (w.url !== credential) reject();
      }
      return {
        provider: this.#provider,
        environment,
        purpose,
        account_id,
        credential,
        guild_id,
        channel_id,
        scopes,
      };
    } catch {
      reject();
    }
  }
}
