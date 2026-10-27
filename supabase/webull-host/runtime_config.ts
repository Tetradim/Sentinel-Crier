import type { ApplicationOptions } from "./application.ts";
/** Reads protected server configuration only. Returned values must never be logged. */
export function runtimeOptions(
  read: (name: string) => string | undefined,
): ApplicationOptions {
  const required = (name: string) => {
    const value = read(name);
    if (
      !value || value.length > 32768 ||
      value.includes(String.fromCharCode(0)) || /[\r\n]/u.test(value)
    ) {
      throw Error("Missing or invalid " + name);
    }
    return value;
  };
  const options: ApplicationOptions = {
    projectUrl: required("SUPABASE_URL"),
    publishableKey: read("CRIER_AUTH_PUBLISHABLE_KEY") ||
      required("SUPABASE_ANON_KEY"),
    serviceRoleKey: required("SUPABASE_SERVICE_ROLE_KEY"),
  };
  const approval = read("CRIER_WEBULL_INTEGRATION_APPROVED") ?? "false";
  if (!["true", "false"].includes(approval)) {
    throw Error("Invalid CRIER_WEBULL_INTEGRATION_APPROVED");
  }
  if (approval === "false") return options;
  const environment = required("CRIER_WEBULL_ENVIRONMENT");
  if (environment !== "sandbox" && environment !== "production") {
    throw Error("Invalid CRIER_WEBULL_ENVIRONMENT");
  }
  options.authorization = {
    environment,
    approved: true,
    clientId: required("CRIER_WEBULL_CLIENT_ID"),
    clientSecret: required("CRIER_WEBULL_CLIENT_SECRET"),
    scope: required("CRIER_WEBULL_SCOPE"),
    appKey: required("CRIER_WEBULL_APP_KEY"),
    appSecret: required("CRIER_WEBULL_APP_SECRET"),
    vaultKey: required("CRIER_WEBULL_VAULT_KEY"),
    keyId: required("CRIER_WEBULL_VAULT_KEY_ID"),
  };
  const previous = read("CRIER_WEBULL_PREVIOUS_VAULT_KEYS");
  if (previous) {
    try {
      const keys = JSON.parse(previous);
      if (
        !keys || typeof keys !== "object" || Array.isArray(keys) ||
        Object.keys(keys).length > 8
      ) throw Error();
      options.authorization.previousVaultKeys = keys;
    } catch {
      throw Error("Invalid CRIER_WEBULL_PREVIOUS_VAULT_KEYS");
    }
  }
  return options;
}
