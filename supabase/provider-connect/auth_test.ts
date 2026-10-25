import { AuthRejected, CustomerAuth } from "./auth.ts";

function assert(value: unknown, message = "assertion failed"): asserts value {
  if (!value) throw new Error(message);
}
async function rejected(operation: () => unknown | Promise<unknown>) {
  try {
    await operation();
  } catch (error) {
    assert(error instanceof AuthRejected);
    return;
  }
  throw new Error("expected authentication rejection");
}
const projectUrl = "https://abcdefghijklmnopqrst.supabase.co";
const baseUrl = projectUrl + "/functions/v1/crier-oauth";
const publishableKey = "sb_publishable_synthetic";
const id = "12345678-1234-4234-8234-123456789abc";
const user = { id, is_anonymous: false };
const credentials = {
  access_token: "synthetic.access.token",
  refresh_token: "synthetic-refresh",
  expires_in: 7200,
  token_type: "bearer",
  user,
};
const ticket = "A".repeat(43);
function fixture(body: unknown = credentials) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const auth = new CustomerAuth({
    projectUrl,
    publishableKey,
    fetch: (input, init) => {
      calls.push({ url: String(input), init });
      return Promise.resolve(Response.json(body));
    },
  });
  return { auth, calls };
}
async function loginForm(auth: CustomerAuth) {
  const response = await auth.browserLogin(
    new Request(baseUrl + "/auth/browser?ticket=" + ticket),
    { baseUrl, nextTicket: ticket },
  );
  const html = await response.text();
  const csrf = /name="csrf" value="([^"]+)"/.exec(html)![1];
  return { response, html, csrf, cookie: "__Host-crier-login=" + csrf };
}
function post(
  csrf: string,
  cookie: string,
  extra: { origin?: string; ticket?: string; suffix?: string } = {},
) {
  return new Request(baseUrl + "/auth/browser", {
    method: "POST",
    headers: {
      origin: extra.origin ?? projectUrl,
      cookie,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      csrf,
      ticket: extra.ticket ?? ticket,
      email: "synthetic@example.invalid",
      password: "private-password",
    }).toString() + (extra.suffix ?? ""),
  });
}

Deno.test("customer auth pins project origin and rejects secret credentials", async () => {
  for (
    const url of [
      projectUrl + "/",
      projectUrl + ":444",
      projectUrl + "/evil",
      "https://example.supabase.co",
      "http://abcdefghijklmnopqrst.supabase.co",
      "https://abcdefghijklmnopqrst.supabase.co@evil.test",
    ]
  ) {
    await rejected(() => new CustomerAuth({ projectUrl: url, publishableKey }));
  }
  await rejected(() =>
    new CustomerAuth({ projectUrl, publishableKey: "sb_secret_synthetic" })
  );
});

Deno.test("owner uses server user endpoint, rejects anonymous/profile identities", async () => {
  const { auth, calls } = fixture({
    ...user,
    user_metadata: { id: "untrusted" },
  });
  assert(await auth.owner("Bearer synthetic.jwt") === id);
  assert(calls[0].url === projectUrl + "/auth/v1/user");
  const init = calls[0].init!;
  assert(init.redirect === "error" && init.signal instanceof AbortSignal);
  assert(new Headers(init.headers).get("apikey") === publishableKey);
  assert(
    new Headers(init.headers).get("authorization") === "Bearer synthetic.jwt",
  );
  for (
    const bad of [{ id, is_anonymous: true }, { id }, {
      id: "bad",
      is_anonymous: false,
    }, { user_metadata: user }]
  ) {
    await rejected(() => fixture(bad).auth.owner("Bearer synthetic.jwt"));
  }
  await rejected(() => auth.owner("synthetic.jwt"));
  await rejected(() =>
    auth.browserOwner(
      new Request(baseUrl, {
        headers: {
          cookie: "__Host-crier-session=one; __Host-crier-session=two",
        },
      }),
    )
  );
  assert(
    await auth.browserOwner(
      new Request(baseUrl, {
        headers: {
          cookie: "other=ignored; __Host-crier-session=synthetic.jwt",
        },
      }),
    ) === id,
  );
});

