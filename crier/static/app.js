"use strict";
let token = "",
  currentSettings = null,
  scenario = "option_buy",
  payload = null,
  previewVersion = 0,
  noticeTimer;
const $ = (id) => document.getElementById(id);
const fields = [
  "display_name",
  "format",
  "color",
  "timezone",
  "show_quantity",
  "show_time",
  "paused",
];
function notice(message) {
  $("notice").textContent = message;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => ($("notice").textContent = ""), 7000);
}
async function api(path, options = {}) {
  const sessionToken = token;
  const response = await fetch("/api/" + path, {
    ...options,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });
  const data = await response.json();
  if (sessionToken !== token) throw new Error("Console locked. Unlock to continue.");
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail) ? data.detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" / ")}: ${item.msg}`).join("; ") : "Check the fields and try again.",
    );
  return data;
}
function settingsFromForm() {
  return Object.fromEntries(
    fields.map((key) => [
      key,
      $(key).type === "checkbox" ? $(key).checked : $(key).value,
    ]),
  );
}
function populate(settings) {
  fields.forEach((key) => {
    if ($(key).type === "checkbox") $(key).checked = settings[key];
    else $(key).value = settings[key];
  });
}
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function markdown(target, content) {
  // Deliberately tiny renderer: text, bold and fenced ledgers only. Never HTML.
  target.replaceChildren();
  target.className = "markdown";
  const pieces = content.split("```");
  pieces.forEach((piece, index) => {
    if (index % 2) {
      target.append(node("pre", piece.trim()));
      return;
    }
    piece.split("\n").forEach((line) => {
      if (!line) return;
      const row = node("div", undefined, "markdown-line");
      line
        .split("**")
        .forEach((part, i) =>
          row.append(
            i % 2 ? node("strong", part) : document.createTextNode(part),
          ),
        );
      target.append(row);
    });
  });
}
function draw(data) {
  payload = data;
  const card = $("card");
  card.replaceChildren();
  const embed = data.embeds?.[0];
  card.hidden = !embed;
  $("text-preview").hidden = !!embed;
  if (!embed) {
    markdown($("text-preview"), data.content);
    return;
  }
  card.style.borderLeftColor = "#" + embed.color.toString(16).padStart(6, "0");
  card.append(
    node("div", embed.author.name, "embed-author"),
    node("div", embed.title, "embed-title"),
    node("div", embed.description, "embed-description"),
  );
  const grid = node("div", undefined, "embed-fields");
  embed.fields.forEach((field) => {
    const box = node(
      "div",
      undefined,
      "embed-field" + (field.inline ? "" : " full"),
    );
    box.append(node("strong", field.name));
    if (field.value.startsWith("```text\n"))
      box.append(node("pre", field.value.slice(8, -4)));
    else box.append(node("p", field.value));
    grid.append(box);
  });
  card.append(grid, node("div", embed.footer.text, "embed-footer"));
}
async function preview() {
  if (!token) return;
  const version = ++previewVersion;
  try {
    const result = await api("preview", {
      method: "POST",
      body: JSON.stringify({ scenario, settings: settingsFromForm() }),
    });
    if (version === previewVersion) {
      draw(result.payload);
      $("copy").disabled = false;
    }
  } catch (error) {
    if (version === previewVersion) {
      payload = null;
      $("copy").disabled = true;
      $("card").hidden = true;
      $("text-preview").hidden = false;
      $("text-preview").textContent = error.message;
    }
  }
}
async function status() {
  const data = await api("status");
  $("mode").textContent = data.paused
    ? "DELIVERY PAUSED"
    : data.delivery_enabled
      ? "DELIVERY ENABLED"
      : "PREVIEW MODE";
  const states = {
    not_started: "Not connected",
    connecting: "Connecting",
    observing: "Observing account",
    capture_only: "Capture only · validation required",
    stale: "Connection stale",
    error: "Connection needs attention",
    reconnecting: "Reconnecting",
    stopped: "Observer stopped",
  };
  $("broker-state").textContent =
    states[data.observer.state] || data.observer.state;
  $("discord-state").textContent = data.discord_configured
    ? "Webhook configured"
    : "Webhook not configured";
  $("delivery-state").textContent = data.sender_failed
    ? "Sender stopped — check server"
    : data.paused
      ? "Paused — new fills remain queued"
      : data.delivery_enabled
        ? "Enabled"
        : "Preview only — no messages sent";
  const observer = data.observer;
  const selected = data.monitor?.selected || "none";
  const updated = Number(observer.updated || 0);
  const recent = updated > 0 && Date.now() / 1000 - updated < 90;
  const active = !["not_started", "stopped", "stale", "error"].includes(observer.state);
  $("observer-details").textContent = updated > 0
    ? `Reported source: ${observer.broker || "unspecified broker"} · ${observer.environment || "environment not reported"}. Last update: ${new Date(updated * 1000).toLocaleString()}.`
    : "No account source or environment reported yet.";
  $("monitor-state").textContent = data.monitor?.running
    ? `Managed by this server · ${selected} · Running`
    : recent && active
      ? "Separate watcher · Recent heartbeat. No monitor process is running under this server."
      : updated > 0
        ? `No managed monitor running${selected !== "none" ? " (selected: " + selected + ")" : ""}. Last reported watcher is ${states[observer.state] || observer.state}.`
        : selected === "none"
          ? "No managed monitor selected. No watcher reported."
          : `Managed monitor selected: ${selected} · Not running`;
  $("intake-state").textContent = `Event intake: ${data.intake?.configured ? (data.intake.verified ? "configured and verified" : "configured · verification required") : "not configured"}`;
  $("capture-delivery").textContent = data.delivery_enabled
    ? (data.paused ? "Delivery paused. Confirmed alerts remain queued." : "Publisher enabled. Confirming can send an alert to Discord.")
    : "Preview mode. Confirmed alerts remain queued and can deliver only if the publisher is enabled later.";
  $("review-state").textContent = data.review_count
    ? `${data.review_count} observations need review in the private audit log.`
    : "No observations waiting for review.";
}
async function history() {
  const rows = await api("history");
  $("activity-count").textContent = String(rows.length);
  $("history").replaceChildren();
  if (!rows.length) {
    $("history").append(
      node(
        "div",
        "Your first queued fill alert will appear here. Sample previews are never added to your activity.",
        "empty",
      ),
    );
    return;
  }
  rows.forEach((row) => {
    const line = node("article", undefined, "history-row");
    const info = node("div");
    info.append(
      node("strong", row.fill.contract),
      node("p", `${row.fill.side} · ${row.fill.quantity} @ $${row.fill.price}`),
    );
    if (row.fill.verification === "user_confirmed") info.append(node("p", "User-confirmed · manual receipt", "provenance"));
    const state = node("div", row.status, "state");
    if (row.note) state.append(node("small", row.note));
    line.append(info, state);
    $("history").append(line);
  });
}
$("unlock-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  const button = event.submitter;
  button.disabled = true;
  try {
    currentSettings = await api("settings");
    populate(currentSettings);
    await Promise.all([status(), history(), receipts(), capabilities()]);
    $("unlock").hidden = true;
    $("console").hidden = false;
    $("token").value = "";
    await preview();
  } catch (error) {
    token = "";
    notice(error.message);
  } finally {
    button.disabled = false;
  }
});
$("settings-form").addEventListener("input", preview);
$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  event.submitter.disabled = true;
  try {
    currentSettings = await api("settings", {
      method: "PUT",
      body: JSON.stringify(settingsFromForm()),
    });
    notice("Presentation saved. It will apply to new alerts.");
    await status();
  } catch (error) {
    notice(error.message);
  } finally {
    event.submitter.disabled = false;
  }
});
document.querySelectorAll("[data-scenario]").forEach((button) =>
  button.addEventListener("click", () => {
    scenario = button.dataset.scenario;
    document.querySelectorAll("[data-scenario]").forEach((b) => {
      b.classList.toggle("selected", b === button);
      b.setAttribute("aria-pressed", String(b === button));
    });
    preview();
  }),
);
document.querySelectorAll("[data-panel]").forEach((button) =>
  button.addEventListener("click", () => {
    document
      .querySelectorAll(".view")
      .forEach((panel) => (panel.hidden = panel.id !== button.dataset.panel));
    document.querySelectorAll("[data-panel]").forEach((b) => {
      b.classList.toggle("active", b === button);
      if (b === button) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    if (button.dataset.panel === "capture")
      Promise.all([receipts(), status()]).catch((e) => notice(e.message));
    if (button.dataset.panel === "activity")
      history().catch((e) => notice(e.message));
    if (button.dataset.panel === "connections")
      status().catch((e) => notice(e.message));
  }),
);
$("refresh").addEventListener("click", () =>
  history().catch((e) => notice(e.message)),
);
$("copy").addEventListener("click", async () => {
  if (!payload) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    notice("Sample message JSON copied.");
  } catch {
    notice(
      "Clipboard is unavailable. Open this console over HTTPS or localhost.",
    );
  }
});
$("lock").addEventListener("click", () => {
  token = "";
  payload = null;
  currentSettings = null;
  ++previewVersion;
  $("console").hidden = true;
  $("unlock").hidden = false;
  $("history").replaceChildren();
  $("card").replaceChildren();
  $("text-preview").textContent = "";
  $("mode").textContent = "PREVIEW MODE";
  selectedReceipt = null;
  $("receipt-form").reset();
  $("receipt-review").reset();
  $("receipt-review").hidden = true;
  $("receipt-text").value = "";
  $("receipt-list").replaceChildren();
  $("receipt-source").textContent = "";
  $("receipt-warnings").replaceChildren();
  $("receipt-result").textContent = "Select a saved receipt to review.";
  $("settings-form").reset();
  $("activity-count").textContent = "0";
  $("capabilities").replaceChildren();
  clearTimeout(noticeTimer);
  $("notice").textContent = "";
  $("token").focus();
});

let selectedReceipt = null;
const reviewFields = [
  ["broker", "Broker slug"],
  ["environment", "Account environment", ["sandbox", "production"]],
  ["account", "Stable account alias"],
  ["order_id", "Original order ID"],
  ["symbol", "Stock ticker or full OCC option symbol"],
  ["category", "Asset type", ["US_STOCK", "US_OPTION"]],
  ["side", "Trade side", ["BUY", "SELL"]],
  ["intent", "Opening / closing intent", ["OPEN", "CLOSE", "UNKNOWN"]],
  ["cumulative_qty", "Total filled quantity"],
  ["average_price", "Cumulative average fill price"],
  ["occurred_at", "Fill date and time with UTC offset"],
  ["status", "Fill status", ["FILLED", "PARTIAL"]],
];
reviewFields.forEach(([key, label, choices]) => {
  const box = node("div");
  const caption = node("label", label);
  caption.htmlFor = "review-" + key;
  const input = node(choices ? "select" : "input");
  input.id = "review-" + key;
  input.required = true;
  if (choices) {
    const empty = node("option", "Select explicitly");
    empty.value = "";
    input.append(empty);
    choices.forEach((choice) => { const option = node("option", choice); option.value = choice; input.append(option); });
  } else {
    input.autocomplete = "off";
    if (["cumulative_qty", "average_price"].includes(key)) {
      input.inputMode = "decimal";
      input.pattern = "[0-9]+([.][0-9]+)?";
    }
    if (key === "occurred_at") input.placeholder = "2026-10-13T14:30:00-05:00";
  }
  box.append(caption, input);
  $("review-fields").append(box);
});
async function capabilities() {
  const data = await api("capabilities");
  $("capabilities").replaceChildren();
  data.brokers.forEach((broker) => {
    const card = node("article", undefined, "panel");
    card.append(node("h3", broker.name), node("p", broker.mode), node("p", broker.description, "fine"));
    $("capabilities").append(card);
  });
}
function showReceipt(receipt) {
  selectedReceipt = receipt;
  $("receipt-source").textContent = receipt.text;
  $("receipt-result").textContent = `${receipt.status} · ${receipt.broker} · ${receipt.environment}${receipt.result?.outcome ? " · " + receipt.result.outcome : ""}`;
  $("receipt-warnings").replaceChildren(...(receipt.warnings || []).map((warning) => node("li", warning)));
  $("receipt-review").hidden = receipt.status !== "pending";
  reviewFields.forEach(([key]) => { $("review-" + key).value = receipt.draft?.[key] ?? (["broker", "environment"].includes(key) ? receipt[key] : ""); });
}
async function receipts() {
  const items = await api("receipts");
  $("receipt-list").replaceChildren();
  if (!items.length) $("receipt-list").append(node("p", "No receipts yet. Save one to begin reviewing.", "fine"));
  items.forEach((receipt) => {
    const button = node("button", undefined, "receipt-item");
    button.type = "button";
    button.append(node("strong", `${receipt.broker} · ${receipt.environment}`), node("span", `${receipt.status} · ${new Date(typeof receipt.created === "number" ? receipt.created * 1000 : receipt.created).toLocaleString()}`));
    button.addEventListener("click", () => showReceipt(receipt));
    $("receipt-list").append(button);
  });
}
$("receipt-sample").addEventListener("click", () => {
  $("receipt-broker").value = "robinhood";
  $("receipt-environment").value = "sandbox";
  $("receipt-text").value = `account: SYNTHETIC-demo
order_id: SYNTHETIC-order-001
symbol: SPY261218C00600000
category: US_OPTION
side: BUY
intent: OPEN
cumulative_qty: 1
average_price: 2.50
occurred_at: 2026-10-13T14:30:00-05:00
status: FILLED`;
  notice("Synthetic sandbox sample loaded. Nothing has been saved or queued.");
});
async function receiptAction(form, action) {
  const buttons = [...form.querySelectorAll("button")];
  buttons.forEach((button) => { button.disabled = true; });
  try { await action(); }
  catch (error) { if (token) notice(error.message); }
  finally { buttons.forEach((button) => { button.disabled = false; }); }
}
$("receipt-form").addEventListener("submit", (event) => {
  event.preventDefault();
  receiptAction(event.currentTarget, async () => {
    const receipt = await api("receipts", { method: "POST", body: JSON.stringify({text: $("receipt-text").value, broker: $("receipt-broker").value.trim(), environment: $("receipt-environment").value}) });
    showReceipt(receipt);
    await receipts();
    notice(receipt.status === "pending" ? "Saved for review. Nothing queued." : "This receipt was already processed. No additional alert queued.");
  });
});
$("receipt-review").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!selectedReceipt || selectedReceipt.status !== "pending") return;
  const snapshot = Object.fromEntries(reviewFields.map(([key]) => [key, $("review-" + key).value.trim()]));
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(snapshot.occurred_at)) {
    notice("Supply the full fill date and time including year and UTC offset.");
    $("review-occurred_at").focus(); return;
  }
  receiptAction(event.currentTarget, async () => {
    const receipt = await api(`receipts/${encodeURIComponent(selectedReceipt.id)}/confirm`, {method: "POST", body: JSON.stringify({snapshot})});
    showReceipt(receipt);
    await Promise.all([receipts(), history(), status()]);
    notice("Receipt confirmed. Check the result and Activity for queue status.");
  });
});
$("receipt-reject").addEventListener("click", () => {
  if (!selectedReceipt || selectedReceipt.status !== "pending") return;
  receiptAction($("receipt-review"), async () => {
    const receipt = await api(`receipts/${encodeURIComponent(selectedReceipt.id)}/reject`, {method: "POST", body: "{}"});
    showReceipt(receipt); await receipts(); notice("Receipt rejected. Nothing queued.");
  });
});
$("receipt-refresh").addEventListener("click", () => receipts().catch((error) => notice(error.message)));
