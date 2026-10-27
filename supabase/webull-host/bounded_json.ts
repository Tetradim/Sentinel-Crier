/** Bound retained reply bytes and cancellation latency without trusting cleanup. */
export async function readBoundedJson(
  response: Response,
  maxBytes: number,
  signal: AbortSignal,
): Promise<unknown> {
  const failed = () => Error("Invalid Webull response");
  if (!response.ok || !response.body || signal.aborted) {
    void response.body?.cancel().catch(() => {});
    throw failed();
  }
  const reader = response.body.getReader();
  // One owned buffer bounds metadata overhead even for tiny or empty chunks.
  const bytes = new Uint8Array(maxBytes);
  let abort!: () => void;
  const aborted = new Promise<never>((_, reject) => {
    abort = () => reject(failed());
  });
  signal.addEventListener("abort", abort, { once: true });
  let size = 0;
  try {
    const declared = response.headers.get("content-length");
    if (declared && /^\d+$/u.test(declared) && Number(declared) > maxBytes) {
      throw failed();
    }
    while (true) {
      if (signal.aborted) throw failed();
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      if (value.byteLength > maxBytes - size) throw failed();
      bytes.set(value, size);
      size += value.byteLength;
    }
    if (signal.aborted) throw failed();
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, size)),
    );
  } catch {
    // Stream failures and abort reasons can contain credentials or reply data.
    throw failed();
  } finally {
    signal.removeEventListener("abort", abort);
    // cancel() closes pending reads immediately; its underlying cleanup promise
    // can stall indefinitely and must not extend request or revocation deadlines.
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
