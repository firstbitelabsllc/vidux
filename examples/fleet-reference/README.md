# Reference Fleet Configuration

A complete 4-automation fleet for a web project: 1 writer + 2 radars + 1 coordinator.

## Fleet Manifest

| Automation | Role | Schedule | Slot |
|-----------|------|----------|------|
| myapp-writer | writer | every 30m | :00, :30 |
| myapp-ux-radar | radar | every 30m | :05, :35 |
| myapp-perf-radar | radar | every 30m | :10, :40 |
| myapp-coordinator | coordinator | every 2h | :15 |

## Slot Map

```
:00  myapp-writer
:05  myapp-ux-radar
:10  myapp-perf-radar
:15  myapp-coordinator (every 2h)
:20  (available)
:25  (available)
:30  myapp-writer
:35  myapp-ux-radar
:40  myapp-perf-radar
:45  (available)
:50  (available)
:55  (available)
```

Max concurrency: 1 (no overlapping slots). 6 open slots for expansion.

## Quality Target

- Writer: deep runs (15-40 min) or quick exits (<1 min when queue is empty)
- Radars: quick checks (<2 min) unless new evidence found, then thorough write-up
- Coordinator: always quick (<2 min) — reads memory files, checks bimodal quality, adjusts prompts

## Files

- `writer.toml` — Codex automation config for the writer
- `ux-radar.toml` — Codex automation config for the UX radar
- `perf-radar.toml` — Codex automation config for the performance radar
- `coordinator.toml` — Codex automation config for the coordinator
