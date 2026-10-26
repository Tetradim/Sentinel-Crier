/** Server HTTP boundary. No credentials are read from a mobile client or module import. */
export type Environment = "sandbox" | "production";
export interface Order {
  client_order_id: string;
  account_id: string;
  environment: Environment;
  asset: "stock" | "option";
  symbol: string;
  quantity: number;
  limit_price: string;
  side: "buy" | "sell";
}
export interface Receipt {
  client_order_id: string;
  broker_order_id?: string;
  status:
    | "accepted"
    | "partially_filled"
    | "filled"
    | "canceled"
    | "rejected"
    | "unknown";
  filled_quantity: number;
  average_fill_price?: string;
}
export interface StoredOrder {
  owner: string;
  order: Order;
  fingerprint: string;
  receipt: Receipt;
  revision: number;
  cancel_claimed: boolean;
  cancel_pending: boolean;
  cancel_revision: number | null;
}
/** All claims and CAS updates must be atomic and durable across processes/restarts. */
export interface Ledger {
  reserve(
    owner: string,
    order: Order,
    fingerprint: string,
  ): Promise<{ created: boolean; row: StoredOrder }>;
  read(owner: string, id: string): Promise<StoredOrder | null>;
  settleCancel(
    owner: string,
    id: string,
    cancelRevision: number,
  ): Promise<void>;
  claimCancel(
    owner: string,
    id: string,
    revision: number,
  ): Promise<StoredOrder | null>;
  save(
    owner: string,
    id: string,
    revision: number,
    receipt: Receipt,
    action?: "submit" | "lookup" | "cancel",
  ): Promise<boolean>;
}
export interface Connection {
  state: "connected" | "authorization_required" | "unavailable";
  environment: Environment;
  account_id?: string;
}
/** The one approval-dependent boundary: signed official Connect resource mappings.
 * Must bind the vault token's owner/environment/identity to the selected account,
 * resolve exact stock/OCC contracts, validate responses, and never retry mutations.
 * submit MUST use SELL_TO_CLOSE for option sells and broker-enforced reduce-only
 * or atomic owned-quantity reservations for stock sells; snapshots alone cannot
 * prevent shorts. submit receives a frozen validated LIMIT/DAY intent; cancel must report observed
 * state, never convert acknowledgement into a cancellation or a fill. */
