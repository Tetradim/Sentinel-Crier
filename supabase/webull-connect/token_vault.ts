/** Offline server-side custody only. Callers supply keys, clocks and storage context. */
import {
  parseTokenResponse,
  type TokenResponseOptions,
} from "./oauth_contract.ts";

const SCHEMA = "crier.webull-token.v1";
const MAX_PLAINTEXT = 32768;
const DATE_LIMIT = 8_640_000_000_000_000;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const inspectDeno = Symbol.for("Deno.customInspect");
const inspectNode = Symbol.for("nodejs.util.inspect.custom");

export interface VaultContext {
  ownerRef: string;
  environment: "sandbox" | "production";
  generation: number;
}
export interface EncryptedEnvelope {
  schema: typeof SCHEMA;
  key_id: string;
  nonce: string;
  ciphertext: string;
  identity_hash: string;
  access_expires_at_ms: number;
  refresh_expires_at_ms: number;
}
function invalid(): never {
  throw new Error("Invalid Webull token vault operation");
}
/** Snapshot own data properties; reject accessors, symbols and unusual prototypes. */
function fields(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object") invalid();
  const proto = Object.getPrototypeOf(value);
  if (proto !== null && proto !== Object.prototype) invalid();
  if (Reflect.ownKeys(value).length !== keys.length) invalid();
  const result: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !Object.hasOwn(descriptor, "value")) invalid();
    result[key] = descriptor.value;
  }
  return result;
}
function text(value: unknown, max = MAX_PLAINTEXT): string {
  if (
    typeof value !== "string" || !value.trim() || value.length > max ||
    // deno-lint-ignore no-control-regex -- explicitly reject C0, DEL and C1 controls.
    /[\u0000-\u001f\u007f-\u009f]/u.test(value)
  ) invalid();
  return value;
}
function timestamp(value: unknown): number {
  if (
    typeof value !== "number" || !Number.isSafeInteger(value) ||
    Math.abs(value) > DATE_LIMIT
  ) invalid();
  return value;
}
function deadlines(access: unknown, refresh: unknown): void {
  const a = timestamp(access), r = timestamp(refresh);
  if (a <= 0 || r <= a) invalid();
}
function scope(value: unknown): VaultContext {
  const f = fields(value, ["ownerRef", "environment", "generation"]);
  const ownerRef = text(f.ownerRef, 200);
  if (f.environment !== "sandbox" && f.environment !== "production") invalid();
  if (
    typeof f.generation !== "number" || !Number.isSafeInteger(f.generation) ||
    f.generation <= 0
  ) invalid();
  return { ownerRef, environment: f.environment, generation: f.generation };
}
function encode(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll(
    "/",
    "_",
  ).replace(/=+$/u, "");
}
function decode(
  value: unknown,
  min: number,
  max: number,
): Uint8Array<ArrayBuffer> {
  if (
    typeof value !== "string" || value.length < min || value.length > max ||
    !/^[A-Za-z0-9_-]+$/u.test(value)
  ) invalid();
  const bytes = Uint8Array.from(
    atob(
      value.replaceAll("-", "+").replaceAll("_", "/") +
        "=".repeat((4 - value.length % 4) % 4),
    ),
    (c) => c.charCodeAt(0),
  );
  if (encode(bytes) !== value) invalid();
  return bytes;
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
  if (
    f.schema !== SCHEMA || typeof f.identity_hash !== "string" ||
    !/^[0-9a-f]{64}$/u.test(f.identity_hash)
  ) invalid();
  const key_id = text(f.key_id, 200);
  decode(f.nonce, 16, 16);
  const ciphertext = decode(f.ciphertext, 22, 65536);
  if (ciphertext.length < 16 || ciphertext.length > MAX_PLAINTEXT + 16) {
    invalid();
  }
  deadlines(f.access_expires_at_ms, f.refresh_expires_at_ms);
  return {
    schema: SCHEMA,
    key_id,
    nonce: f.nonce as string,
    ciphertext: f.ciphertext as string,
    identity_hash: f.identity_hash,
    access_expires_at_ms: timestamp(f.access_expires_at_ms),
    refresh_expires_at_ms: timestamp(f.refresh_expires_at_ms),
  };
}
function aad(
  context: VaultContext,
  value: Omit<EncryptedEnvelope, "nonce" | "ciphertext">,
): Uint8Array<ArrayBuffer> {
  return encoder.encode(
    JSON.stringify([
      SCHEMA,
      context.ownerRef,
      context.environment,
      context.generation,
      value.key_id,
      value.identity_hash,
      value.access_expires_at_ms,
      value.refresh_expires_at_ms,
    ]),
  );
}
async function identityHash(identity: string): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", encoder.encode(identity)),
  );
  return Array.from(digest, (n) => n.toString(16).padStart(2, "0")).join("");
}
function validKey(value: CryptoKey): void {
  if (
    !(value instanceof CryptoKey) || value.type !== "secret" ||
    value.extractable || value.algorithm.name !== "AES-GCM" ||
    (value.algorithm as AesKeyAlgorithm).length !== 256 ||
    value.usages.length !== 2 || !value.usages.includes("encrypt") ||
    !value.usages.includes("decrypt")
  ) invalid();
}
export async function importVaultKey(bytes: Uint8Array): Promise<CryptoKey> {
  try {
    if (!(bytes instanceof Uint8Array) || bytes.byteLength !== 32) invalid();
    return await crypto.subtle.importKey(
      "raw",
      new Uint8Array(bytes),
      "AES-GCM",
      false,
      ["encrypt", "decrypt"],
    );
  } catch {
    invalid();
  }
}

