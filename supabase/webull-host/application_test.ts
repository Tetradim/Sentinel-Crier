// deno-lint-ignore-file require-await -- asynchronous HTTP test doubles.
import { createApplication } from "./application.ts";
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw Error("Unexpected result");
}
const owner = "b013cf27-fbab-4425-9c6c-6c3236766514";
Deno.test("deployable application strips only exact known prefix and defaults to disabled trading", async () => {
  let auth = 0;
  const app = await createApplication({
    projectUrl: "https://abcdefghijklmnopqrst.supabase.co",
    publishableKey: "public",
    serviceRoleKey: "server",
    fetch: async (url) => {
      if (String(url).endsWith("/auth/v1/user")) {
        auth++;
        return Response.json({ id: owner, is_anonymous: false });
      }
      throw Error("Unexpected request");
    },
  });
  const response = await app(
    new Request(
      "https://internal/functions/v1/crier-webull-host/v1/capabilities",
      { headers: { authorization: "Bearer customer" } },
    ),
  );
  eq(response.status, 200);
  const value = await response.json();
  eq(value.available, false);
  eq(value.authorization_available, false);
  eq(auth, 1);
  eq(
    (await app(
      new Request(
        "https://internal/functions/v1/crier-webull-host-evil/v1/capabilities",
        { headers: { authorization: "Bearer customer" } },
      ),
    )).status,
    404,
  );
});
Deno.test("invalid approval configuration fails construction without returning any credentials", async () => {
  let failed = false;
  try {
    await createApplication({
      projectUrl: "https://abcdefghijklmnopqrst.supabase.co",
      publishableKey: "public",
      serviceRoleKey: "server",
      authorization: {
        environment: "sandbox",
        clientId: "id",
        clientSecret: "private",
        scope: "trade",
        appKey: "key",
        appSecret: "secret",
        vaultKey: "bad",
        keyId: "primary",
        approved: true,
      },
    });
  } catch (error) {
    failed = true;
    if (String(error).includes("private")) throw Error("Secret leaked");
  }
  eq(failed, true);
});
Deno.test("preflight validates coordinator configuration before advertising authorization", async () => {
  let failed = false;
  try {
    await createApplication({
      projectUrl: "https://abcdefghijklmnopqrst.supabase.co",
      publishableKey: "public",
      serviceRoleKey: "server",
      authorization: {
        environment: "sandbox",
        approved: true,
        clientId: "",
        clientSecret: "secret",
        scope: "trade",
        appKey: "key",
        appSecret: "secret",
        vaultKey: btoa("\x07".repeat(32)).replace(/=+$/u, ""),
        keyId: "primary",
      },
    });
  } catch {
    failed = true;
  }
  eq(failed, true);
});
Deno.test("authenticated admission failure refuses source operations before any provider call", async () => {
  const app = await createApplication({
    projectUrl: "https://abcdefghijklmnopqrst.supabase.co",
    publishableKey: "public",
    serviceRoleKey: "server",
    fetch: async () => Response.json({ id: owner, is_anonymous: false }),
    admitRequest: async () => false,
  });
  eq(
    (await app(
      new Request("https://internal/v1/capabilities", {
        headers: { authorization: "Bearer customer" },
      }),
    )).status,
    429,
  );
});
