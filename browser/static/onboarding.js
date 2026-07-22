// Pure first-run and authority-state rendering for the Vidux cockpit.
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

  function renderEmpty(onboarding = {}, plans = []) {
    const planCount = plans.length;
    const singlePlan = planCount === 1 ? plans[0] : null;
    const onboardingState = onboarding.state || (planCount === 0 ? "empty" : "needs_brief");
    const projectCount = Number(onboarding.projects_total || 0);
    const title = onboardingState === "empty"
      ? "Connect your first project"
      : (onboardingState === "projects_found"
        ? `${projectCount} ${projectCount === 1 ? "project" : "projects"} found`
        : (singlePlan ? "Set the current goal" : "Choose current work"));
    const copy = onboardingState === "empty"
      ? "No Git projects or PLAN.md files were found under this scan root."
      : (onboardingState === "projects_found"
        ? `${projectCount} Git ${projectCount === 1 ? "project was" : "projects were"} found, but none has a PLAN.md yet.`
        : (singlePlan
          ? "This project has a plan, but it does not yet say what matters next."
          : `${planCount} plans are indexed. Choose one to make its goal and next step explicit.`));
    const action = planCount === 0
      ? `<button class="mission-empty-action" type="button" data-refresh-plans>Scan again</button>`
      : (singlePlan
        ? `<button class="mission-empty-action" type="button" data-dashboard-rel="${escapeAttr(singlePlan.rel)}" data-dashboard-tab="PLAN.md">Open plan</button>`
        : `<button class="mission-empty-action" type="button" data-open-sidebar>Choose a plan</button>`);
    const projectNames = Array.isArray(onboarding.projects)
      ? onboarding.projects.slice(0, 4).map(project => project?.name).filter(Boolean)
      : [];
    const projectLine = onboardingState === "projects_found" && projectNames.length
      ? `<p class="mission-project-list">Found: ${escapeText(projectNames.join(", "))}${onboarding.truncated ? ", and more" : ""}</p>`
      : "";
    const setupGuide = (onboardingState === "empty" || onboardingState === "projects_found")
      ? `<div class="mission-setup-guide">
          <span>Open a terminal in your project</span>
          <code>${escapeText(onboarding.init_command || "vidux init --here")}</code>
          <span>Then return here and scan again.</span>
        </div>`
      : `<p class="mission-brief-hint">Add an <code>Operator Brief</code> with an outcome and next step; Vidux will keep the highest priority in focus.</p>`;
    return `<section class="mission-control is-empty" data-onboarding-state="${escapeAttr(onboardingState)}" aria-label="Mission control">
  <div class="mission-empty-copy">
    <div class="mission-kicker">Setup needed</div>
    <h2>${escapeText(title)}</h2>
    <p>${escapeText(copy)}</p>
    ${projectLine}
    ${setupGuide}
  </div>
  ${action}
</section>`;
  }

  function renderAuthority(authority = {}) {
    if (authority.state !== "conflict") return "";
    return `<div class="mission-authority-note" role="status">
        <div>
          <div class="mission-section-label">Current-work tie</div>
          <p>${escapeText(authority.explanation || "More than one plan claims the same priority.")}</p>
        </div>
        <button type="button" data-open-sidebar>Compare plans</button>
      </div>`;
  }

  window.ViduxOnboarding = { renderEmpty, renderAuthority };
})();
