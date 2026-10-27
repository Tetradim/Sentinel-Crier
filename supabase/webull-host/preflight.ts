/** Operator check: prints configuration state, never secret values. No network. */
import { createApplication } from "./application.ts";
import { runtimeOptions } from "./runtime_config.ts";
export async function preflight(read: (name: string) => string | undefined) {
  try {
    const options = runtimeOptions(read);
    await createApplication(options);
    return {
      valid: true,
      authorization_enabled: Boolean(options.authorization),
      environment: options.authorization?.environment ?? null,
      callback_url: options.projectUrl.replace(/\/$/u, "") +
        "/functions/v1/crier-webull-host/v1/connect/callback",
      trading_adapter_installed: false,
      broker_acceptance_verified: false,
    };
  } catch {
    return {
      valid: false,
      error:
        "Protected configuration is missing or invalid. No secret values were emitted.",
    };
  }
}
if (import.meta.main) {
  const result = await preflight((name) => Deno.env.get(name));
  console.log(JSON.stringify(result, null, 2));
  if (!result.valid) Deno.exit(1);
}
