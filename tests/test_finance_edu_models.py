"""finance_edu 模型测试"""

from src.finance_edu.models import (
    FinanceComplianceReport,
    FinanceComplianceIssue,
    FinanceEduScene,
    FinanceEduScript,
    FinanceEduScriptSegment,
    FinanceEduStoryboard,
    FinanceEduTopic,
)


def test_finance_topic_defaults():
    topic = FinanceEduTopic(topic="60秒带你搞懂MACD")
    assert topic.duration == 60
    assert topic.risk_level == "education_only"
    assert topic.topic_type == "indicator"
    assert topic.audience == "beginner"
    assert topic.visual_style == "black_gold"


def test_finance_topic_to_dict_roundtrip():
    topic = FinanceEduTopic(topic="MACD", topic_type="indicator", audience="beginner")
    data = topic.to_dict()
    restored = FinanceEduTopic.from_dict(data)
    assert restored.topic == "MACD"
    assert restored.topic_type == "indicator"
    assert restored.duration == 60


def test_script_segment_to_dict():
    seg = FinanceEduScriptSegment(
        scene_type="hook",
        start=0,
        duration=3,
        narration="测试口播",
        screen_title="测试标题",
        screen_subtitle="测试副标题",
        bullets=["要点1"],
    )
    data = seg.to_dict()
    assert data["scene_type"] == "hook"
    assert data["bullets"] == ["要点1"]


def test_script_collect_all_text():
    script = FinanceEduScript(
        title="测试标题",
        hook="测试钩子",
        narration="完整口播",
        segments=[
            FinanceEduScriptSegment(
                scene_type="hook", start=0, duration=3,
                narration="口播内容", screen_title="标题", screen_subtitle="副标题",
                bullets=["要点"],
            )
        ],
        risk_disclaimer="风险提示",
    )
    text = script.collect_all_text()
    assert "测试标题" in text
    assert "口播内容" in text
    assert "风险提示" in text


def test_storyboard_roundtrip():
    scene = FinanceEduScene(
        scene_id="s1",
        scene_type="hook",
        start=0,
        duration=3,
        title="标题",
        subtitle="副标题",
        bullets=[],
        narration="口播",
        visual_style="black_gold",
        template_id="hook_title",
        chart_type="none",
        chart_hint="",
    )
    storyboard = FinanceEduStoryboard(title="测试", scenes=[scene])
    data = storyboard.to_dict()
    restored = FinanceEduStoryboard.from_dict(data)
    assert len(restored.scenes) == 1
    assert restored.scenes[0].template_id == "hook_title"
