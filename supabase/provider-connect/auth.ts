/** Customer authentication only. Provider passwords and service keys never enter here. */
export class AuthRejected extends Error {
  constructor() {
    super("Customer authentication rejected");
    this.name = "AuthRejected";
  }
}

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: "bearer";
  user: { id: string };
}

export interface BrowserLoginOptions {
  /** Exact configured HTTPS function base, e.g. https://project.supabase.co/functions/v1/crier-oauth. */
  baseUrl: string;
  /** GET only: opaque launch ticket, carried in the POST body, never an arbitrary return URL. */
  nextTicket?: string;
  /** Required on POST: durable atomic claim for single-use, including simultaneous POSTs. */
  claimCsrf?: (sha256: string, expiresAt: number) => Promise<boolean>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TICKET = /^[A-Za-z0-9_-]{43}$/;
const TOKEN = /^[A-Za-z0-9._~-]{1,8192}$/;
const LOGIN_COOKIE = "__Host-crier-login";
const SESSION_COOKIE = "__Host-crier-session";
const encoder = new TextEncoder();
function reject(): never {
  throw new AuthRejected();
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) reject();
  return value as Record<string, unknown>;
}

function userId(value: unknown): string {
  const user = record(value);
  if (
    typeof user.id !== "string" || !UUID.test(user.id) ||
    user.is_anonymous !== false
  ) reject();
  return user.id.toLowerCase();
}

function token(value: unknown): string {
  if (typeof value !== "string" || !TOKEN.test(value)) reject();
  return value;
}

function session(value: unknown): Session {
  const body = record(value);
  if (
    body.token_type !== "bearer" || !Number.isInteger(body.expires_in) ||
    (body.expires_in as number) < 1 || (body.expires_in as number) > 86400
  ) reject();
  const accessToken = token(body.access_token);
  if (!/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(accessToken)) {
    reject();
  }
  return {
    access_token: accessToken,
    refresh_token: token(body.refresh_token),
    expires_in: body.expires_in as number,
    token_type: "bearer",
    user: { id: userId(body.user) },
  };
}

