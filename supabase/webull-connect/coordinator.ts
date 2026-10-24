/** Server-only composition. All authentication, signing and persistence are trusted ports.
 * No HTTP handlers, cookies, broker network calls or live approval are supplied here. */
import {
  buildAuthorizationParameters,
  createTokenRequest,
  type OAuthEnvironment,
} from "./oauth_contract.ts";
import { createSessionMaterial, hashSessionToken } from "./session_material.ts";
import {
  type createTokenVault,
  type EncryptedEnvelope,
} from "./token_vault.ts";

export type TokenState =
  | "authorization_pending"
  | "active"
  | "refresh_pending"
  | "unknown"
  | "revoked";
export interface CoordinatorStore {
  begin(
    owner: string,
    environment: OAuthEnvironment,
    expectedGeneration: number,
    operationId: string,
    stateHash: string,
    bindingHash: string,
    callback: string,
  ): Promise<
    { generation: number; operationId: string; expiresAtMs: number } | null
  >;
  consume(
    owner: string,
    environment: OAuthEnvironment,
    stateHash: string,
    bindingHash: string,
    callback: string,
  ): Promise<{ generation: number; operationId: string } | null>;
  read(
    owner: string,
    environment: OAuthEnvironment,
  ): Promise<
    {
      state: TokenState;
      generation: number;
      envelope: EncryptedEnvelope | null;
    } | null
  >;
  commit(
    owner: string,
    environment: OAuthEnvironment,
    generation: number,
    operationId: string,
    envelope: EncryptedEnvelope,
  ): Promise<boolean>;
  claimRefresh(
    owner: string,
    environment: OAuthEnvironment,
    expectedGeneration: number,
    operationId: string,
  ): Promise<
    {
      priorGeneration: number;
      newGeneration: number;
      envelope: EncryptedEnvelope;
    } | null
  >;
  markUnknown(
    owner: string,
    environment: OAuthEnvironment,
    generation: number,
    operationId: string,
  ): Promise<boolean>;
  revoke(owner: string, environment: OAuthEnvironment): Promise<number>;
}
export interface CoordinatorConfig {
  environment: OAuthEnvironment;
  clientId: string;
  clientSecret: string;
  scope: string;
  callback: string;
  approvedBrowserEntry: string;
  /** Explicit caller approval; synthetic fixtures do not establish vendor acceptance. */
  integrationApproved: boolean;
  signingReady: boolean;
}
export interface CoordinatorOptions {
  config: CoordinatorConfig;
  verifyPrincipal(input: unknown): Promise<string>;
  store: CoordinatorStore;
  vault: ReturnType<typeof createTokenVault>;
  /** Trusted dispatcher must sign the request and must not retry rotating grants. */
  transport(
    request: ReturnType<typeof createTokenRequest>,
    signal: AbortSignal,
  ): Promise<unknown>;
  nowMs?: () => number;
  timeoutMs?: number;
}
export interface CallbackInput {
  state: string;
  browserBinding: string;
  code: string;
}
export interface CoordinatorStatus {
  state: TokenState | "unlinked";
  generation: number;
  accessExpiresAtMs?: number;
  refreshExpiresAtMs?: number;
}
function invalid(): never {
  throw new Error("Invalid Webull coordinator operation");
}
function text(value: unknown, max: number): string {
  if (
    typeof value !== "string" || !value.trim() || value.length > max ||
    // deno-lint-ignore no-control-regex -- reject C0, DEL and C1 controls.
    /[\u0000-\u001f\u007f-\u009f]/u.test(value)
  ) invalid();
  return value;
}
function snapshot(value: unknown): Record<string, unknown> {
  if (
    !value || typeof value !== "object" ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  ) invalid();
  const keys = Reflect.ownKeys(value);
  if (keys.length > 32) invalid();
  const result: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    if (typeof key !== "string" || key.length > 200) invalid();
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !Object.hasOwn(d, "value")) invalid();
    result[key] = d.value;
  }
  return result;
}
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  const f = snapshot(value);
  if (
    Object.keys(f).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(f, key))
  ) invalid();
  return f;
}
function generation(value: unknown, allowZero = false): number {
  if (
    typeof value !== "number" || !Number.isSafeInteger(value) ||
    value < (allowZero ? 0 : 1)
  ) invalid();
  return value;
}
function operation(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(
      value,
    )
  ) invalid();
  return value;
}
function clock(value: unknown): number {
  if (
    typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 ||
    value > 8_640_000_000_000_000
  ) invalid();
  return value;
}
function boundedReply(value: unknown): Record<string, unknown> {
  const f = snapshot(value);
  let length = 0;
  for (const [key, v] of Object.entries(f)) {
    if (
      typeof v !== "string" && typeof v !== "number" &&
      typeof v !== "boolean" && v !== null
    ) invalid();
    if (typeof v === "string" && v.length > 32768) invalid();
    length += key.length + String(v).length;
    if (length > 65536) invalid();
  }
  return f;
}
class Authorization {
  #url: string;
  #binding: string;
  readonly generation: number;
  readonly expiresAtMs: number;
  constructor(
    url: string,
    binding: string,
    generation: number,
    expiresAtMs: number,
  ) {
    this.#url = url;
    this.#binding = binding;
    this.generation = generation;
    this.expiresAtMs = expiresAtMs;
    Object.freeze(this);
  }
  url(): string {
    return this.#url;
  }
  /** Future server handler must deliver this only in a Secure HttpOnly cookie. */
  browserBinding(): string {
    return this.#binding;
  }
  toJSON(): string {
    return "WebullAuthorization [REDACTED]";
  }
  toString(): string {
    return this.toJSON();
  }
  [Symbol.for("Deno.customInspect")](): string {
    return this.toJSON();
  }
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toJSON();
  }
}
class Coordinator {
  #options: CoordinatorOptions;
  #config: CoordinatorConfig;
  #timeout: number;
  constructor(options: CoordinatorOptions) {
    const f = snapshot(options);
    const permitted = [
      "config",
      "verifyPrincipal",
      "store",
      "vault",
      "transport",
      "nowMs",
      "timeoutMs",
    ];
    if (Object.keys(f).some((key) => !permitted.includes(key))) invalid();
    const c = exact(f.config, [
      "environment",
      "clientId",
      "clientSecret",
      "scope",
      "callback",
      "approvedBrowserEntry",
      "integrationApproved",
      "signingReady",
    ]);
    if (
      c.integrationApproved !== true || c.signingReady !== true ||
      (c.environment !== "sandbox" && c.environment !== "production")
    ) invalid();
    const entry = c.environment === "sandbox"
      ? "https://passport.webull.com/oauth2/sandbox/authenticate/login"
      : "https://passport.webull.com/oauth2/authenticate/login";
    if (c.approvedBrowserEntry !== entry) invalid();
    for (const key of ["clientId", "clientSecret", "scope"]) {
      text(c[key], 32768);
    }
    buildAuthorizationParameters({
      client_id: c.clientId as string,
      scope: c.scope as string,
      state: "configuration-check",
      redirect_uri: c.callback as string,
    });
    if (
      typeof f.verifyPrincipal !== "function" ||
      typeof f.transport !== "function" ||
      (f.nowMs !== undefined && typeof f.nowMs !== "function")
    ) invalid();
    for (
      const [port, methods] of [[f.store, [
        "begin",
        "consume",
        "read",
        "commit",
        "claimRefresh",
        "markUnknown",
        "revoke",
      ]], [f.vault, ["open", "sealReply"]]] as const
    ) {
      if (
        !port ||
        methods.some((method) =>
          typeof (port as Record<string, unknown>)[method] !== "function"
        )
      ) invalid();
    }
    const timeout = f.timeoutMs ?? 10000;
    if (
      typeof timeout !== "number" || !Number.isInteger(timeout) ||
      timeout < 1 || timeout > 30000
    ) invalid();
    this.#timeout = timeout;
    this.#config = Object.freeze({ ...c }) as unknown as CoordinatorConfig;
    this.#options = Object.freeze({ ...options });
    Object.freeze(this);
  }
  #now(): number {
    return clock((this.#options.nowMs ?? Date.now)());
  }
  async #owner(input: unknown): Promise<string> {
    return text(await this.#options.verifyPrincipal(input), 200);
  }
  async #guard<T>(action: () => Promise<T>): Promise<T> {
    try {
      return await action();
    } catch {
      invalid();
    }
  }
  async #unknown(owner: string, g: number, op: string): Promise<void> {
    try {
      await this.#options.store.markUnknown(
        owner,
        this.#config.environment,
        g,
        op,
      );
    } catch { /* Failed cleanup cannot make an uncertain grant retryable. */ }
  }
  async #dispatch(
    request: ReturnType<typeof createTokenRequest>,
  ): Promise<{ reply: unknown; receipt: number }> {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const timeout = new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => {
          abort.abort();
          reject(new Error("timeout"));
        }, this.#timeout);
      });
      const reply = await Promise.race([
        Promise.resolve().then(() =>
          this.#options.transport(request, abort.signal)
        ),
        timeout,
      ]);
      return { reply: boundedReply(reply), receipt: this.#now() };
    } finally {
      clearTimeout(timer);
    }
  }
  async #read(owner: string) {
    const row = await this.#options.store.read(owner, this.#config.environment);
    if (row) {
      generation(row.generation);
      if (
        ![
          "active",
          "authorization_pending",
          "refresh_pending",
          "unknown",
          "revoked",
        ].includes(row.state)
      ) invalid();
    }
    return row;
  }
  async begin(authInput: unknown): Promise<Authorization> {
    return await this.#guard(async () => {
      const owner = await this.#owner(authInput), c = this.#config;
      const current = await this.#read(owner),
        expected = current?.generation ?? 0;
      const material = await createSessionMaterial(), op = crypto.randomUUID();
      const reserved = await this.#options.store.begin(
        owner,
        c.environment,
        expected,
        op,
        material.stateHash,
        material.bindingHash,
        c.callback,
      );
      if (
        !reserved || generation(reserved.generation) !== expected + 1 ||
        operation(reserved.operationId) !== op ||
        clock(reserved.expiresAtMs) <= this.#now()
      ) invalid();
      const params = buildAuthorizationParameters({
        client_id: c.clientId,
        scope: c.scope,
        state: material.state(),
        redirect_uri: c.callback,
      });
      return new Authorization(
        `${c.approvedBrowserEntry}?${params}`,
        material.browserBinding(),
        reserved.generation,
        reserved.expiresAtMs,
      );
    });
  }
  async callback(
    authInput: unknown,
    input: CallbackInput,
  ): Promise<CoordinatorStatus> {
    return await this.#guard(async () => {
      const owner = await this.#owner(authInput), c = this.#config;
      const f = exact(input, ["state", "browserBinding", "code"]),
        code = text(f.code, 32768);
      const stateHash = await hashSessionToken(f.state as string),
        bindingHash = await hashSessionToken(f.browserBinding as string);
      const reserved = await this.#options.store.consume(
        owner,
        c.environment,
        stateHash,
        bindingHash,
        c.callback,
      );
      if (!reserved) invalid();
      const g = generation(reserved.generation),
        op = operation(reserved.operationId);
      try {
        const { reply, receipt } = await this.#dispatch(
          createTokenRequest(c.environment, {
            client_id: c.clientId,
            client_secret: c.clientSecret,
            grant_type: "authorization_code",
            code,
          }),
        );
        const envelope = await this.#options.vault.sealReply(
          { ownerRef: owner, environment: c.environment, generation: g },
          reply,
          { nowMs: receipt },
        );
        if (
          await this.#options.store.commit(
            owner,
            c.environment,
            g,
            op,
            envelope,
          ) !== true
        ) invalid();
        return this.#active(g, envelope);
      } catch {
        await this.#unknown(owner, g, op);
        invalid();
      }
    });
  }
  #active(g: number, e: EncryptedEnvelope): CoordinatorStatus {
    return Object.freeze({
      state: "active",
      generation: g,
      accessExpiresAtMs: clock(e.access_expires_at_ms),
      refreshExpiresAtMs: clock(e.refresh_expires_at_ms),
    });
  }
  async refresh(authInput: unknown): Promise<CoordinatorStatus> {
    return await this.#guard(async () => {
      const owner = await this.#owner(authInput),
        c = this.#config,
        current = await this.#read(owner);
      if (!current || current.state !== "active") invalid();
      const op = crypto.randomUUID();
      const claim = await this.#options.store.claimRefresh(
        owner,
        c.environment,
        current.generation,
        op,
      );
      if (
        !claim || generation(claim.priorGeneration) !== current.generation ||
        generation(claim.newGeneration) !== current.generation + 1
      ) invalid();
      const g = claim.newGeneration;
      try {
        const old = await this.#options.vault.open(
          {
            ownerRef: owner,
            environment: c.environment,
            generation: claim.priorGeneration,
          },
          claim.envelope,
          this.#now(),
        );
        const { reply, receipt } = await this.#dispatch(
          createTokenRequest(c.environment, {
            client_id: c.clientId,
            client_secret: c.clientSecret,
            grant_type: "refresh_token",
            refresh_token: old.refreshToken(),
          }),
        );
        const envelope = await this.#options.vault.sealReply(
          { ownerRef: owner, environment: c.environment, generation: g },
          reply,
          { nowMs: receipt, expectedIdentity: old.identityId() },
        );
        if (
          await this.#options.store.commit(
            owner,
            c.environment,
            g,
            op,
            envelope,
          ) !== true
        ) invalid();
        return this.#active(g, envelope);
      } catch {
        await this.#unknown(owner, g, op);
        invalid();
      }
    });
  }
  async status(authInput: unknown): Promise<CoordinatorStatus> {
    return await this.#guard(async () => {
      const row = await this.#read(await this.#owner(authInput));
      if (!row) return Object.freeze({ state: "unlinked", generation: 0 });
      if (row.state === "active") {
        if (!row.envelope) invalid();
        return this.#active(row.generation, row.envelope);
      }
      return Object.freeze({ state: row.state, generation: row.generation });
    });
  }
  async revoke(authInput: unknown): Promise<CoordinatorStatus> {
    return await this.#guard(async () =>
      Object.freeze({
        state: "revoked",
        generation: generation(
          await this.#options.store.revoke(
            await this.#owner(authInput),
            this.#config.environment,
          ),
        ),
      })
    );
  }
  toJSON(): string {
    return "WebullCoordinator [REDACTED]";
  }
  toString(): string {
    return this.toJSON();
  }
  [Symbol.for("Deno.customInspect")](): string {
    return this.toJSON();
  }
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toJSON();
  }
}
export function createCoordinator(options: CoordinatorOptions): Coordinator {
  try {
    return new Coordinator(options);
  } catch {
    invalid();
  }
}
