// Read-only projection of provider-neutral work leases. Host adapters own
// identity and mutation through the local CLI; the browser cannot impersonate
// a worker, run a provider, or take over an active lease.
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

  function escapeText(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  function compact(value, fallback = "") {
    const result = String(value ?? "").replace(/\s+/g, " ").trim();
    return result || fallback;
  }

  function leaseLabel(raw, nowMs = Date.now()) {
    const expires = new Date(raw).getTime();
    if (!Number.isFinite(expires)) return "lease time unknown";
    const seconds = Math.ceil((expires - nowMs) / 1000);
    if (seconds <= 0) return "lease expired";
    if (seconds < 90) return `expires in ${seconds}s`;
    if (seconds < 7200) return `expires in ${Math.ceil(seconds / 60)}m`;
    return `expires in ${Math.ceil(seconds / 3600)}h`;
  }

  function renderActive(active, nowMs = Date.now()) {
    if (!Array.isArray(active) || active.length === 0) {
      return `<div class="coordination-empty">No live owner. Claim a slice before editing.</div>`;
    }
    return active.map(item => {
      const lease = leaseLabel(item.expires_at, nowMs);
      const soon = /expired|\d+s$|in [1-3]m$/.test(lease) ? " is-expiring" : "";
      const work = compact(item.claim, compact(item.task_id, "Unlabelled work surface"));
      const lane = compact(item.lane, compact(item.task_id, "Plan work"));
      const checkpoint = compact(
        typeof item.checkpoint === "object" ? item.checkpoint?.summary : item.checkpoint,
      );
      const resume = compact(item.resume || item.checkpoint?.resume);
      return `
        <article class="coordination-card${soon}" data-coordination-owner="${escapeAttr(item.owner || "")}">
          <div class="coordination-card-head">
            <strong>${escapeText(compact(item.owner, "Unknown owner"))}</strong>
            <span>${escapeText(lease)}</span>
          </div>
          <p class="coordination-lane">${escapeText(lane)}</p>
          <p class="coordination-work">${escapeText(work)}</p>
          ${checkpoint ? `<p class="coordination-checkpoint"><span>Checkpoint</span>${escapeText(checkpoint)}</p>` : ""}
          ${resume ? `<p class="coordination-resume"><span>Resume</span><code>${escapeText(resume)}</code></p>` : ""}
        </article>`;
    }).join("");
  }

  function handoffLabel(status) {
    if (status === "usage_exhausted") return "Usage exhausted";
    if (status === "expired") return "Lease expired";
    if (status === "blocked") return "Blocked handoff";
    if (status === "handoff") return "Ready for takeover";
    if (status === "cancelled") return "Released";
    if (status === "in_progress") return "In progress";
    return "Completed";
  }

  function renderHandoffs(handoffs) {
    const resumable = Array.isArray(handoffs)
      ? handoffs.filter(item => (item.status || item.release_status || item.state) !== "done").slice(0, 6)
      : [];
    if (resumable.length === 0) return "";
    return `
      <div class="coordination-handoffs">
        <h4>Ready to resume</h4>
        ${resumable.map(item => `
          <article class="coordination-handoff is-${escapeAttr(item.status || item.release_status || item.state || "handoff")}">
            <div><strong>${escapeText(handoffLabel(item.status || item.release_status || item.state))}</strong><span>${escapeText(compact(item.owner, "Unknown owner"))}</span></div>
            <p>${escapeText(compact(item.claim, compact(item.task_id, "Plan work")))}</p>
            ${item.checkpoint ? `<p>${escapeText(compact(typeof item.checkpoint === "object" ? item.checkpoint.summary : item.checkpoint))}</p>` : ""}
            ${(item.resume || item.checkpoint?.resume) ? `<code>${escapeText(compact(item.resume || item.checkpoint?.resume))}</code>` : ""}
          </article>`).join("")}
      </div>`;
  }

  function render(planPath) {
    return `
      <section class="coordination-panel" data-coordination-panel data-plan-path="${escapeAttr(planPath)}" data-coordination-state="loading" aria-labelledby="coordination-title">
        <div class="coordination-head">
          <div>
            <p class="coordination-kicker">Shared control room</p>
            <h3 id="coordination-title">Live work</h3>
            <p>Who owns each slice, where they left it, and what is safe to resume.</p>
          </div>
          <span class="coordination-count" data-coordination-count>…</span>
        </div>
        <div class="coordination-active" data-coordination-active aria-live="polite">
          <div class="coordination-empty">Checking live owners…</div>
        </div>
        <div data-coordination-handoffs></div>
      </section>`;
  }

  function currentPanel(planPath) {
    const panel = document.querySelector("[data-coordination-panel]");
    return panel && panel.getAttribute("data-plan-path") === planPath ? panel : null;
  }

  async function refresh(planPath, isCurrent = () => true) {
    const panel = currentPanel(planPath);
    if (!panel || !isCurrent()) return;
    const activeNode = panel.querySelector("[data-coordination-active]");
    const handoffNode = panel.querySelector("[data-coordination-handoffs]");
    const countNode = panel.querySelector("[data-coordination-count]");
    try {
      const res = await fetch(`/api/coordination?plan_path=${encodeURIComponent(planPath)}`);
      if (!res.ok) {
        panel.setAttribute("data-coordination-state", "unavailable");
        replaceHTMLIfChanged(
          activeNode,
          `<div class="coordination-empty">Live work is available only from the local Mac.</div>`,
          "unavailable",
        );
        replaceHTMLIfChanged(handoffNode, "", "unavailable");
        replaceTextIfChanged(countNode, "local only");
        return;
      }
      const data = await res.json();
      const active = Array.isArray(data.active) ? data.active : [];
      const handoffs = Array.isArray(data.handoffs) ? data.handoffs : [];
      const activeHTML = renderActive(active);
      const handoffHTML = renderHandoffs(handoffs);
      panel.setAttribute("data-coordination-state", "ready");
      replaceHTMLIfChanged(activeNode, activeHTML);
      replaceHTMLIfChanged(handoffNode, handoffHTML);
      replaceTextIfChanged(countNode, `${active.length} live`);
    } catch (_error) {
      panel.setAttribute("data-coordination-state", "error");
      replaceHTMLIfChanged(
        activeNode,
        `<div class="coordination-empty">Could not read local coordination state.</div>`,
        "error",
      );
      replaceHTMLIfChanged(handoffNode, "", "error");
      replaceTextIfChanged(countNode, "offline");
    }
  }

  function setup(planPath, options = {}) {
    const isCurrent = typeof options.isCurrent === "function" ? options.isCurrent : () => true;
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

  window.ViduxCoordinationPanel = {
    render,
    renderActive,
    renderHandoffs,
    leaseLabel,
    refresh,
    setup,
  };
})();
