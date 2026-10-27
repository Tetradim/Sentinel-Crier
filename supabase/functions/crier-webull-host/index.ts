import { createApplication } from "../../webull-host/application.ts";
import { runtimeOptions } from "../../webull-host/runtime_config.ts";

let handler: (request: Request) => Promise<Response>;
try {
  handler = await createApplication(
    runtimeOptions((name) => Deno.env.get(name)),
  );
} catch {
  handler = () =>
    Promise.resolve(
      Response.json({ error: "webull_service_configuration_required" }, {
        status: 503,
        headers: {
          "cache-control": "no-store",
          "referrer-policy": "no-referrer",
        },
      }),
    );
}
// No trading adapter is installed here. An approved, reviewed resource binding
// must be added explicitly; an environment flag cannot enable invented orders.
Deno.serve(handler);
