"""炒股科普分镜生成器"""

from __future__ import annotations

import json
from typing import Any

from src.console.model_router import chat_json_detail
from src.finance_edu.constants import SCENE_TEMPLATE_MAP, VISUAL_STYLES
from src.finance_edu.models import (
    FinanceEduScene,
    FinanceEduScript,
    FinanceEduStoryboard,
    FinanceEduTopic,
)
from src.finance_edu.prompts import FINANCE_STORYBOARD_PROMPT


async def generate_finance_storyboard(
    topic: FinanceEduTopic,
    script: FinanceEduScript,
) -> FinanceEduStoryboard:
    """使用 AI 生成分镜，失败时根据脚本自动生成默认分镜"""
    script_json = json.dumps(script.to_dict(), ensure_ascii=False, indent=2)
    prompt = FINANCE_STORYBOARD_PROMPT.format(script_json=script_json)
    system = "你是一个专业的短视频分镜设计师，只输出合法 JSON。"

    result = chat_json_detail(
        task="finance_storyboard_generation",
        system=system,
        prompt=prompt,
        max_tokens=3000,
    )

    data = result.get("data")
    if data and isinstance(data.get("scenes"), list) and len(data["scenes"]) >= 5:
        return _normalize_storyboard(topic, data)

    return generate_default_storyboard(topic, script)


def _normalize_storyboard(topic: FinanceEduTopic, data: dict[str, Any]) -> FinanceEduStoryboard:
    """规范化分镜格式"""
    scenes: list[FinanceEduScene] = []
    for i, s in enumerate(data.get("scenes", [])):
        scene_type = str(s.get("scene_type", ""))
        if not scene_type:
            continue
        template_id = str(s.get("template_id", ""))
        if not template_id:
            template_id = SCENE_TEMPLATE_MAP.get(scene_type, "concept_card")
        scenes.append(FinanceEduScene(
            scene_id=str(s.get("scene_id", f"s{i+1}")),
            scene_type=scene_type,
            start=float(s.get("start", 0)),
            duration=float(s.get("duration", 5)),
            title=str(s.get("title", "")),
            subtitle=str(s.get("subtitle", "")),
            bullets=list(s.get("bullets") or []),
            narration=str(s.get("narration", "")),
            visual_style=str(s.get("visual_style", topic.visual_style)),
            template_id=template_id,
            chart_type=str(s.get("chart_type", "none")),
            chart_hint=str(s.get("chart_hint", "")),
            risk_note=str(s.get("risk_note", "")),
        ))

    if not scenes:
        return generate_default_storyboard(topic, FinanceEduScript(
            title=data.get("title", ""), hook="", narration="",
            segments=[], risk_disclaimer="", total_duration=topic.duration,
        ))

    return FinanceEduStoryboard(
        title=str(data.get("title") or topic.topic),
        scenes=scenes,
    )


def generate_default_storyboard(
    topic: FinanceEduTopic,
    script: FinanceEduScript,
) -> FinanceEduStoryboard:
    """根据脚本自动生成默认 7 段分镜"""
    scenes: list[FinanceEduScene] = []
    for i, seg in enumerate(script.segments):
        template_id = SCENE_TEMPLATE_MAP.get(seg.scene_type, "concept_card")
        chart_type = "macd" if topic.topic_type == "indicator" and seg.scene_type in {"how_it_works", "concept", "pitfall"} else "none"
        scenes.append(FinanceEduScene(
            scene_id=f"s{i+1}",
            scene_type=seg.scene_type,
            start=seg.start,
            duration=seg.duration,
            title=seg.screen_title or seg.narration[:16],
            subtitle=seg.screen_subtitle or "",
            bullets=seg.bullets,
            narration=seg.narration,
            visual_style=topic.visual_style,
            template_id=template_id,
            chart_type=chart_type,
            chart_hint="",
            risk_note="指标存在滞后性" if seg.scene_type == "pitfall" else "",
        ))

    return FinanceEduStoryboard(
        title=script.title,
        scenes=scenes,
    )
