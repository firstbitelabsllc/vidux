# Browser UI

A local browser surface for inspecting plans across `DEV_ROOT`, scanning the cross-plan fleet queue, reading sibling docs, adding named or anchored comments, dropping bounded local notes into a plan's `INBOX.md`, and queueing transient next-turn direction for an existing goal or loop.

## What ships

- `bin/vidux-browse` starts the local server and, by default, opens the UI in a browser.
- `browser/server.py` serves the read-mostly HTTP API and static frontend.
- `browser/static/` contains the frontend assets.
- `browser/artifacts/` stores ad-hoc HTML artifacts that the UI can list and open.
- `${VIDUX_BROWSER_COMMENTS_FILE:-~/.vidux-browser/comments.jsonl}` stores named comments and optional anchor metadata as append-only app data.
- `${VIDUX_BROWSER_STEERING_FILE:-~/.vidux-browser/steering.jsonl}` stores the local, plan-scoped one-shot steering journal.
- `${VIDUX_CLAIMS_FILE:-~/.agent-ledger/claims.jsonl}` stores provider-neutral live work leases and bounded handoffs.

## Launching it

```bash
bin/vidux-browse
bin/vidux-browse --no-open
bin/vidux-browse --foreground
bin/vidux-browse --port 7291 --root ~/Development/vidux --no-open
```

Source-grounded defaults from the launcher and server:

- URL: `http://127.0.0.1:7191`
- Bind host: `VIDUX_BROWSER_HOST` defaults to `127.0.0.1`
- Port: `VIDUX_BROWSER_PORT` defaults to `7191`
- Browser-open host: `VIDUX_BROWSER_OPEN_HOST` defaults to `127.0.0.1`
- Repo root for the launcher: `VIDUX_ROOT` defaults to `~/Development/vidux`
- Scan root for the server: `VIDUX_DEV_ROOT` defaults to `~/Development`
- Activity ledger source: `VIDUX_LEDGER_FILE` defaults to `~/.agent-ledger/activity.jsonl`
- Ledger tab caps: `VIDUX_LEDGER_ITEM_LIMIT` defaults to `20`; `VIDUX_LEDGER_SCAN_LIMIT` defaults to `5000`
- Steering journal: `VIDUX_BROWSER_STEERING_FILE` defaults to `~/.vidux-browser/steering.jsonl`
- Work-claims journal: `VIDUX_CLAIMS_FILE` defaults to `~/.agent-ledger/claims.jsonl`

In background mode the launcher writes a PID file and log under
`${XDG_STATE_HOME:-~/.local/state}/vidux/` (`browser.pid` / `browser.log`;
overridable via `VIDUX_BROWSER_PIDFILE` / `VIDUX_BROWSER_LOG`) and waits for
`GET /api/health` before declaring success. Older builds used
`${TMPDIR:-/tmp}/vidux-browser.{pid,log}` — `vidux doctor` warns if that
legacy shared path still exists. If something is already listening on the
target port, the launcher reuses it only when the health payload matches the
requested `repo_root`, `dev_root`, path-safe steering and coordination store
identities, `port`, and current server/mailbox/coordination module mtimes.

The launcher accepts `--port`, `--host`, `--root`/`--dev-root`, `--open-host`,
`--comments-path`, `--steering-path`, and `--claims-path`; unknown flags exit 2.

## HTTP surface

The stdlib-only server exposes these routes:

- `GET /api/health` returns `ok`, root/port/server identity, path-safe steering and coordination store ids, their module mtimes, and `artifacts_dir`; `bin/vidux-browse` uses these to avoid opening a stale, older-code, foreign, or differently scoped listener on the same port. Journal paths are not returned.
- `GET /api/vidux/truth` returns cached read-only config and runtime-doctor status for the browser chrome. Cold calls return a warming payload and refresh the truth bundle in the background, so monitor probes never block on runtime doctor.
- `GET /api/vidux/truth?refresh=sync` forces the synchronous config/runtime-doctor proof path for manual checks and tests.
- The truth payload includes `runtime_doctor.system_memory` (a compact copy of `system_memory_pressure`): `memory_pressure_free_pct`/`memory_pct_source` from `memory_pressure -Q`; `vm_free_mb`/`vm_speculative_mb`/`vm_pages_source` from `vm_stat`.
- `GET /api/plans` returns discovered plans plus metadata, a server-calculated `summary` (fleet counts/task completion/remaining ETA), and a bounded `dashboard` object (`in_progress` tasks, `blocked` tasks, open `ASK-OWNER.md` and `INBOX.md` entries). The dashboard also carries path-free onboarding state for empty roots, Git projects without plans, plans without an Operator Brief, and tied current-work priorities.
- `GET /api/ledger?path=<PLAN.md>` returns bounded, newest-first publish/checkpoint ledger rows for that plan, falling back to recent same-repo rows when plan-specific proof is absent.
- `GET /api/steering?plan_path=<PLAN.md>` returns cockpit-safe active steering state for one exact plan to loopback clients. It never returns the plan/store path, source/consumer labels, or lease material.
- `GET /api/coordination?plan_path=<PLAN.md>` returns active owners and resumable handoffs for that exact plan to loopback clients. It omits host, PID, journal path, tokens, and provider/account identity; there is no coordination write route.
- `POST /api/steering` lets the loopback cockpit enqueue, retry, or dismiss an active exact-plan item. Host-only lease, acknowledge, and fail transitions are not HTTP actions.
- `GET /api/artifacts` returns the HTML artifact shelf under `browser/artifacts/`.
- `GET /api/file?path=...` returns an allowed markdown file or HTML artifact.
- `GET /api/comments?path=...` returns named comments attached to an allowed markdown file or HTML artifact.
- `POST /api/artifact` writes a bounded HTML artifact (`slug` + `html` JSON payload).
- `POST /api/comments` appends a bounded named or anchored comment to the separate comments store.
- `POST /api/local-plan-note` appends a bounded local note to a plan directory's `INBOX.md`.

## Read/write safety model

The server is narrow:

- **Every request's `Host` header is checked against an allowlist before anything else runs** — independent of, and prior to, the `Origin`/`Referer` matching described below. This closes DNS rebinding: a page served from an attacker-registered domain that resolves to `127.0.0.1` (or the LAN bind address) presents a `Host` header equal to that attacker domain, and its `Origin`/`Referer` headers agree with that same `Host` — so an Origin-must-match-Host check alone can't tell the rebound request apart from a legitimate one. The Host allowlist accepts loopback identities (`127.0.0.1`, `localhost`, `::1`) plus, in `VIDUX_BROWSER_HOST=0.0.0.0` LAN-bind mode, RFC 1918 IPv4 or RFC 4193 IPv6 literals. Open a LAN-bound server by its private IP address; domain Host values remain denied.
- `POST /api/comments` is the one write route that intentionally accepts real cross-machine LAN peers (see below). When the peer is not loopback, LAN-bind mode requires both the actual TCP peer and the `Host` header to be private-use IP literals (RFC 1918/4193). A public or spoofed TCP peer therefore cannot borrow a private `Host`, and a DNS-rebound domain's `Host` is not a raw private-IP literal.
- Reads are limited to `DEV_ROOT` and an allowlist of plan-adjacent files: `PLAN.md`, `PROGRESS.md`, `INBOX.md`, `ASK-OWNER.md`, `DOCTRINE.md`, and `README.md`.
- Markdown under `investigations/` and `evidence/` is also allowed.
- HTML reads are limited to `browser/artifacts/`.
- `node_modules` paths are rejected even if the filename matches the allowlist.
- Allowed text is redacted before it is parsed or returned. This covers raw plan-adjacent files, plan/dashboard metadata, Claude session excerpts, ledger excerpts, artifact titles, and comments returned through JSON routes. Plans or artifacts with a secret-shaped path segment are omitted from discovery. A plan with one or more matches reports `content_redacted=true` and `sensitive_redactions=<count>`; the UI keeps that incomplete-content state visible.
- JSON payloads, plain-text HTTP errors, and request log lines share the same final redaction backstop. Percent-escaped request targets are decoded before log scanning so URL encoding cannot defeat token boundaries, then control characters are flattened to keep each request on one physical log line.
- The high-confidence detector covers known provider-token prefixes, bearer credentials, JWTs, private-key blocks, values of explicit secret/key/token assignments when the value is at least 12 characters, explicit password assignments when the value is at least 4 characters, and standalone mixed-character values of at least 40 characters that clear the entropy threshold. Hex digests and explicit example/redacted/unset placeholders remain visible to reduce proof noise.
- Artifact writes and local plan-note writes are loopback-only, require `Content-Type: application/json`, and reject cross-origin posts.
- Steering reads and writes are loopback-only. Browser writes require same-origin JSON; the HTTP action allowlist cannot lease, acknowledge, fail, invoke a provider, or start an executor.
- Steering bodies and labels reject sensitive-value matches. The store and lock file use the same regular-single-link and atomic-write protections as other local mutation surfaces. A corrupt journal fails closed in HTTP instead of returning a valid-looking partial queue.
- Lease tokens are random, hash-only at rest, omitted from list/browser payloads, and intended to return through stdin JSON. Acknowledgement and dismissal compact the body into a bounded tombstone; retry preserves the original FIFO position.
- Artifact, comment, and local plan-note writes reject detector matches instead of persisting a redacted value. Existing comments are redacted on read. Secret-shaped artifact slugs are rejected.
- Filesystem mutations fail closed unless the destination is absent or a regular file with exactly one link. Final-component symlinks, hard links, non-regular files, symlinked store directories, and aliased lock/store files are rejected before any payload bytes are written. Rewrites use a temporary file plus atomic replacement inside an already-opened parent directory, so a target swap cannot redirect bytes into the alias referent.
- Comment writes may come from LAN viewers of the vidux-browse UI but still require JSON and a same-origin `Origin` or `Referer` header, on top of the Host-allowlist check above.
- Markdown rendered client-side (`marked.js` output) is sanitized through a locally vendored DOMPurify (`browser/static/vendor/dompurify.min.js`) before it reaches the DOM. This closes stored XSS through a crafted plan or comment body. Artifact HTML uses the separate boundary below.
- HTML artifact responses are download-only (`Content-Disposition: attachment`) and carry `Content-Security-Policy`, `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, and `X-Frame-Options: SAMEORIGIN` headers.
- The cockpit parses artifact HTML before rendering, removes scripts, bases, nested frames, objects, embeds, stylesheet/network-hint links, refresh policies, event handlers, form targets, and non-fragment navigation, then prepends its own CSP to a sandboxed `srcdoc`. The iframe grants only `allow-same-origin` for host-owned sizing and annotations; it does not grant scripts, forms, popups, or top-level navigation.
- Comments NEVER edit plan files, `INBOX.md`, or artifact HTML — they append JSONL to the comments store; optional anchors point back to rendered elements only.
- The local truth band is read-only: `GET /api/vidux/truth` returns cached/warming state quickly, then refreshes `python3 scripts/vidux-config.py check --json` and `scripts/vidux-doctor.sh --json` in the background. Use `?refresh=sync` for the synchronous path. Neither route runs `vidux doctor` or runtime doctor `--fix`; warning-only runtime state stays a warning, never proof of a clean fleet.
- When system-memory truth is available, the band renders the runtime warning/blocker summary alongside the `memory_pressure` free percentage; the title preserves the `memory_pressure -Q` / `vm_stat` source split.
- The `Ledger` tab is read-only: it scans the activity JSONL tail, ignores noisy non-publish rows, matches plan rows by `plan_path`/`files`/`files_claimed`, and never appends, edits, or deletes ledger data.

Secret detection is defense in depth, not a credential vault. Keep credentials out of plans, sessions, ledgers, comments, and artifacts; rotate any credential that was exposed before the browser hid it.

## Artifact styling

Artifact HTML uses a separate network-isolated, sandboxed iframe boundary rather than the Markdown DOMPurify path. Its CSP has no HTTP(S) source: inline styles, data fonts, and data/blob images or media are allowed; scripts, forms, workers, objects, frames, manifests, connections, and all network resource URLs are denied. Remote HTTP(S) assets are intentionally blocked. Fragment-only navigation remains available; every other HTML, SVG, or image-map link loses its navigation target.

Shared visual scaffolding lives in `browser/static/artifact-base.css`. Put this marker after the artifact's local `<style>` block:

```html
<link rel="stylesheet" href="../static/artifact-base.css" data-vidux-artifact-base>
```

The relative `../static/` path works when opening a local artifact file directly from `browser/artifacts/`. In vidux-browse, the cockpit removes every artifact-owned `<link>`, fetches the trusted `artifact-base.css` bytes itself, and injects those bytes as an inline `<style>` only when this marker is present. This keeps the iframe self-contained without broadening `style-src` to same-origin URLs. Keep OS dark-mode tokens in the shared CSS, not in a per-artifact `prefers-color-scheme: dark` block.

## Plan-note behavior

`POST /api/local-plan-note` is the only plan-writing endpoint. It does not edit `PLAN.md` directly — it appends a timestamped entry to the target plan directory's `INBOX.md`:

- Creates `INBOX.md` if it does not exist.
- Inserts new notes under `## Open`.
- Preserves any existing `## Processed` section.
- Records `Source` and optional `Agent` metadata.
- Rejects a note or metadata label that contains a high-confidence sensitive value.