Deno.test("native sign in, refresh and signup return only validated safe fields", async () => {
  const { auth, calls } = fixture({ ...credentials, private: "discarded" });
  const result = await auth.signIn(
    "synthetic@example.invalid",
    "private-password",
  );
  assert(result.user.id === id && !("private" in result));
  assert(calls[0].url.endsWith("/auth/v1/token?grant_type=password"));
  assert(!new Headers(calls[0].init?.headers).has("cookie"));
  await auth.refresh("refresh-token");
  assert(calls[1].url.endsWith("grant_type=refresh_token"));
  const confirmed = await fixture({ id }).auth.signUp(
    "synthetic@example.invalid",
    "private-password",
  );
  assert(confirmed.requiresEmailConfirmation && confirmed.session === null);
  assert(
    !(await auth.signUp("synthetic@example.invalid", "private-password"))
      .requiresEmailConfirmation,
  );
  for (
    const bad of [
      { ...credentials, expires_in: 0 },
      { ...credentials, expires_in: 86401 },
      { ...credentials, expires_in: 1.5 },
      { ...credentials, token_type: "other" },
      { ...credentials, access_token: "bad;cookie" },
      { ...credentials, user: { id, is_anonymous: true } },
    ]
  ) {
    await rejected(() =>
      fixture(bad).auth.signIn("synthetic@example.invalid", "private-password")
    );
  }
});

Deno.test("upstream failures, malformed and oversized bodies have generic errors", async () => {
  for (
    const make of [
      () => Promise.reject(new Error("PRIVATE_PASSWORD")),
      () => Promise.resolve(new Response("PRIVATE_PASSWORD", { status: 400 })),
      () => Promise.resolve(new Response("not json")),
      () => Promise.resolve(new Response("x".repeat(65537))),
    ]
  ) {
    const auth = new CustomerAuth({ projectUrl, publishableKey, fetch: make });
    await rejected(() =>
      auth.signIn("synthetic@example.invalid", "private-password")
    );
  }
});

Deno.test("browser login renders accessible form and stores only bounded HttpOnly access cookie", async () => {
  const { auth, calls } = fixture();
  const form = await loginForm(auth);
  assert(
    form.html.includes("Do not enter a brokerage password") &&
      form.html.includes("<label>Email"),
  );
  assert(
    form.response.headers.get("content-security-policy")?.includes(
      "form-action 'self'",
    ),
  );
  assert(
    form.response.headers.get("set-cookie")?.includes(
      "Secure; HttpOnly; SameSite=Lax; Path=/",
    ),
  );
  let claimed = false;
  const response = await auth.browserLogin(post(form.csrf, form.cookie), {
    baseUrl,
    claimCsrf: (hash, expiry) => {
      assert(/^[0-9a-f]{64}$/.test(hash) && expiry > Date.now() / 1000);
      claimed = true;
      return Promise.resolve(true);
    },
  });
  assert(claimed && calls.length === 1 && response.status === 303);
  assert(
    response.headers.get("location") ===
      baseUrl + "/oauth/browser?ticket=" + ticket,
  );
  const cookies = response.headers.getSetCookie();
  assert(
    cookies.some((value) =>
      value.startsWith("__Host-crier-login=;") && value.includes("Max-Age=0")
    ),
  );
  assert(
    cookies.some((value) =>
      value.startsWith("__Host-crier-session=synthetic.access.token;") &&
      value.includes("Max-Age=3600")
    ),
  );
  assert(!cookies.join().includes("synthetic-refresh"));
});

Deno.test("browser login rejects missing/replayed CSRF, cross origin, duplicate fields and arbitrary returns before sign in", async () => {
  const { auth, calls } = fixture();
  const form = await loginForm(auth);
  const accepts = { baseUrl, claimCsrf: () => Promise.resolve(true) };
  const attempts: [Request, typeof accepts | { baseUrl: string }][] = [
    [post(form.csrf, form.cookie), { baseUrl }],
    [post(form.csrf, form.cookie), {
      baseUrl,
      claimCsrf: () => Promise.resolve(false),
    }],
    [post(form.csrf, form.cookie, { origin: "https://evil.test" }), accepts],
    [post(form.csrf, "__Host-crier-login=wrong"), accepts],
    [post(form.csrf, form.cookie + "; " + form.cookie), accepts],
    [
      post(form.csrf, form.cookie, {
        suffix: "&email=other%40example.invalid",
      }),
      accepts,
    ],
    [post(form.csrf, form.cookie, { ticket: "https://evil.test" }), accepts],
    [
      post(
        "A".repeat(43) + ".1000000000",
        "__Host-crier-login=" + "A".repeat(43) + ".1000000000",
      ),
      accepts,
    ],
  ];
  for (const [request, options] of attempts) {
    const response = await auth.browserLogin(request, options);
    assert(
      response.status === 401 &&
        response.headers.get("cache-control") === "no-store",
    );
    assert(!(await response.text()).includes("private-password"));
  }
  assert(calls.length === 0);
});
