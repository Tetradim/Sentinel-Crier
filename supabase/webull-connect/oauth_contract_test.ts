import {
  buildAuthorizationParameters,
  createTokenRequest,
  oauthApiEndpoints,
  parseTokenResponse,
} from "./oauth_contract.ts";

function assert(value: unknown, message = "assertion failed"): asserts value {
  if (!value) throw new Error(message);
}
function rejects(fn: () => unknown) {
  try {
    fn();
  } catch (error) {
    assert(error instanceof Error);
    assert(error.message === "Invalid Webull OAuth contract");
    return;
  }
  throw new Error("expected rejection");
}
const issued = Date.parse("2024-09-01T19:37:22.532Z");
function response(patch: Record<string, unknown> = {}) {
  return {
    access_token: "access-SENSITIVE",
    token_type: "Bearer",
    expires_in: "60",
    rt_expires_in: "120",
    refresh_token: "refresh-SENSITIVE",
    created_at: "2024-09-01T19:37:22.532+0000",
    identity_id: "identity-SENSITIVE",
    ...patch,
  };
}
const credentials = { client_id: "client+&= /", client_secret: "secret+&= /" };

Deno.test("pins environments and keeps browser parameters secret free", () => {
  assert(
    oauthApiEndpoints("sandbox").token ===
      "https://oauth-open-api.sandbox.webull.com/oauth2/tokens/create",
  );
  assert(
    oauthApiEndpoints("production").authorizationCode ===
      "https://us-oauth-open-api.webull.com/oauth2/auth-codes/get",
  );
  rejects(() => oauthApiEndpoints("https://evil.test" as never));
  const input = {
    client_id: "client",
    scope: "read",
    state: "random-state",
    redirect_uri: "https://example.test/callback",
  };
  const params = buildAuthorizationParameters(input);
  assert(params.get("response_type") === "code" && params.size === 5);
  assert(params.get("redirect_uri") === input.redirect_uri);
  rejects(() =>
    buildAuthorizationParameters({ ...input, client_secret: "secret" } as never)
  );
  for (const bad of ["", " ", "x\ny", true, null]) {
    rejects(() =>
      buildAuthorizationParameters({ ...input, state: bad } as never)
    );
  }
});

Deno.test("serializes only documented mutually exclusive form fields", () => {
  const request = createTokenRequest("sandbox", {
    ...credentials,
    grant_type: "authorization_code",
    code: "code+&= /",
  });
  assert(request.method === "POST");
  assert(request.contentType === "application/x-www-form-urlencoded");
  const body = new URLSearchParams(request.serializeForm());
  assert(
    body.get("code") === "code+&= /" &&
      body.get("client_secret") === credentials.client_secret,
  );
  assert(body.size === 4 && !body.has("redirect_uri"));
  const refresh = createTokenRequest("production", {
    ...credentials,
    grant_type: "refresh_token",
    refresh_token: "refresh",
  });
  assert(
    new URLSearchParams(refresh.serializeForm()).get("refresh_token") ===
      "refresh",
  );
  for (
    const patch of [
      { refresh_token: "other" },
      { redirect_uri: "https://example.test" },
      { code_verifier: "pkce" },
      { url: "https://evil.test" },
      { code: "" },
      { grant_type: "password" },
    ]
  ) {
    rejects(() =>
      createTokenRequest(
        "sandbox",
        {
          ...credentials,
          grant_type: "authorization_code",
          code: "code",
          ...patch,
        } as never,
      )
    );
  }
  rejects(() =>
    createTokenRequest(
      "sandbox",
      { ...credentials, grant_type: "refresh_token" } as never,
    )
  );
});

Deno.test("uses issuance time and accepts documented timezone representations", () => {
  for (const zone of ["+0000", "Z", "+00:00"]) {
    const result = parseTokenResponse(
      response({ created_at: `2024-09-01T19:37:22.532${zone}` }),
      { nowMs: issued + 30_000 },
    );
    assert(result.accessExpiresAtMs === issued + 60_000);
    assert(result.refreshExpiresAtMs === issued + 120_000);
    assert(result.accessToken() === "access-SENSITIVE");
    assert(result.refreshToken() === "refresh-SENSITIVE");
    assert(result.identityId() === "identity-SENSITIVE");
  }
  assert(
    parseTokenResponse(
      response({ created_at: "2024-09-01T21:37:22.532+0200" }),
      { nowMs: issued },
    ).accessExpiresAtMs === issued + 60_000,
  );
  rejects(() => parseTokenResponse(response(), { nowMs: issued + 60_000 }));
  rejects(() =>
    parseTokenResponse(response({ rt_expires_in: "1" }), {
      nowMs: issued + 1_000,
    })
  );
  rejects(() =>
    parseTokenResponse(response(), {
      nowMs: issued,
      expectedIdentity: "different",
    })
  );
  parseTokenResponse(response(), {
    nowMs: issued,
    expectedIdentity: "identity-SENSITIVE",
  });
});

