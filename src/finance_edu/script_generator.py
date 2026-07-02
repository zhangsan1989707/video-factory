"""炒股科普脚本生成器"""

from __future__ import annotations

import json
import re
from typing import Any

from src.console.model_router import chat_json_detail
from src.finance_edu.constants import (
    AUDIENCES,
    DEFAULT_RISK_DISCLAIMER,
    SCRIPT_STRUCTURE,
    TOPIC_TYPES,
    VISUAL_STYLES,
)
from src.finance_edu.models import FinanceEduScript, FinanceEduScriptSegment, FinanceEduTopic
from src.finance_edu.prompts import FINANCE_SCRIPT_PROMPT


def _extract_core_topic(full_topic: str) -> str:
    """从完整标题中提取核心主题词

    例: "60秒带你搞懂MACD" -> "MACD"
         "新手怎么看均线" -> "均线"
         "成交量放大到底说明什么" -> "成交量"
    """
    cleaned = full_topic.strip()
    # 去掉 "60秒/一分钟/快速/轻松/简单 + 带你/来/一起 + 搞懂/看懂/学会/了解/读懂" 前缀
    cleaned = re.sub(r"^(?:60\s*秒|一分钟|快速|轻松|简单).{0,4}(?:搞懂|看懂|学会|了解|读懂)", "", cleaned)
    # 去掉 "新手/小白/初学者 + 怎么/如何 + 看/学/用/玩" 前缀
    cleaned = re.sub(r"^(?:新手|小白|初学者)(?:怎么|如何)(?:看|学|用|玩)?", "", cleaned)
    # 去掉 "为什么 + 新手/散户/一定要/必须" 前缀
    cleaned = re.sub(r"^为什么.{0,8}(?:新手|散户|一定要|必须)(?:懂|学|了解)?", "", cleaned)
    # 去掉 "什么是/聊聊/说说/讲讲" 前缀
    cleaned = re.sub(r"^(?:什么是|聊聊|说说|讲讲)", "", cleaned)
    # 去掉 "是什么/说明什么/怎么办/怎么看/怎么用" 等后缀
    cleaned = re.sub(r"(?:是什么|说明什么|怎么办|怎么看|怎么用)$", "", cleaned)
    cleaned = cleaned.strip("？?！!。，、 的了")
    return cleaned if cleaned else full_topic


async def generate_finance_script(topic: FinanceEduTopic) -> FinanceEduScript:
    """使用 AI 生成炒股科普脚本，失败时返回兜底脚本"""
    core_topic = _extract_core_topic(topic.topic)
    prompt = FINANCE_SCRIPT_PROMPT.format(
        topic=core_topic,
        topic_type_label=TOPIC_TYPES.get(topic.topic_type, topic.topic_type),
        audience_label=AUDIENCES.get(topic.audience, topic.audience),
        visual_style_label=VISUAL_STYLES.get(topic.visual_style, topic.visual_style),
    )
    system = "你是一个专业的中文股票知识科普短视频编导，只输出合法 JSON。"

    result = chat_json_detail(
        task="finance_script_generation",
        system=system,
        prompt=prompt,
        max_tokens=3000,
    )

    data = result.get("data")
    if data and isinstance(data.get("segments"), list) and len(data["segments"]) >= 5:
        return _normalize_script(topic, core_topic, data)

    return _fallback_script(topic, core_topic)


def _normalize_script(topic: FinanceEduTopic, core_topic: str, data: dict[str, Any]) -> FinanceEduScript:
    """规范化脚本格式"""
    segments: list[FinanceEduScriptSegment] = []
    for seg in data.get("segments", []):
        scene_type = str(seg.get("scene_type", ""))
        if not scene_type:
            continue
        narration = str(seg.get("narration", "")).strip()
        if not narration:
            continue
        segments.append(FinanceEduScriptSegment(
            scene_type=scene_type,
            start=float(seg.get("start", 0)),
            duration=float(seg.get("duration", 5)),
            narration=narration,
            screen_title=str(seg.get("screen_title", "")),
            screen_subtitle=str(seg.get("screen_subtitle", "")),
            bullets=list(seg.get("bullets") or []),
        ))

    if not segments:
        return _fallback_script(topic, core_topic)

    narration = "\n".join(s.narration for s in segments)
    risk_disclaimer = str(data.get("risk_disclaimer") or DEFAULT_RISK_DISCLAIMER)

    return FinanceEduScript(
        title=str(data.get("title") or f"60秒搞懂{core_topic}"),
        hook=str(data.get("hook") or segments[0].narration[:30]),
        narration=narration,
        segments=segments,
        risk_disclaimer=risk_disclaimer,
        total_duration=topic.duration,
    )


def _fallback_script(topic: FinanceEduTopic, core_topic: str) -> FinanceEduScript:
    """LLM 不可用时的兜底脚本"""
    t = core_topic
    segments = [
        FinanceEduScriptSegment(
            scene_type="hook", start=0, duration=3,
            narration=f"很多新手一听到{t}就头大，今天 60 秒帮你搞懂。",
            screen_title=f"{t}怎么用？", screen_subtitle="新手最容易踩的坑", bullets=[],
        ),
        FinanceEduScriptSegment(
            scene_type="misunderstanding", start=3, duration=5,
            narration=f"{t}不是买卖按钮，它只是帮你观察趋势变化的工具。",
            screen_title="它不是买卖按钮", screen_subtitle="只是一个观察工具",
            bullets=["不是预测器", "不是指令", "只是辅助"],
        ),
        FinanceEduScriptSegment(
            scene_type="concept", start=8, duration=10,
            narration=f"简单理解，{t}的核心就是看趋势的变化快慢，帮你判断当前市场在什么状态。",
            screen_title=f"{t}的核心", screen_subtitle="趋势变化的快慢",
            bullets=["看趋势", "看变化", "看位置"],
        ),
        FinanceEduScriptSegment(
            scene_type="how_it_works", start=18, duration=14,
            narration=f"用{t}的时候，你要关注几个关键信号。信号出现时说明趋势可能在变化，但不代表一定会反转。",
            screen_title="关键信号", screen_subtitle="趋势变化的信号",
            bullets=["信号出现", "趋势变化", "不一定反转"],
        ),
        FinanceEduScriptSegment(
            scene_type="how_to_use", start=32, duration=13,
            narration=f"真正使用{t}时，不能只看单一信号，还要结合趋势位置、成交量和自己的风险承受能力。",
            screen_title="别只看单一信号", screen_subtitle="还要看这三件事",
            bullets=["趋势位置", "成交量", "风险空间"],
        ),
        FinanceEduScriptSegment(
            scene_type="pitfall", start=45, duration=10,
            narration=f"尤其要注意，{t}本身有滞后性。信号出现时，行情可能已经走了一段了。",
            screen_title="注意滞后性", screen_subtitle="信号出现时行情可能已经走了一段",
            bullets=["指标会滞后", "位置不同意义不同", "不要追信号"],
        ),
        FinanceEduScriptSegment(
            scene_type="summary", start=55, duration=5,
            narration=f"一句话记住，{t}是观察工具，不是预测工具，更不能单独作为买卖依据。",
            screen_title="一句话记住", screen_subtitle=f"{t}看趋势，不预测未来", bullets=[],
        ),
    ]

    narration = "\n".join(s.narration for s in segments)
    return FinanceEduScript(
        title=f"60秒搞懂{t}",
        hook=segments[0].narration[:30],
        narration=narration,
        segments=segments,
        risk_disclaimer=DEFAULT_RISK_DISCLAIMER,
        total_duration=topic.duration,
    )
