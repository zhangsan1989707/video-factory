from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.console.lark_sync import sync_selected_projects
from src.console.store import write_json


class LarkSyncTest(unittest.TestCase):
    def test_sync_selected_projects_writes_lark_records(self) -> None:
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "lark.json", {
                "enabled": True,
                "base_token": "base123",
                "table_id": "tbl123",
            })
            with (
                patch("src.console.lark_sync.CONFIG_DIR", config_dir),
                patch("src.console.lark_sync.subprocess.run", side_effect=fake_run),
            ):
                result = sync_selected_projects(
                    {"id": "JOB-1", "time_window": "daily"},
                    [{
                        "name": "alpha",
                        "full_name": "demo/alpha",
                        "repo_url": "https://github.com/demo/alpha",
                        "stars": 12,
                        "daily_growth": "估算日均 star 约 +3/天",
                    }],
                )

        payload = json.loads(calls[0][0][calls[0][0].index("--json") + 1])
        self.assertEqual(result, {"status": "synced", "count": 1, "error": ""})
        self.assertEqual(payload["任务 ID"], "JOB-1")
        self.assertEqual(payload["项目全名"], "demo/alpha")
        self.assertEqual(payload["Stars"], 12)
        self.assertEqual(payload["Daily Growth"], "估算日均 star 约 +3/天")
        self.assertIn("--as", calls[0][0])


if __name__ == "__main__":
    unittest.main()
