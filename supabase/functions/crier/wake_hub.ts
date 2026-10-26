import type { WakeSource } from './stream.ts';

import type { SupabaseClient, RealtimeChannel } from 'npm:@supabase/supabase-js@2.118.0';
type Channel = RealtimeChannel;
type Client = Pick<SupabaseClient, 'channel' | 'removeChannel'>;
type Listener = { wake: () => void; failed: () => void };
type Entry = { channel: Channel; listeners: Set<Listener>; ready: Promise<void>; dead: boolean };

// One service-role subscription per channel per Edge isolate, shared by SSE viewers.
// No opaque pairing tokens, order data or telemetry enter Realtime.
export function createWakeHub(client: Client, timeoutMs = 8_000): WakeSource {
 const entries = new Map<string, Entry>();
 return {
  async subscribe(channelId, wake, failed) {
   let entry = entries.get(channelId);
   if (!entry) {
    const channel = client.channel('crier:' + channelId, { config: { private: true } });
    let resolve!: () => void; let reject!: (error: Error) => void;
    const ready = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
    entry = { channel, listeners: new Set(), ready, dead: false };
    const current = entry;
    entries.set(channelId, current);
    const timer = setTimeout(() => fail('SUBSCRIBE_TIMEOUT'), timeoutMs);
    const fail = (state: string) => {
     if (current.dead) return;
     current.dead = true; clearTimeout(timer);
     if (entries.get(channelId) === current) entries.delete(channelId);
     reject(Object.assign(new Error('Private wake unavailable'), { wakeState: state }));
     for (const listener of [...current.listeners]) listener.failed();
     current.listeners.clear();
     void client.removeChannel(channel).catch(() => {});
    };
    channel.on('broadcast', { event: 'wake' }, () => {
     for (const listener of [...current.listeners]) listener.wake();
    }).subscribe((state) => {
     if (state === 'SUBSCRIBED') { clearTimeout(timer); resolve(); }
     else if (state === 'CHANNEL_ERROR' || state === 'TIMED_OUT' || state === 'CLOSED') fail(state);
    });
   }
   const listener = { wake, failed }; entry.listeners.add(listener);
   try { await entry.ready; if (entry.dead) throw new Error('Private wake closed'); }
   catch (error) { entry.listeners.delete(listener); throw error; }
   const current = entry;
   return () => {
    current.listeners.delete(listener);
    if (!current.listeners.size && !current.dead) {
     current.dead = true;
     if (entries.get(channelId) === current) entries.delete(channelId);
     void client.removeChannel(current.channel).catch(() => {});
    }
   };
  },
 };
}