async function boundedText(
  response: Response | Request,
  limit: number,
): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) reject();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > limit) {
        await reader.cancel();
        reject();
      }
      chunks.push(part.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function cookie(request: Request, name: string): string {
  const raw = request.headers.get("cookie") ?? "";
  if (raw.length > 16384) reject();
  const values = raw.split(";").map((part) => part.trim()).filter((part) =>
    part.split("=", 1)[0] === name
  );
  if (values.length !== 1) reject();
  return values[0].slice(name.length + 1);
}

function credentialInput(email: string, password: string): void {
  if (
    typeof email !== "string" || email.length > 254 ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
    typeof password !== "string" || password.length < 1 ||
    password.length > 1024 || /[\r\n\0]/.test(password)
  ) reject();
}

function browserHeaders(): Headers {
  return new Headers({
    "cache-control": "no-store",
    "pragma": "no-cache",
    "content-type": "text/html; charset=utf-8",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "content-security-policy":
      "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
  });
}

function setCookie(
  headers: Headers,
  name: string,
  value: string,
  age: number,
): void {
  headers.append(
    "set-cookie",
    `${name}=${value}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=${age}`,
  );
}

export class CustomerAuth {
  private readonly projectUrl: string;
  private readonly publishableKey: string;
  private readonly fetcher: typeof fetch;

  constructor(
    options: {
      projectUrl: string;
      publishableKey: string;
      fetch?: typeof fetch;
    },
  ) {
    if (
      !/^https:\/\/[a-z]{20}\.supabase\.co$/.test(options.projectUrl) ||
      typeof options.publishableKey !== "string" ||
      !/^sb_publishable_[A-Za-z0-9_-]{1,256}$/.test(options.publishableKey)
    ) reject();
    this.projectUrl = options.projectUrl;
    this.publishableKey = options.publishableKey;
    this.fetcher = options.fetch ?? fetch;
  }

  private async call(
    path: string,
    body?: Record<string, string>,
    authorization?: string,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const headers = new Headers({ apikey: this.publishableKey });
      if (authorization) headers.set("authorization", authorization);
      if (body) headers.set("content-type", "application/json");
      const response = await this.fetcher(this.projectUrl + path, {
        method: body ? "POST" : "GET",
        headers,
        body: body ? JSON.stringify(body) : undefined,
        redirect: "error",
        signal: controller.signal,
      });
      if (!response.ok) {
        await response.body?.cancel();
        reject();
      }
      return JSON.parse(await boundedText(response, 65536));
    } catch {
      reject();
    } finally {
      clearTimeout(timeout);
    }
  }

  async owner(authorization: string): Promise<string> {
    if (
      typeof authorization !== "string" ||
      !/^Bearer [A-Za-z0-9._~-]{1,8192}$/.test(authorization)
    ) reject();
    return userId(await this.call("/auth/v1/user", undefined, authorization));
  }

  async browserOwner(request: Request): Promise<string> {
    return await this.owner("Bearer " + token(cookie(request, SESSION_COOKIE)));
  }

  async signIn(email: string, password: string): Promise<Session> {
    credentialInput(email, password);
    return session(
      await this.call("/auth/v1/token?grant_type=password", {
        email,
        password,
      }),
    );
  }

  async refresh(refreshToken: string): Promise<Session> {
    return session(
      await this.call("/auth/v1/token?grant_type=refresh_token", {
        refresh_token: token(refreshToken),
      }),
    );
  }

  async signUp(
    email: string,
    password: string,
  ): Promise<{ session: Session | null; requiresEmailConfirmation: boolean }> {
    credentialInput(email, password);
    const body = record(
      await this.call("/auth/v1/signup", { email, password }),
    );
    if (body.access_token != null) {
      return { session: session(body), requiresEmailConfirmation: false };
    }
    // Do not disclose whether the returned user is an existing account or a new registration.
    return { session: null, requiresEmailConfirmation: true };
  }

  /** Double-submit CSRF + exact Origin + mandatory durable one-use claim. Cookie is
   * cleared on POST; no refresh token is stored in cookies. */
  async browserLogin(
    request: Request,
    options: BrowserLoginOptions,
  ): Promise<Response> {
    const headers = browserHeaders();
    try {
      const base = new URL(options.baseUrl);
      if (
        base.protocol !== "https:" || base.username || base.password ||
        base.search || base.hash ||
        options.baseUrl !== base.origin + base.pathname ||
        base.pathname !== "/functions/v1/crier-oauth"
      ) reject();
      const url = new URL(request.url);
      if (
        url.origin !== base.origin ||
        url.pathname !== base.pathname + "/auth/browser"
      ) reject();
      if (request.method === "GET") {
        const ticket = options.nextTicket;
        if (ticket !== undefined && !TICKET.test(ticket)) reject();
        const bytes = crypto.getRandomValues(new Uint8Array(32));
        const nonce = btoa(String.fromCharCode(...bytes)).replaceAll("+", "-")
          .replaceAll("/", "_").replaceAll("=", "");
        const csrf = `${nonce}.${Math.floor(Date.now() / 1000) + 300}`;
        setCookie(headers, LOGIN_COOKIE, csrf, 300);
        return new Response(
          `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Crier customer sign in</title><main><h1>Crier customer sign in</h1><p>Use your Crier customer account. Do not enter a brokerage password.</p><form method="post" action="${base.pathname}/auth/browser"><input type="hidden" name="csrf" value="${csrf}"><input type="hidden" name="ticket" value="${
            ticket ?? ""
          }"><p><label>Email <input name="email" type="email" autocomplete="username" maxlength="254" required></label></p><p><label>Password <input name="password" type="password" autocomplete="current-password" maxlength="1024" required></label></p><button type="submit">Sign in</button></form></main></html>`,
          { headers },
        );
      }
      if (request.method !== "POST") {
        return new Response("Method not allowed", { status: 405, headers });
      }
      setCookie(headers, LOGIN_COOKIE, "", 0);
      if (
        url.search || request.headers.get("origin") !== base.origin ||
        request.headers.get("content-type")?.split(";", 1)[0].trim() !==
          "application/x-www-form-urlencoded"
      ) reject();
      const form = new URLSearchParams(await boundedText(request, 8192));
      if (
        [...form.keys()].some((key) =>
          !["csrf", "ticket", "email", "password"].includes(key)
        ) ||
        ["csrf", "ticket", "email", "password"].some((key) =>
          form.getAll(key).length !== 1
        )
      ) reject();
      const csrf = form.get("csrf")!;
      const match = /^([A-Za-z0-9_-]{43})\.([0-9]{10})$/.exec(csrf);
      const now = Math.floor(Date.now() / 1000);
      if (
        !match || csrf !== cookie(request, LOGIN_COOKIE) || +match[2] <= now ||
        +match[2] > now + 300
      ) reject();
      if (!options.claimCsrf) reject();
      {
        const hash = [
          ...new Uint8Array(
            await crypto.subtle.digest("SHA-256", encoder.encode(csrf)),
          ),
        ].map((n) => n.toString(16).padStart(2, "0")).join("");
        if (!await options.claimCsrf(hash, +match[2])) reject();
      }
      const ticket = form.get("ticket")!;
      if (!TICKET.test(ticket)) reject();
      const signedIn = await this.signIn(
        form.get("email")!,
        form.get("password")!,
      );
      setCookie(
        headers,
        SESSION_COOKIE,
        signedIn.access_token,
        Math.min(3600, signedIn.expires_in),
      );
      headers.set(
        "location",
        options.baseUrl + "/oauth/browser?ticket=" + ticket,
      );
      return new Response(null, { status: 303, headers });
    } catch {
      return new Response(
        "Customer sign in could not be completed. Please start again.",
        { status: 401, headers },
      );
    }
  }
}