This behavior is covered by `tests/test_browser_server.py`.

An existing `INBOX.md` must be a regular, single-link file. Vidux will not follow or replace a symlink or hard-linked inbox; it returns a bounded write error and leaves the referent unchanged.

## Comment behavior

`POST /api/comments` is an annotation endpoint, not a plan-writing one. It accepts `target_path`, `author`, `body`, and optional `anchor` metadata, then appends a JSONL record to `${VIDUX_BROWSER_COMMENTS_FILE:-~/.vidux-browser/comments.jsonl}`.

- Targets must resolve through the same allowlist as `GET /api/file`.
- Plan-tab comments attach to the markdown file being viewed; artifact comments to the artifact HTML file.
- The UI remembers the commenter name in browser `localStorage`.
- Cross-machine LAN viewers can comment when on the vidux-browse origin.
- Rejects new comment bodies, authors, anchors, or target paths that contain a high-confidence sensitive value; legacy stored values are redacted on read.
- Rejects a comments store, lock file, or store directory that is a filesystem alias. Accepted updates are serialized across threads and server processes, then committed by atomic replacement.
- For precise placement, use the top-bar `Annotate` control or `Cmd/Ctrl+Shift+C`, then click the target surface. Capture decorates the shared browser chrome plus generic rendered HTML elements, so artifact authors need no per-file annotation hooks. The composer opens as a target-positioned popover. Annotation/filter shortcuts are ignored while typing in inputs, textareas, selects, or contenteditable fields.
- Anchors store sanitized selector, label, excerpt, tag, kind, and index metadata — best-effort display pointers; the source markdown or artifact stays unchanged.
- The rendered `Target` pill scrolls to and highlights the captured element when still present.

## Discovery model

Plan discovery is filesystem-based. The server scans `DEV_ROOT` with these layout globs:

- `*/ai/plans/*/PLAN.md`
- `*/vidux/*/PLAN.md`
- `*/projects/*/PLAN.md`
- `*/PLAN.md`

For first-run setup, Vidux also inspects direct child Git directories under `DEV_ROOT`. This inventory exposes project names and setup state only, never project paths. A project without a plan appears as unconnected and can be initialized from that project's terminal with:

```bash
vidux init --here
```

The generated plan already contains an Operator Brief and an unproven scorecard. If two valid briefs share the highest priority, the browser shows a current-work tie, names the deterministic fallback, and tells the operator to change one brief's `Priority` rather than silently presenting the file-time winner as intentional authority.

Each discovered plan reports task counts, ETA totals for active tasks, sibling-file availability, and linked or auto-discovered investigations. The topbar uses `/api/plans.summary` so the fleet-wide remaining-hours readout is computed server-side from the same task parser as the plan rows. The sidebar keeps persisted hot/tasks/ETA filter chips and a sort menu for `mtime`, remaining `ETA`, and freshness, with filtering applied before grouping and sorting.

The default pane uses the `/api/plans.dashboard` payload. Server-side extraction keeps each category bounded, includes source path and line metadata, and marks categories `truncated=true` when the fleet has more rows than the payload includes. The ordinary plan list strips private extractor scratch fields before returning rows.

The per-plan `Ledger` tab loads lazily through `/api/ledger` after a plan is selected, keeping `/api/plans` small while still exposing proof, handoff status, resume hints, file-claim counts, ledger line numbers, and same-repo fallback rows.

## Related references

- Read [Scripts](/reference/scripts) for the CLI and maintenance helpers that sit alongside the browser.
- Read [Configuration](/reference/config) if you need the repo-level defaults that other vidux tooling consumes.
