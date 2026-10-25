import { createHandler } from "../../provider-connect/gateway.ts";

// This is a separate credential boundary. Nothing here changes relay tokens or
// provisions real provider applications, encryption keys, or database schemas.
function configuredHandler(): (request: Request) => Promise<Response> {
  const encoded = Deno.env.get("CRIER_OAUTH_ENCRYPTION_KEY") ?? "";
  if (!/^[A-Za-z0-9_-]{43}$/.test(encoded)) throw new Error("Unavailable");
  const key = Uint8Array.from(
    atob(encoded.replaceAll("-", "+").replaceAll("_", "/") + "="),
    (c) => c.charCodeAt(0),
  );
  const canonical = btoa(String.fromCharCode(...key)).replaceAll("+", "-")
    .replaceAll("/", "_").replaceAll("=", "");
  if (key.length !== 32 || canonical !== encoded) {
    throw new Error("Unavailable");
  }
  const applications = (["alpaca", "discord"] as const).flatMap((provider) => {
    const name = provider.toUpperCase();
    const clientId = Deno.env.get(`CRIER_${name}_CLIENT_ID`) ?? "";
    const clientSecret = Deno.env.get(`CRIER_${name}_CLIENT_SECRET`) ?? "";
    if (!clientId && !clientSecret) return [];
    return [{ provider, clientId, clientSecret }];
  });
  return createHandler({
    projectUrl: Deno.env.get("SUPABASE_URL") ?? "",
    publishableKey: Deno.env.get("CRIER_AUTH_PUBLISHABLE_KEY") ?? "",
    serviceKey: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    encryptionKey: key,
    keyId: Deno.env.get("CRIER_OAUTH_KEY_ID") ?? "primary",
    applications,
  });
}
let handler: (request: Request) => Promise<Response>;
try {
  handler = configuredHandler();
} catch {
  handler = () =>
    Promise.resolve(
      Response.json({
        detail:
          "Provider connections unavailable. Operator configuration required.",
      }, {
        status: 503,
        headers: {
          "Cache-Control": "no-store",
          "Referrer-Policy": "no-referrer",
        },
      }),
    );
}
Deno.serve(handler);
