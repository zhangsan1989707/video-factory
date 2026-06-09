from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.console.jobs import job_detail, prepare_plan, render_video, save_script, save_selection, validate_plan
from src.console.store import create_job


def sample_projects() -> list[dict[str, object]]:
    return [
        {
            "name": "alpha",
            "full_name": "demo/alpha",
            "repo_url": "",
            "stars": 1520,
            "description": "AI agent workflow",
            "description_zh": "AI 工作流工具",
            "recommendation": "解决重复操作",
            "visual_potential": "README 可展示",
            "audience": "AI 开发者",
        },
        {
            "name": "beta",
            "full_name": "demo/beta",
            "repo_url": "",
            "stars": 88,
            "description": "CLI helper",
            "description_zh": "命令行助手",
            "recommendation": "减少切工具",
            "visual_potential": "终端截图可展示",
            "audience": "开发者",
        },
    ]


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="github-video-console-smoke-") as tmp:
        jobs_dir = Path(tmp) / "jobs"
        with (
            patch("src.console.store.JOBS_DIR", jobs_dir),
            patch("src.console.jobs.JOBS_DIR", jobs_dir),
            patch("src.console.jobs.route_snapshot", return_value={
                "provider": "",
                "provider_name": "",
                "model": "",
                "enabled": "",
                "configured": "",
            }),
        ):
            job = create_job("GH-HOTLIST-20990101-SMOKE", {
                "title": "控制台真实渲染验证",
                "project_count": 2,
                "template_params": {"bgm": "none"},
            })
            selection = save_selection(job["id"], {"items": sample_projects()})
            save_script(job["id"], {"segments": selection["segments"]})
            prepared = prepare_plan(job["id"])
            validated = await validate_plan(job["id"])
            rendered = await render_video(job["id"])
            detail = job_detail(job["id"])

            official = Path(rendered["job"]["official_video"])
            if rendered["job"]["status"] != "completed":
                raise AssertionError(f"job did not complete: {rendered['job']}")
            if not official.exists() or official.stat().st_size <= 0:
                raise AssertionError("official video was not generated")
            required_files = {
                "final.mp4",
                official.name,
                "cover_frame.png",
                "cover_frame.json",
                "publish_pack.json",
                "readiness_report.json",
                "quality_report.json",
                "shot_plan.json",
                "asset_manifest.json",
                "script.json",
            }
            artifact_names = {item["name"] for item in detail["artifacts"]["files"]}
            missing = sorted(required_files - artifact_names)
            if missing:
                raise AssertionError(f"missing artifacts: {missing}")
            if not detail["video_versions"] or detail["video_versions"][-1]["name"] != official.name:
                raise AssertionError("official video version was not indexed")
            if prepared["readiness_report"]["status"] != "ready":
                raise AssertionError(f"unexpected readiness: {prepared['readiness_report']}")
            if validated["plan_validation"]["status"] != "passed":
                raise AssertionError(f"unexpected validation: {validated['plan_validation']}")

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
                    str(official),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            data = json.loads(probe.stdout)
            streams = data.get("streams", [])
            if not any(stream.get("codec_type") == "video" for stream in streams):
                raise AssertionError("official video has no video stream")
            if not any(stream.get("codec_type") == "audio" for stream in streams):
                raise AssertionError("official video has no audio stream")
            print(json.dumps({
                "job_id": job["id"],
                "official_video": str(official),
                "duration": data.get("format", {}).get("duration"),
                "size": data.get("format", {}).get("size"),
                "artifact_count": len(artifact_names),
                "video_versions": detail["video_versions"],
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
