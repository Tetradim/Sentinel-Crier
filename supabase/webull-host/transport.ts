/** Official Webull signing algorithm. No API resource mappings are guessed here. */
import { createHash } from "node:crypto";
import type { Environment } from "./gateway.ts";
interface SignInput {
  host: string;
  path: string;
  query?: Record<string, string>;
  body?: string;
  appKey: string;
  appSecret: string;
  timestamp: string;
  nonce: string;
}
const utf8 = new TextEncoder();
export async function signWebullRequest(
  input: SignInput,
): Promise<Record<string, string>> {
  const signed: Record<string, string> = {
    host: input.host,
    "x-app-key": input.appKey,
    "x-timestamp": input.timestamp,
    "x-signature-algorithm": "HMAC-SHA1",
    "x-signature-version": "1.0",
    "x-signature-nonce": input.nonce,
  };
  for (const key of Object.keys(input.query ?? {})) {
    if (Object.hasOwn(signed, key)) throw Error("Signing header collision");
  }
  const merged = { ...input.query, ...signed },
    parameters = Object.keys(merged).sort().map((k) => k + "=" + merged[k])
      .join("&");
  const source = input.path + "&" + parameters +
    (input.body
      ? "&" +
        createHash("md5").update(input.body, "utf8").digest("hex").toUpperCase()
      : "");
  const encoded = encodeURIComponent(source).replace(
    /[!'()*]/gu,
    (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase(),
  );
  const key = await crypto.subtle.importKey(
    "raw",
    utf8.encode(input.appSecret + "&"),
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, utf8.encode(encoded));
  return {
    ...signed,
    "x-signature": btoa(String.fromCharCode(...new Uint8Array(signature))),
    "x-version": "v3",
  };
}
export interface ConnectRequest {
  path: string;
  method: "GET" | "POST";
  query?: Record<string, string>;
  body?: unknown;
  accessToken: string;
  signal?: AbortSignal;
}
export function createConnectTransport(
  options: {
    environment: Environment;
    appKey: string;
    appSecret: string;
    fetch?: typeof fetch;
  },
) {
  if (
    !["sandbox", "production"].includes(options.environment) ||
    !options.appKey || !options.appSecret
  ) throw Error("Invalid Webull transport configuration");
  const host = options.environment === "sandbox"
      ? "oauth-open-api.sandbox.webull.com"
      : "us-oauth-open-api.webull.com",
    appKey = options.appKey,
    appSecret = options.appSecret,
    fetcher = options.fetch ?? fetch;
  return async (request: ConnectRequest): Promise<unknown> => {
    if (
      !/^\/oauth-openapi\/[a-zA-Z0-9/_-]+$/u.test(request.path) ||
      request.path.includes("//") ||
      !["GET", "POST"].includes(request.method) || !request.accessToken ||
      /[\r\n]/u.test(request.accessToken) ||
      (request.method === "GET" && request.body !== undefined)
    ) throw Error("Invalid Webull request");
    const body = request.body === undefined
        ? undefined
        : JSON.stringify(request.body),
      query = { ...request.query };
    if (body && body.length > 65536) throw Error("Webull body too large");
    const headers = await signWebullRequest({
      host,
      path: request.path,
      query,
      body,
      appKey,
      appSecret,
      timestamp: new Date().toISOString().replace(/\.\d{3}Z$/u, "Z"),
      nonce: crypto.randomUUID().replaceAll("-", ""),
    });
    const url = new URL("https://" + host + request.path);
    for (const [key, value] of Object.entries(query)) {
      url.searchParams.set(key, value);
    }
    const response = await fetcher(url, {
      method: request.method,
      redirect: "error",
      headers: {
        ...headers,
        authorization: "Bearer " + request.accessToken,
        accept: "application/json",
        ...(body ? { "content-type": "application/json" } : {}),
      },
      body,
      signal: request.signal ?? AbortSignal.timeout(10000),
    });
    // Neither HTTP errors nor ambiguous network failures trigger another request.
    if (!response.ok) throw Error("Webull request failed");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 1048576) throw Error("Webull response too large");
    try {
      return JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
    } catch {
      throw Error("Invalid Webull response");
    }
  };
}
