#!/usr/bin/env python3
"""Manual benchmark helper for the legacy pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_pipeline


SAMPLE_REPOS = [
    "https://github.com/psf/requests",
    "https://github.com/pallets/flask",
]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_plan_fixture(base: Path) -> None:
    _write_json(base / "shot_plan.json", {
        "title": "Benchmark dry run",
        "shots": [
            {
                "start": 0,
                "duration": 3,
                "visual_asset": "",
                "visual_treatment": "hotlist_opening",
                "narration_intent": "开场",
                "subtitle": "Benchmark timing dry run.",
            }
        ],
    })
    _write_json(base / "asset_manifest.json", {"assets": []})


def format_timing_summary(report: dict) -> str:
    lines = [f"total: {report.get('total_seconds', 0):.3f}s"]
    for stage in report.get("stages", []):
        lines.append(f"- {stage.get('name')}: {stage.get('seconds', 0):.3f}s")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> Path:
    if args.real_hotlist:
        output = Path(args.output or "output/benchmark-hotlist/final.mp4")
        return await run_pipeline(
            url=",".join(args.repo or SAMPLE_REPOS),
            output=str(output),
            orientation="vertical",
            style="hotlist",
            no_bgm=args.no_bgm,
        )

    plan_dir = Path(args.output or "output/benchmark-dry-run")
    plan_dir.mkdir(parents=True, exist_ok=True)
    _create_plan_fixture(plan_dir)
    return await run_pipeline(url="", from_plan=str(plan_dir), dry_run=True, orientation="vertical")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a repeatable pipeline timing benchmark")
    parser.add_argument("--output", type=str, help="Output directory for dry-run, or final mp4 path for --real-hotlist")
    parser.add_argument("--real-hotlist", action="store_true", help="Run a real two-repository hotlist render")
    parser.add_argument("--repo", action="append", help="Repository URL for --real-hotlist; can be repeated")
    parser.add_argument("--no-bgm", action="store_true", help="Skip BGM for real hotlist benchmark")
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    report_dir = result if result.is_dir() else result.parent
    report_path = report_dir / "timing_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"output: {result}")
        print(f"timing_report: {report_path}")
        print(format_timing_summary(report))


if __name__ == "__main__":
    main()
