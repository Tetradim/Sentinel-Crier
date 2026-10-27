import { signWebullRequest } from "./transport.ts";
import {
  type createTokenRequest,
  oauthApiEndpoints,
} from "../webull-connect/oauth_contract.ts";
import type { Environment } from "./gateway.ts";
export function createSignedTokenTransport(
  options: {
    environment: Environment;
    appKey: string;
    appSecret: string;
    fetch?: typeof fetch;
  },
) {
  const endpoint = oauthApiEndpoints(options.environment).token,
    url = new URL(endpoint),
    fetcher = options.fetch ?? fetch,
    { appKey, appSecret } = options;
  if (!appKey || !appSecret || /[\r\n]/u.test(appKey + appSecret)) {
    throw Error("Invalid signing configuration");
  }
  return async (
    request: ReturnType<typeof createTokenRequest>,
    signal: AbortSignal,
  ): Promise<unknown> => {
    if (
      request.endpoint !== endpoint || request.method !== "POST" ||
      request.contentType !== "application/x-www-form-urlencoded" ||
      signal.aborted
    ) throw Error("Invalid token dispatch");
    const body = request.serializeForm();
    if (body.length > 65536) throw Error("Invalid token body");
    const headers = await signWebullRequest({
      host: url.host,
      path: url.pathname,
      body,
      appKey,
      appSecret,
      timestamp: new Date().toISOString().replace(/\.\d{3}Z$/u, "Z"),
      nonce: crypto.randomUUID().replaceAll("-", ""),
    });
    const response = await fetcher(endpoint, {
      method: "POST",
      redirect: "error",
      headers: {
        ...headers,
        "content-type": request.contentType,
        accept: "application/json",
      },
      body,
      signal,
    });
    if (!response.ok || !response.body) throw Error("Token exchange failed");
    const reader = response.body.getReader(), chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 65536) throw Error("Token reply too large");
        chunks.push(value);
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    try {
      return JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
    } catch {
      throw Error("Invalid token reply");
    }
  };
}
