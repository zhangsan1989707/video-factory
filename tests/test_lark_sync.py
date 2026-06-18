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


class SyncAllCandidatesTest(unittest.TestCase):
    def test_sync_all_candidates_builds_records_and_upserts(self) -> None:
        from src.console.lark_sync import sync_all_candidates

        upsert_calls = []

        def fake_upsert(base_token, table_id, records, key_fields, **kwargs):
            upsert_calls.append({
                "base_token": base_token,
                "table_id": table_id,
                "records": records,
                "key_fields": key_fields,
            })
            return {"created": len(records), "updated": 0, "errors": []}

        with patch("src.console.lark_sync.upsert_records", side_effect=fake_upsert):
            job = {"id": "GH-HOTLIST-20260618-001", "scheduled": True}
            candidates = [
                {
                    "full_name": "a/b",
                    "name": "A",
                    "html_url": "https://github.com/a/b",
                    "description": "x",
                    "description_zh": "X",
                    "stargazers_count": 100,
                    "growth_text": "+10/天",
                    "language": "Python",
                    "topics": ["ai"],
                    "rationale": "r",
                    "risk": "r",
                    "audience": "a",
                    "score": 80,
                    "has_homepage": True,
                    "rank": 1,
                    "time_window": "daily",
                },
            ]
            result_meta = {
                "cache_status": "fresh",
                "data_source": "trending",
                "time_window": "daily",
            }
            result = sync_all_candidates(
                job=job,
                candidates=candidates,
                result_meta=result_meta,
                fetch_time="2026-06-18 09:00",
                base_token="bt",
                table_id="tblA",
            )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["records_count"], 1)
        record = upsert_calls[0]["records"][0]
        self.assertEqual(record["项目全名"], "a/b")
        self.assertEqual(record["抓取时间"], "2026-06-18 09:00")
        self.assertEqual(record["抓取方式"], "调度")
        self.assertEqual(record["时间窗口"], "daily")
        self.assertEqual(record["缓存状态"], "fresh")
        self.assertTrue(record["是否有主页"] is True)
        self.assertEqual(record["Topics"], "ai")

    def test_sync_all_candidates_marks_manual_when_not_scheduled(self) -> None:
        from src.console.lark_sync import sync_all_candidates

        captured = {}

        def fake_upsert(*args, **kwargs):
            captured["records"] = kwargs.get("records") or (args[2] if len(args) > 2 else None)
            return {"created": 0, "updated": 0, "errors": []}

        with patch("src.console.lark_sync.upsert_records", side_effect=fake_upsert):
            job = {"id": "X", "scheduled": False}
            candidates = [
                {"full_name": "a/b", "name": "A", "html_url": "x",
                 "stargazers_count": 0, "rank": 1, "topics": []},
            ]
            sync_all_candidates(
                job=job,
                candidates=candidates,
                result_meta={"cache_status": "hit", "data_source": "trending", "time_window": "daily"},
                fetch_time="t",
                base_token="bt",
                table_id="tblA",
            )

        self.assertEqual(captured["records"][0]["抓取方式"], "手动")

    def test_sync_all_candidates_skips_when_no_config(self) -> None:
        from src.console.lark_sync import sync_all_candidates

        result = sync_all_candidates(
            job={"id": "X"},
            candidates=[],
            result_meta={},
            fetch_time="t",
            base_token="",
            table_id="",
        )
        self.assertEqual(result["status"], "skipped")


class LarkSyncScanPublishedTest(unittest.TestCase):
    def test_scan_published_full_names_returns_completed_set(self) -> None:
        import tempfile

        from src.console.lark_sync import scan_published_full_names

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("src.console.lark_sync.JOBS_DIR", tmp_path):
                # Completed job with official_video
                (tmp_path / "J1").mkdir()
                (tmp_path / "J1" / "task.json").write_text(
                    '{"status":"completed","official_video":"/v/a.mp4"}'
                )
                (tmp_path / "J1" / "selected_projects.json").write_text(
                    '{"items":[{"full_name":"a/b"},{"full_name":"c/d"}]}'
                )

                # Incomplete job — should be ignored
                (tmp_path / "J2").mkdir()
                (tmp_path / "J2" / "task.json").write_text('{"status":"selected"}')
                (tmp_path / "J2" / "selected_projects.json").write_text(
                    '{"items":[{"full_name":"e/f"}]}'
                )

                # Completed but no official_video — should be ignored
                (tmp_path / "J3").mkdir()
                (tmp_path / "J3" / "task.json").write_text('{"status":"completed"}')
                (tmp_path / "J3" / "selected_projects.json").write_text(
                    '{"items":[{"full_name":"g/h"}]}'
                )

                result = scan_published_full_names()
                self.assertEqual(result, {"a/b", "c/d"})

    def test_scan_published_full_names_handles_missing_files(self) -> None:
        import tempfile

        from src.console.lark_sync import scan_published_full_names

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("src.console.lark_sync.JOBS_DIR", tmp_path):
                # Empty dir
                result = scan_published_full_names()
                self.assertEqual(result, set())

                # Dir with task.json but no selected_projects.json
                (tmp_path / "J1").mkdir()
                (tmp_path / "J1" / "task.json").write_text(
                    '{"status":"completed","official_video":"/v/a.mp4"}'
                )
                result = scan_published_full_names()
                self.assertEqual(result, set())

                # Corrupted JSON
                (tmp_path / "J2").mkdir()
                (tmp_path / "J2" / "task.json").write_text("not json")
                result = scan_published_full_names()
                self.assertEqual(result, set())


class MarkPublishedTest(unittest.TestCase):
    def test_mark_published_updates_published_flag(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import mark_published_in_lark

        update_calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"items":[{"record_id":"recExisting"}]}}', "")
            if "+record-update" in cmd:
                update_calls.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            job = {"id": "X", "fetch_time": "2026-06-18 09:00"}
            selected = [
                {"full_name": "a/b", "video_title": "T", "official_video": "/path/to/v.mp4"},
            ]
            result = mark_published_in_lark(
                job=job, selected=selected, published_at="2026-06-18 12:00",
                base_token="bt", table_id="tblS",
            )

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["missing"], [])
        # 检查 update 命令的 json payload
        update_cmd = update_calls[0]
        json_idx = update_cmd.index("--json")
        payload = json.loads(update_cmd[json_idx + 1])
        self.assertTrue(payload["已发布"] is True)
        self.assertEqual(payload["发布时间"], "2026-06-18 12:00")
        self.assertEqual(payload["视频路径"], "/path/to/v.mp4")
        self.assertEqual(payload["视频标题"], "T")

    def test_mark_published_logs_missing_records(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import mark_published_in_lark

        with patch(
            "src.console.lark_sync.subprocess.run",
            side_effect=lambda *a, **k: CompletedProcess(a[0], 0, '{"data":{"items":[]}}', ""),
        ):
            job = {"id": "X", "fetch_time": "t"}
            result = mark_published_in_lark(
                job=job, selected=[{"full_name": "x/y"}], published_at="t",
                base_token="bt", table_id="tblS",
            )

        self.assertEqual(result["updated"], 0)
        self.assertIn("x/y", result["missing"])

    def test_mark_published_skips_when_no_config(self) -> None:
        from src.console.lark_sync import mark_published_in_lark

        result = mark_published_in_lark(
            job={"id": "X", "fetch_time": "t"}, selected=[{"full_name": "a/b"}],
            published_at="t", base_token="", table_id="",
        )
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
