from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.pipeline import run_pipeline


SAMPLE_REPOS = [
    "https://github.com/psf/requests",
    "https://github.com/pallets/flask",
]


@unittest.skipUnless(os.environ.get("GITHUB_VIDEO_RUN_SLOW_E2E") == "1", "set GITHUB_VIDEO_RUN_SLOW_E2E=1 to run slow real e2e smoke")
class RealE2ESmokeTest(unittest.TestCase):
    def test_hotlist_pipeline_generates_probeable_video_from_public_repos(self) -> None:
        stages: list[str] = []

        def record_stage(stage: str, _message: str) -> None:
            stages.append(stage)

        async def run() -> dict:
            with tempfile.TemporaryDirectory(prefix="github-video-real-e2e-") as tmp:
                output = Path(tmp) / "hotlist-real-e2e" / "final.mp4"
                try:
                    await run_pipeline(
                        url=",".join(SAMPLE_REPOS),
                        output=str(output),
                        orientation="vertical",
                        style="hotlist",
                        no_bgm=True,
                        stage_callback=record_stage,
                    )
                except Exception as exc:
                    last_stage = stages[-1] if stages else "github_api"
                    raise AssertionError(f"real e2e failed near {last_stage}: {exc}") from exc

                if not output.exists() or output.stat().st_size <= 0:
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
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                data = json.loads(probe.stdout)
                streams = data.get("streams", [])
                duration = float(data.get("format", {}).get("duration") or 0)
                size = int(data.get("format", {}).get("size") or 0)
                if not any(stream.get("codec_type") == "video" for stream in streams):
                    raise AssertionError("final.mp4 has no video stream")
                if not any(stream.get("codec_type") == "audio" for stream in streams):
                    raise AssertionError("final.mp4 has no audio stream")
                if duration <= 0 or size <= 0:
                    raise AssertionError(f"invalid media probe: duration={duration}, size={size}")
                return {
                    "output": str(output),
                    "duration": duration,
                    "size": size,
                    "stages": stages,
                }

        result = asyncio.run(run())
        self.assertIn("capturing_assets", result["stages"])
        self.assertIn("generating_tts", result["stages"])
        self.assertIn("composing_video", result["stages"])


if __name__ == "__main__":
    unittest.main()
