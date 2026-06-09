from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.console.store import write_json
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


if __name__ == "__main__":
    unittest.main()
