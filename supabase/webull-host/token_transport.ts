import { signWebullRequest } from "./transport.ts";
import {
  type createTokenRequest,
  oauthApiEndpoints,
} from "../webull-connect/oauth_contract.ts";
import type { Environment } from "./gateway.ts";
import { readBoundedJson } from "./bounded_json.ts";
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
    if (signal.aborted) throw Error("Invalid token dispatch");
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
    return await readBoundedJson(response, 65536, signal);
  };
}
