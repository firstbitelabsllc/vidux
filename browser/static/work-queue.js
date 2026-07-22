// Pure rendering for the bounded Simple-mode cross-project work queue.
(function () {
  function escapeText(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  function shortPath(value) {
    const parts = String(value || "").replace(/\\/g, "/").split("/").filter(Boolean);
    return parts.slice(-2).join("/");
  }

  function items(category, excludedRel, limit = 8) {
    if (Array.isArray(category?.simple_items)) {
      return category.simple_items.slice(0, limit);
    }
    return (category?.items || [])
      .filter(item => item?.rel && item.rel !== excludedRel)
      .slice(0, limit);
  }

  function metadata(item) {
    return [
      item.owner ? `Owner ${item.owner}` : "",
      item.blocker ? `Blocked by ${item.blocker}` : "",
      item.validation ? `Check ${item.validation}` : "",
      item.proof ? `Proof ${shortPath(item.proof)}` : "",
    ].filter(Boolean).join(" · ");
  }

  function renderList(title, category, selectedRel, emptyText) {
    const shown = items(category, selectedRel);
    const excluded = (category?.items || []).filter(item => item?.rel === selectedRel).length;
    const fallbackTotal = Number(category?.total || 0) - excluded;
    const total = Math.max(shown.length, Number(category?.simple_total ?? fallbackTotal));
    const rows = shown.length
      ? shown.map(item => {
        const meta = metadata(item);
        const severity = item.severity && item.severity !== "unspecified"
          ? item.severity.toUpperCase()
          : "→";
        return `<button class="simple-queue-row" type="button" data-dashboard-rel="${escapeAttr(item.rel)}" data-dashboard-tab="${escapeAttr(item.tab || "PLAN.md")}" title="${escapeAttr(item.label || "Open plan")}">
        <span class="simple-queue-project">${escapeText(item.repo || "Project")}</span>
        <span class="simple-queue-copy">
          <strong>${escapeText(item.label || "Open plan")}</strong>
          ${meta ? `<small>${escapeText(meta)}</small>` : ""}
        </span>
        <span class="simple-queue-severity severity-${escapeAttr(item.severity || "unspecified")}">${escapeText(severity)}</span>
      </button>`;
      }).join("")
      : `<p>${escapeText(emptyText)}</p>`;
    const count = total ? `${shown.length} of ${total}` : "0";
    const viewAll = total > shown.length
      ? `<button class="simple-queue-view-all" type="button" data-view-all-work>View all</button>`
      : "";
    return `<section class="simple-queue-list">
    <div class="simple-queue-list-head"><h3>${escapeText(title)}</h3><span>${escapeText(count)}</span></div>
    ${rows}${viewAll}
  </section>`;
  }

  function render(categories = {}, selectedRel = "") {
    const category = key => categories[key] || { items: [], total: 0 };
    return `<section class="simple-queue" aria-label="Project work queue">
    <header><div class="mission-section-label">Across projects</div><h2>Next, resume, or unblock</h2></header>
    <div class="simple-queue-grid">
      ${renderList("Next", category("next"), selectedRel, "No urgent work is queued.")}
      ${renderList("Resume", category("in_progress"), selectedRel, "Nothing else is in progress.")}
      ${renderList("Needs attention", category("blocked"), selectedRel, "No other work is blocked.")}
    </div>
  </section>`;
  }

  window.ViduxWorkQueue = { items, metadata, render };
})();
