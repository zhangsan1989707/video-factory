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


class LarkSyncUpsertTest(unittest.TestCase):
    def test_upsert_records_creates_when_missing(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import upsert_records

        create_calls = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"items":[]}}', "")
            if "+record-batch-create" in cmd:
                create_calls.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"record_ids":["recNew"]}}', "")
            if "+record-update" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            records = [
                {"项目全名": "a/b", "抓取时间": "2026-06-18 09:00", "Stars": 100},
            ]
            result = upsert_records(
                base_token="bt",
                table_id="tblA",
                records=records,
                key_fields=("项目全名", "抓取时间"),
            )
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(create_calls), 1)

    def test_upsert_records_updates_when_existing(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import upsert_records

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(
                    cmd,
                    0,
                    '{"data":{"items":[{"record_id":"recX","fields":{"项目全名":"a/b","抓取时间":"2026-06-18 09:00"}}]}}',
                    "",
                )
            if "+record-update" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"record":{}}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            records = [{"项目全名": "a/b", "抓取时间": "2026-06-18 09:00", "Stars": 200}]
            result = upsert_records("bt", "tblA", records, key_fields=("项目全名", "抓取时间"))
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)

    def test_upsert_records_empty_list(self) -> None:
        from src.console.lark_sync import upsert_records

        result = upsert_records("bt", "tblA", [], key_fields=("项目全名",))
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