export interface Provider {
  connection(
    owner: string,
    environment: Environment,
    signal: AbortSignal,
  ): Promise<Connection>;
  begin(
    owner: string,
    environment: Environment,
    signal: AbortSignal,
  ): Promise<{ authorization_url: string; flow_id: string }>;
  position(
    owner: string,
    environment: Environment,
    account: string,
    symbol: string,
    signal: AbortSignal,
  ): Promise<{ symbol: string; quantity: number }>;
  submit(
    owner: string,
    order: Readonly<Order>,
    signal: AbortSignal,
  ): Promise<Receipt>;
  lookup(
    owner: string,
    order: Readonly<Order>,
    signal: AbortSignal,
  ): Promise<Receipt>;
  cancel(
    owner: string,
    order: Readonly<Order>,
    signal: AbortSignal,
  ): Promise<Receipt>;
}
export interface Capabilities {
  available: boolean;
  environments: Environment[];
  stocks: string[];
  options: boolean;
}
export interface GatewayOptions {
  verify(token: string): Promise<string>;
  provider: Provider;
  ledger: Ledger;
  capabilities: Capabilities;
  timeoutMs?: number;
}
class HttpError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super(code);
  }
}
function fail(status = 400, code = "invalid_request"): never {
  throw new HttpError(status, code);
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
function exact(value: unknown, keys: string[]) {
  const f = object(value);
  if (
    Object.keys(f).length !== keys.length ||
    keys.some((k) => !Object.hasOwn(f, k))
  ) fail();
  return f;
}
function text(value: unknown, max = 200): string {
  if (
    typeof value !== "string" || !value || value.length > max ||
    // deno-lint-ignore no-control-regex -- Reject controls and spaces in protocol fields.
    /[\x00-\x20\x7f]/u.test(value)
  ) fail();
  return value;
}
function uuid(value: unknown): string {
  const id = text(value, 36);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(id)
  ) fail();
  return id;
}
function clientId(value: unknown): string {
  const id = text(value, 36);
  if (!/^[a-f0-9]{32}$/u.test(id)) uuid(id);
  return id;
}
function env(value: unknown): Environment {
  if (value !== "sandbox" && value !== "production") fail();
  return value;
}
function positiveDecimal(value: unknown): string {
  const price = text(value, 24);
  if (
    !/^(?:0|[1-9]\d{0,11})(?:\.\d{1,8})?$/u.test(price) || !/[1-9]/u.test(price)
  ) fail();
  return price;
}
export function canonicalSymbol(
  value: unknown,
  asset?: "stock" | "option",
): string {
  const symbol = text(value, 21),
    stock = /^[A-Z]{1,6}(?:\.[A-Z])?$/u.test(symbol),
    option = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/u.test(symbol);
  if (
    asset === "stock"
      ? !stock
      : asset === "option"
      ? !option
      : !stock && !option
  ) fail();
  if (option) {
    const match = /([0-9]{6})[CP]([0-9]{8})$/u.exec(symbol)!;
    const date = match[1],
      year = 2000 + Number(date.slice(0, 2)),
      month = Number(date.slice(2, 4)),
      day = Number(date.slice(4));
    const check = new Date(Date.UTC(year, month - 1, day));
    if (
      check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 ||
      check.getUTCDate() !== day || Number(match[2]) === 0
    ) fail();
  }
  return symbol;
}
export function parseOrder(value: unknown): Order {
  const f = exact(value, [
    "client_order_id",
    "account_id",
    "environment",
    "asset",
    "symbol",
    "quantity",
    "limit_price",
    "side",
  ]);
  if (
    (f.asset !== "stock" && f.asset !== "option") ||
    (f.side !== "buy" && f.side !== "sell") ||
    !Number.isSafeInteger(f.quantity) || Number(f.quantity) < 1 ||
    Number(f.quantity) > 1000000
  ) fail();
  return Object.freeze({
    client_order_id: clientId(f.client_order_id),
    account_id: text(f.account_id),
    environment: env(f.environment),
    asset: f.asset,
    symbol: canonicalSymbol(f.symbol, f.asset),
    quantity: f.quantity as number,
    limit_price: positiveDecimal(f.limit_price),
    side: f.side,
  });
}
export function validateReceipt(value: unknown, order: Order): Receipt {
  const f = object(value),
    allowed = [
      "client_order_id",
      "broker_order_id",
      "status",
      "filled_quantity",
      "average_fill_price",
    ];
  if (
    Object.keys(f).some((k) => !allowed.includes(k)) ||
    f.client_order_id !== order.client_order_id ||
    ![
      "accepted",
      "partially_filled",
      "filled",
      "canceled",
      "rejected",
      "unknown",
    ].includes(String(f.status)) || !Number.isSafeInteger(f.filled_quantity) ||
    Number(f.filled_quantity) < 0 || Number(f.filled_quantity) > order.quantity
  ) fail();
  const q = Number(f.filled_quantity);
  if (
    (f.status === "filled" && q !== order.quantity) ||
    (f.status === "partially_filled" && (q === 0 || q === order.quantity)) ||
    ((f.status === "accepted" || f.status === "unknown" ||
      f.status === "rejected") && q !== 0)
  ) fail();
  return Object.freeze({
    client_order_id: order.client_order_id,
    ...(f.broker_order_id !== undefined
      ? { broker_order_id: text(f.broker_order_id) }
      : {}),
    status: f.status as Receipt["status"],
    filled_quantity: q,
    ...(f.average_fill_price !== undefined
      ? { average_fill_price: positiveDecimal(f.average_fill_price) }
      : {}),
  });
}
async function bounded<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  ms: number,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      Promise.resolve().then(() => fn(controller.signal)),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          controller.abort();
          reject(Error("operation_timeout"));
        }, ms);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
