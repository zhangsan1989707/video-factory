from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader

from src.hotlist_v2.render import _build_script_from_timeline, _data_from_projects, _timeline_context, render_hotlist_v2_previews_from_projects
from src.hotlist_v2.template import DEFAULT_STYLE, STYLE_PROFILES, TEMPLATE_DIR, list_template_styles, normalize_style, render_composition, supported_styles


class HotlistV2RenderTest(unittest.TestCase):
    def test_template_registry_exposes_first_batch_styles(self) -> None:
        styles = {item["style"] for item in list_template_styles()}

        self.assertEqual(normalize_style("missing"), DEFAULT_STYLE)
        self.assertEqual(normalize_style("black_gold"), "chinese_editorial")
        self.assertEqual(styles, {
            "tech_hotspot",
            "apple_minimal",
            "claude_warm",
            "sspai_editorial",
            "bytedance_product",
            "chinese_editorial",
        })
        self.assertEqual(styles, supported_styles())

    def test_each_registered_style_renders_hyperframes_composition(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/project",
                "name": "project",
                "description_zh": "适合做成中文短视频切入点。",
                "stars": 1000,
                "language": "Python",
            }
        ])
        render_data = {**data, **_timeline_context(data)}

        with TemporaryDirectory() as tmp:
            for style in sorted(supported_styles()):
                output = Path(tmp) / f"{style}.html"
                render_composition(render_data, output, style=style)
                html = output.read_text(encoding="utf-8")

                self.assertIn('data-composition-id="main"', html)
                self.assertIn(f'data-style="{style}"', html)
                self.assertIn('id="screen-intro"', html)
                self.assertIn('id="screen-list"', html)
                self.assertIn('id="screen-detail-01"', html)
                self.assertIn('id="screen-hook"', html)
                self.assertIn('window.__timelines["main"]', html)

    def test_preview_rendering_uses_each_registered_style(self) -> None:
        projects = [
            {
                "full_name": "demo/project",
                "name": "project",
                "description_zh": "适合做成中文短视频切入点。",
                "stars": 1000,
                "language": "Python",
            }
        ]
        calls = []

        def fake_capture(html_path: Path, targets: list[tuple[str, Path]]) -> list[Path]:
            calls.append((html_path, targets))
            return [target_path for _screen_id, target_path in targets]

        with TemporaryDirectory() as tmp, patch("src.hotlist_v2.render._capture_html_screens", side_effect=fake_capture):
            for style in sorted(supported_styles()):
                output_dir = Path(tmp) / style / "preview_frames"
                previews = render_hotlist_v2_previews_from_projects(projects, output_dir, style=style)
                html = calls[-1][0].read_text(encoding="utf-8")
                screen_ids = [screen_id for screen_id, _target in calls[-1][1]]

                self.assertEqual(len(previews), 4)
                self.assertIn(f'data-style="{style}"', html)
                self.assertEqual(screen_ids, ["screen-intro", "screen-list", "screen-detail-01", "screen-hook"])

    def test_template_falls_back_to_default_style_profile_when_missing(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/project",
                "name": "project",
                "description_zh": "适合做成中文短视频切入点。",
                "stars": 1000,
                "language": "Python",
            }
        ])
        render_data = {**data, **_timeline_context(data), "style_key": DEFAULT_STYLE}
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
        template = env.get_template("hotlist-v2.html")

        html = template.render(**render_data, default_style_profile=STYLE_PROFILES[DEFAULT_STYLE])

        self.assertIn(f"--canvas-bg: {STYLE_PROFILES[DEFAULT_STYLE]['canvas_bg']};", html)
        self.assertIn(f'data-style="{DEFAULT_STYLE}"', html)

    def test_ten_projects_expand_to_full_hyperframes_timeline(self) -> None:
        projects = [
            {
                "full_name": f"demo/project-{index}",
                "name": f"project-{index}",
                "description_zh": "适合做成中文短视频切入点。",
                "stars": 1000 - index,
                "language": "Python",
            }
            for index in range(1, 11)
        ]
        narration_segments = [
            {"id": "intro", "text": "今天看 10 个 GitHub 热榜项目。"},
            *[
                {"id": f"project-{index}", "text": f"第 {index} 个项目，值得关注。"}
                for index in range(1, 11)
            ],
            {"id": "outro", "text": "评论区告诉我你想先看哪个。"},
        ]

        data = _data_from_projects(projects)
        timeline = _timeline_context(data, narration_segments=narration_segments)
        script = _build_script_from_timeline(timeline)

        self.assertEqual(data["total_projects"], 10)
        self.assertEqual(len(timeline["detail_screens"]), 10)
        self.assertEqual(timeline["detail_screens"][-1]["screen_id"], "screen-detail-10")
        self.assertEqual(len(script.segments), 13)
        self.assertGreater(script.total_duration, 16)

    def test_audio_durations_extend_visual_timeline(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/project",
                "name": "project",
                "description_zh": "一个值得关注的项目。",
                "stars": 1000,
                "language": "Python",
            }
        ])

        timeline = _timeline_context(data, segment_durations={"intro": 9.2, "project-1": 11.0})
        script = _build_script_from_timeline(timeline)

        self.assertEqual(timeline["intro_screen"]["duration"], 9.6)
        self.assertEqual(timeline["detail_screens"][0]["duration"], 11.4)
        self.assertEqual(timeline["list_screen"]["start"], 9.6)
        self.assertEqual(script.segments[2].timestamp, timeline["detail_screens"][0]["start"])

    def test_missing_forks_render_as_unknown_instead_of_zero(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/project",
                "name": "project",
                "description": "CLI helper",
                "stars": 120,
                "language": "Python",
            }
        ])

        self.assertEqual(data["projects"][0]["forks"], "未知")

    def test_detail_copy_filters_producer_advice(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/project",
                "name": "project",
                "description": "Terminal workflow helper",
                "description_zh": "适合做成中文短视频切入点：可以从项目用途、适合人群和实际价值三个角度介绍。",
                "project_highlight": "把重复命令收拢成更短路径",
                "viewer_benefit": "减少终端和文档之间来回切换",
                "stars": 120,
                "forks": 8,
                "language": "Python",
            }
        ])

        project = data["projects"][0]
        self.assertEqual(project["description"], "Terminal workflow helper")
        self.assertIn("把重复命令收拢成更短路径", project["purpose"])
        self.assertIn("把重复命令收拢成更短路径", project["reason"])
        self.assertIn("证据", project["reason"])
        self.assertNotIn("短视频", project["reason"])
        self.assertNotIn("功能上", project["reason"])

    def test_ai_projects_get_specific_hooks_outcomes_and_tags(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "gorden/GordenSuperPPTSkills",
                "name": "GordenSuperPPTSkills",
                "description": "AI powered PowerPoint presentation workflow",
                "topics": ["ai", "ppt", "workflow"],
                "stars": 3290,
                "daily_growth": "+329",
                "language": "Python",
            },
            {
                "full_name": "baoyu/baoyu-design",
                "name": "baoyu-design",
                "description": "Claude agent skills for generating UI design drafts",
                "topics": ["ai", "design", "claude"],
                "stars": 980,
                "daily_growth": "+45",
                "language": "JavaScript",
            },
        ])

        ppt_project, design_project = data["projects"]
        self.assertIn("PPT", ppt_project["hook"])
        self.assertIn("PPT", ppt_project["outcome"])
        self.assertIn("#PPT自动化", ppt_project["audience_tags"])
        self.assertIn("🔥", ppt_project["trend_label"])
        self.assertEqual(ppt_project["trend_heat"], "hot")
        self.assertIn("PPT自动化", ppt_project["display_tags"])

        self.assertIn("设计", design_project["hook"])
        self.assertIn("设计", design_project["outcome"])
        self.assertIn("#AI设计", design_project["audience_tags"])
        self.assertEqual(design_project["trend_heat"], "steady")
        self.assertNotEqual(ppt_project["outcome"], design_project["outcome"])
        self.assertEqual(data["total_new_stars"], "374")
        self.assertIn("证据", ppt_project["reason"])
        self.assertNotIn("值得关注", ppt_project["reason"])

    def test_fact_card_replaces_empty_hotlist_copy(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/unknown",
                "name": "unknown",
                "description_zh": "近期热度上升，重点看它的具体用途、实现效果和上手成本。",
                "stars": 42,
                "daily_growth": "",
                "language": "",
            }
        ])

        project = data["projects"][0]
        self.assertEqual(data["total_new_stars"], "待确认")
        self.assertEqual(project["core_problem"], "功能证据待补齐")
        self.assertIn("证据", project["reason"])
        self.assertIn("待补充真实截图", project["visual_asset_label"])
        self.assertNotIn("近期热度上升", project["description"])
        self.assertNotIn("具体用途", project["reason"])

    def test_missing_repo_description_renders_readme_purpose(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "vorpus/performativeUI",
                "name": "performativeUI",
                "description": "",
                "description_zh": "README 显示：AI-native React components for satirical product interfaces.",
                "repo_description_missing": True,
                "description_source": "readme",
                "readme_excerpt": "# performative-ui\n\nAI-native React components for satirical product interfaces.",
                "stars": 545,
                "daily_growth": "+272",
                "language": "TypeScript",
                "repo_url": "https://github.com/vorpus/performativeUI",
            }
        ])

        project = data["projects"][0]
        self.assertIn("AI-native React components", project["description"])
        self.assertIn("AI-native React components", project["purpose"])
        self.assertIn("GitHub 简介字段未填写", project["risk_note"])
        self.assertNotIn("缺少项目描述", project["description"])
        self.assertNotIn("建议跳过", project["reason"])

    def test_duplicate_outcomes_are_rewritten(self) -> None:
        data = _data_from_projects([
            {
                "full_name": "demo/agent-one",
                "name": "agent-one",
                "description": "AI agent workflow",
                "topics": ["ai", "agent"],
                "stars": 100,
                "language": "Python",
            },
            {
                "full_name": "demo/agent-two",
                "name": "agent-two",
                "description": "AI agent workflow",
                "topics": ["ai", "agent"],
                "stars": 90,
                "language": "Python",
            },
        ])

        first, second = data["projects"]
        self.assertNotEqual(first["outcome"], second["outcome"])
        self.assertIn("更具体地说", second["outcome"])


    def test_capture_html_screens_closes_browser_on_error(self) -> None:
        """Browser must be closed even when screenshot fails."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import MagicMock, patch

        from src.hotlist_v2.render import _capture_html_screens

        fake_browser = MagicMock()
        fake_page = MagicMock()
        fake_browser.new_page.return_value = fake_page
        # Simulate wait_for_selector raising an error
        fake_page.wait_for_selector.side_effect = RuntimeError("screen not found")

        fake_pw = MagicMock()
        fake_pw.chromium.launch.return_value = fake_browser
        fake_pw.__enter__ = MagicMock(return_value=fake_pw)
        fake_pw.__exit__ = MagicMock(return_value=False)

        with TemporaryDirectory() as tmp, patch("playwright.sync_api.sync_playwright", return_value=fake_pw):
            html_path = Path(tmp) / "test.html"
            html_path.write_text("<html></html>")
            try:
                _capture_html_screens(html_path, [("screen-missing", Path(tmp) / "out.png")])
            except RuntimeError:
                pass

        # Browser must be closed regardless of the error
        fake_browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
