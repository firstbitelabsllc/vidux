// Sidebar ordering helpers for vidux browser. Kept outside app.js so the main
// browser script stays under the source-size smoke limit.
(function () {
  const KEY = "vidux:sidebar-sort";
  const DEFAULT = "mtime";
  const MODES = new Set(["mtime", "eta", "status"]);
  const freshness = { hot: 0, stale: 1, cold: 2 };

  function normalize(mode) {
    return MODES.has(mode) ? mode : DEFAULT;
  }

  function getStored() {
    try {
      return normalize(localStorage.getItem(KEY) || DEFAULT);
    } catch (e) {
      return DEFAULT;
    }
  }

  function store(mode) {
    try {
      localStorage.setItem(KEY, normalize(mode));
    } catch (e) {
      // Sorting still works for the current session when storage is disabled.
    }
  }

  function eta(plan) {
    const stats = plan?.aggregate_stats || plan?.task_stats || {};
    const value = Number(stats.eta_total || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function rank(plan) {
    return freshness[plan?.status] ?? 3;
  }

  function alpha(a, b) {
    return String(a.repo || "").localeCompare(String(b.repo || ""))
      || String(a.slug || "").localeCompare(String(b.slug || ""))
      || String(a.rel || "").localeCompare(String(b.rel || ""));
  }

  function planComparator(mode = DEFAULT) {
    const sortMode = normalize(mode);
    return (a, b) => {
      if (sortMode === "eta") {
        return (eta(b) - eta(a)) || ((b.mtime || 0) - (a.mtime || 0)) || alpha(a, b);
      }
      if (sortMode === "status") {
        return (rank(a) - rank(b)) || ((b.mtime || 0) - (a.mtime || 0)) || alpha(a, b);
      }
      return ((b.mtime || 0) - (a.mtime || 0)) || alpha(a, b);
    };
  }

  function sortedPlans(plans, mode = DEFAULT) {
    return [...plans].sort(planComparator(mode));
  }

  function newest(plans) {
    return plans.reduce((mtime, plan) => Math.max(mtime, plan.mtime || 0), 0);
  }

  function repoComparator(groups, mode = DEFAULT) {
    const sortMode = normalize(mode);
    return (a, b) => {
      const plansA = groups.get(a) || [];
      const plansB = groups.get(b) || [];
      if (sortMode === "eta") {
        const etaA = plansA.reduce((sum, plan) => sum + eta(plan), 0);
        const etaB = plansB.reduce((sum, plan) => sum + eta(plan), 0);
        return (etaB - etaA) || (newest(plansB) - newest(plansA)) || a.localeCompare(b);
      }
      if (sortMode === "status") {
        const rankA = plansA.reduce((best, plan) => Math.min(best, rank(plan)), 3);
        const rankB = plansB.reduce((best, plan) => Math.min(best, rank(plan)), 3);
        return (rankA - rankB) || (newest(plansB) - newest(plansA)) || a.localeCompare(b);
      }
      return (newest(plansB) - newest(plansA)) || a.localeCompare(b);
    };
  }

  window.ViduxSidebarSort = { KEY, DEFAULT, normalize, getStored, store, sortedPlans, repoComparator };
})();
