from __future__ import annotations

import unittest

from src.hotlist_v2.render import _build_script_from_timeline, _data_from_projects, _timeline_context


class HotlistV2RenderTest(unittest.TestCase):
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
        self.assertIn("功能上", project["reason"])
        self.assertNotIn("短视频", project["reason"])

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

        self.assertIn("设计", design_project["hook"])
        self.assertIn("设计", design_project["outcome"])
        self.assertIn("#AI设计", design_project["audience_tags"])
        self.assertNotEqual(ppt_project["outcome"], design_project["outcome"])

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


if __name__ == "__main__":
    unittest.main()
