from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.console.preflight import preflight_snapshot
from src.console.server import ConsoleHandler


class ConsolePreflightTest(unittest.TestCase):
    def test_preflight_snapshot_reports_required_render_checks(self) -> None:
        report = preflight_snapshot()

        self.assertIn(report["status"], {"ready", "blocked"})
        self.assertIn("checks", report)
        check_ids = {item["id"] for item in report["checks"]}
        self.assertIn("ffmpeg", check_ids)
        self.assertIn("ffprobe", check_ids)
        self.assertIn("node", check_ids)
        self.assertIn("npx", check_ids)
        self.assertIn("node.hyperframes", check_ids)
        self.assertIn("playwright.browsers", check_ids)
        self.assertIn("python.edge_tts", check_ids)
        self.assertIn("config.model_provider", check_ids)

    def test_model_provider_check_warns_when_configured_provider_failed_last_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            providers = {
                "providers": [
                    {
                        "id": "xiaomi",
                        "name": "Xiaomi",
                        "enabled": True,
                        "configured": True,
                        "api_key": "secret",
                        "last_test": "连接失败: Not supported model MiMo-V2.5-Pro",
                    }
                ]
            }
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                config_dir.mkdir(parents=True)
                (config_dir / "providers.json").write_text(json.dumps(providers), encoding="utf-8")

                report = preflight_snapshot()

        check = next(item for item in report["checks"] if item["id"] == "config.model_provider")
        self.assertEqual(check["status"], "warning")
        self.assertIn("最近连接测试失败", check["message"])
        self.assertEqual(report["warning_count"], 2)

    def test_model_provider_check_passes_after_successful_connection_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            providers = {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "enabled": True,
                        "configured": True,
                        "api_key": "secret",
                        "last_test": "连接成功: ok",
                    }
                ]
            }
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                config_dir.mkdir(parents=True)
                (config_dir / "providers.json").write_text(json.dumps(providers), encoding="utf-8")

                report = preflight_snapshot()

        check = next(item for item in report["checks"] if item["id"] == "config.model_provider")
        self.assertEqual(check["status"], "ok")
        self.assertIn("已通过连接测试", check["message"])

    def test_preflight_endpoint_returns_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/preflight", timeout=10) as response:
                        report = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertIn(report["status"], {"ready", "blocked"})
        self.assertTrue(report["checks"])


if __name__ == "__main__":
    unittest.main()
