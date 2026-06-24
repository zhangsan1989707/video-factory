from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from src.console.lark_sync import sync_selected_projects
from src.console.store import write_json


class LarkSyncTest(unittest.TestCase):
    def _make_run(self, create_payloads: list):
        """record-list 返回空（触发新增），batch-create 捕获 payload。"""
        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"items":[]}}', "")
            if "+record-batch-create" in cmd:
                create_payloads.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"record_ids":["recNew"]}}', "")
            if "+record-upsert" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{}}', "")
            return CompletedProcess(cmd, 0, "{}", "")
        return fake_run

    def test_sync_selected_projects_writes_lark_records(self) -> None:
        create_payloads = []

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "lark.json", {
                "enabled": True,
                "base_token": "base123",
                "selected_data_table_id": "tbl-selected",
                "sync_selected_data": True,
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.lark_sync.subprocess.run", side_effect=self._make_run(create_payloads)),
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

        # 通过批量 batch-create 写入，table_id 来自 selected_data_table_id
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["errors"], [])
        batch_cmd = create_payloads[0]
        self.assertIn("tbl-selected", batch_cmd)
        payload = json.loads(batch_cmd[batch_cmd.index("--json") + 1])
        # batch-create 用列式结构 {"fields":[...], "rows":[[...]]}
        fields = payload["fields"]
        row = payload["rows"][0]
        field_map = dict(zip(fields, row))
        self.assertEqual(field_map["任务 ID"], "JOB-1")
        self.assertEqual(field_map["项目全名"], "demo/alpha")
        self.assertEqual(field_map["Stars"], 12)
        self.assertEqual(field_map["Daily Growth"], "估算日均 star 约 +3/天")

    def test_sync_selected_projects_backward_compat_uses_legacy_table_id(self) -> None:
        """旧配置只有 table_id（无 selected_data_table_id）应向后兼容。"""
        create_payloads = []
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "lark.json", {
                "enabled": True,
                "base_token": "base123",
                "table_id": "tbl-legacy",
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.lark_sync.subprocess.run", side_effect=self._make_run(create_payloads)),
            ):
                result = sync_selected_projects({"id": "J"}, [{"full_name": "a/b", "name": "b"}])
        self.assertEqual(result["status"], "synced")
        self.assertIn("tbl-legacy", create_payloads[0])

    def test_sync_selected_projects_respects_sync_selected_data_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "lark.json", {
                "enabled": True,
                "base_token": "base123",
                "selected_data_table_id": "tbl",
                "sync_selected_data": False,
            })
            with patch("src.console.store.CONFIG_DIR", config_dir):
                result = sync_selected_projects({"id": "J"}, [{"full_name": "a/b"}])
        self.assertEqual(result["status"], "disabled")

    def test_sync_selected_projects_returns_partial_on_timeout(self) -> None:
        """超时后应立即返回 partial，不应阻塞等待线程完成。"""
        import time as _time

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "lark.json", {
                "enabled": True,
                "base_token": "base123",
                "selected_data_table_id": "tbl",
                "sync_selected_data": True,
            })

            def slow_run(cmd, *a, **kw):
                _time.sleep(5)
                return CompletedProcess(cmd, 0, "{}", "")

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.lark_sync.subprocess.run", side_effect=slow_run),
                patch("src.console.lark_sync.LARK_SYNC_TOTAL_TIMEOUT", 0.2),
            ):
                start = _time.monotonic()
                result = sync_selected_projects({"id": "J"}, [{"full_name": "a/b", "name": "b"}])
                elapsed = _time.monotonic() - start
        self.assertEqual(result["status"], "partial")
        self.assertIn("已中止", result["error"])
        # 关键断言：超时后不应阻塞等待线程完成
        # 0.2s 超时 + 少量开销，如果 shutdown(wait=True) 则会阻塞 5s
        self.assertLess(elapsed, 2.0, "超时后不应阻塞等待线程完成")


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
            if "+record-upsert" in cmd:
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

        # 验证 list 命令用了 --filter-json 和 --format json
        # （fake_run 无法直接拿到 list 调用，用单独断言验证命令构造）

    def test_upsert_records_updates_when_existing(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import upsert_records

        upsert_calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(
                    cmd,
                    0,
                    '{"data":{"items":[{"record_id":"recX","fields":{"项目全名":"a/b","抓取时间":"2026-06-18 09:00"}}]}}',
                    "",
                )
            if "+record-upsert" in cmd:
                upsert_calls.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"record":{}}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            records = [{"项目全名": "a/b", "抓取时间": "2026-06-18 09:00", "Stars": 200}]
            result = upsert_records("bt", "tblA", records, key_fields=("项目全名", "抓取时间"))
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        # 更新走 +record-upsert --record-id
        self.assertEqual(len(upsert_calls), 1)
        self.assertIn("--record-id", upsert_calls[0])
        self.assertEqual(upsert_calls[0][upsert_calls[0].index("--record-id") + 1], "recX")

    def test_upsert_records_empty_list(self) -> None:
        from src.console.lark_sync import upsert_records

        result = upsert_records("bt", "tblA", [], key_fields=("项目全名",))
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["errors"], [])

    def test_upsert_records_list_cmd_uses_filter_json_and_format(self) -> None:
        """record-list 调用必须用 --filter-json（view-filter 语法）和 --format json。"""
        from subprocess import CompletedProcess

        from src.console.lark_sync import upsert_records

        list_cmds: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                list_cmds.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"items":[]}}', "")
            if "+record-batch-create" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"record_ids":["recNew"]}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            upsert_records("bt", "tblA", [{"项目全名": "a/b", "抓取时间": "t"}], key_fields=("项目全名", "抓取时间"))

        self.assertEqual(len(list_cmds), 1)
        cmd = list_cmds[0]
        # 必须用 --filter-json，不能用不存在的 --filter
        self.assertIn("--filter-json", cmd)
        self.assertNotIn("--filter", [c for c in cmd if c != "--filter-json"])
        # 必须 --format json
        self.assertIn("--format", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        # filter-json 内容是合法 view-filter JSON
        filter_payload = json.loads(cmd[cmd.index("--filter-json") + 1])
        self.assertEqual(filter_payload["logic"], "and")
        self.assertEqual(
            filter_payload["conditions"],
            [["项目全名", "==", "a/b"], ["抓取时间", "==", "t"]],
        )

    def test_upsert_records_batch_create_payload_is_fields_rows_shape(self) -> None:
        """batch-create 的 --json 必须是 {"fields":[...],"rows":[...]}，而非 record 列表。"""
        from subprocess import CompletedProcess

        from src.console.lark_sync import upsert_records

        create_calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                return CompletedProcess(cmd, 0, '{"data":{"items":[]}}', "")
            if "+record-batch-create" in cmd:
                create_calls.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"record_ids":["recNew"]}}', "")
            return CompletedProcess(cmd, 0, "{}", "")

        with patch("src.console.lark_sync.subprocess.run", side_effect=fake_run):
            upsert_records(
                "bt", "tblA",
                [{"项目全名": "a/b", "Stars": 100}, {"项目全名": "c/d", "Stars": 200}],
                key_fields=("项目全名",),
            )

        self.assertEqual(len(create_calls), 1)
        payload = json.loads(create_calls[0][create_calls[0].index("--json") + 1])
        self.assertIsInstance(payload, dict)
        self.assertIn("fields", payload)
        self.assertIn("rows", payload)
        self.assertIn("项目全名", payload["fields"])
        self.assertIn("Stars", payload["fields"])
        # rows 是二维数组，列顺序与 fields 一致
        self.assertEqual(len(payload["rows"]), 2)
        for row in payload["rows"]:
            self.assertEqual(len(row), len(payload["fields"]))


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


