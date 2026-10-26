import { createClient } from 'npm:@supabase/supabase-js@2.118.0';
import { createHandler } from './gateway.ts';
import { createWakeHub } from './wake_hub.ts';

// These are runtime-provided server secrets. Never ship them in desktop/mobile builds.
const url = Deno.env.get('SUPABASE_URL') ?? '';
const serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
const wakeSource = url && serviceKey ? createWakeHub(createClient(url, serviceKey, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
})) : undefined;
Deno.serve(createHandler({ url, serviceKey, wakeSource }));
