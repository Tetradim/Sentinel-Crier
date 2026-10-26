export type RpcResult = { status: number; body: unknown };
export type WakeSource = {
  subscribe(channel: string, wake: () => void, failed: () => void): Promise<() => void>;
};
export type StreamOptions = {
  rpc: (path: string, query?: Record<string, string>) => Promise<RpcResult>;
  source: WakeSource;
  channel: string;
  role: string;
  after: string;
  signal: AbortSignal;
  heartbeatMs?: number;
  lifetimeMs?: number;
  dashboardMs?: number;
};
const encoder = new TextEncoder();
const MAX_FRAME = 1_048_576;
const MAX_QUEUE = 2 * MAX_FRAME;

// A private wake is only a hint. Each drain reauthenticates and reads committed rows.
export async function createPushStream(o: StreamOptions): Promise<Response> {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  let closed = false;
  let release: (() => void) | undefined;
  const timers: {beat?: ReturnType<typeof setInterval>; lifetime?: ReturnType<typeof setTimeout>} = {};
  let dashboardTimer: ReturnType<typeof setTimeout> | undefined;
  let eventsDirty = false;
  let dashboardDirty = false;
  let eventsRunning = false;
  let dashboardRunning = false;
  let cursor = o.after;
  let active = false;
  const close = () => {
    if (closed) return;
    closed = true;
    clearInterval(timers.beat); clearTimeout(timers.lifetime); clearTimeout(dashboardTimer);
    o.signal.removeEventListener('abort', close);
    release?.(); release = undefined;
    try { controller?.close(); } catch { /* already cancelled */ }
  };
  const stream = new ReadableStream<Uint8Array>({
    start(c) { controller = c; },
    cancel() { close(); },
  }, { highWaterMark: MAX_QUEUE, size: (chunk) => chunk.byteLength });
  function emit(name: string, body: unknown) {
    if (closed) return;
    const bytes = encoder.encode(`event: ${name}\ndata: ${JSON.stringify(body)}\n\n`);
    if (bytes.byteLength > MAX_FRAME || bytes.byteLength > (controller.desiredSize ?? 0)) {
      close(); return;
    }
    controller.enqueue(bytes);
  }
  function dashboardSoon() {
    if (closed || !active || dashboardRunning || dashboardTimer || !dashboardDirty) return;
    dashboardTimer = setTimeout(() => { dashboardTimer = undefined; void dashboard(); }, o.dashboardMs ?? 250);
  }
  async function dashboard() {
    if (closed || dashboardRunning) return;
    // Never start expensive snapshot work ahead of an outstanding intent drain.
    if (eventsRunning || eventsDirty) { dashboardSoon(); return; }
    dashboardRunning = true; dashboardDirty = false;
    try {
      const result = await o.rpc('/api/sync/dashboard');
      if (closed) return;
      if (result.status !== 200) { close(); return; }
      emit('dashboard', result.body);
    } catch { close(); }
    finally { dashboardRunning = false; dashboardSoon(); }
  }
  async function events() {
    if (closed || !active || eventsRunning) return;
    eventsRunning = true;
    try {
      while (eventsDirty && !closed) {
        eventsDirty = false;
        // Hosts observe only: their execution engine never ingests remote events.
        const result = o.role === 'host'
          ? await o.rpc('/api/sync/clock')
          : await o.rpc('/api/sync/events', { after: cursor, wait: '0' });
        if (closed) return;
        if (result.status !== 200) { close(); return; }
        if (o.role !== 'host') {
          const page = result.body as {events: unknown[]; cursor: number};
          if (!Array.isArray(page?.events) || !Number.isSafeInteger(page.cursor) || page.cursor < Number(cursor)) { close(); return; }
          if (page.events.length) emit('events', page);
          cursor = String(page.cursor);
          if (page.events.length >= 500) eventsDirty = true;
        }
      }
    } catch { close(); }
    finally { eventsRunning = false; dashboardSoon(); }
  }
  function wake() {
    eventsDirty = true; dashboardDirty = true;
    void events(); dashboardSoon();
  }
  o.signal.addEventListener('abort', close, { once: true });
  if (o.signal.aborted) close();
  try {
    // Subscription acknowledgement precedes initial drain; an intervening wake sets dirty.
    release = await o.source.subscribe(o.channel, wake, close);
    if (closed) { release(); throw new Error('Stream unavailable'); }
  } catch {
    close();
    return Response.json({ detail: 'Push unavailable; use polling' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
  active = true;
  emit('ready', { version: 1, transport: 'push' });
  wake();
  timers.beat = setInterval(() => {
    wake();
    emit('heartbeat', { server_time_ms: Date.now() });
  }, o.heartbeatMs ?? 15_000);
  timers.lifetime = setTimeout(close, o.lifetimeMs ?? 90_000);
  return new Response(stream, { headers: {
    'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'X-Accel-Buffering': 'no',
  } });
}
