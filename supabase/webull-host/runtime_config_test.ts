import { runtimeOptions } from "./runtime_config.ts";
const baseline: Record<string, string> = {
  SUPABASE_URL: "https://abcdefghijklmnopqrst.supabase.co",
  SUPABASE_SERVICE_ROLE_KEY: "server",
  SUPABASE_ANON_KEY: "public",
};
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw Error("Unexpected value");
}
Deno.test("runtime remains authorization-disabled without explicit provider approval", () => {
  const options = runtimeOptions((name) => baseline[name]);
  eq(options.authorization, undefined);
});
Deno.test("approved runtime requires explicit environment and all protected configuration", () => {
  let failure = "";
  try {
    runtimeOptions((name) =>
      ({ ...baseline, CRIER_WEBULL_INTEGRATION_APPROVED: "true" })[name]
    );
  } catch (error) {
    failure = String(error);
  }
  if (!failure.includes("CRIER_WEBULL_ENVIRONMENT")) {
    throw Error("Missing explicit source environment check");
  }
});
Deno.test("malformed approval flag cannot silently activate or hide bad configuration", () => {
  let failed = false;
  try {
    runtimeOptions((name) =>
      name === "CRIER_WEBULL_INTEGRATION_APPROVED" ? "TRUE" : baseline[name]
    );
  } catch {
    failed = true;
  }
  eq(failed, true);
});
