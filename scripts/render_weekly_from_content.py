#!/usr/bin/env python3
"""Render a hotlist video from an authored content file.

Unlike ``scripts/render_hotlist_v2.py`` (which fetches + auto-enriches through a
model provider), this entry point takes a hand-curated ``content.json`` that
already contains Chinese copy and narration segments. It reuses the hotlist-v2
rendering stack (HyperFrames HTML -> TTS -> ffmpeg mix) and the shared BGM /
loudness post-processing.

Usage:
    python scripts/render_weekly_from_content.py \
        --content output/weekly-20261102/content.json \
        --out output/weekly-20261102/final.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.hotlist_v2.render as _hotlist_render  # noqa: E402
from src.composer.bgm import post_process_video  # noqa: E402
from src.hotlist_v2.render import _data_from_projects, render_hotlist_v2_from_data  # noqa: E402
from src.hotlist_v2.template import DEFAULT_STYLE, supported_styles  # noqa: E402
from src.utils.config import TTS_VOICE  # noqa: E402

# Subtitle safe-area CSS: two-line captions sit ~209px above the bottom, which
# otherwise overlaps the list footer (118px) and the outro CTA (170px).
_SAFE_AREA_CSS = (
    "<style>\n"
    ".list-screen { padding-bottom: 180px !important; }\n"
    ".hook-screen { padding-bottom: 238px !important; }\n"
    ".hook-btn.secondary {\n"
    "  background: #eef1f6 !important;\n"
    "  color: #3d4451 !important;\n"
    "  font-weight: 600 !important;\n"
    "}\n"
    "</style>\n"
)


def _install_safe_area_css_patch() -> None:
    """Wrap render_composition to inject subtitle safe-area CSS into the HTML."""
    original = _hotlist_render.render_composition
    if getattr(original, "_safe_area_patched", False):
        return

    def patched(data, output_path, durations=None, style=DEFAULT_STYLE):
        result = original(data, output_path, durations=durations, style=style)
        path = Path(output_path)
        html = path.read_text(encoding="utf-8")
        marker = ".list-screen { padding-bottom: 180px !important; }"
        if marker not in html:
            html = html.replace("</head>", _SAFE_AREA_CSS + "</head>", 1)
            path.write_text(html, encoding="utf-8")
        return result

    patched._safe_area_patched = True  # type: ignore[attr-defined]
    _hotlist_render.render_composition = patched  # type: ignore[assignment]


# Period branding: the stock template hardcodes "本周" (this week) in several
# places. For a monthly edition we rewrite those labels after render_composition
# so the on-screen copy reads "本月" / "月报速递" / the supplied period suffix.
def _install_period_branding_patch(period_label: str | None, report_label: str | None) -> None:
    if not period_label and not report_label:
        return
    original = _hotlist_render.render_composition
    if getattr(original, "_period_patched", False):
        return

    def patched(data, output_path, durations=None, style=DEFAULT_STYLE):
        result = original(data, output_path, durations=durations, style=style)
        path = Path(output_path)
        html = path.read_text(encoding="utf-8")
        if period_label:
            html = html.replace("精选本周 GitHub", f"精选{period_label} GitHub")
            html = html.replace("· 本周", f"· {period_label}")
            html = html.replace("本周冠军", f"{period_label}冠军")
            html = html.replace("本周<br>", f"{period_label}<br>")
        if report_label:
            html = html.replace("周报速递", report_label)
        path.write_text(html, encoding="utf-8")
        return result

    patched._period_patched = True  # type: ignore[attr-defined]
    _hotlist_render.render_composition = patched  # type: ignore[assignment]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render hotlist video from authored content")
    parser.add_argument("--content", required=True, help="Path to content.json")
    parser.add_argument("--out", required=True, help="Final video path")
    parser.add_argument("--style", default="apple_minimal", choices=sorted(supported_styles()))
    parser.add_argument("--issue", type=int, default=None, help="Issue number override")
    parser.add_argument("--voice", default=None, help="TTS voice override")
    parser.add_argument("--rate", default=None, help="TTS rate override, e.g. +20%%")
    parser.add_argument("--no-bgm", action="store_true", help="Skip BGM mixing")
    parser.add_argument("--bgm-volume", type=float, default=0.07)
    parser.add_argument("--period-label", default=None, help="On-screen period word, e.g. 本月 / 本季度")
    parser.add_argument("--report-label", default=None, help="On-screen report badge, e.g. 月报速递")
    args = parser.parse_args()

    content_path = Path(args.content).resolve()
    payload = json.loads(content_path.read_text(encoding="utf-8"))
    projects = payload.get("projects") or []
    if not projects:
        raise SystemExit("content.json 缺少 projects")

    narration = payload.get("narration") or []
    list_narration = str(payload.get("list_narration") or "").strip()

    data = _data_from_projects(projects, issue_number=args.issue)

    # Intro copy and list narration overrides.
    for key in ("theme_highlight", "theme_tags"):
        if payload.get(key):
            data[key] = payload[key]
    if list_narration:
        data["list_narration"] = list_narration

    # Allow an explicit on-screen date (e.g. "2026 年 10 月") for monthly editions.
    meta = payload.get("meta") or {}
    if meta.get("date_display"):
        data["date"] = str(meta["date_display"])

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    _install_safe_area_css_patch()
    period_label = args.period_label or meta.get("period_label")
    report_label = args.report_label or meta.get("report_label")
    _install_period_branding_patch(period_label, report_label)

    asyncio.run(
        render_hotlist_v2_from_data(
            data,
            output_path=out,
            style=args.style or DEFAULT_STYLE,
            narration_segments=narration,
            limit=len(projects),
            voice=args.voice or TTS_VOICE,
            rate=args.rate,
        )
    )
    post_process_video(out, no_bgm=args.no_bgm, bgm_volume=args.bgm_volume)
    print(f"FINAL={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
