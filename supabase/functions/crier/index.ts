import { createHandler } from "./gateway.ts";

// These are runtime-provided server secrets. Never ship them in desktop/mobile builds.
Deno.serve(createHandler({
  url: Deno.env.get("SUPABASE_URL") ?? "",
  serviceKey: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
}));
