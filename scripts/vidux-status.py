#!/usr/bin/env python3
"""vidux-status — read-only scan of all PLAN.md files on the machine.

Renders a two-bucket board: "Tied to this chat" (focus repos) and "Other
tracked plans" (everything else). Example and fixture trees are skipped so
documentation/test PLAN.md files do not masquerade as resumable work. Each row:
10-cell progress bar, remaining AI-hours from [ETA: Xh] tags on
pending+in_progress, last-Progress timestamp.

Usage:
    vidux-status.py                         # compact board, cwd's repo is focus
    vidux-status.py --all                   # include empty / shipped / stale
    vidux-status.py --json                  # machine-readable
    vidux-status.py --focus repo1 repo2     # explicit focus repos
    vidux-status.py --root /path/to/scan    # override search root (default ~/Development)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# README.md documents VIDUX_DEV_ROOT as an
# alternative to --root for this scan root (and explicitly recommends it for
# a non-standard clone location), but this only ever read the hardcoded
# ~/Development default -- only browser/server.py's DEV_ROOT honored the
# env var. Matches that file's exact os.environ.get pattern.
DEFAULT_ROOT = Path(
    os.environ.get("VIDUX_DEV_ROOT", str(Path.home() / "Development"))
).expanduser()
LEDGER_PATH = Path.home() / ".agent-ledger" / "activity.jsonl"
SKIP_PARTS = {
    "node_modules",
    ".git",
    "_archive",
    ".next",
    "dist",
    "build",
    "worktrees",
    "examples",
    "fixtures",
}
SKIP_SUBSTRINGS = ("-worktrees/", "/.agents/skills/vidux/", "/ai/skills/vidux/")

STATUS_TAGS = ("pending", "in_progress", "completed", "blocked")
# SKILL.md's "## Tasks" status FSM documents an optional extended flow --
# pending -> in_progress -> [in_review] -> [merged] -> completed, plus a
# separate [verify] rung for the generator/evaluator pattern -- and real
# plans use these tags. None of them are terminal, so for board-counting
# purposes they fold into the same "in_progress" bucket completed tasks are
# not. Without this alias these tags simply failed to match TASK_LINE_RE and
# were silently excluded from every count: a plan with all its live work
# sitting in [in_review] reported pending=0/in_progress=0/blocked=0 and
# misreported as 100% shipped.
IN_PROGRESS_ALIAS_TAGS = ("in_review", "verify", "merged")
TASK_LINE_RE = re.compile(
    r"^-\s+\[(pending|in_progress|completed|blocked|in_review|verify|merged)\]\s+(.*)$"
)
ETA_RE = re.compile(r"\[ETA:\s*(\d+(?:\.\d+)?)h\]")
PROGRESS_LINE_RE = re.compile(r"^-\s*\[?(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?)")
NEGATIVE_PROSE_BLOCKER_RE = re.compile(r"\b(?:not|no longer|not currently)\s+blocked\s+by\b", re.I)
OWNER_REVIEW_RE = re.compile(r"\bownership\s+review\b", re.I)
OWNER_REVIEW_GATE_RE = re.compile(
    r"\b(no\s+(?:cleanup\s+)?deletion|no\s+branch\s+removal|non-removable|"
    r"owner\s+must\s+review|before\s+any\s+cleanup|cleanup\s+remains\s+closed)\b",
    re.I,
)
PROSE_BLOCKER_PATTERNS = (
    re.compile(r"\bblocked\s+(?:by|until)\s+([^.\];]+)", re.I),
    re.compile(r"\bwaiting\s+on\s+([^.\];]+)", re.I),
    re.compile(r"\bcannot\s+proceed\s+until\s+([^.\];]+)", re.I),
    re.compile(r"\b([^.\[\]]{1,140}?)\s+must\s+be\s+solved\s+first\b", re.I),
    re.compile(r"\bpending\s+ownership\s+review\b([^.\];]{0,140})", re.I),
    re.compile(r"\bowner\s+cleanup\s+decisions?\b([^.\];]{0,140})", re.I),
    re.compile(r"\bowner\s+decisions?\s+(?:resolve|required|needed|must|before|to)\b([^.\];]{0,140})", re.I),
    re.compile(r"\bowner\s+approval\s+(?:required|needed|before)\b([^.\];]{0,140})", re.I),
    re.compile(r"\bapproval\s+required\s+before\s+apply\b([^.\];]{0,140})", re.I),
    re.compile(r"\bcleanup\s+approval\b([^.\];]{0,140})", re.I),
    re.compile(r"\boperator[- ]gated\b([^.\];]{0,140})", re.I),
    re.compile(r"\boperator\s+approval\s+(?:required|needed|before)\b([^.\];]{0,140})", re.I),
    re.compile(r"\bASK-OWNER-MANDATORY\b([^.\];]{0,140})", re.I),
)


@dataclass
class PlanStatus:
    path: str
    short: str
    pending: int
    in_progress: int
    completed: int
    blocked: int
    eta_hours: float
    progress_ts: Optional[str]
    latest_progress: Optional[str]
    mtime_ts: str
    stale_days: int
    pending_tasks: list[str]
    in_progress_tasks: list[str]
    blocked_tasks: list[str]
    flags: list[str]

    @property
    def denom(self) -> int:
        return self.pending + self.in_progress + self.completed + self.blocked

    @property
    def percent(self) -> int:
        return round(100 * self.completed / self.denom) if self.denom else 0

    @property
    def is_empty(self) -> bool:
        return (self.pending + self.in_progress + self.completed + self.blocked) == 0

    @property
    def is_shipped(self) -> bool:
        return (
            self.pending == 0
            and self.in_progress == 0
            and self.blocked == 0
            and self.completed > 0
        )

    @property
    def latest(self) -> str:
        return self.progress_ts or self.mtime_ts


def find_plans(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("PLAN.md"):
        s = str(p)
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        if any(sub in s for sub in SKIP_SUBSTRINGS):
            continue
        out.append(p)
    return out


def split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def task_has_prose_blocker(text: str) -> bool:
    if NEGATIVE_PROSE_BLOCKER_RE.search(text):
        return False
    if OWNER_REVIEW_RE.search(text) and OWNER_REVIEW_GATE_RE.search(text):
        return True
    return any(pattern.search(text) for pattern in PROSE_BLOCKER_PATTERNS)


def status_for_task(tag: str, task_text: str) -> str:
    if tag in IN_PROGRESS_ALIAS_TAGS:
        tag = "in_progress"
    if tag in {"pending", "in_progress"} and task_has_prose_blocker(task_text):
        return "blocked"
    return tag


def empty_task_buckets() -> dict[str, list[str]]:
    return {tag: [] for tag in STATUS_TAGS}


def record_task(
    counts: dict[str, int],
    buckets: dict[str, list[str]],
    tag: str,
    task_text: str,
) -> str:
    counted_tag = status_for_task(tag, task_text)
    counts[counted_tag] += 1
    buckets[counted_tag].append(task_text.strip())
    return counted_tag


def list_task_counts(text: str) -> tuple[dict[str, int], float, dict[str, list[str]]]:
    counts = {tag: 0 for tag in STATUS_TAGS}
    buckets = empty_task_buckets()

    eta_sum = 0.0
    for line in text.splitlines():
        s = line.strip()
        m = TASK_LINE_RE.match(s)
        if not m:
            continue
        tag = record_task(counts, buckets, m.group(1), m.group(2))
        if tag in {"pending", "in_progress"}:
            for m in ETA_RE.finditer(s):
                try:
                    eta_sum += float(m.group(1))
                except ValueError:
                    pass
    return counts, eta_sum, buckets


def claims_board_task_counts(text: str) -> tuple[dict[str, int], float, dict[str, list[str]]]:
    counts = {tag: 0 for tag in STATUS_TAGS}
    buckets = empty_task_buckets()
    eta_sum = 0.0
    in_claims_board = False
    status_col: Optional[int] = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## claims board"):
            in_claims_board = True
            status_col = None
            continue
        if in_claims_board and stripped.startswith("## "):
            break
        if not in_claims_board:
            continue

        cells = split_table_cells(line)
        if not cells:
            continue
        normalized = [cell.lower().strip("* ") for cell in cells]
        if status_col is None:
            if len(normalized) >= 2 and normalized[0] == "task" and normalized[1] == "status":
                status_col = 1
            continue
        if status_col >= len(cells):
            continue

        status = cells[status_col].strip()
        if status.startswith("[") and status.endswith("]"):
            tag = status[1:-1]
            if tag in counts or tag in IN_PROGRESS_ALIAS_TAGS:
                task_text = " ".join(cell for idx, cell in enumerate(cells) if idx != status_col)
                counted_tag = record_task(counts, buckets, tag, task_text)
                if counted_tag in {"pending", "in_progress"}:
                    for m in ETA_RE.finditer(line):
                        try:
                            eta_sum += float(m.group(1))
                        except ValueError:
                            pass

    return counts, eta_sum, buckets


def stale_days_for_mtime(mtime: datetime) -> int:
    return max(0, (datetime.now(timezone.utc).date() - mtime.date()).days)


def flags_for_plan(
    counts: dict[str, int],
    stale_days: int,
    buckets: dict[str, list[str]],
) -> list[str]:
    flags = []
    if counts["blocked"]:
        flags.append("blocked")
    if counts["in_progress"]:
        flags.append("in_progress")

    shipped = (
        counts["pending"] == 0
        and counts["in_progress"] == 0
        and counts["blocked"] == 0
        and counts["completed"] > 0
    )
    if stale_days > 7 and not shipped:
        flags.append("stale")

    active_text = " ".join(
        buckets["pending"] + buckets["in_progress"] + buckets["blocked"]
    ).lower()
    if any(token in active_text for token in ("auth", "signin", "sign-in", "oauth")):
        flags.append("auth_gap")
    if "ASK-OWNER" in active_text or "ask-owner" in active_text:
        flags.append("leo_gate")
    return flags


def parse_plan(p: Path, dev_root: Path) -> PlanStatus:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    counts, eta_sum, task_buckets = claims_board_task_counts(text)
    if sum(counts.values()) == 0:
        counts, eta_sum, task_buckets = list_task_counts(text)

    progress_ts: Optional[str] = None
    latest_progress: Optional[str] = None
    in_progress_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Progress"):
            in_progress_section = True
            continue
        if in_progress_section and stripped.startswith("## "):
            break
        if in_progress_section:
            m = PROGRESS_LINE_RE.match(line.lstrip())
            if m:
                ts = m.group(1)
                if progress_ts is None or ts > progress_ts:
                    progress_ts = ts
                    latest_progress = stripped

    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        # The plan can vanish between discovery and stat; treat it as freshly
        # touched rather than aborting the whole status board.
        mtime = datetime.now(tz=timezone.utc)
    stale_days = stale_days_for_mtime(mtime)

    try:
        rel = p.relative_to(dev_root)
        if rel == Path("PLAN.md"):
            short = dev_root.name or p.parent.name or str(p).removesuffix("/PLAN.md")
        else:
            short = str(rel).removesuffix("/PLAN.md")
    except ValueError:
        short = str(p).removesuffix("/PLAN.md")
    short = short.replace("/vidux/", "/")

    return PlanStatus(
        path=str(p),
        short=short,
        pending=counts["pending"],
        in_progress=counts["in_progress"],
        completed=counts["completed"],
        blocked=counts["blocked"],
        eta_hours=eta_sum,
        progress_ts=progress_ts,
        latest_progress=latest_progress,
        mtime_ts=mtime.strftime("%Y-%m-%d"),
        stale_days=stale_days,
        pending_tasks=task_buckets["pending"],
        in_progress_tasks=task_buckets["in_progress"],
        blocked_tasks=task_buckets["blocked"],
        flags=flags_for_plan(counts, stale_days, task_buckets),
    )


def latest_ledger_eid(path: Path = LEDGER_PATH) -> Optional[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            recent_lines = deque(fh, maxlen=200)
    except OSError:
        return None

    for line in reversed(recent_lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = data.get("eid") or data.get("event_id")
        if isinstance(eid, str) and eid:
            return eid
    return None


def current_repo() -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def is_tied(plan: PlanStatus, focus: set[str]) -> bool:
    return any(part in focus for part in plan.short.split("/"))


def bar(percent: int, cells: int = 10) -> str:
    filled = round(percent / 100 * cells)
    return "▓" * filled + "░" * (cells - filled)


def eta_col(plan: PlanStatus) -> str:
    if plan.is_shipped and plan.pending == 0 and plan.in_progress == 0 and plan.denom:
        return "shipped"
    if plan.eta_hours == 0:
        return "∅ AI-hrs"
    return f"{plan.eta_hours:.1f} AI-hrs left"


def staleness(mtime: str) -> str:
    try:
        m = datetime.strptime(mtime, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc).date() - m.date()).days
    except ValueError:
        return mtime
    if days <= 0:
        return "today"
    if days == 1:
        return "1d"
    if days <= 7:
        return f"{days}d"
    return f"{days}d stale"


def render_row(plan: PlanStatus, name_width: int = 34) -> str:
    name = plan.short if len(plan.short) <= name_width else plan.short[: name_width - 1] + "…"
    name = name.ljust(name_width)
    pct = plan.percent
    extra = ""
    if pct == 0 or plan.blocked:
        parts = []
        if plan.pending:
            parts.append(f"{plan.pending}p")
        if plan.in_progress:
            parts.append(f"{plan.in_progress}i")
        if plan.blocked:
            parts.append(f"{plan.blocked}b")
        if parts:
            extra = "  [" + "/".join(parts) + "]"
    return f"  {name} {bar(pct)} {pct:>3}%  ·  {eta_col(plan):<15}  ·  {staleness(plan.mtime_ts)}{extra}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan PLAN.md files and render a status board.")
    ap.add_argument("--all", action="store_true", help="Include empty / shipped / stale plans")
    ap.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    ap.add_argument("--focus", nargs="*", default=None, help="Repo names to put in 'tied' bucket")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Search root (default ~/Development)")
    args = ap.parse_args()
    # Resolve before any use: a relative root (`--root .`) otherwise has an
    # empty `.name`, which degrades every root-level plan's short name to the
    # literal "PLAN.md" and breaks the tied-bucket match against the cwd repo.
    args.root = args.root.resolve()

    if not args.root.is_dir():
        # README quick-start runs `vidux status` from an arbitrary project dir.
        # Fleet default ~/Development is often absent on a stranger machine —
        # fall back to cwd so the cwd PLAN.md path below still works.
        default_missing = (
            args.root == DEFAULT_ROOT.resolve()
            and not os.environ.get("VIDUX_DEV_ROOT")
        )
        if default_missing:
            # Warn on stderr, not stdout: `vidux status --json` emits its
            # payload on stdout, and a warning line there breaks callers that
            # pipe stdout into json.loads even though we exit 0.
            print(
                f"warn: search root missing ({args.root}); "
                "showing cwd plan only (set VIDUX_DEV_ROOT or create ~/Development)",
                file=sys.stderr,
                flush=True,
            )
            args.root = Path.cwd().resolve()
        else:
            print(f"error: search root does not exist: {args.root}", file=sys.stderr, flush=True)
            return 1

    plans = [parse_plan(p, args.root) for p in find_plans(args.root)]

    if not args.all:
        plans = [p for p in plans if not p.is_empty and not p.is_shipped]

    # Always include the current directory's PLAN.md, even when cwd lies
    # outside the scan root — the plan you are standing in belongs on the
    # board regardless of --root.
    cwd_plan = Path.cwd() / "PLAN.md"
    if cwd_plan.is_file():
        seen = {str(Path(p.path).resolve()) for p in plans}
        if str(cwd_plan.resolve()) not in seen:
            plans.append(parse_plan(cwd_plan.resolve(), args.root))

    focus: set[str] = set(args.focus) if args.focus is not None else set()
    cwd_repo = current_repo()
    if cwd_repo and not args.focus:
        focus.add(cwd_repo)

    tied = sorted([p for p in plans if is_tied(p, focus)], key=lambda p: (-p.percent, p.mtime_ts), reverse=False)
    other = sorted([p for p in plans if not is_tied(p, focus)], key=lambda p: (-p.percent, p.mtime_ts), reverse=False)

    if args.json:
        print(json.dumps({
            "focus_repos": sorted(focus),
            "latest_ledger_eid": latest_ledger_eid(),
            "tied": [asdict(p) for p in tied],
            "other": [asdict(p) for p in other],
        }, indent=2))
        return 0

    focus_label = ", ".join(sorted(focus)) if focus else "(none — pass --focus to set)"
    print(f"🎯 Tied to this chat  ({focus_label})")
    print("━" * 70)
    if not tied:
        print("  (no active plans in focus)")
    else:
        for p in tied:
            print(render_row(p))
    print()
    other_count_label = "tracked" if args.all else "active"
    print(f"📋 Other tracked plans  ({len(other)} {other_count_label})")
    print("━" * 70)
    for p in other[:20]:
        print(render_row(p))
    if len(other) > 20:
        print(f"  … {len(other) - 20} more (use --all to see full list)")

    total_eta = sum(p.eta_hours for p in plans)
    n_with_eta = sum(1 for p in plans if p.eta_hours > 0)
    if total_eta > 8:
        print()
        print(f"⚠  heavy queue: {total_eta:.1f} AI-hrs in flight across {n_with_eta} plan(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
