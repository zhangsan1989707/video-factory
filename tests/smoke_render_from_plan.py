from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from src.pipeline import run_pipeline


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="github-video-render-smoke-") as tmp:
        job_dir = Path(tmp)
        write_json(job_dir / "asset_manifest.json", {"assets": []})
        write_json(job_dir / "info.json", {"projects": [{"name": "alpha"}, {"name": "beta"}]})
        write_json(job_dir / "shot_plan.json", {
            "title": "E2E 渲染验证",
            "shots": [
                {
                    "start": 0,
                    "duration": 3.0,
                    "visual_asset": "",
                    "visual_treatment": "hotlist_opening",
                    "narration_intent": "开场",
                    "subtitle": "这是一次本机端到端渲染验证。",
                },
                {
                    "start": 3.0,
                    "duration": 3.0,
                    "visual_asset": "",
                    "visual_treatment": "hotlist_ranking:#1 alpha 1.5K Star;#2 beta 88 Star",
                    "narration_intent": "榜单",
                    "subtitle": "系统会生成语音、合成画面，并输出最终视频。",
                },
                {
                    "start": 6.0,
                    "duration": 3.0,
                    "visual_asset": "",
                    "visual_treatment": "hotlist_closing:#1 alpha 1.5K Star;#2 beta 88 Star",
                    "narration_intent": "结尾",
                    "subtitle": "如果这个文件生成成功，说明本机渲染链路可用。",
                },
            ],
        })

        await run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style="hotlist",
            dry_run=True,
        )
        await run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style="hotlist",
            no_bgm=True,
        )

        final = job_dir / "final.mp4"
        if not final.exists() or final.stat().st_size <= 0:
            raise AssertionError("final.mp4 was not generated")
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size",
                "-show_streams",
                "-of",
                "json",
                str(final),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(probe.stdout)
        streams = data.get("streams", [])
        if not any(stream.get("codec_type") == "video" for stream in streams):
            raise AssertionError("final.mp4 has no video stream")
        if not any(stream.get("codec_type") == "audio" for stream in streams):
            raise AssertionError("final.mp4 has no audio stream")
        print(json.dumps({
            "output": str(final),
            "duration": data.get("format", {}).get("duration"),
            "size": data.get("format", {}).get("size"),
            "streams": [
                {
                    "codec_type": stream.get("codec_type"),
                    "codec_name": stream.get("codec_name"),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                }
                for stream in streams
            ],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
