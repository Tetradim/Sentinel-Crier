import { createPushStream } from './stream.ts';

function assert(value: unknown, message = 'Assertion failed'): asserts value {
  if (!value) throw new Error(message);
}

Deno.test('push subscribes before draining and replays durable pages on a wake', async () => {
  const abort = new AbortController(); let subscribed = false; let wake = () => {}; let released = 0;
  let available = false;
  const response = await createPushStream({
    channel: 'test', role: 'follower', after: '0', signal: abort.signal,
    source: { subscribe: async (_, callback) => { await Promise.resolve(); subscribed = true; wake = callback; return () => { released++; }; } },
    rpc: async (path, query) => {
      await Promise.resolve();
      assert(subscribed, 'Drain raced subscription');
      if (path.endsWith('/dashboard')) return {status: 200, body: {version: 1}};
      return {status: 200, body: {events: available && query?.after === '0' ? [{cursor: 1, event: {action: 'cancel'}}] : [], cursor: available ? 1 : 0}};
    },
  });
  const reader = response.body!.getReader(); const decoder = new TextDecoder();
  assert(decoder.decode((await reader.read()).value).includes('event: ready'));
  available = true; wake();
  const next = decoder.decode((await reader.read()).value);
  assert(next.includes('event: events') && next.includes('cancel'));
  abort.abort(); await reader.cancel(); assert(released === 1);
});

Deno.test('host push never reads follower intents and revocation closes the stream', async () => {
  const abort = new AbortController(); let wake = () => {}; let revoked = false;
  const response = await createPushStream({channel: 'test', role: 'host', after: '0', signal: abort.signal,
    source: {subscribe: async (_, callback) => { await Promise.resolve(); wake = callback; return () => {}; }},
    rpc: async path => { await Promise.resolve(); assert(!path.endsWith('/events')); return {status: revoked ? 401 : 200, body: {}}; },
  });
  const reader = response.body!.getReader(); await reader.read();
  await Promise.resolve(); revoked = true; wake();
  for (let i = 0; i < 5; i++) { if ((await reader.read()).done) { abort.abort(); return; } }
  abort.abort(); throw new Error('Revoked stream stayed open');
});

Deno.test('unavailable private subscription falls back without claiming push', async () => {
  const response = await createPushStream({channel: 'test', role: 'host', after: '0', signal: new AbortController().signal,
    source: {subscribe: () => Promise.reject(new Error('offline'))},
    rpc: () => { throw new Error('No drain without subscription'); },
  });
  assert(response.status === 503); await response.body?.cancel();
});
