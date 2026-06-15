from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.console.store import write_json
from src.models import AssetManifest
from src.pipeline import run_pipeline


class PipelineFromPlanTest(unittest.TestCase):
    def test_vertical_from_plan_dry_run_validates_artifacts_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            write_json(plan_dir / "shot_plan.json", {
                "title": "测试热榜",
                "shots": [
                    {
                        "start": 0,
                        "duration": 5,
                        "visual_asset": "",
                        "visual_treatment": "hotlist_opening",
                        "narration_intent": "开场",
                        "subtitle": "今天看一个开源项目。",
                    }
                ],
            })
            write_json(plan_dir / "asset_manifest.json", {"assets": []})

            result = asyncio.run(run_pipeline(
                url="",
                output=str(plan_dir / "final.mp4"),
                orientation="vertical",
                from_plan=str(plan_dir),
                dry_run=True,
            ))

            self.assertEqual(result, plan_dir)
            self.assertTrue((plan_dir / "script.json").exists())
            self.assertFalse((plan_dir / "final.mp4").exists())
            report = json.loads((plan_dir / "timing_report.json").read_text(encoding="utf-8"))
            self.assertIn("total_seconds", report)
            self.assertEqual([item["name"] for item in report["stages"]], ["script_generation"])

    def test_stage_callback_is_unchanged_when_timing_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            write_json(plan_dir / "shot_plan.json", {
                "title": "测试热榜",
                "shots": [
                    {
                        "start": 0,
                        "duration": 1,
                        "visual_asset": "",
                        "visual_treatment": "hotlist_opening",
                        "narration_intent": "开场",
                        "subtitle": "今天看一个开源项目。",
                    }
                ],
            })
            write_json(plan_dir / "asset_manifest.json", {"assets": []})
            events: list[tuple[str, str]] = []

            asyncio.run(run_pipeline(
                url="",
                output=str(plan_dir / "final.mp4"),
                orientation="vertical",
                from_plan=str(plan_dir),
                dry_run=True,
                stage_callback=lambda stage, message: events.append((stage, message)),
            ))

            self.assertEqual(events, [])
            self.assertTrue((plan_dir / "timing_report.json").exists())

    def test_failed_run_does_not_write_timing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)

            with self.assertRaises(FileNotFoundError):
                asyncio.run(run_pipeline(
                    url="",
                    output=str(plan_dir / "final.mp4"),
                    orientation="vertical",
                    from_plan=str(plan_dir),
                    dry_run=True,
                ))

            self.assertFalse((plan_dir / "timing_report.json").exists())

    def test_vertical_from_plan_runs_capture_and_tts_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            write_json(plan_dir / "shot_plan.json", {
                "title": "测试热榜",
                "shots": [
                    {
                        "start": 0,
                        "duration": 1,
                        "visual_asset": "web-1",
                        "visual_treatment": "hotlist_opening",
                        "narration_intent": "开场",
                        "subtitle": "今天看一个开源项目。",
                    }
                ],
            })
            write_json(plan_dir / "asset_manifest.json", {
                "assets": [
                    {
                        "id": "web-1",
                        "type": "webpage",
                        "source": "https://example.com",
                        "path": "https://example.com",
                        "caption": "示例页面",
                        "use_case": "测试",
                        "quality": "high",
                    }
                ]
            })

            starts: dict[str, float] = {}

            async def fake_capture(manifest: AssetManifest, output_dir: Path) -> AssetManifest:
                starts["capture"] = time.perf_counter()
                await asyncio.sleep(0.03)
                for asset in manifest.assets:
                    asset.path = str(output_dir / "asset.png")
                return manifest

            async def fake_tts(*args, **kwargs):
                starts["tts"] = time.perf_counter()
                await asyncio.sleep(0.03)
                return []

            with (
                patch("src.pipeline.capture_assets", side_effect=fake_capture),
                patch("src.pipeline.generate_all_audio", side_effect=fake_tts),
                patch("src.pipeline.compose_vertical_video", return_value=plan_dir / "final.mp4"),
                patch("src.pipeline.post_process_video", side_effect=lambda path, **kwargs: path),
            ):
                result = asyncio.run(run_pipeline(
                    url="",
                    output=str(plan_dir / "final.mp4"),
                    orientation="vertical",
                    from_plan=str(plan_dir),
                    no_bgm=True,
                ))

            self.assertEqual(result, plan_dir / "final.mp4")
            self.assertIn("capture", starts)
            self.assertIn("tts", starts)
            self.assertLess(abs(starts["capture"] - starts["tts"]), 0.02)
            report = json.loads((plan_dir / "timing_report.json").read_text(encoding="utf-8"))
            stage_names = [item["name"] for item in report["stages"]]
            self.assertIn("capture_assets", stage_names)
            self.assertIn("generate_tts", stage_names)
            self.assertIn("capture_and_tts_concurrent", stage_names)

    def test_hotlist_fetches_repositories_concurrently_and_keeps_order(self) -> None:
        from src.models import ProjectInfo

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "final.mp4"
            starts: dict[str, float] = {}

            async def fake_fetch(owner: str, repo: str) -> ProjectInfo:
                starts[repo] = time.perf_counter()
                await asyncio.sleep(0.03 if repo == "slow" else 0.01)
                return ProjectInfo(
                    name=repo,
                    owner=owner,
                    description=f"{owner}/{repo}",
                    readme="",
                    stars=10,
                    language="Python",
                    repo_url=f"https://github.com/{owner}/{repo}",
                )

            async def fake_capture(manifest, output_dir):
                await asyncio.sleep(0)
                return manifest

            async def fake_tts(*args, **kwargs):
                await asyncio.sleep(0)
                return []

            with (
                patch("src.pipeline.fetch_repo_info", side_effect=fake_fetch),
                patch("src.pipeline.capture_assets", side_effect=fake_capture),
                patch("src.pipeline.generate_all_audio", side_effect=fake_tts),
                patch("src.pipeline.compose_vertical_video", return_value=output),
                patch("src.pipeline.post_process_video", side_effect=lambda path, **kwargs: path),
            ):
                result = asyncio.run(run_pipeline(
                    url="https://github.com/acme/slow,https://github.com/acme/fast",
                    output=str(output),
                    orientation="vertical",
                    style="hotlist",
                    no_bgm=True,
                ))

            self.assertEqual(result, output)
            self.assertLess(abs(starts["slow"] - starts["fast"]), 0.02)
            info = (output.parent / "info.json").read_text(encoding="utf-8")
            self.assertLess(info.index('"name": "slow"'), info.index('"name": "fast"'))


if __name__ == "__main__":
    unittest.main()
