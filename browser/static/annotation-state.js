(function () {
  const STATES = {
    UNAVAILABLE: "unavailable",
    IDLE: "idle",
    CAPTURE_ACTIVE: "capture-active",
    TARGET_PICKED: "target-picked",
    COMPOSER_OPEN: "composer-open",
    SAVING: "saving",
    SAVED: "saved",
    ERROR: "error",
  };
  const ACTIVE = new Set([
    STATES.CAPTURE_ACTIVE,
    STATES.TARGET_PICKED,
    STATES.COMPOSER_OPEN,
    STATES.SAVING,
    STATES.SAVED,
    STATES.ERROR,
  ]);
  const VIEW = {
    [STATES.UNAVAILABLE]: ["Annotate", "Select a plan or artifact to annotate"],
    [STATES.IDLE]: ["Annotate", "Annotate selected view", "Annotate selected view (Cmd/Ctrl+Shift+C)"],
    [STATES.CAPTURE_ACTIVE]: ["Cancel", "Cancel annotation target capture"],
    [STATES.TARGET_PICKED]: ["Retarget", "Annotation target picked; retarget"],
    [STATES.COMPOSER_OPEN]: ["Retarget", "Annotation composer open; retarget"],
    [STATES.SAVING]: ["Saving", "Saving annotation comment"],
    [STATES.SAVED]: ["Saved", "Annotation comment saved"],
    [STATES.ERROR]: ["Retry", "Annotation save failed; retry target capture"],
  };

  function derive({ currentTarget, targetPath, phase, capture, anchor, popoverOpen }) {
    if (!currentTarget) return STATES.UNAVAILABLE;
    if (targetPath !== currentTarget) return STATES.IDLE;
    if (phase === STATES.SAVING || phase === STATES.SAVED || phase === STATES.ERROR) return phase;
    if (capture) return STATES.CAPTURE_ACTIVE;
    if (popoverOpen) return STATES.COMPOSER_OPEN;
    if (anchor) return STATES.TARGET_PICKED;
    return STATES.IDLE;
  }

  function paintButton(button, state) {
    if (!button) return;
    const view = VIEW[state] || VIEW[STATES.IDLE];
    const active = ACTIVE.has(state);
    button.dataset.annotationState = state;
    button.disabled = state === STATES.UNAVAILABLE || state === STATES.SAVING;
    button.textContent = view[0];
    button.classList.toggle("is-active", active);
    button.classList.toggle("is-saving", state === STATES.SAVING);
    button.classList.toggle("is-saved", state === STATES.SAVED);
    button.classList.toggle("is-error", state === STATES.ERROR);
    button.setAttribute("aria-pressed", String(active));
    button.setAttribute("aria-label", view[1]);
    button.title = view[2] || view[1];
  }

  window.ViduxAnnotationState = { STATES, derive, paintButton };
})();