class SyncSelectionGateTest(unittest.TestCase):
    """手动与调度任务都应同步已选到飞书（行为统一）。"""

    def test_sync_selection_to_lark_syncs_manual_job(self) -> None:
        """手动任务也应调用 sync_selected_projects（不再跳过）"""
        from src.console import jobs, store

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch("src.console.jobs.JOBS_DIR", tmp_path),
                patch("src.console.store.JOBS_DIR", tmp_path),
            ):
                job_id = "TEST-MANUAL"
                job_dir = tmp_path / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "task.json").write_text(json.dumps({
                    "id": job_id, "scheduled": False, "status": "selected", "lark_sync": {}
                }))

                sync_calls = []

                def fake_sync(*args, **kwargs):
                    sync_calls.append(args)
                    return {"status": "synced", "count": 1, "error": ""}

                with patch("src.console.jobs.sync_selected_projects", side_effect=fake_sync):
                    jobs._sync_selection_to_lark(job_id, [{"full_name": "a/b"}])

                self.assertEqual(len(sync_calls), 1, "手动任务也应调用 sync_selected_projects")

    def test_sync_selection_to_lark_runs_for_scheduled_job(self) -> None:
        """调度任务正常同步已选到飞书"""
        from src.console import jobs, store

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch("src.console.jobs.JOBS_DIR", tmp_path),
                patch("src.console.store.JOBS_DIR", tmp_path),
            ):
                job_id = "TEST-SCHED"
                job_dir = tmp_path / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "task.json").write_text(json.dumps({
                    "id": job_id, "scheduled": True, "status": "selected", "lark_sync": {}
                }))

                sync_calls = []

                def fake_sync(*args, **kwargs):
                    sync_calls.append(1)
                    return {"status": "synced", "count": 1, "error": ""}

                with patch("src.console.jobs.sync_selected_projects", side_effect=fake_sync):
                    jobs._sync_selection_to_lark(job_id, [{"full_name": "a/b"}])

                self.assertEqual(len(sync_calls), 1, "调度任务应调用 sync_selected_projects")


