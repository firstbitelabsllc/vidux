// Compact marker/target-map renderer for existing annotation comments.
(function () {
  const STORAGE_KEY = "vidux:comment-markers-hidden";
  const HIGHLIGHT_DURATION_MS = 2200;
  let activePreview = null;
  let previewedTargets = [];
  const highlightTimers = new WeakMap();

  function escapeText(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function compact(value, limit = 90) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
  }

  function getStoredHidden() {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  }

  function setStoredHidden(hidden) {
    try {
      localStorage.setItem(STORAGE_KEY, hidden ? "true" : "false");
    } catch {
      // localStorage may be unavailable in constrained browser contexts.
    }
  }

  function clearPreviews() {
    if (!activePreview) {
      previewedTargets = [];
      return;
    }
    previewedTargets.forEach(target => activePreview(target, false));
    previewedTargets = [];
  }

  function clear(options = {}) {
    clearPreviews();
    const doc = options.document || document;
    doc.querySelectorAll(".comment-marker-layer").forEach(layer => layer.remove());
  }

  function updateToggle(button, hidden) {
    if (!button) return;
    button.textContent = hidden ? "Show" : "Hide";
    button.title = hidden ? "Show annotation markers" : "Hide annotation markers";
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-pressed", hidden ? "false" : "true");
    button.setAttribute("data-comment-markers-hidden", hidden ? "true" : "false");
  }

  function renderPanel(targetPath, hidden, targetLabel) {
    return `
      <section class="comments-panel annotation-review-rail" id="comments-panel" data-vidux-zone="mode-detail" data-target-path="${escapeText(targetPath)}" data-comment-scope="current-view" data-comment-state="loading" data-comment-count="0" data-comment-target-count="0" data-comment-markers-hidden="${hidden ? "true" : "false"}" data-active-filter="all" aria-labelledby="comments-panel-title">
        <div class="comments-head">
          <div>
            <h3 id="comments-panel-title">Comments</h3>
            <p>${escapeText(targetLabel)}</p>
          </div>
          <div class="comments-tools">
            <span class="comment-count" id="comment-count">loading</span>
            <button type="button" class="comment-marker-toggle" id="comment-markers-toggle" data-comment-marker-toggle aria-pressed="${hidden ? "false" : "true"}">${hidden ? "Show" : "Hide"}</button>
          </div>
        </div>
        <div class="comment-filter-row" role="group" aria-label="Comment filters" data-comment-filters>
          <button type="button" class="comment-filter is-active" data-comment-filter="all" aria-pressed="true">All</button>
          <button type="button" class="comment-filter" data-comment-filter="open" aria-pressed="false" disabled>Open</button>
          <button type="button" class="comment-filter" data-comment-filter="mine" aria-pressed="false" disabled>Mine</button>
        </div>
        <div class="comment-target-map" id="comment-target-map" data-comment-target-map data-comment-target-count="0"></div>
        <div class="comment-list" id="comment-list" data-comment-list></div>
      </section>`;
  }

  function bindToggle(panel, hidden, onChange) {
    const button = panel?.querySelector("[data-comment-marker-toggle]");
    updateToggle(button, hidden);
    if (!button) return;
    button.addEventListener("click", () => {
      const next = button.getAttribute("data-comment-markers-hidden") !== "true";
      setStoredHidden(next);
      updateToggle(button, next);
      if (onChange) onChange(next);
    });
  }

  function visibleRect(rect) {
    if (!rect || (!rect.width && !rect.height)) return false;
    return [rect.top, rect.right, rect.bottom, rect.left].every(Number.isFinite);
  }

  function markerPosition(rect) {
    const left = Math.min(Math.max(rect.right - 10, 8), window.innerWidth - 34);
    const top = Math.min(Math.max(rect.top - 8, 8), window.innerHeight - 34);
    return { left: Math.round(left), top: Math.round(top) };
  }

  function groupLabel(group) {
    return compact(group.label || group.comments[0]?.anchor?.label || "Target", 72);
  }

  function safeQuery(root, selector) {
    if (!root || !selector) return null;
    try {
      return root.querySelector(selector);
    } catch {
      return null;
    }
  }

  function accessibleArtifactFrames(doc) {
    return [...doc.querySelectorAll("iframe.artifact-frame")].map(frame => {
      try {
        const frameDoc = frame.contentDocument;
        return frameDoc && frameDoc.body ? { frame, doc: frameDoc } : null;
      } catch {
        return null;
      }
    }).filter(Boolean);
  }

  function rectForAnchorElement(element, frame) {
    const rect = element.getBoundingClientRect();
    if (!frame) return rect;
    const frameRect = frame.getBoundingClientRect();
    return {
      left: frameRect.left + rect.left,
      top: frameRect.top + rect.top,
      right: frameRect.left + rect.right,
      bottom: frameRect.top + rect.bottom,
      width: rect.width,
      height: rect.height,
    };
  }

  function ensureFrameAnchorStyle(frame) {
    try {
      const doc = frame.contentDocument;
      if (!doc || doc.getElementById("vidux-anchor-visual-style")) return;
      const style = doc.createElement("style");
      style.id = "vidux-anchor-visual-style";
      style.textContent = ".is-anchor-highlight,.is-anchor-preview{outline:2px solid #2f6df6!important;outline-offset:3px!important;background:rgba(47,109,246,.12)!important;transition:background .18s ease-out,outline-color .18s ease-out!important;}";
      doc.head.appendChild(style);
    } catch {
      // Cross-origin frames are skipped; srcdoc artifacts are readable.
    }
  }

  function labelForResolvedAnchor(element, frame, anchor, options) {
    if (anchor?.label) return anchor.label;
    if (!frame && options.hostLabel) return options.hostLabel(element);
    return compact(element.innerText || element.textContent || element.getAttribute("aria-label") || element.tagName.toLowerCase(), 120);
  }

  function buildResolvedAnchor(element, frame, anchor, options) {
    if (!element) return null;
    if (frame) ensureFrameAnchorStyle(frame);
    return {
      element,
      frame,
      rect: rectForAnchorElement(element, frame),
      label: labelForResolvedAnchor(element, frame, anchor, options),
      key: element,
    };
  }

  function findExcerptAnchor(root, excerpt) {
    if (!root || !excerpt) return null;
    const candidates = root.querySelectorAll("[data-vidux-anchor],h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,table,tr,th,td,article,section,main,aside,header,footer,figure,figcaption,details,summary,div,span,a,button");
    return [...candidates].find(el => {
      const text = compact(el.innerText || el.textContent || "", 180);
      return text.includes(excerpt) || excerpt.includes(text);
    }) || null;
  }

  function resolveAnchorTarget(anchor, options = {}) {
    const doc = options.document || document;
    if (!anchor) return null;
    if (anchor.selector) {
      const found = safeQuery(doc, anchor.selector);
      if (found) return buildResolvedAnchor(found, null, anchor, options);
      for (const { frame, doc: frameDoc } of accessibleArtifactFrames(doc)) {
        const frameFound = safeQuery(frameDoc, anchor.selector);
        if (frameFound) return buildResolvedAnchor(frameFound, frame, anchor, options);
      }
    }
    const excerpt = compact(anchor.excerpt || anchor.label || "", 120);
    if (!excerpt) return null;
    const found = findExcerptAnchor(doc, excerpt);
    if (found) return buildResolvedAnchor(found, null, anchor, options);
    for (const { frame, doc: frameDoc } of accessibleArtifactFrames(doc)) {
      const frameFound = findExcerptAnchor(frameDoc, excerpt);
      if (frameFound) return buildResolvedAnchor(frameFound, frame, anchor, options);
    }
    return null;
  }

  function setHighlight(target, enabled) {
    const element = target?.element || target;
    if (!element || !element.classList) return;
    if (target?.frame) ensureFrameAnchorStyle(target.frame);
    if (!enabled) {
      const timer = highlightTimers.get(element);
      if (timer !== undefined) clearTimeout(timer);
      highlightTimers.delete(element);
    }
    element.classList.toggle("is-anchor-highlight", Boolean(enabled));
  }

  function jumpToTarget(target, options = {}) {
    if (!target) return;
    if (target.frame) target.frame.scrollIntoView({ block: "center", behavior: "smooth" });
    target.element.scrollIntoView({ block: "center", behavior: "smooth" });
    const previousTimer = highlightTimers.get(target.element);
    if (previousTimer !== undefined) {
      clearTimeout(previousTimer);
      highlightTimers.delete(target.element);
    }
    setHighlight(target, true);
    const duration = Number.isFinite(options.highlightDuration)
      ? Math.max(0, options.highlightDuration)
      : HIGHLIGHT_DURATION_MS;
    if (!duration) return;
    const timer = setTimeout(() => {
      setHighlight(target, false);
    }, duration);
    highlightTimers.set(target.element, timer);
  }

  function setPreview(target, enabled) {
    const element = target?.element || target;
    if (!element || !element.classList) return;
    if (target?.frame) ensureFrameAnchorStyle(target.frame);
    element.classList.toggle("is-anchor-preview", Boolean(enabled));
  }

  function renderTargetMap(container, groups, hidden, options) {
    if (!container) return;
    container.setAttribute("data-comment-target-count", String(groups.length));
    container.setAttribute("data-comment-markers-hidden", hidden ? "true" : "false");
    if (!groups.length) {
      container.innerHTML = '<span class="comment-target-map-empty">No anchored targets.</span>';
      return;
    }
    const body = groups.map((group, index) => {
      const label = groupLabel(group);
      const count = group.comments.length;
      return `
        <button type="button" class="comment-target-chip" data-comment-target-jump="${index}">
          <span>${escapeText(label)}</span>
          <strong>${count}</strong>
        </button>`;
    }).join("");
    container.innerHTML = `
      <span class="comment-target-map-label">Targets</span>
      <div class="comment-target-chips">${body}</div>`;
    container.querySelectorAll("[data-comment-target-jump]").forEach(button => {
      button.addEventListener("mouseenter", () => {
        const group = groups[Number(button.getAttribute("data-comment-target-jump"))];
        if (group && options.preview) {
          activePreview = options.preview;
          options.preview(group.target, true);
          previewedTargets.push(group.target);
        }
      });
      button.addEventListener("mouseleave", () => {
        const group = groups[Number(button.getAttribute("data-comment-target-jump"))];
        if (group && options.preview) options.preview(group.target, false);
      });
      button.addEventListener("click", () => {
        const group = groups[Number(button.getAttribute("data-comment-target-jump"))];
        if (group && options.jump) options.jump(group.comments[0].anchor);
      });
    });
  }

  function collectGroups(comments, resolve) {
    const grouped = new Map();
    comments.forEach(comment => {
      if (!comment || !comment.anchor) return;
      const target = resolve ? resolve(comment.anchor) : null;
      if (!target || !target.element || !target.rect) return;
      const key = target.key || target.element;
      if (!grouped.has(key)) {
        grouped.set(key, {
          target,
          label: target.label || comment.anchor.label,
          comments: [],
        });
      }
      grouped.get(key).comments.push(comment);
    });
    return [...grouped.values()].sort((a, b) => {
      const top = a.target.rect.top - b.target.rect.top;
      return top || a.target.rect.left - b.target.rect.left;
    });
  }

  function render(options = {}) {
    const doc = options.document || document;
    clear({ document: doc });
    const comments = Array.isArray(options.comments) ? options.comments : [];
    const hidden = Boolean(options.hidden);
    const groups = collectGroups(comments, options.resolve);
    if (options.panel) {
      options.panel.setAttribute("data-comment-markers-hidden", hidden ? "true" : "false");
      options.panel.setAttribute("data-comment-target-count", String(groups.length));
    }
    renderTargetMap(options.targetMap, groups, hidden, options);
    if (hidden || !groups.length) return { targets: groups.length, markers: 0 };

    const layer = doc.createElement("div");
    layer.id = "comment-marker-layer";
    layer.className = "comment-marker-layer";
    layer.setAttribute("data-comment-marker-layer", "");
    doc.body.appendChild(layer);

    let markers = 0;
    groups.forEach((group, index) => {
      const rect = group.target.rect;
      if (!visibleRect(rect)) return;
      const pos = markerPosition(rect);
      const count = group.comments.length;
      const label = groupLabel(group);
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "comment-marker";
      button.setAttribute("data-comment-marker", "");
      button.setAttribute("data-comment-marker-index", String(index));
      button.setAttribute("data-comment-marker-count", String(count));
      button.setAttribute("aria-label", `${count} comment${count === 1 ? "" : "s"} on ${label}`);
      button.title = `${count} comment${count === 1 ? "" : "s"} on ${label}`;
      button.style.left = `${pos.left}px`;
      button.style.top = `${pos.top}px`;
      button.innerHTML = `
        <span class="comment-marker-dot"></span>
        <span class="comment-marker-count">${count}</span>`;
      button.addEventListener("mouseenter", () => {
        if (options.preview) {
          activePreview = options.preview;
          options.preview(group.target, true);
          previewedTargets.push(group.target);
        }
      });
      button.addEventListener("mouseleave", () => {
        if (options.preview) options.preview(group.target, false);
      });
      button.addEventListener("click", () => {
        if (options.jump) options.jump(group.comments[0].anchor);
      });
      layer.appendChild(button);
      markers += 1;
    });
    return { targets: groups.length, markers };
  }

  window.ViduxCommentMarkers = {
    getStoredHidden,
    setStoredHidden,
    updateToggle,
    bindToggle,
    renderPanel,
    HIGHLIGHT_DURATION_MS,
    ensureFrameAnchorStyle,
    resolveAnchorTarget,
    jumpToTarget,
    setHighlight,
    setPreview,
    clear,
    render,
  };
})();
