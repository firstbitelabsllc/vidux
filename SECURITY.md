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

## What We Watch For

- Scripts that could execute arbitrary code from untrusted plan files
- Git operations that could overwrite or delete user data
- Prompt injection vectors in plan/evidence files that could alter agent behavior
- Credential leakage in git history — audited repeatedly, not a one-time
  point-in-time claim (see `evidence/*-panel-*.md` for the dated audit trail
  and any open findings)

## Supported versions

Only the latest supported version line receives security fixes.

| Version          | Status              |
| ---------------- | ------------------- |
| Current `main` / unreleased `3.0` source | supported |
| `2.x` and older commits                  | unsupported |
