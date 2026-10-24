/** Server-only pending OAuth state. No cookies, credentials, storage or HTTP. */
const tokenPattern = /^[A-Za-z0-9_-]{43}$/u;

export async function hashSessionToken(token: string): Promise<string> {
  if (typeof token !== "string" || !tokenPattern.test(token)) {
    throw new Error("Invalid Webull session token");
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(token),
  );
  return Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll(
    "/",
    "_",
  ).replace(/=+$/u, "");
}

class SessionMaterial {
  #state: string;
  #binding: string;
  readonly stateHash: string;
  readonly bindingHash: string;

  constructor(
    state: string,
    binding: string,
    stateHash: string,
    bindingHash: string,
  ) {
    this.#state = state;
    this.#binding = binding;
    this.stateHash = stateHash;
    this.bindingHash = bindingHash;
    Object.freeze(this);
  }
  state(): string {
    return this.#state;
  }
  browserBinding(): string {
    return this.#binding;
  }
  toJSON(): string {
    return "WebullSessionMaterial [REDACTED]";
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

/** Raw values are used only for Webull state and a server HttpOnly cookie.
 * Persist only the hashes, bound to verified owner/environment/callback in SQL.
 * This factory is not customer authentication or a cookie/redirect handler.
 */
export async function createSessionMaterial(): Promise<SessionMaterial> {
  const state = randomToken(), binding = randomToken();
  const [stateHash, bindingHash] = await Promise.all([
    hashSessionToken(state),
    hashSessionToken(binding),
  ]);
  return new SessionMaterial(state, binding, stateHash, bindingHash);
}
