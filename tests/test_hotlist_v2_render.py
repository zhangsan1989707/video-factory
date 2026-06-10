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


if __name__ == "__main__":
    unittest.main()