Deno.test("rejects malformed schema, durations, dates and deadline overflow", () => {
  for (const key of Object.keys(response())) {
    const missing = response();
    delete missing[key as keyof typeof missing];
    rejects(() => parseTokenResponse(missing, { nowMs: issued }));
  }
  for (
    const value of [
      true,
      60,
      1.5,
      Infinity,
      NaN,
      "1.5",
      "Infinity",
      "-1",
      "0",
      " 60",
      "1e3",
      "9007199254740991",
      "",
    ]
  ) {
    for (const key of ["expires_in", "rt_expires_in"]) {
      rejects(() =>
        parseTokenResponse(response({ [key]: value }), { nowMs: issued })
      );
    }
  }
  for (
    const value of [
      "2024-09-01T19:37:22",
      "2024-02-30T00:00:00Z",
      "2024-09-01T24:00:00Z",
      "2024-09-01T19:37:22+2500",
      "2024-09-01T19:37:22+1260",
      "garbage",
    ]
  ) {
    rejects(() =>
      parseTokenResponse(response({ created_at: value }), { nowMs: issued })
    );
  }
  for (const key of ["access_token", "refresh_token", "identity_id"]) {
    for (const value of ["", " ", "secret\r\n", false]) {
      rejects(() =>
        parseTokenResponse(response({ [key]: value }), { nowMs: issued })
      );
    }
  }
  rejects(() =>
    parseTokenResponse(response({ token_type: "bearer" }), { nowMs: issued })
  );
  rejects(() => parseTokenResponse(response(), { nowMs: NaN }));
  rejects(() =>
    parseTokenResponse(response(), { nowMs: issued, expectedIdentity: "" })
  );
});

Deno.test("default serialization and inspection redact opaque secrets", () => {
  const request = createTokenRequest("sandbox", {
    ...credentials,
    grant_type: "authorization_code",
    code: "code-SENSITIVE",
  });
  const token = parseTokenResponse(response(), { nowMs: issued });
  for (const value of [request, token]) {
    const output = [
      JSON.stringify(value),
      Deno.inspect(value),
      String(value),
      JSON.stringify({ ...value }),
    ].join(" ");
    for (
      const secret of [
        credentials.client_secret,
        "code-SENSITIVE",
        "access-SENSITIVE",
        "refresh-SENSITIVE",
        "identity-SENSITIVE",
      ]
    ) assert(!output.includes(secret));
    assert(output.includes("REDACTED"));
  }
});

Deno.test("validates boundary inputs without echoing supplied secrets", () => {
  for (const field of ["client_id", "client_secret", "code"]) {
    for (const value of ["", " ", "secret\u0000tail", 3, null]) {
      rejects(() =>
        createTokenRequest(
          "sandbox",
          {
            ...credentials,
            grant_type: "authorization_code",
            code: "valid",
            [field]: value,
          } as never,
        )
      );
    }
  }
  rejects(() =>
    createTokenRequest(
      "production",
      {
        ...credentials,
        grant_type: "refresh_token",
        refresh_token: "refresh",
        code: "code",
      } as never,
    )
  );
  rejects(() =>
    createTokenRequest("other" as never, {
      ...credentials,
      grant_type: "refresh_token",
      refresh_token: "refresh",
    })
  );
  for (const body of [null, [], false, "access-SENSITIVE"]) {
    rejects(() => parseTokenResponse(body, { nowMs: issued }));
  }
  for (const value of [Infinity, 1.5, "1", 8_640_000_000_000_001]) {
    rejects(() => parseTokenResponse(response(), { nowMs: value } as never));
  }
  for (const key of ["expires_in", "rt_expires_in"]) {
    rejects(() =>
      parseTokenResponse(response({ [key]: "8640000000001" }), {
        nowMs: issued,
      })
    );
  }
  for (
    const created_at of [
      "2023-02-29T00:00:00Z",
      "2024-09-01T19:37:22+1401",
      "2024-09-01T19:37:60Z",
      "2024-09-01T19:37:22.5320Z",
    ]
  ) {
    rejects(() =>
      parseTokenResponse(response({ created_at }), { nowMs: issued })
    );
  }
});

Deno.test("requires a structurally valid server callback without URL normalization surprises", () => {
  const input = {
    client_id: "client",
    scope: "read",
    state: "state",
    redirect_uri: "https://example.test/callback",
  };
  for (
    const redirect_uri of [
      "http://example.test/callback",
      "https://user@example.test/callback",
      "https://:password@example.test/callback",
      "https://@example.test/callback",
      "https://example.test/callback?",
      "https://example.test/callback#",
      "https://example.test/callback?a=b",
      "https://example.test/callback#fragment",
      "https://example.test/call back",
      " https://example.test/callback",
      "https://example.test/call\\back",
      "https://example.test:65536/callback",
      "https://example.test:bad/callback",
      "https:///example.test/callback",
      "not a URL",
    ]
  ) rejects(() => buildAuthorizationParameters({ ...input, redirect_uri }));
  const redirect_uri = "https://example.test:8443/path%20part/callback";
  assert(
    buildAuthorizationParameters({ ...input, redirect_uri }).get(
      "redirect_uri",
    ) === redirect_uri,
  );
});

Deno.test("strict option keys prevent accidental loss of identity binding", () => {
  for (
    const options of [
      { nowMs: issued, expectedIdentitiy: "different" },
      { nowMs: issued, extra: true },
      { nowMs: issued, [Symbol("extra")]: true },
      Object.create({ nowMs: issued }),
      Object.assign(Object.create({ expectedIdentity: "different" }), {
        nowMs: issued,
      }),
    ]
  ) rejects(() => parseTokenResponse(response(), options as never));
  rejects(() =>
    parseTokenResponse(response(), {
      nowMs: issued,
      expectedIdentity: undefined,
    })
  );
});

Deno.test("bounds future issuance with the local 30 second clock policy", () => {
  const future = (delta: number) =>
    response({ created_at: new Date(issued + delta).toISOString() });
  assert(
    parseTokenResponse(future(30_000), { nowMs: issued }).accessExpiresAtMs ===
      issued + 90_000,
  );
  rejects(() => parseTokenResponse(future(30_001), { nowMs: issued }));
  rejects(() => parseTokenResponse(response(), { nowMs: issued + 60_000 }));
});
