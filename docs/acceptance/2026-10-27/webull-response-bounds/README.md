# Webull HTTP boundary verification

Source revision and successful CI runs are recorded in [source evidence](source-evidence.json).

Resource replies previously called `arrayBuffer()` before checking the one-MiB size limit. Token replies streamed within 64 KiB, but waited for stream cleanup and could leave a stalled body read pending after caller cancellation. A caller-supplied resource cancellation signal also replaced the resource client's ten-second deadline.

Both transports now use a shared bounded JSON reader with an owned fixed-size buffer. It enforces actual bytes while reading, validates UTF-8, refuses non-success replies and cancels without awaiting an untrusted cleanup promise. Body reads race cancellation; abort reasons and read exceptions are replaced with a fixed error. Resource requests combine caller cancellation and their deadline, reject pre-aborted dispatch and enforce the outbound body limit in UTF-8 bytes. Pinned HTTPS hosts, signed requests, redirect refusal and absence of mutation retries remain unchanged.

Fourteen transport regressions cover streaming overflow, exact bounds, invalid UTF-8, reused chunk buffers, stalled bodies/cleanup, pre-aborted dispatch, independent resource deadlines and oversized Unicode requests. Seven initial regressions failed against the prior implementation. Three additional buffer/request-size regressions were also observed failing before their repairs. The complete Webull suite has 52 tests. SQL/authorization integration has ten tests; the intercepted Alpaca-paper receiver compatibility suite has three.

No real HTTP broker traffic, orders, Discord messages, configuration changes or service deployments were performed. A fixed buffer bounds retained byte storage; the upstream stream can still deliver an oversized chunk before rejection. JSON decoding/parsing also allocates bounded-size strings/objects, so the byte limit is not a whole-process memory limit. Trusted token callers supply their coordinator deadline; the resource transport independently supplies ten seconds. This change does not install the approved Webull account/order adapter, enable trading, prove vendor interoperability or replace physical acceptance.

Webull's [Connect overview](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) and [OAuth guide](https://developer.webull.com/apis/docs/connect-api/authentication/) were checked on October 27, 2026. Public references still direct integrations to their issued Connect resource paths and headers. No personal Trading API schema was guessed into an active Connect adapter.
