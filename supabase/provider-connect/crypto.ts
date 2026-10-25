/** Server-only AES-256-GCM custody. Keys must come from external configuration. */
export type FlowContext = {
  flow_id: string;
  owner_id: string;
  provider: "alpaca" | "discord";
  purpose: "alerts" | "trade";
  environment: "paper" | "live";
  challenge: string;
};
export type Envelope = {
  version: 1;
  key_id: string;
  nonce: string;
  ciphertext: string;
};
export class CryptoRejected extends Error {
  constructor() {
    super("Authorization flow rejected");
    this.name = "CryptoRejected";
  }
}
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
function reject(): never {
  throw new CryptoRejected();
}
function encode(bytes: Uint8Array): string {
  return btoa(Array.from(bytes, (v) => String.fromCharCode(v)).join(""))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}
function decode(value: unknown, max: number): Uint8Array<ArrayBuffer> {
  if (
    typeof value !== "string" || !value.length || value.length > max ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) reject();
  const bytes = Uint8Array.from(
    atob(
      value.replaceAll("-", "+").replaceAll("_", "/") +
        "=".repeat((4 - value.length % 4) % 4),
    ),
    (c) => c.charCodeAt(0),
  );
  if (encode(bytes) !== value) reject();
  return bytes;
}
function aad(
  context: FlowContext,
  kind: string,
  keyId: string,
): Uint8Array<ArrayBuffer> {
  if (
    !context || typeof context !== "object" ||
    typeof context.flow_id !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(context.flow_id) ||
    typeof context.owner_id !== "string" || context.owner_id.length < 1 ||
    context.owner_id.length > 200 ||
    context.owner_id.trim() !== context.owner_id ||
    Array.from(context.owner_id).some((c) =>
      c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127
    ) ||
    decoder.decode(encoder.encode(context.owner_id)) !== context.owner_id ||
    typeof context.challenge !== "string" ||
    !/^[a-f0-9]{64}$/.test(context.challenge) ||
    !["alpaca", "discord"].includes(context.provider) ||
    !["alerts", "trade"].includes(context.purpose) ||
    !["paper", "live"].includes(context.environment) ||
    context.provider === "discord" && context.purpose !== "alerts" ||
    !["state", "grant"].includes(kind)
  ) reject();
  return encoder.encode(
    JSON.stringify([
      "sentinel-crier-oauth-v1",
      1,
      keyId,
      kind,
      context.flow_id,
      context.owner_id,
      context.challenge,
      context.provider,
      context.environment,
      context.purpose,
    ]),
  );
}
export function randomToken(): string {
  return encode(crypto.getRandomValues(new Uint8Array(32)));
}
export async function sha256(text: string): Promise<string> {
  if (typeof text !== "string") reject();
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text))),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
export class GrantCipher {
  #keys = new Map<string, Uint8Array<ArrayBuffer>>();
  #current: string;
  constructor(keys: Record<string, Uint8Array>, currentKeyId: string) {
    try {
      if (
        !keys || typeof keys !== "object" || !Object.keys(keys).length ||
        Object.keys(keys).length > 16
      ) reject();
      for (const [id, key] of Object.entries(keys)) {
        if (
          !/^[A-Za-z0-9_-]{1,64}$/.test(id) || !(key instanceof Uint8Array) ||
          key.length !== 32
        ) reject();
        this.#keys.set(id, new Uint8Array(key));
      }
      if (!this.#keys.has(currentKeyId)) reject();
      this.#current = currentKeyId;
    } catch {
      reject();
    }
  }
  async seal(
    context: FlowContext,
    kind: "state" | "grant",
    value: unknown,
  ): Promise<Envelope> {
    try {
      const additionalData = aad(context, kind, this.#current);
      const json = JSON.stringify(value, (_key, v) => {
        if (
          v === undefined || typeof v === "function" || typeof v === "symbol" ||
          typeof v === "number" && !Number.isFinite(v)
        ) reject();
        return v;
      });
      if (typeof json !== "string") reject();
      const plaintext = encoder.encode(json);
      if (plaintext.length > 65536) reject();
      const key = await crypto.subtle.importKey(
        "raw",
        this.#keys.get(this.#current)!,
        "AES-GCM",
        false,
        ["encrypt"],
      );
      const nonce = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv: nonce, additionalData, tagLength: 128 },
        key,
        plaintext,
      );
      return {
        version: 1,
        key_id: this.#current,
        nonce: encode(nonce),
        ciphertext: encode(new Uint8Array(ciphertext)),
      };
    } catch {
      reject();
    }
  }
  async open(
    context: FlowContext,
    kind: "state" | "grant",
    envelope: unknown,
  ): Promise<unknown> {
    try {
      if (
        !envelope || typeof envelope !== "object" || Array.isArray(envelope) ||
        Object.keys(envelope).sort().join(",") !==
          "ciphertext,key_id,nonce,version"
      ) reject();
      const e = envelope as Envelope;
      if (
        e.version !== 1 || typeof e.key_id !== "string" ||
        !this.#keys.has(e.key_id)
      ) reject();
      const additionalData = aad(context, kind, e.key_id);
      const nonce = decode(e.nonce, 16),
        ciphertext = decode(e.ciphertext, 87403);
      if (
        nonce.length !== 12 || ciphertext.length < 17 ||
        ciphertext.length > 65552
      ) reject();
      const key = await crypto.subtle.importKey(
        "raw",
        this.#keys.get(e.key_id)!,
        "AES-GCM",
        false,
        ["decrypt"],
      );
      return JSON.parse(
        decoder.decode(
          await crypto.subtle.decrypt(
            { name: "AES-GCM", iv: nonce, additionalData, tagLength: 128 },
            key,
            ciphertext,
          ),
        ),
      );
    } catch {
      reject();
    }
  }
}