class BuildFilterTest(unittest.TestCase):
    def test_build_filter_returns_view_filter_json(self) -> None:
        from src.console.lark_sync import _build_filter

        result = _build_filter(
            {"项目全名": "a/b", "抓取时间": "2026-06-18 09:00"},
            ("项目全名", "抓取时间"),
        )
        payload = json.loads(result)
        self.assertEqual(payload["logic"], "and")
        self.assertEqual(len(payload["conditions"]), 2)
        self.assertEqual(payload["conditions"][0], ["项目全名", "==", "a/b"])
        self.assertEqual(payload["conditions"][1], ["抓取时间", "==", "2026-06-18 09:00"])

    def test_build_filter_single_field(self) -> None:
        from src.console.lark_sync import _build_filter

        result = _build_filter({"项目全名": "a/b"}, ("项目全名",))
        payload = json.loads(result)
        self.assertEqual(payload["conditions"], [["项目全名", "==", "a/b"]])


class MarkPublishedTest(unittest.TestCase):
    def test_mark_published_updates_published_flag(self) -> None:
        from subprocess import CompletedProcess

        from src.console.lark_sync import mark_published_in_lark

        update_calls: list[list[str]] = []
        list_calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            if "+record-list" in cmd:
                list_calls.append(cmd)
                return CompletedProcess(cmd, 0, '{"data":{"items":[{"record_id":"recExisting"}]}}', "")
            if "+record-upsert" in cmd:
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
        # list 命令用 --filter-json + --format json
        self.assertEqual(len(list_calls), 1)
        self.assertIn("--filter-json", list_calls[0])
        self.assertIn("--format", list_calls[0])
        self.assertEqual(list_calls[0][list_calls[0].index("--format") + 1], "json")
        # update 走 +record-upsert --record-id（不是 +record-update）
        self.assertEqual(len(update_calls), 1)
        self.assertIn("--record-id", update_calls[0])
        self.assertEqual(update_calls[0][update_calls[0].index("--record-id") + 1], "recExisting")
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


class ReadLarkConfigTest(unittest.TestCase):
    def test_read_lark_config_normalizes(self) -> None:
        from src.console import lark_sync, store

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "lark.json").write_text(json.dumps({
                "enabled": True, "base_token": "bt", "table_id": "tblLegacy"
            }))
            with patch.object(store, "CONFIG_DIR", tmp_path):
                cfg = lark_sync.read_lark_config()
            assert cfg["enabled"] is True
            assert cfg["selected_data_table_id"] == "tblLegacy"  # backward compat
            assert cfg["all_data_table_id"] == ""
            assert cfg["sync_all_data"] is True

    def test_read_lark_config_returns_defaults_when_missing(self) -> None:
        from src.console import lark_sync, store

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(store, "CONFIG_DIR", tmp_path):
                cfg = lark_sync.read_lark_config()
            assert cfg["enabled"] is False
            assert cfg["base_token"] == ""
            assert cfg["all_data_table_id"] == ""
            assert cfg["selected_data_table_id"] == ""


if __name__ == "__main__":
    unittest.main()