/** Explicit getters only; default JSON, string and runtime inspection redact secrets. */
class OpenedToken {
  #access: string;
  #refresh: string;
  #identity: string;
  readonly accessExpiresAtMs: number;
  readonly refreshExpiresAtMs: number;
  constructor(
    access: string,
    refresh: string,
    identity: string,
    accessExpiry: number,
    refreshExpiry: number,
  ) {
    this.#access = access;
    this.#refresh = refresh;
    this.#identity = identity;
    this.accessExpiresAtMs = accessExpiry;
    this.refreshExpiresAtMs = refreshExpiry;
    Object.freeze(this);
  }
  accessToken(): string {
    return this.#access;
  }
  refreshToken(): string {
    return this.#refresh;
  }
  identityId(): string {
    return this.#identity;
  }
  needsRefresh(nowMs: number): boolean {
    return timestamp(nowMs) >= this.accessExpiresAtMs;
  }
  toJSON(): string {
    return "WebullOpenedToken [REDACTED]";
  }
  toString(): string {
    return this.toJSON();
  }
  [inspectDeno](): string {
    return this.toJSON();
  }
  [inspectNode](): string {
    return this.toJSON();
  }
}

class TokenVault {
  #activeKeyId: string;
  #keys: Map<string, CryptoKey>;
  constructor(activeKeyId: string, keys: ReadonlyMap<string, CryptoKey>) {
    this.#activeKeyId = text(activeKeyId, 200);
    if (!(keys instanceof Map)) invalid();
    this.#keys = new Map();
    for (const [id, key] of keys) {
      text(id, 200);
      validKey(key);
      this.#keys.set(id, key);
    }
    if (!this.#keys.has(activeKeyId)) invalid();
    Object.freeze(this);
  }
  async #seal(
    context: VaultContext,
    token: OpenedToken,
  ): Promise<Readonly<EncryptedEnvelope>> {
    deadlines(token.accessExpiresAtMs, token.refreshExpiresAtMs);
    const metadata = {
      schema: SCHEMA,
      key_id: this.#activeKeyId,
      identity_hash: await identityHash(token.identityId()),
      access_expires_at_ms: token.accessExpiresAtMs,
      refresh_expires_at_ms: token.refreshExpiresAtMs,
    } as const;
    const plaintext = encoder.encode(
      JSON.stringify({
        access_token: token.accessToken(),
        refresh_token: token.refreshToken(),
        identity_id: token.identityId(),
      }),
    );
    try {
      if (plaintext.byteLength > MAX_PLAINTEXT) invalid();
      const nonce = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = new Uint8Array(
        await crypto.subtle.encrypt(
          {
            name: "AES-GCM",
            iv: nonce,
            tagLength: 128,
            additionalData: aad(context, metadata),
          },
          this.#keys.get(this.#activeKeyId)!,
          plaintext,
        ),
      );
      return Object.freeze({
        ...metadata,
        nonce: encode(nonce),
        ciphertext: encode(ciphertext),
      });
    } finally {
      plaintext.fill(0);
    }
  }
  async sealReply(
    context: VaultContext,
    rawReply: unknown,
    options: TokenResponseOptions,
  ): Promise<Readonly<EncryptedEnvelope>> {
    try {
      const bound = scope(context);
      const token = parseTokenResponse(rawReply, options);
      const access = text(token.accessToken()),
        refresh = text(token.refreshToken()),
        identity = text(token.identityId());
      return await this.#seal(
        bound,
        new OpenedToken(
          access,
          refresh,
          identity,
          token.accessExpiresAtMs,
          token.refreshExpiresAtMs,
        ),
      );
    } catch {
      invalid();
    }
  }
  async open(
    context: VaultContext,
    encrypted: unknown,
    nowMs: number,
  ): Promise<OpenedToken> {
    try {
      const bound = scope(context),
        value = envelope(encrypted),
        now = timestamp(nowMs);
      const key = this.#keys.get(value.key_id);
      if (!key || value.refresh_expires_at_ms <= now) invalid();
      const plaintext = new Uint8Array(
        await crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: decode(value.nonce, 16, 16),
            additionalData: aad(bound, value),
            tagLength: 128,
          },
          key,
          decode(value.ciphertext, 22, 65536),
        ),
      );
      try {
        if (plaintext.byteLength > MAX_PLAINTEXT) invalid();
        const f = fields(JSON.parse(decoder.decode(plaintext)), [
          "access_token",
          "refresh_token",
          "identity_id",
        ]);
        const access = text(f.access_token),
          refresh = text(f.refresh_token),
          identity = text(f.identity_id);
        if (await identityHash(identity) !== value.identity_hash) invalid();
        return new OpenedToken(
          access,
          refresh,
          identity,
          value.access_expires_at_ms,
          value.refresh_expires_at_ms,
        );
      } finally {
        plaintext.fill(0);
      }
    } catch {
      invalid();
    }
  }
  async rewrap(
    context: VaultContext,
    encrypted: unknown,
    nowMs: number,
  ): Promise<Readonly<EncryptedEnvelope>> {
    try {
      const bound = scope(context);
      return await this.#seal(bound, await this.open(bound, encrypted, nowMs));
    } catch {
      invalid();
    }
  }
}

export function createTokenVault(
  activeKeyId: string,
  keys: ReadonlyMap<string, CryptoKey>,
): TokenVault {
  try {
    return new TokenVault(activeKeyId, keys);
  } catch {
    invalid();
  }
}
