"""Generate grounded narration from a shot plan."""

import re

from src.models import ShotPlan, VideoScript, ScriptSegment


BANNED_WORDS = ("兄弟们", "卧槽", "绝了", "神器", "宝藏项目", "真的牛", "快去Star")
REPLACEMENTS = {
    "Stars": "星标数",
    "Practice modes": "练习模式",
    "Follow-along": "跟读",
    "Dictation": "听写",
    "Self-test": "自测",
    "Spelling from memory": "拼写回忆",
    "Smart mode": "智能模式",
    "Automatically calculates learning words based on memory curves": "会根据记忆曲线安排学习内容",
}


def _clean_line(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    for word in BANNED_WORDS:
        text = text.replace(word, "")
    for source, target in REPLACEMENTS.items():
        text = text.replace(source, target)
    text = text.replace(" / ", "、").replace("/", "、")
    text = text.replace("快去 GitHub 点 Star", "可以去 GitHub 看源码")
    text = text.replace("快去GitHub点Star", "可以去 GitHub 看源码")
    text = text.strip(" ，。")
    return text if text.endswith(("？", "！", "?", "!")) else text + "。"


def generate_script_from_shot_plan(plan: ShotPlan) -> VideoScript:
    """Convert V2 shots to the legacy VideoScript shape for TTS reuse."""
    segments = []
    for shot in plan.shots:
        narration = _clean_line(shot.subtitle)
        segments.append(ScriptSegment(
            timestamp=shot.start,
            duration=shot.duration,
            narration=narration,
            action="asset",
            target=shot.visual_asset,
            focus_area=shot.visual_treatment,
        ))

    return VideoScript(
        title=plan.title,
        segments=segments,
        total_duration=sum(segment.duration for segment in segments),
    )
