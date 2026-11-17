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
    FinanceVisualSpec,
)
from src.finance_edu.prompts import FINANCE_STORYBOARD_PROMPT

# 各主题的图解预设：scene_type -> visual_spec
_TOPIC_CHART_PRESETS: dict[str, dict[str, dict]] = {
    "MACD": {
        "concept": {
            "chart_type": "macd",
            "highlight_target": "dif_dea_histogram",
            "chart_stage": "concept",
            "annotations": ["DIF 是快线", "DEA 是慢线", "红绿柱反映差距"],
            "animation_steps": [
                {"at": 0.2, "action": "draw_zero_axis"},
                {"at": 0.5, "action": "draw_dif_line"},
                {"at": 0.8, "action": "draw_dea_line"},
                {"at": 1.2, "action": "grow_histogram"},
            ],
        },
        "how_it_works": {
            "chart_type": "macd",
            "highlight_target": "golden_cross",
            "chart_stage": "signal",
            "annotations": ["DIF 上穿 DEA", "红柱增强", "趋势可能转强"],
            "animation_steps": [
                {"at": 0.2, "action": "draw_price_line"},
                {"at": 0.6, "action": "draw_dif_line"},
                {"at": 0.9, "action": "draw_dea_line"},
                {"at": 1.3, "action": "grow_histogram"},
                {"at": 2.0, "action": "highlight_golden_cross"},
                {"at": 2.8, "action": "show_warning_label"},
            ],
        },
        "pitfall": {
            "chart_type": "macd",
            "highlight_target": "high_position_cross",
            "chart_stage": "pitfall",
            "annotations": ["高位金叉可能失效", "指标有滞后性", "位置比信号更重要"],
            "animation_steps": [
                {"at": 0.2, "action": "draw_high_price"},
                {"at": 0.8, "action": "draw_dif_dea"},
                {"at": 1.5, "action": "show_golden_cross_at_high"},
                {"at": 2.5, "action": "show_decline_after"},
            ],
        },
    },
    "KDJ": {
        "concept": {
            "chart_type": "kdj",
            "highlight_target": "k_d_j_lines",
            "chart_stage": "concept",
            "annotations": ["K 线：快速随机值", "D 线：K 的均值", "J 线：K 与 D 的偏离"],
        },
        "how_it_works": {
            "chart_type": "kdj",
            "highlight_target": "overbought_oversold",
            "chart_stage": "signal",
            "annotations": ["超买区 > 80", "超卖区 < 20", "J 线最敏感"],
        },
    },
    "均线": {
        "concept": {
            "chart_type": "ma",
            "highlight_target": "ma5_ma10_ma20",
            "chart_stage": "concept",
            "annotations": ["MA5：5日均线", "MA10：10日均线", "MA20：20日均线"],
        },
        "how_it_works": {
            "chart_type": "ma",
            "highlight_target": "golden_cross_arrangement",
            "chart_stage": "signal",
            "annotations": ["多头排列：MA5 > MA10 > MA20", "空头排列：MA5 < MA10 < MA20", "趋势确认"],
        },
    },
    "成交量": {
        "concept": {
            "chart_type": "volume",
            "highlight_target": "volume_bars",
            "chart_stage": "concept",
            "annotations": ["量增价涨：健康", "量缩价涨：谨慎", "放量下跌：风险"],
        },
    },
    "支撑位": {
        "concept": {
            "chart_type": "support_resistance",
            "highlight_target": "support_line",
            "chart_stage": "concept",
            "annotations": ["支撑位：价格多次触底", "突破支撑：可能继续下跌", "支撑变压力"],
        },
    },
    "压力位": {
        "concept": {
            "chart_type": "support_resistance",
            "highlight_target": "resistance_line",
            "chart_stage": "concept",
            "annotations": ["压力位：价格多次触顶", "突破压力：可能继续上涨", "压力变支撑"],
        },
    },
    "止损": {
        "concept": {
            "chart_type": "stop_loss",
            "highlight_target": "stop_loss_line",
            "chart_stage": "concept",
            "annotations": ["买入点", "止损线", "跌破即离场"],
        },
    },
}


def _get_chart_preset(topic_name: str, scene_type: str) -> dict | None:
    """根据主题名和场景类型获取图解预设"""
    for key, presets in _TOPIC_CHART_PRESETS.items():
        if key in topic_name:
            return presets.get(scene_type)
    return None


def _resolve_chart_type(topic_name: str, scene_type: str) -> str:
    """根据主题名推断 chart_type"""
    for key in _TOPIC_CHART_PRESETS:
        if key in topic_name:
            return _TOPIC_CHART_PRESETS[key].get(scene_type, {}).get("chart_type", "none")
    return "none"


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
        chart_type = str(s.get("chart_type", "none"))
        if chart_type == "none":
            chart_type = _resolve_chart_type(topic.topic, scene_type)

        preset = _get_chart_preset(topic.topic, scene_type)
        vs_data = s.get("visual_spec") or preset or {}
        visual_spec = FinanceVisualSpec.from_dict(vs_data)
        if visual_spec.chart_type == "none" and chart_type != "none":
            visual_spec.chart_type = chart_type

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
            chart_type=chart_type,
            chart_hint=str(s.get("chart_hint", "")),
            risk_note=str(s.get("risk_note", "")),
            visual_spec=visual_spec,
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
        chart_type = _resolve_chart_type(topic.topic, seg.scene_type)

        preset = _get_chart_preset(topic.topic, seg.scene_type)
        visual_spec = FinanceVisualSpec.from_dict(preset) if preset else FinanceVisualSpec(
            chart_type=chart_type,
            highlight_target="none",
            chart_stage=seg.scene_type,
        )

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
            visual_spec=visual_spec,
        ))

    return FinanceEduStoryboard(
        title=script.title,
        scenes=scenes,
    )
