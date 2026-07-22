// Comment review rail rendering helpers. Kept outside app.js so the browser
// shell can stay small while comments grow into their own surface.
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

  function compactPath(raw) {
    const value = String(raw || "").replace(/\\/g, "/");
    if (!value) return "Current view";
    const parts = value.split("/").filter(Boolean);
    return parts.slice(-3).join("/") || value;
  }

  function countLabel(count) {
    return `${count} ${count === 1 ? "comment" : "comments"}`;
  }

  function formatCommentTime(raw) {
    if (!raw) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function renderCommentAnchor(comment) {
    const anchor = comment.anchor;
    if (!anchor || typeof anchor !== "object") return "";
    const label = anchor.label || anchor.excerpt || "captured target";
    return `
      <div class="comment-anchor">
        <button type="button" data-comment-jump="${escapeAttr(comment.id || "")}">Target</button>
        <span>${escapeText(label)}</span>
      </div>`;
  }

  function renderComment(comment) {
    const anchorHTML = renderCommentAnchor(comment);
    const isSteering = String(comment.body || "").trim().toLowerCase().startsWith("@pm");
    return `
      <article class="comment-item ${isSteering ? "is-steering" : ""}" data-comment-id="${escapeAttr(comment.id || "")}">
        <div class="comment-meta">
          <strong>${escapeText(comment.author || "Anonymous")}</strong>
          <span>${escapeText(formatCommentTime(comment.created_at))}</span>
        </div>
        ${anchorHTML}
        <div class="comment-body">${escapeText(comment.body || "").replace(/\n/g, "<br>")}</div>
      </article>`;
  }

  function renderList(comments) {
    if (!comments.length) {
      return `<div class="comment-empty" data-comment-empty="true">No comments yet. Press <kbd>Cmd/Ctrl+Shift+C</kbd> then click a target to annotate.</div>`;
    }
    return comments.map(renderComment).join("");
  }

  window.ViduxCommentRail = {
    countLabel,
    renderList,
    targetLabel: compactPath,
  };
})();
