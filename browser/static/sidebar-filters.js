// Sidebar quick-filter helpers for vidux browser. Kept outside app.js so the
// main browser script stays under the source-size smoke limit.
(function () {
  const KEY = "vidux:sidebar-filter-chips";
  const MODES = ["hot", "tasks", "eta"];
  const MODE_SET = new Set(MODES);
  const LABELS = { hot: "hot", tasks: "tasks", eta: "ETA" };

  function normalize(value) {
    const items = value instanceof Set ? [...value] : (Array.isArray(value) ? value : []);
    return new Set(items.filter(mode => MODE_SET.has(mode)));
  }

  function getStored() {
    try {
      return normalize(JSON.parse(localStorage.getItem(KEY) || "[]"));
    } catch (e) {
      return new Set();
    }
  }

  function store(chips) {
    const active = normalize(chips);
    try {
      localStorage.setItem(KEY, JSON.stringify(MODES.filter(mode => active.has(mode))));
    } catch (e) {
      // Filtering still works for the current session when storage is disabled.
    }
  }

  function stats(plan) {
    return plan?.aggregate_stats || plan?.task_stats || {};
  }

  function eta(plan) {
    const value = Number(stats(plan).eta_total || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function hasTasks(plan) {
    return Number(stats(plan).total || 0) > 0;
  }

  function matches(plan, chips) {
    const active = normalize(chips);
    if (active.has("hot") && plan?.status !== "hot") return false;
    if (active.has("tasks") && !hasTasks(plan)) return false;
    if (active.has("eta") && eta(plan) <= 0) return false;
    return true;
  }

  function active(chips) {
    return normalize(chips).size > 0;
  }

  function summary(chips) {
    return MODES.filter(mode => normalize(chips).has(mode)).map(mode => LABELS[mode]).join(", ");
  }

  function toggle(chips, mode) {
    const next = normalize(chips);
    if (!MODE_SET.has(mode)) return next;
    if (next.has(mode)) next.delete(mode);
    else next.add(mode);
    return next;
  }

  function syncButtons(buttons, chips) {
    const activeChips = normalize(chips);
    for (const button of buttons || []) {
      const pressed = activeChips.has(button.dataset.filterChip);
      button.classList.toggle("is-active", pressed);
      button.setAttribute("aria-pressed", pressed ? "true" : "false");
    }
  }

  window.ViduxSidebarFilters = { KEY, MODES, LABELS, normalize, getStored, store, matches, active, summary, toggle, syncButtons };
})();
