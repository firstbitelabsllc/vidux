"""WCAG 1.4.3 AA (4.5:1) contrast guard for the browser UI's status colors.

Several light-theme status tokens render as small text (10.5-11.5px) and
sit at a razor-thin 4.5-5.0:1 margin against the page surfaces. This test
pins their computed ratios so a future palette edit can't silently regress
them below AA.

Coverage the guard grew to include, each from a real shipped regression:

- Every surface a token actually renders on, not just --paper: status
  labels also render on --paper-2 (the darker card/panel surface, where
  they once failed at 4.23-4.26:1) and on --select (when a focusable
  .dashboard-item is hovered/focused).
- Usages that live in receipts.html's own inline <style> (e.g. the
  ".exportable" pill colors, which failed at 3.91:1/4.23:1), invisible to a
  test that only parses the :root block.
- Dark-theme pairings, not only light-theme values against --paper/
  --paper-2: a dark-mode AA failure (receipts.html's hardcoded button
  backgrounds going near-invisible against dark var(--paper) text) once
  shipped undetected.
- The bare `@media (prefers-color-scheme: dark)` fallback block (used when
  index.html's FOUC-guard falls through because localStorage throws), which
  once omitted --error/--warning entirely while a comment falsely claimed
  they were already handled by the :root.theme-dark class block -- which
  never applies without that class.
- New :root.theme-dark properties (--shadow-sm/-md/-lg) going missing from
  the fallback block, caught by checking the live property set rather than a
  fixed token tuple."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = ROOT / "browser" / "static" / "style.css"

# these background reference colors used to be
# hardcoded here (PAPER="#f8f5ee" etc). A concurrent palette rebrand shipped
# to style.css (:root --paper became #f7f9f8) WITHOUT touching this file, so
# the WCAG regression guard was silently validating a phantom palette that no
# longer matched the shipped surface. The guard now reads --paper/--paper-2/
# --select from the live CSS in setUp (self.paper etc), so it always tracks
# whatever palette actually ships.

# Tokens confirmed used as `color:` (not just background/border) on small
# text in browser/static/style.css, at the time of this fix.
# added "warning" (failed AA at 11px on
# .ops-chip.is-warn, 3.91:1/3.61:1 -- darkened same as the original 4) and
# "task-blocked" (already passing, 4.97:1/4.59:1, just missing from this
# regression test despite being used identically to the other 5).
TEXT_TOKENS = (
    "task-shipped", "task-in-progress", "task-completed", "task-in-review",
    "warning", "task-blocked", "cold", "error", "hot",
)


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _linearize(c: int) -> float:
    c_srgb = c / 255
    return c_srgb / 12.92 if c_srgb <= 0.03928 else ((c_srgb + 0.055) / 1.055) ** 2.4


def _relative_luminance(hexcolor: str) -> float:
    r, g, b = _hex_to_rgb(hexcolor)
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    l1, l2 = _relative_luminance(hex1), _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _first_root_block(css: str) -> str:
    # The light-theme token values live in the first `:root { ... }` block.
    start = css.index(":root {")
    end = css.index("}", start)
    return css[start:end]


def _named_block(css: str, marker: str) -> str:
    start = css.index(marker)
    brace = css.index("{", start)
    end = css.index("}", brace)
    return css[brace:end]


def _custom_properties(block: str) -> dict[str, str]:
    return {
        name: value.strip()
        for name, value in re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block)
    }


DARK_STATUS_TOKENS = (
    "error", "error-bg", "error-ink", "warning", "warning-bg", "warning-ink",
)

# Status labels that render on --select (not just --paper/--paper-2)
# whenever their ancestor .dashboard-item is :hover/:focus-visible.
SELECT_TOKENS = ("task-in-progress", "task-blocked")


class StyleContrastTests(unittest.TestCase):
    def setUp(self):
        self.css = STYLE_CSS.read_text(encoding="utf-8")
        self.root_block = _first_root_block(self.css)
        self.dark_block = _named_block(self.css, ":root.theme-dark {")
        # Read the actual shipped background surfaces from the live CSS rather
        # than hardcoding them, so a palette change can't leave this guard
        # checking a stale target.
        self.paper = self._token_value("paper")
        self.paper_2 = self._token_value("paper-2")
        self.select_light = self._token_value("select")
        self.dark_paper = self._dark_token_value("paper")
        self.dark_paper_2 = self._dark_token_value("paper-2")
        self.select_dark = self._dark_token_value("select")

    def _token_value(self, token: str) -> str:
        match = re.search(rf"--{re.escape(token)}:\s*(#[0-9a-fA-F]{{6}})", self.root_block)
        self.assertIsNotNone(match, f"--{token} not found in :root block")
        return match.group(1)

    def _dark_token_value(self, token: str) -> str:
        match = re.search(rf"--{re.escape(token)}:\s*(#[0-9a-fA-F]{{6}})", self.dark_block)
        self.assertIsNotNone(match, f"--{token} not found in :root.theme-dark block")
        return match.group(1)

    def test_light_theme_status_text_colors_meet_wcag_aa(self):
        for token in TEXT_TOKENS:
            value = self._token_value(token)
            ratio = _contrast_ratio(value, self.paper)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--{token} ({value}) vs --paper ({self.paper}) is {ratio:.2f}:1, "
                f"below WCAG 1.4.3 AA (4.5:1) for the small text it's used at",
            )

    def test_light_theme_status_text_colors_meet_wcag_aa_against_paper_2(self):
        for token in TEXT_TOKENS:
            value = self._token_value(token)
            ratio = _contrast_ratio(value, self.paper_2)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--{token} ({value}) vs --paper-2 ({self.paper_2}) is {ratio:.2f}:1, "
                f"below WCAG 1.4.3 AA (4.5:1) for the small text it's used at",
            )

    def test_dark_theme_status_text_colors_meet_wcag_aa(self):
        # The light-theme checks above have no dark-theme counterpart, so a
        # real dark-mode AA failure would sail through green. Mirrors
        # test_light_theme_status_text_colors_meet_wcag_aa against the
        # dark-theme surfaces instead.
        for token in TEXT_TOKENS:
            value = self._dark_token_value(token)
            ratio = _contrast_ratio(value, self.dark_paper)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--{token} ({value}) vs dark --paper ({self.dark_paper}) is "
                f"{ratio:.2f}:1, below WCAG 1.4.3 AA (4.5:1)",
            )

    def test_dark_theme_status_text_colors_meet_wcag_aa_against_paper_2(self):
        for token in TEXT_TOKENS:
            value = self._dark_token_value(token)
            ratio = _contrast_ratio(value, self.dark_paper_2)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--{token} ({value}) vs dark --paper-2 ({self.dark_paper_2}) is "
                f"{ratio:.2f}:1, below WCAG 1.4.3 AA (4.5:1)",
            )

    def test_dashboard_status_labels_meet_wcag_aa_against_select(self):
        # --task-in-progress/--task-blocked render on --select (not
        # --paper/--paper-2) whenever the keyboard-focusable .dashboard-item
        # ancestor is :hover/:focus-visible -- --select is a harder surface
        # than either in both themes.
        for token in SELECT_TOKENS:
            light_value = self._token_value(token)
            light_ratio = _contrast_ratio(light_value, self.select_light)
            self.assertGreaterEqual(
                light_ratio,
                4.5,
                f"--{token} ({light_value}) vs light --select ({self.select_light}) "
                f"is {light_ratio:.2f}:1, below WCAG 1.4.3 AA (4.5:1)",
            )
            dark_value = self._dark_token_value(token)
            dark_ratio = _contrast_ratio(dark_value, self.select_dark)
            self.assertGreaterEqual(
                dark_ratio,
                4.5,
                f"--{token} ({dark_value}) vs dark --select ({self.select_dark}) "
                f"is {dark_ratio:.2f}:1, below WCAG 1.4.3 AA (4.5:1)",
            )

    def test_dark_media_fallback_matches_theme_dark_for_every_custom_property(self):
        # Generalizes the fixed-tuple check (below) to every custom property
        # in :root.theme-dark, so a future addition (e.g. --shadow-sm/-md/-lg)
        # can't go missing from the bare fallback again without a
        # token-by-token test update.
        media_dark_block = _named_block(
            self.css, "@media (prefers-color-scheme: dark) {"
        )
        theme_props = _custom_properties(self.dark_block)
        media_props = _custom_properties(media_dark_block)
        missing = sorted(set(theme_props) - set(media_props))
        self.assertFalse(
            missing,
            f"properties in :root.theme-dark missing from the bare "
            f"@media(prefers-color-scheme: dark) fallback block: {missing} "
            f"-- it will silently diverge if a browser hits this path with "
            f"localStorage disabled",
        )
        mismatched = {
            name: (theme_props[name], media_props[name])
            for name in theme_props
            if name in media_props and theme_props[name] != media_props[name]
        }
        self.assertFalse(
            mismatched,
            f"properties differ between :root.theme-dark and the bare "
            f"@media dark fallback -- keep them in sync: {mismatched}",
        )

    def test_dark_media_fallback_declares_error_and_warning_families(self):
        # The bare @media(prefers-color-scheme: dark) block is a real,
        # reachable fallback path (FOUC-guard falls through to it when
        # localStorage throws), so it must carry the same --error/--warning
        # values as :root.theme-dark rather than silently omitting them.
        theme_dark_block = _named_block(self.css, ":root.theme-dark {")
        media_dark_block = _named_block(
            self.css, "@media (prefers-color-scheme: dark) {"
        )
        for token in DARK_STATUS_TOKENS:
            pattern = rf"--{re.escape(token)}:\s*(#[0-9a-fA-F]{{6}})"
            theme_match = re.search(pattern, theme_dark_block)
            media_match = re.search(pattern, media_dark_block)
            self.assertIsNotNone(
                theme_match, f"--{token} not found in :root.theme-dark block"
            )
            self.assertIsNotNone(
                media_match,
                f"--{token} not found in the @media(prefers-color-scheme: "
                f"dark) fallback block -- it will silently fail WCAG AA if "
                f"a browser hits this path with localStorage disabled",
            )
            self.assertEqual(
                theme_match.group(1),
                media_match.group(1),
                f"--{token} differs between :root.theme-dark and the bare "
                f"@media dark fallback -- keep them in sync",
            )


if __name__ == "__main__":
    unittest.main()
