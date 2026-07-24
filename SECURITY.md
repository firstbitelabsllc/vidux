# Security Policy

## Reporting a vulnerability

If you discover a security issue in vidux, please report it responsibly:

1. **Do not open a public GitHub issue.** Security issues should be reported privately.
2. Use GitHub private vulnerability reporting for `firstbitelabsllc/vidux` when available.
3. Include: what you found, steps to reproduce, and potential impact.
4. You'll receive an acknowledgment per the [Response SLA](#response-sla) below.

## Response SLA

We aim to acknowledge security reports within 5 business days. Critical issues
will be addressed as quickly as possible; non-critical fixes follow the next
release cycle.

## Scope

Vidux's core is a discipline for reading and writing markdown plan files; it
does not handle authentication or user credentials, and does not transmit
data anywhere by itself. It does not run a network service by default beyond
the one named below.

Vidux does ship one local HTTP server: `browser/server.py` (`vidux dev` /
`vidux browse`), a stdlib `http.server`-based read/annotate UI for plan files.
Its threat model:
- Binds to `127.0.0.1` by default; a Host-header allowlist (independent of
  Origin/Referer matching) rejects any request whose Host doesn't present as
  a loopback identity, closing DNS-rebinding-class bypasses. See
  `docs/reference/browser.md`'s safety-model section for the full mechanism.
- `VIDUX_BROWSER_HOST=0.0.0.0` is an explicit, documented opt-in for
  trusted-LAN read access (README.md); write endpoints stay loopback-gated
  in that mode with one documented exception (comments).
- Serves only files resolved through an allowlist jail (`safe_resolve`/
  `is_allowed_file_target`) under the configured `dev_root` — no arbitrary
  filesystem read.

The primary security surface is:
- **Automation prompts** — repo-local lane prompts that drive agent behavior
- **Git operations** — scripts that commit, push, and create PRs
- **Shell scripts** — `scripts/` directory executed by agents
- **The local browser UI** — `browser/server.py` and `browser/static/*.js`
- **Shared temp / multi-user hosts** — a shared `TMPDIR` (or world-writable
  `/tmp`) can leave browser pid/log residue visible across users or jobs.
  Isolation bugs here are in scope.

## Security design decisions

- **XDG-scoped browser state.** Live pid/log files live under
  `${XDG_STATE_HOME:-~/.local/state}/vidux/browser.{pid,log}` (not shared
  temp). Legacy `${TMPDIR}/vidux-browser.pid` is warn-only.
- **Loopback-first browser bind.** Default `127.0.0.1` plus Host allowlist;
  LAN bind is explicit opt-in (see Scope above).

## What We Watch For

- Scripts that could execute arbitrary code from untrusted plan files
- Git operations that could overwrite or delete user data
- Prompt injection vectors in plan/evidence files that could alter agent behavior
- Credential leakage in git history — audited repeatedly, not a one-time
  point-in-time claim (see `evidence/*-panel-*.md` for the dated audit trail
  and any open findings)

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x / current `main` | Yes |
| < 1.0 | No |

Only the latest `main` (and any tag at or above 1.0) receives security fixes.
