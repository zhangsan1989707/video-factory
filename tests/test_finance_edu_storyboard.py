"""finance_edu 分镜生成测试"""

from src.finance_edu.models import FinanceEduScript, FinanceEduScriptSegment, FinanceEduTopic
from src.finance_edu.storyboard import generate_default_storyboard


def _make_topic(**kwargs) -> FinanceEduTopic:
    defaults = {"topic": "MACD", "topic_type": "indicator", "audience": "beginner", "visual_style": "black_gold"}
    defaults.update(kwargs)
    return FinanceEduTopic(**defaults)


def _make_script(segments: list[dict] | None = None) -> FinanceEduScript:
    if segments is None:
        segments = [
            {"scene_type": "hook", "start": 0, "duration": 3, "narration": "测试口播1", "screen_title": "标题1", "screen_subtitle": "副标题1", "bullets": []},
            {"scene_type": "misunderstanding", "start": 3, "duration": 5, "narration": "测试口播2", "screen_title": "标题2", "screen_subtitle": "副标题2", "bullets": ["要点"]},
            {"scene_type": "concept", "start": 8, "duration": 10, "narration": "测试口播3", "screen_title": "标题3", "screen_subtitle": "副标题3", "bullets": []},
            {"scene_type": "how_it_works", "start": 18, "duration": 14, "narration": "测试口播4", "screen_title": "标题4", "screen_subtitle": "副标题4", "bullets": []},
            {"scene_type": "how_to_use", "start": 32, "duration": 13, "narration": "测试口播5", "screen_title": "标题5", "screen_subtitle": "副标题5", "bullets": []},
            {"scene_type": "pitfall", "start": 45, "duration": 10, "narration": "测试口播6", "screen_title": "标题6", "screen_subtitle": "副标题6", "bullets": []},
            {"scene_type": "summary", "start": 55, "duration": 5, "narration": "测试口播7", "screen_title": "标题7", "screen_subtitle": "副标题7", "bullets": []},
        ]
    script_segs = [
        FinanceEduScriptSegment(
            scene_type=s["scene_type"], start=s["start"], duration=s["duration"],
            narration=s["narration"], screen_title=s["screen_title"],
            screen_subtitle=s["screen_subtitle"], bullets=s.get("bullets", []),
        )
        for s in segments
    ]
    return FinanceEduScript(
        title="测试脚本", hook="钩子", narration="口播",
        segments=script_segs, risk_disclaimer="风险提示",
    )


def test_default_storyboard_has_seven_scenes():
    topic = _make_topic()
    script = _make_script()
    storyboard = generate_default_storyboard(topic, script)
    assert len(storyboard.scenes) == 7


def test_default_storyboard_scene_types():
    topic = _make_topic()
    script = _make_script()
    storyboard = generate_default_storyboard(topic, script)
    scene_types = [s.scene_type for s in storyboard.scenes]
    assert scene_types == [
        "hook", "misunderstanding", "concept",
        "how_it_works", "how_to_use", "pitfall", "summary",
    ]


def test_default_storyboard_template_ids():
    topic = _make_topic()
    script = _make_script()
    storyboard = generate_default_storyboard(topic, script)
    templates = [s.template_id for s in storyboard.scenes]
    assert "hook_title" in templates
    assert "myth_vs_truth" in templates
    assert "summary_quote" in templates
