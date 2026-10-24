/** Pure server-side contract groundwork. No dispatch, persistence, or browser entry selection. */
export type OAuthEnvironment = "sandbox" | "production";

function invalid(): never {
  // Never attach received bodies, credentials, or validation values to errors.
  throw new Error("Invalid Webull OAuth contract");
}
function text(value: unknown): string {
  if (
    typeof value !== "string" || !value.trim() ||
    // deno-lint-ignore no-control-regex -- reject C0, DEL, and C1 controls intentionally.
    /[\u0000-\u001f\u007f-\u009f]/u.test(value)
  ) invalid();
  return value;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function exactKeys(value: Record<string, unknown>, keys: string[]): void {
  if (
    Reflect.ownKeys(value).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(value, key))
  ) invalid();
}

/** These API URLs are distinct from the approval-dependent browser login entry. */
export function oauthApiEndpoints(
  environment: OAuthEnvironment,
): Readonly<{ token: string; authorizationCode: string }> {
  let host: string;
  if (environment === "sandbox") {
    host = "https://oauth-open-api.sandbox.webull.com";
  } else if (environment === "production") {
    host = "https://us-oauth-open-api.webull.com";
  } else invalid();
  return Object.freeze({
    token: `${host}/oauth2/tokens/create`,
    authorizationCode: `${host}/oauth2/auth-codes/get`,
  });
}

/** Structural server callback policy; future configuration must pin the exact registered URI. */
function serverCallback(value: unknown): string {
  const source = text(value);
  if (source.length > 2048 || /[\s\\?#\uD800-\uDFFF]/u.test(source)) invalid();
  const authority = /^https:\/\/([^/?#]+)(?:\/|$)/iu.exec(source)?.[1];
  if (!authority || authority.includes("@")) invalid();
  try {
    const url = new URL(source);
    if (
      url.protocol !== "https:" || !url.hostname || url.username ||
      url.password || url.search || url.hash
    ) invalid();
  } catch {
    invalid();
  }
  return source;
}
export interface AuthorizationInput {
  client_id: string;
  scope: string;
  state: string;
  redirect_uri: string;
}
/** Parameters only: callers must separately establish the approved browser entry. */
export function buildAuthorizationParameters(
  input: AuthorizationInput,
): URLSearchParams {
  const fields = record(input);
  exactKeys(fields, ["client_id", "scope", "state", "redirect_uri"]);
  const params = new URLSearchParams({ response_type: "code" });
  for (const key of ["client_id", "scope", "state", "redirect_uri"]) {
    params.set(
      key,
      key === "redirect_uri" ? serverCallback(fields[key]) : text(fields[key]),
    );
  }
  return params;
}

type Credentials = { client_id: string; client_secret: string };
export type TokenGrantInput =
  & Credentials
  & (
    | { grant_type: "authorization_code"; code: string; refresh_token?: never }
    | { grant_type: "refresh_token"; refresh_token: string; code?: never }
  );

const inspectDeno = Symbol.for("Deno.customInspect");
const inspectNode = Symbol.for("nodejs.util.inspect.custom");

/** Secrets are exposed only by the explicit form serialization method. */
class TokenRequest {
  #form: string;
  readonly endpoint: string;
  readonly method = "POST";
  readonly contentType = "application/x-www-form-urlencoded";
  constructor(endpoint: string, form: string) {
    this.endpoint = endpoint;
    this.#form = form;
    Object.freeze(this);
  }
  serializeForm(): string {
    return this.#form;
  }
  toJSON(): string {
    return "WebullTokenRequest [REDACTED]";
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

export function createTokenRequest(
  environment: OAuthEnvironment,
  input: TokenGrantInput,
): TokenRequest {
  const endpoint = oauthApiEndpoints(environment).token;
  const fields = record(input);
  const grant = fields.grant_type;
  if (grant !== "authorization_code" && grant !== "refresh_token") invalid();
  const grantKey = grant === "authorization_code" ? "code" : "refresh_token";
  exactKeys(fields, ["client_id", "client_secret", "grant_type", grantKey]);
  const form = new URLSearchParams();
  for (const key of ["client_id", "client_secret", "grant_type", grantKey]) {
    form.set(key, text(fields[key]));
  }
  return new TokenRequest(endpoint, form.toString());
}

function seconds(value: unknown): number {
  if (typeof value !== "string" || !/^[0-9]+$/u.test(value)) invalid();
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) invalid();
  return parsed;
}
const DATE_LIMIT = 8_640_000_000_000_000;
/** Crier local clock policy, not a guarantee about Webull issuance clocks. */
export const MAX_ISSUANCE_CLOCK_SKEW_MS = 30_000;
function timestamp(value: unknown): number {
  const source = text(value);
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|[+-]\d{2}:?\d{2})$/u
      .exec(source);
  if (!match) invalid();
  const [, y, m, d, h, min, sec, , zone] = match;
  const year = Number(y), month = Number(m), day = Number(d);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    month < 1 || month > 12 || day < 1 || day > days[month - 1] ||
    Number(h) > 23 || Number(min) > 59 || Number(sec) > 59
  ) invalid();
  if (zone !== "Z") {
    const compact = zone.replace(":", "");
    const hours = Number(compact.slice(1, 3)),
      minutes = Number(compact.slice(3));
    if (hours > 14 || minutes > 59 || (hours === 14 && minutes !== 0)) {
      invalid();
    }
  }
  const normalized = source.replace(/([+-]\d{2})(\d{2})$/u, "$1:$2");
  const result = Date.parse(normalized);
  if (!Number.isSafeInteger(result) || Math.abs(result) > DATE_LIMIT) invalid();
  return result;
}
function deadline(issued: number, lifetime: number, now: number): number {
  const ms = lifetime * 1000;
  const result = issued + ms;
  if (
    !Number.isSafeInteger(ms) || !Number.isSafeInteger(result) ||
    Math.abs(result) > DATE_LIMIT || result <= now
  ) invalid();
  return result;
}

/** Tokens and identity remain private even during default object inspection. */
class TokenResponse {
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
  toJSON(): string {
    return "WebullTokenResponse [REDACTED]";
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

export interface TokenResponseOptions {
  /** Injected receipt clock in epoch milliseconds; expiry is always based on created_at. */
  nowMs: number;
  /** Supply the previously bound identity when validating a refresh response. */
  expectedIdentity?: string;
}
export function parseTokenResponse(
  body: unknown,
  options: TokenResponseOptions,
): TokenResponse {
  const fields = record(body);
  const config = record(options);
  const prototype = Object.getPrototypeOf(config);
  if (prototype !== null && prototype !== Object.prototype) invalid();
  exactKeys(
    config,
    Object.hasOwn(config, "expectedIdentity")
      ? ["nowMs", "expectedIdentity"]
      : ["nowMs"],
  );
  const now = config.nowMs;
  if (
    typeof now !== "number" || !Number.isSafeInteger(now) ||
    Math.abs(now) > DATE_LIMIT
  ) invalid();
  const access = text(fields.access_token),
    refresh = text(fields.refresh_token),
    identity = text(fields.identity_id);
  if (fields.token_type !== "Bearer") invalid();
  if (
    Object.hasOwn(config, "expectedIdentity") &&
    text(config.expectedIdentity) !== identity
  ) invalid();
  const issued = timestamp(fields.created_at);
  if (issued - now > MAX_ISSUANCE_CLOCK_SKEW_MS) invalid();
  return new TokenResponse(
    access,
    refresh,
    identity,
    deadline(issued, seconds(fields.expires_in), now),
    deadline(issued, seconds(fields.rt_expires_in), now),
  );
}
