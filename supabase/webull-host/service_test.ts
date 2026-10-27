// deno-lint-ignore-file require-await -- Async test doubles implement asynchronous ports.
import { createHostedGateway, createRpcLedger } from "./service.ts";
import type { Order } from "./gateway.ts";
const o: Order = {
  client_order_id: "b013cf27-fbab-4425-9c6c-6c3236766514",
  account_id: "account-a",
  environment: "sandbox",
  asset: "stock",
  symbol: "AAPL",
  quantity: 1,
  limit_price: "1",
  side: "buy",
};
function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw Error("unexpected result");
}
Deno.test("RPC ledger requires exact reservation reply and never retries failed RPC", async () => {
  let calls = 0;
  const ledger = createRpcLedger(async () => {
    calls++;
    throw Error("database timeout");
  });
  try {
    await ledger.reserve("owner", o, JSON.stringify(o));
    throw Error("should reject");
  } catch (error) {
    if (!(error instanceof Error) || error.message === "should reject") {
      throw error;
    }
  }
  eq(calls, 1);
  const malformed = createRpcLedger(async () => ({
    created: true,
    row: { owner: "other-owner" },
  }));
  try {
    await malformed.reserve("owner", o, JSON.stringify(o));
    throw Error("should reject");
  } catch (error) {
    if (!(error instanceof Error) || error.message === "should reject") {
      throw error;
    }
  }
});
Deno.test("unconfigured hosted service verifies customer then reports unavailable", async () => {
  let calls = 0;
  const handle = createHostedGateway({
    supabaseUrl: "https://project.supabase.co",
    publishableKey: "public",
    serviceRoleKey: "server-private",
    fetch: async () => {
      calls++;
      return Response.json({ id: o.client_order_id, is_anonymous: false });
    },
  });
  const response = await handle(
    new Request("https://host.test/v1/capabilities", {
      headers: { authorization: "Bearer customer" },
    }),
  );
  eq(response.status, 200);
  eq((await response.json()).available, false);
  eq(calls, 1);
});
Deno.test("RPC ledger preserves only recognized inventory refusals", async () => {
  for (
    const reason of [
      "insufficient_tracked_long_position",
      "source_inventory_reconciliation_required",
    ]
  ) {
    const denied = { created: false, row: null, reason };
    const ledger = createRpcLedger(async () => denied);
    eq(await ledger.reserve("owner", o, JSON.stringify(o)), denied);
  }
  for (
    const denied of [
      {
        created: true,
        row: null,
        reason: "insufficient_tracked_long_position",
      },
      { created: false, row: null, reason: "unknown" },
      {
        created: false,
        row: null,
        reason: "insufficient_tracked_long_position",
        extra: true,
      },
    ]
  ) {
    let rejected = false;
    try {
      await createRpcLedger(async () => denied).reserve(
        "owner",
        o,
        JSON.stringify(o),
      );
    } catch {
      rejected = true;
    }
    eq(rejected, true);
  }
});
