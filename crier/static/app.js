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
  const response = await fetch("/api/" + path, {
    ...options,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the fields and try again.",
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
        "Your first confirmed fill will appear here. Sample previews are never added to your activity.",
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
    await Promise.all([status(), history()]);
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
  $("token").focus();
});
