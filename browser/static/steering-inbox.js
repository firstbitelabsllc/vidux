// Provider-neutral one-shot steering UI. Queue mechanics live behind the local
// /api/steering boundary; this module never invokes a model, runner, or shell.
(function () {
  let pollTimer = 0;
  const renderSignatures = new WeakMap();

  function replaceHTMLIfChanged(node, html, signature = html) {
    if (!node || renderSignatures.get(node) === signature) return false;
    node.innerHTML = html;
    renderSignatures.set(node, signature);
    return true;
  }

  function replaceTextIfChanged(node, text) {
    if (!node || node.textContent === text) return false;
    node.textContent = text;
    return true;
  }

  const FAILURE_COPY = {
    usage_exhausted: "Usage window exhausted. The goal may still be running; this steer was not delivered.",
    transport_unavailable: "The response transport was unavailable. Your steer is still here.",
    lease_expired: "No response was confirmed before the handling lease expired.",
    response_unconfirmed: "The host could not confirm a reply, so this steer was kept.",
    consumer_crash: "The handling process stopped before a reply was confirmed.",
    policy_blocked: "This steer was blocked by the active policy boundary.",
    invalid_intent: "This steer could not be applied safely.",
  };

  function escapeText(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  function formatTime(raw) {
    if (!raw) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return String(raw);
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function render(planPath) {
    return `
      <section class="steering-inbox" data-steering-inbox data-plan-path="${escapeAttr(planPath)}" data-steering-state="loading" aria-labelledby="steering-title">
        <div class="steering-head">
          <div>
            <p class="steering-kicker">One-shot intent</p>
            <h3 id="steering-title">Steer next turn</h3>
            <p>Queued locally for the next safe loop boundary. This does not send a chat message.</p>
          </div>
          <span class="steering-capacity" data-steering-capacity>…</span>
        </div>
        <form class="steering-composer" data-steering-form>
          <label class="visually-hidden" for="steering-message">Steer the next loop turn</label>
          <textarea id="steering-message" name="message" rows="2" maxlength="8192" placeholder="What should the running goal consider next?"></textarea>
          <div class="steering-compose-actions">
            <span>⌘/Ctrl + Enter</span>
            <button type="submit">Queue steer</button>
          </div>
        </form>
        <p class="steering-write-status" data-steering-write-status role="status" aria-live="polite"></p>
        <div class="steering-items" data-steering-items aria-live="polite">
          <div class="steering-empty">Checking for queued intent…</div>
        </div>
      </section>`;
  }

  function statusLabel(status) {
    if (status === "claimed") return "Being handled";
    if (status === "retryable") return "Retry needed";
    if (status === "failed") return "Needs attention";
    return "Queued";
  }

  function renderItems(items) {
    if (!Array.isArray(items) || items.length === 0) {
      return `<div class="steering-empty">No steer waiting. The loop continues from its plan.</div>`;
    }
    return items.map(item => {
      const status = ["queued", "claimed", "retryable", "failed"].includes(item.status)
        ? item.status
        : "failed";
      const failure = item.failure_code
        ? (FAILURE_COPY[item.failure_code] || "The steer was not acknowledged and remains visible.")
        : "";
      const retry = status === "retryable"
        ? `<button type="button" data-steering-action="retry" data-steering-id="${escapeAttr(item.id || "")}">Retry</button>`
        : "";
      const dismiss = ["queued", "retryable", "failed"].includes(status)
        ? `<button type="button" class="is-quiet" data-steering-action="dismiss" data-steering-id="${escapeAttr(item.id || "")}">Dismiss</button>`
        : "";
      return `
        <article class="steering-item is-${status}" data-steering-id="${escapeAttr(item.id || "")}" data-steering-status="${status}">
          <div class="steering-item-head">
            <span class="steering-state">${escapeText(statusLabel(status))}</span>
            <span class="steering-time">${escapeText(formatTime(item.created_at))}</span>
          </div>
          <p>${escapeText(item.message || "")}</p>
          ${failure ? `<p class="steering-failure">${escapeText(failure)}</p>` : ""}
          ${(retry || dismiss) ? `<div class="steering-item-actions">${retry}${dismiss}</div>` : ""}
        </article>`;
    }).join("");
  }

  function currentPanel(planPath) {
    const panel = document.querySelector("[data-steering-inbox]");
    return panel && panel.getAttribute("data-plan-path") === planPath ? panel : null;
  }

  async function refresh(planPath, isCurrent = () => true) {
    const panel = currentPanel(planPath);
    if (!panel || !isCurrent()) return;
    const items = panel.querySelector("[data-steering-items]");
    const capacity = panel.querySelector("[data-steering-capacity]");
    try {
      const res = await fetch(`/api/steering?plan_path=${encodeURIComponent(planPath)}`);
      if (!res.ok) {
        const message = res.status === 403
          ? "Steering is available only from the local Mac."
          : `Steering unavailable (${res.status}).`;
        panel.setAttribute("data-steering-state", "unavailable");
        panel.querySelector("[data-steering-form]")?.setAttribute("hidden", "");
        replaceHTMLIfChanged(
          items,
          `<div class="steering-empty">${escapeText(message)}</div>`,
          `unavailable:${res.status}`,
        );
        replaceTextIfChanged(capacity, "local only");
        return;
      }
      const data = await res.json();
      const activeItems = Array.isArray(data.items) ? data.items : [];
      const itemsHTML = renderItems(activeItems);
      panel.setAttribute("data-steering-state", "ready");
      panel.querySelector("[data-steering-form]")?.removeAttribute("hidden");
      replaceHTMLIfChanged(items, itemsHTML);
      replaceTextIfChanged(capacity, `${activeItems.length}/${Number(data.capacity || 8)} active`);
    } catch (_error) {
      panel.setAttribute("data-steering-state", "error");
      replaceHTMLIfChanged(
        items,
        `<div class="steering-empty">Could not read local steering state.</div>`,
        "error",
      );
      replaceTextIfChanged(capacity, "offline");
    }
  }

  async function postAction(planPath, payload, statusNode, isCurrent) {
    const res = await fetch("/api/steering", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_path: planPath, ...payload }),
    });
    if (!res.ok) throw new Error((await res.text()) || `request failed (${res.status})`);
    if (statusNode) {
      statusNode.textContent = payload.action === "enqueue"
        ? "Queued for the next safe boundary."
        : "Steering state updated.";
    }
    await refresh(planPath, isCurrent);
  }

  function setup(planPath, options = {}) {
    const panel = currentPanel(planPath);
    if (!panel) return;
    const isCurrent = typeof options.isCurrent === "function" ? options.isCurrent : () => true;
    const form = panel.querySelector("[data-steering-form]");
    const textarea = form?.querySelector("textarea");
    const statusNode = panel.querySelector("[data-steering-write-status]");
    const submit = form?.querySelector('button[type="submit"]');
    let writing = false;

    const submitSteer = async () => {
      if (writing) return;
      const message = String(textarea?.value || "").trim();
      if (!message || !form || !textarea) {
        if (statusNode) statusNode.textContent = "Write a steer first.";
        return;
      }
      writing = true;
      if (submit) submit.disabled = true;
      if (statusNode) statusNode.textContent = "Queueing locally…";
      try {
        await postAction(planPath, { action: "enqueue", message, source: "vidux-cockpit" }, statusNode, isCurrent);
        textarea.value = "";
        textarea.focus();
      } catch (error) {
        if (statusNode) statusNode.textContent = String(error.message || error);
      } finally {
        writing = false;
        if (submit) submit.disabled = false;
      }
    };

    form?.addEventListener("submit", event => {
      event.preventDefault();
      submitSteer();
    });
    textarea?.addEventListener("keydown", event => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        submitSteer();
      }
    });
    panel.addEventListener("click", async event => {
      const button = event.target.closest?.("[data-steering-action]");
      if (!button) return;
      const action = button.getAttribute("data-steering-action");
      const id = button.getAttribute("data-steering-id");
      if (!action || !id) return;
      button.disabled = true;
      try {
        await postAction(planPath, { action, id }, statusNode, isCurrent);
      } catch (error) {
        if (statusNode) statusNode.textContent = String(error.message || error);
        button.disabled = false;
      }
    });

    refresh(planPath, isCurrent);
    if (pollTimer) window.clearInterval(pollTimer);
    pollTimer = window.setInterval(() => {
      if (!isCurrent()) {
        window.clearInterval(pollTimer);
        pollTimer = 0;
        return;
      }
      refresh(planPath, isCurrent);
    }, 5000);
  }

  function isBusy(documentRef = document) {
    const composer = documentRef.querySelector("[data-steering-form] textarea");
    return Boolean(composer && (documentRef.activeElement === composer || String(composer.value || "").trim()));
  }

  window.ViduxSteeringInbox = { render, renderItems, refresh, setup, isBusy };
})();
