#!/usr/bin/env python3
"""User-facing vidux.config.json inspector and initializer."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


CONFIG_NAME = "vidux.config.json"
EXAMPLE_NAME = "vidux.config.example.json"
VALID_PLAN_STORE_MODES = {"inline", "local", "external"}
SECRET_WORDS = ("token", "secret", "password", "api_key", "apikey")
OPTIONAL_OBJECT_KEYS = ("defaults", "guidelines", "dashboard", "ledger", "backpressure", "pruning")


def vidux_root() -> Path:
    configured = os.environ.get("VIDUX_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def user_config_path() -> Path:
    """Return the install-independent live config path for this user."""
    configured = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(configured).expanduser() if configured else Path.home() / ".config"
    return (config_home / "vidux" / CONFIG_NAME).resolve()


def _expand_path(value: str, *, base: Path) -> Path:
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def resolve_config(explicit: str | None = None) -> dict[str, Any]:
    """Return the active config candidate and why it was selected."""
    root = vidux_root()
    live_path = user_config_path()
    candidates: list[tuple[str, Path]] = []
    if explicit:
        candidates.append(("explicit", Path(explicit).expanduser()))
    env_path = os.environ.get("VIDUX_CONFIG")
    if env_path and not explicit:
        candidates.append(("env", Path(env_path).expanduser()))
    if not explicit and not env_path:
        candidates.extend(
            [
                ("xdg", live_path),
                ("example", root / EXAMPLE_NAME),
            ]
        )

    checked: list[str] = []
    seen_checked: set[str] = set()
    for source, path in candidates:
        resolved = path.resolve()
        resolved_text = str(resolved)
        if resolved_text in seen_checked:
            continue
        seen_checked.add(resolved_text)
        checked.append(resolved_text)
        if resolved.exists():
            return {
                "source": source,
                "path": resolved,
                "exists": True,
                "checked": checked,
                "live_config_present": source != "example" and resolved.name == CONFIG_NAME,
                "using_example": source == "example",
            }

    fallback = live_path
    return {
        "source": "missing",
        "path": fallback,
        "exists": False,
        "checked": checked or [str(fallback)],
        "live_config_present": False,
        "using_example": False,
    }


def _issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _normalized_key(key: str) -> str:
    return key.lower().replace("-", "_")


def _secret_like_key(key: str) -> bool:
    lowered = _normalized_key(key)
    return any(word in lowered for word in SECRET_WORDS)


def _secret_path_key(key: str) -> bool:
    lowered = _normalized_key(key)
    return lowered.endswith("_file") and any(word in lowered for word in SECRET_WORDS)


def _looks_pathish(value: str) -> bool:
    return (
        value.startswith(("~", ".", "/"))
        or "/" in value
        or value.endswith((".token", ".key", ".pem", ".json"))
    )


def _walk_secret_values(value: Any, *, path: str = "") -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            if _secret_like_key(str(key)) and isinstance(item, str):
                if _secret_path_key(str(key)):
                    pathish = True
                else:
                    pathish = _looks_pathish(item)
                if not pathish and item.strip():
                    issues.append(
                        _issue(
                            "warning",
                            "inline_secret_value",
                            f"{current} looks like an inline secret; prefer a token_file path",
                        )
                    )
            issues.extend(_walk_secret_values(item, path=current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(_walk_secret_values(item, path=f"{path}[{index}]"))
    return issues


def load_config(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [_issue("error", "config_missing", f"config not found: {path}")]
    except IsADirectoryError:
        return None, [_issue("error", "config_is_directory", f"config path is a directory, not a file: {path}")]
    except json.JSONDecodeError as exc:
        return None, [_issue("error", "json_parse_error", f"{path}:{exc.lineno}:{exc.colno} {exc.msg}")]
    if not isinstance(payload, dict):
        return None, [_issue("error", "config_not_object", "top-level config must be a JSON object")]
    return payload, []


def validate_config(config: dict[str, Any], *, config_path: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    config_dir = config_path.resolve().parent

    plan_store = config.get("plan_store")
    plan_store_summary: dict[str, Any] = {}
    if not isinstance(plan_store, dict):
        issues.append(_issue("error", "plan_store_missing", "plan_store must be an object"))
    else:
        mode = plan_store.get("mode", "local")
        if mode not in VALID_PLAN_STORE_MODES:
            issues.append(
                _issue(
                    "error",
                    "plan_store_bad_mode",
                    f"plan_store.mode must be one of {sorted(VALID_PLAN_STORE_MODES)}",
                )
            )
        raw_path = plan_store.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            issues.append(_issue("error", "plan_store_path_missing", "plan_store.path must be a non-empty string"))
            resolved_path = None
        else:
            resolved_path = _expand_path(raw_path, base=config_dir)
        plan_store_summary = {
            "mode": mode,
            "path": raw_path,
            "resolved_path": str(resolved_path) if resolved_path else None,
            "path_exists": bool(resolved_path and resolved_path.exists()),
        }
        if resolved_path and not resolved_path.exists():
            issues.append(
                _issue(
                    "warning",
                    "plan_store_path_missing_on_disk",
                    f"plan_store.path does not exist yet: {resolved_path}",
                )
            )

    if "version" in config and not isinstance(config["version"], str):
        issues.append(_issue("error", "version_not_string", "version must be a string when present"))

    for object_key in OPTIONAL_OBJECT_KEYS:
        if object_key in config and not isinstance(config[object_key], dict):
            issues.append(_issue("error", f"{object_key}_not_object", f"{object_key} must be an object when present"))

    external_roots = config.get("external_plan_roots", [])
    if external_roots is None:
        external_roots = []
    external_roots_detail: list[dict[str, Any]] = []
    if not isinstance(external_roots, list):
        issues.append(_issue("error", "external_plan_roots_not_list", "external_plan_roots must be a list"))
        external_roots_summary: list[str] = []
    else:
        external_roots_summary = []
        for index, item in enumerate(external_roots):
            if not isinstance(item, str) or not item.strip():
                issues.append(_issue("error", "external_plan_roots_bad_item", f"external_plan_roots[{index}] must be a non-empty string"))
                continue
            resolved = _expand_path(item, base=config_dir)
            external_roots_summary.append(str(resolved))
            external_roots_detail.append(
                {
                    "path": item,
                    "resolved_path": str(resolved),
                    "path_exists": resolved.exists(),
                }
            )

    issues.extend(_walk_secret_values(config))

    return {
        "plan_store": plan_store_summary,
        "external_plan_roots": external_roots_summary,
        "external_plan_roots_detail": external_roots_detail,
        "issues": issues,
        "status": "fail" if any(item["severity"] == "error" for item in issues) else "ok",
    }


def build_report(explicit: str | None = None, *, strict: bool = False) -> dict[str, Any]:
    resolved = resolve_config(explicit)
    report: dict[str, Any] = {
        "status": "fail" if not resolved["exists"] else "ok",
        "source": resolved["source"],
        "path": str(resolved["path"]),
        "exists": resolved["exists"],
        "checked": resolved["checked"],
        "live_config_present": resolved["live_config_present"],
        "using_example": resolved["using_example"],
        "issues": [],
    }
    if not resolved["exists"]:
        report["issues"] = [_issue("error", "config_missing", "no vidux config or example config found")]
        return report
    config, load_issues = load_config(resolved["path"])
    if load_issues:
        report["issues"] = load_issues
        report["status"] = "fail"
        return report
    assert config is not None
    validation = validate_config(config, config_path=resolved["path"])
    report.update({key: value for key, value in validation.items() if key != "issues"})
    issues = list(validation["issues"])
    if strict and resolved["using_example"]:
        issues.append(
            _issue(
                "error",
                "live_config_missing",
                "strict mode requires a live vidux.config.json instead of the example",
            )
        )
    report["issues"] = issues
    report["status"] = "fail" if any(item["severity"] == "error" for item in issues) else "ok"
    return report


def print_human_report(report: dict[str, Any], *, verbose: bool = True) -> None:
    print(f"vidux config check: {report['status']}")
    print(f"source: {report['source']} ({report['path']})")
    if report.get("using_example"):
        print("live config: missing; using checked-in example")
    else:
        print(f"live config: {'present' if report.get('live_config_present') else 'not present'}")
    plan_store = report.get("plan_store") or {}
    if plan_store:
        exists = "exists" if plan_store.get("path_exists") else "missing"
        print(f"plan_store: {plan_store.get('mode')} {plan_store.get('resolved_path')} ({exists})")
    if report.get("issues"):
        print("issues:")
        for item in report["issues"]:
            print(f"- [{item['severity'].upper()}] {item['code']}: {item['message']}")
    elif verbose:
        print("issues: none")


def cmd_path(args: argparse.Namespace) -> int:
    resolved = resolve_config(args.config)
    payload = {key: (str(value) if isinstance(value, Path) else value) for key, value in resolved.items()}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload["path"])
    return 0 if resolved["exists"] else 1


def cmd_check(args: argparse.Namespace) -> int:
    report = build_report(args.config, strict=args.strict)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_human_report(report)
    return 0 if report["status"] == "ok" else 1


def cmd_show(args: argparse.Namespace) -> int:
    report = build_report(args.config, strict=False)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_human_report(report, verbose=False)
    return 0 if report["status"] == "ok" else 1


def cmd_init(args: argparse.Namespace) -> int:
    root = vidux_root()
    source = Path(args.source).expanduser().resolve() if args.source else (root / EXAMPLE_NAME).resolve()
    destination = Path(args.path).expanduser().resolve() if args.path else user_config_path()
    if "node_modules" in root.parts and (destination == root or root in destination.parents):
        print(
            f"vidux config init: refusing to write inside packaged install root: {root}",
            file=sys.stderr,
        )
        return 1
    if not source.exists():
        print(f"vidux config init: source not found: {source}", file=sys.stderr)
        return 1
    if destination.exists() and not args.force:
        print(f"vidux config init: {destination} already exists; pass --force to overwrite", file=sys.stderr)
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    print(f"wrote {destination}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and initialize Vidux user configuration.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    path_cmd = subparsers.add_parser("path", help="Print the active config path.")
    path_cmd.add_argument("--config", help="Explicit config path.")
    path_cmd.add_argument("--json", action="store_true")
    path_cmd.set_defaults(func=cmd_path)

    check_cmd = subparsers.add_parser("check", help="Validate the active config shape.")
    check_cmd.add_argument("--config", help="Explicit config path.")
    check_cmd.add_argument("--strict", action="store_true", help="Fail when only the example config is available.")
    check_cmd.add_argument("--json", action="store_true")
    check_cmd.set_defaults(func=cmd_check)

    show_cmd = subparsers.add_parser("show", help="Show the active config summary without dumping secrets.")
    show_cmd.add_argument("--config", help="Explicit config path.")
    show_cmd.add_argument("--json", action="store_true")
    show_cmd.set_defaults(func=cmd_show)

    init_cmd = subparsers.add_parser("init", help="Copy the example config into the user config directory.")
    init_cmd.add_argument(
        "--path",
        help="Explicit destination path. Defaults to $XDG_CONFIG_HOME/vidux/vidux.config.json or ~/.config/vidux/vidux.config.json.",
    )
    init_cmd.add_argument("--source", help="Source config. Defaults to vidux.config.example.json.")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite an existing destination.")
    init_cmd.set_defaults(func=cmd_init)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