async function body(request: Request): Promise<unknown> {
  if (
    !request.headers.get("content-type")?.toLowerCase().startsWith(
      "application/json",
    )
  ) fail(415, "json_required");
  const reader = request.body?.getReader();
  if (!reader) fail();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 4096) {
        await reader.cancel();
        fail(413, "body_too_large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    fail();
  }
}
function reply(value: unknown, status = 200) {
  return Response.json(value, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}
export function createGateway(
  options: GatewayOptions,
): (r: Request) => Promise<Response> {
  const { verify, provider, ledger } = options,
    capabilities = structuredClone(options.capabilities),
    timeout = options.timeoutMs ?? 10000;
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 30000) {
    throw Error("Invalid timeout");
  }
  const checkEnvironment = (environment: Environment) => {
    if (
      !capabilities.available ||
      !capabilities.environments.includes(environment)
    ) fail(503, "webull_unavailable");
  };
  async function connection(
    owner: string,
    environment: Environment,
    account?: string,
  ) {
    checkEnvironment(environment);
    const c = await bounded(
      (s) => provider.connection(owner, environment, s),
      timeout,
    );
    if (
      c.environment !== environment ||
      !["connected", "authorization_required", "unavailable"].includes(c.state)
    ) fail(503, "webull_unavailable");
    if (account !== undefined) {
      if (c.state !== "connected") fail(409, "authorization_required");
      if (text(c.account_id) !== account) fail(403, "account_not_connected");
    }
    return {
      state: c.state,
      environment,
      ...(c.state === "connected" ? { account_id: text(c.account_id) } : {}),
    };
  }
  function supported(symbol: string, asset?: "stock" | "option") {
    const option = asset === "option" || /\d{6}[CP]\d{8}$/u.test(symbol);
    if (
      option ? !capabilities.options : !capabilities.stocks.includes(symbol)
    ) fail(400, "unsupported_contract");
  }
  async function update(
    row: StoredOrder,
    receipt: Receipt,
    action: "submit" | "lookup" | "cancel" = "submit",
  ) {
    // Read-only reconciliation can race cancellation/another reconciliation. Preserve
    // cumulative fills and terminal state; CAS prevents stale completion overwrites.
    if (
      receipt.filled_quantity < row.receipt.filled_quantity ||
      (["filled", "canceled", "rejected"].includes(row.receipt.status) &&
        receipt.status !== row.receipt.status)
    ) return row.receipt;
    if (
      row.receipt.broker_order_id && receipt.broker_order_id &&
      receipt.broker_order_id !== row.receipt.broker_order_id
    ) return row.receipt;
    if (row.receipt.broker_order_id && !receipt.broker_order_id) {
      receipt = { ...receipt, broker_order_id: row.receipt.broker_order_id };
    }
    await ledger.save(
      row.owner,
      row.order.client_order_id,
      row.revision,
      receipt,
      action,
    );
    const latest = await ledger.read(row.owner, row.order.client_order_id);
    if (!latest) fail(503, "ledger_unavailable");
    return latest.receipt;
  }
  return async (request: Request) => {
    try {
      const auth = request.headers.get("authorization");
      if (!auth || !/^Bearer [^\s]+$/u.test(auth) || auth.length > 16384) {
        fail(401, "unauthorized");
      }
      let owner: string;
      try {
        owner = text(await bounded(() => verify(auth.slice(7)), timeout));
      } catch {
        fail(401, "unauthorized");
      }
      const url = new URL(request.url), path = url.pathname;
      if (path === "/v1/capabilities" && request.method === "GET") {
        return reply(capabilities);
      }
      if (path === "/v1/connect/begin" && request.method === "POST") {
        const f = exact(await body(request), ["environment"]),
          environment = env(f.environment);
        checkEnvironment(environment);
        const started = await bounded(
          (s) => provider.begin(owner, environment, s),
          timeout,
        );
        const target = new URL(started.authorization_url),
          expected = environment === "sandbox"
            ? "/oauth2/sandbox/authenticate/login"
            : "/oauth2/authenticate/login";
        if (
          target.origin !== "https://passport.webull.com" ||
          target.pathname !== expected || target.username || target.password ||
          target.hash
        ) fail(503, "webull_unavailable");
        return reply({
          authorization_url: target.href,
          flow_id: text(started.flow_id),
        });
      }
      if (path === "/v1/connection" && request.method === "GET") {
        const environment = env(
          url.searchParams.get("environment") ?? "sandbox",
        );
        if (
          !capabilities.available ||
          !capabilities.environments.includes(environment)
        ) return reply({ state: "unavailable", environment });
        return reply(await connection(owner, environment));
      }
      if (path === "/v1/orders" && request.method === "POST") {
        const order = parseOrder(await body(request));
        supported(order.symbol, order.asset);
        await connection(owner, order.environment, order.account_id);
        const fingerprint = JSON.stringify(order);
        const existing = await ledger.read(owner, order.client_order_id);
        if (existing) {
          if (existing.fingerprint !== fingerprint) {
            fail(409, "client_order_id_conflict");
          }
          return reply(existing.receipt);
        }
        if (order.side === "sell") {
          const position = await bounded(
            (s) =>
              provider.position(
                owner,
                order.environment,
                order.account_id,
                order.symbol,
                s,
              ),
            timeout,
          );
          if (
            position.symbol !== order.symbol ||
            !Number.isSafeInteger(position.quantity) || position.quantity < 0
          ) fail(503, "invalid_broker_response");
          if (position.quantity < order.quantity) {
            fail(409, "insufficient_long_position");
          }
        }
        const claim = await ledger.reserve(owner, order, fingerprint);
        if (claim.row.fingerprint !== fingerprint) {
          fail(409, "client_order_id_conflict");
        }
        if (!claim.created) return reply(claim.row.receipt);
        let receipt = claim.row.receipt;
        try {
          receipt = validateReceipt(
            await bounded((s) => provider.submit(owner, order, s), timeout),
            order,
          );
        } catch {
          /* Reservation remains permanently non-retryable after any ambiguous dispatch. */
        }
        try {
          return reply(await update(claim.row, receipt));
        } catch {
          return reply(claim.row.receipt);
        }
      }
      const position = /^\/v1\/positions\/([^/]+)$/u.exec(path);
      if (position && request.method === "GET") {
        const environment = env(url.searchParams.get("environment")),
          account = text(url.searchParams.get("account_id")),
          symbol = canonicalSymbol(decodeURIComponent(position[1]));
        supported(symbol);
        await connection(owner, environment, account);
        const value = await bounded(
          (s) => provider.position(owner, environment, account, symbol, s),
          timeout,
        );
        if (
          value.symbol !== symbol || !Number.isSafeInteger(value.quantity) ||
          value.quantity < 0
        ) fail(503, "invalid_broker_response");
        return reply({ symbol, quantity: value.quantity });
      }
      const match = /^\/v1\/orders\/([^/]+)(\/cancel)?$/u.exec(path);
      if (
        match &&
        ((!match[2] && request.method === "GET") ||
          (match[2] && request.method === "POST"))
      ) {
        const id = clientId(match[1]),
          f = match[2]
            ? exact(await body(request), ["environment", "account_id"])
            : {
              environment: url.searchParams.get("environment"),
              account_id: url.searchParams.get("account_id"),
            };
        const environment = env(f.environment), account = text(f.account_id);
        await connection(owner, environment, account);
        let row = await ledger.read(owner, id);
        if (!row) fail(404, "order_not_found");
        if (
          row.order.environment !== environment ||
          row.order.account_id !== account
        ) fail(409, "order_scope_conflict");
        if (match[2]) {
          if (
            row.cancel_claimed ||
            ["filled", "canceled", "rejected"].includes(row.receipt.status)
          ) return reply(row.receipt);
          if (row.receipt.status === "unknown") {
            fail(409, "reconcile_before_cancel");
          }
          const claimed = await ledger.claimCancel(owner, id, row.revision);
          if (!claimed) {
            row = await ledger.read(owner, id);
            if (!row) fail(503, "ledger_unavailable");
            return reply(row.receipt);
          }
          row = claimed;
        }
        const cancelRevision = match[2] ? row.revision : null;
        try {
          const receipt = validateReceipt(
            await bounded(
              (s) =>
                match[2]
                  ? provider.cancel(owner, row!.order, s)
                  : provider.lookup(owner, row!.order, s),
              timeout,
            ),
            row.order,
          );
          return reply(
            await update(row, receipt, match[2] ? "cancel" : "lookup"),
          );
        } catch {
          return reply(row.receipt);
        } finally {
          if (cancelRevision !== null) {
            try {
              await ledger.settleCancel(owner, id, cancelRevision);
            } catch {
              /* A subsequent authoritative lookup can recover an expired cancellation lease. */
            }
          }
        }
      }
      fail(404, "not_found");
    } catch (error) {
      return error instanceof HttpError
        ? reply({ error: error.code }, error.status)
        : reply({ error: "service_unavailable" }, 503);
    }
  };
}
/** Online Supabase Auth verification; bearer payloads are never decoded for trust. */
export function createSupabaseVerifier(
  options: { url: string; publishableKey: string; fetch?: typeof fetch },
): (token: string) => Promise<string> {
  const origin = new URL(options.url);
  if (
    origin.protocol !== "https:" || origin.username || origin.password ||
    origin.search || origin.hash || origin.pathname !== "/"
  ) throw Error("Invalid Supabase origin");
  const endpoint = origin.origin + "/auth/v1/user",
    key = options.publishableKey,
    fetcher = options.fetch ?? fetch;
  if (!key || /[\r\n]/u.test(key)) throw Error("Invalid publishable key");
  return async (token) => {
    if (!token || token.length > 16384 || /\s/u.test(token)) {
      throw Error("Unauthorized");
    }
    const response = await fetcher(endpoint, {
      method: "GET",
      redirect: "error",
      headers: { apikey: key, authorization: "Bearer " + token },
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw Error("Unauthorized");
    const user = object(await response.json());
    if (user.is_anonymous === true) throw Error("Unauthorized");
    return uuid(user.id);
  };
}
