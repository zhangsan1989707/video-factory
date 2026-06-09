#!/usr/bin/env python3
"""Entry point for rendering a hotlist v2 video.

Usage:
    python scripts/render_hotlist_v2.py
    python scripts/render_hotlist_v2.py --limit 5 --window daily
    python scripts/render_hotlist_v2.py --output output/my-video.mp4
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hotlist_v2.render import render_hotlist_v2
from src.hotlist_v2.template import DEFAULT_STYLE


def main():
    parser = argparse.ArgumentParser(description="Render GitHub hotlist v2 video")
    parser.add_argument("--output", "-o", type=str, help="Output video path")
    parser.add_argument("--limit", type=int, default=10, help="Number of projects (default: 10)")
    parser.add_argument("--window", type=str, default="weekly", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--token", type=str, default="", help="GitHub API token (or set GITHUB_TOKEN env)")
    parser.add_argument("--intro-duration", type=int, default=4, help="Intro screen duration (seconds)")
    parser.add_argument("--list-duration", type=int, default=4, help="List screen duration (seconds)")
    parser.add_argument("--detail-duration", type=int, default=4, help="Detail screen duration (seconds)")
    parser.add_argument("--hook-duration", type=int, default=4, help="Hook screen duration (seconds)")
    parser.add_argument("--style", type=str, default=DEFAULT_STYLE, choices=[DEFAULT_STYLE], help="Visual style")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    output = Path(args.output) if args.output else None

    durations = {
        "intro_duration": args.intro_duration,
        "list_duration": args.list_duration,
        "detail_duration": args.detail_duration,
        "hook_duration": args.hook_duration,
    }

    asyncio.run(render_hotlist_v2(
        output_path=output,
        time_window=args.window,
        token=token,
        limit=args.limit,
        durations=durations,
        style=args.style,
    ))


if __name__ == "__main__":
    main()
