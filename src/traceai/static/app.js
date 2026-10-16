"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let session = 0;
  const labels = {"interaction.started": "Interaction started", "model.output_generated": "Model output generated", "review.completed": "Human review completed", "interaction.completed": "Interaction completed", "interaction.stopped": "Interaction stopped", "record.corrected": "Record corrected"};
  function feedback(id, message, error = false) {
    $(id).textContent = message;
    $(id).className = `feedback ${error ? "error" : "success"}`;
  }
  function clearHistory() {
    $("interaction-result").hidden = true;
    $("empty-state").hidden = false;
    $("event-list").replaceChildren();
    $("result-id").textContent = "";
    $("result-status").textContent = "";
    $("event-count").textContent = "";
  }
  async function api(path, options = {}) {
    if (!token) throw new Error("Connect your API token in step 1 first.");
    const response = await fetch(path, {...options, headers: {...options.headers, Authorization: `Bearer ${token}`}, cache: "no-store", redirect: "error"});
    if (response.status === 401) throw new Error("The API token was rejected. Check the token in your Render service settings and reconnect.");
    if (response.status === 404) throw new Error("No records were found for that interaction ID.");
    if (response.status === 409) throw new Error("That event ID already exists with different content. Use a new event ID.");
    if (response.status === 413) throw new Error("The event exceeds the 64 KiB request limit.");
    if (response.status === 422) throw new Error("The event was rejected. Check the UTC timestamp, required fields, and event-specific data.");
    if (response.status === 503) throw new Error("Storage is unavailable. Try again once the service is healthy.");
    if (!response.ok) throw new Error(`The request could not be completed (HTTP ${response.status}).`);
    return response.json();
  }
  async function health() {
    $("refresh-health").disabled = true;
    try {
      const response = await fetch("/health", {cache: "no-store", redirect: "error"});
      const data = await response.json();
      const healthy = response.ok && data.status === "healthy" && data.storage === "available";
      $("health-label").textContent = healthy ? "Service healthy" : "Service needs attention";
      $("health-detail").textContent = healthy ? "API available · PostgreSQL connected" : "Storage may be unavailable. Try refreshing shortly.";
      $("health-dot").className = `dot ${healthy ? "good" : "bad"}`;
    } catch {
      $("health-label").textContent = "Unable to reach service";
      $("health-detail").textContent = "Check your connection. A sleeping service may take a moment to start.";
      $("health-dot").className = "dot bad";
    } finally { $("refresh-health").disabled = false; }
  }
  $("refresh-health").addEventListener("click", health);
  $("connection-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const candidate = $("api-token").value.trim();
    if (!candidate) return;
    token = candidate;
    session++;
    $("api-token").value = "";
    $("api-token").required = false;
    $("connection-status").textContent = "Token set · checked when you submit or find events";
    $("disconnect").hidden = false;
    clearHistory();
    feedback("lookup-status", "");
    feedback("submit-status", "");
  });
  $("disconnect").addEventListener("click", () => {
    token = "";
    session++;
    $("api-token").value = "";
    $("api-token").required = true;
    $("connection-status").textContent = "No token connected";
    $("disconnect").hidden = true;
    clearHistory();
    feedback("lookup-status", "");
    feedback("submit-status", "");
  });
  $("fill-example").addEventListener("click", () => {
    const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    $("event-id").value = `evt-${id}`;
    $("interaction-id").value = `demo-${id.slice(0, 8)}`;
    $("event-type").value = "interaction.started";
    $("occurred-at").value = new Date().toISOString();
    $("model-version").value = "model-1";
    $("application-version").value = "app-1";
    $("event-data").value = JSON.stringify({note: "Synthetic classroom example"}, null, 2);
    $("lookup-id").value = $("interaction-id").value;
    dataHint();
    feedback("submit-status", "Example filled. Connect a token, then select Store event. Nothing has been submitted yet.");
  });
  function dataHint() {
    const type = $("event-type").value;
    $("data-help").textContent = type === "review.completed" ? 'Include reviewerId, action (accept, override, reject, or escalate), and reason in the JSON object.' : type === "record.corrected" ? 'Include correctsEventId and reason. Phase 3 records the correction; it does not apply it to the original event.' : 'Optional details go inside this JSON object. An empty object is valid for this event type.';
  }
  $("event-type").addEventListener("change", dataHint);
  $("occurred-at").value = new Date().toISOString();
  $("event-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const currentSession = session;
    const button = $("submit-event");
    button.disabled = true;
    feedback("submit-status", "Storing event…");
    try {
      const raw = $("event-data").value;
      let data;
      try { data = JSON.parse(raw); } catch { throw new Error('Event data must be valid JSON, for example {"note":"Synthetic example"}.'); }
      if (data === null || Array.isArray(data) || typeof data !== "object") throw new Error("Event data must be a JSON object, not an array or a single value.");
      const fields = {eventId: $("event-id").value, interactionId: $("interaction-id").value, eventType: $("event-type").value, occurredAt: $("occurred-at").value, modelVersion: $("model-version").value, applicationVersion: $("application-version").value};
      // Keep the original data JSON so submitted high-precision numbers are not rounded by JavaScript.
      const body = JSON.stringify(fields).slice(0, -1) + ',"data":' + raw + '}';
      if (new TextEncoder().encode(body).length > 65536) throw new Error("The event exceeds the 64 KiB request limit.");
      const receipt = await api("/api/v1/events", {method: "POST", headers: {"Content-Type": "application/json"}, body});
      if (currentSession !== session) return;
      feedback("submit-status", receipt.duplicate ? `Event ${receipt.eventId} was already stored. No duplicate was created.` : `Stored event ${receipt.eventId}. Find interaction ${receipt.interactionId} to view it.`);
      $("lookup-id").value = fields.interactionId;
    } catch (error) {
      if (currentSession === session) feedback("submit-status", error instanceof TypeError ? "Unable to reach the service. Check your connection and try again." : error.message, true);
    } finally { button.disabled = false; }
  });
  function textElement(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  }
  function renderInteraction(data) {
    $("result-id").textContent = data.interactionId;
    $("result-status").textContent = data.status.replaceAll("_", " ");
    $("event-count").textContent = `${data.events.length} stored event${data.events.length === 1 ? "" : "s"}`;
    $("event-list").replaceChildren();
    data.events.forEach((event, index) => {
      const card = textElement("article", "event-card", "");
      const top = textElement("div", "event-top", "");
      top.append(textElement("span", "event-type", labels[event.eventType] || event.eventType), textElement("span", "event-number", `EVENT ${String(index + 1).padStart(2, "0")}`));
      card.append(top, textElement("div", "event-time", event.occurredAt), textElement("div", "event-id", event.eventId));
      const details = document.createElement("details");
      details.append(textElement("summary", "", "View event details"), textElement("div", "", `Model: ${event.modelVersion} · Application: ${event.applicationVersion}`), textElement("pre", "", JSON.stringify(event.data, null, 2)));
      card.append(details);
      $("event-list").append(card);
    });
    $("empty-state").hidden = true;
    $("interaction-result").hidden = false;
  }
  $("lookup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const currentSession = session;
    $("lookup-button").disabled = true;
    clearHistory();
    feedback("lookup-status", "Finding stored events…");
    try {
      const data = await api(`/api/v1/interactions/${encodeURIComponent($("lookup-id").value)}`);
      if (currentSession !== session) return;
      renderInteraction(data);
      feedback("lookup-status", "Retrieved from the connected database.");
    } catch (error) {
      if (currentSession === session) feedback("lookup-status", error instanceof TypeError ? "Unable to reach the service. Check your connection and try again." : error.message, true);
    } finally { $("lookup-button").disabled = false; }
  });
  window.addEventListener("pagehide", () => $("disconnect").click());
  health();
})();
