"""炒股科普领域模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TopicType = Literal["indicator", "trading_basic", "risk_discipline"]
Audience = Literal["beginner", "junior_retail"]
VisualStyle = Literal["black_gold", "white_card"]
RiskLevel = Literal["education_only"]
ComplianceLevel = Literal["low", "medium", "high"]


@dataclass
class FinanceEduTopic:
    """炒股科普视频主题配置"""
    topic: str
    topic_type: TopicType = "indicator"
    audience: Audience = "beginner"
    duration: int = 60
    platform: str = "douyin_wechat_channels"
    visual_style: VisualStyle = "black_gold"
    risk_level: RiskLevel = "education_only"
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "topic_type": self.topic_type,
            "audience": self.audience,
            "duration": self.duration,
            "platform": self.platform,
            "visual_style": self.visual_style,
            "risk_level": self.risk_level,
            "keywords": self.keywords,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FinanceEduTopic:
        return cls(
            topic=str(data.get("topic", "")),
            topic_type=str(data.get("topic_type", "indicator")),
            audience=str(data.get("audience", "beginner")),
            duration=int(data.get("duration", 60)),
            platform=str(data.get("platform", "douyin_wechat_channels")),
            visual_style=str(data.get("visual_style", "black_gold")),
            risk_level=str(data.get("risk_level", "education_only")),
            keywords=list(data.get("keywords") or []),
        )


@dataclass
class FinanceEduScriptSegment:
    """脚本片段"""
    scene_type: str
    start: float
    duration: float
    narration: str
    screen_title: str
    screen_subtitle: str
    bullets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scene_type": self.scene_type,
            "start": self.start,
            "duration": self.duration,
            "narration": self.narration,
            "screen_title": self.screen_title,
            "screen_subtitle": self.screen_subtitle,
            "bullets": self.bullets,
        }


@dataclass
class FinanceEduScript:
    """炒股科普脚本"""
    title: str
    hook: str
    narration: str
    segments: list[FinanceEduScriptSegment]
    risk_disclaimer: str
    total_duration: int = 60

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "hook": self.hook,
            "narration": self.narration,
            "segments": [s.to_dict() for s in self.segments],
            "risk_disclaimer": self.risk_disclaimer,
            "total_duration": self.total_duration,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FinanceEduScript:
        segments = [
            FinanceEduScriptSegment(
                scene_type=str(s.get("scene_type", "")),
                start=float(s.get("start", 0)),
                duration=float(s.get("duration", 5)),
                narration=str(s.get("narration", "")),
                screen_title=str(s.get("screen_title", "")),
                screen_subtitle=str(s.get("screen_subtitle", "")),
                bullets=list(s.get("bullets") or []),
            )
            for s in (data.get("segments") or [])
        ]
        return cls(
            title=str(data.get("title", "")),
            hook=str(data.get("hook", "")),
            narration=str(data.get("narration", "")),
            segments=segments,
            risk_disclaimer=str(data.get("risk_disclaimer", "")),
            total_duration=int(data.get("total_duration", 60)),
        )

    def collect_all_text(self) -> str:
        """收集脚本中所有文本用于合规检查"""
        parts = [self.title, self.hook, self.narration, self.risk_disclaimer]
        for seg in self.segments:
            parts.extend([seg.narration, seg.screen_title, seg.screen_subtitle])
            parts.extend(seg.bullets)
        return "\n".join(parts)


@dataclass
class FinanceVisualSpec:
    """图解视觉规格"""
    chart_type: str = "none"
    highlight_target: str = "none"
    chart_stage: str = "concept"
    annotations: list[str] = field(default_factory=list)
    animation_steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chart_type": self.chart_type,
            "highlight_target": self.highlight_target,
            "chart_stage": self.chart_stage,
            "annotations": self.annotations,
            "animation_steps": self.animation_steps,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "FinanceVisualSpec":
        if not data:
            return cls()
        return cls(
            chart_type=str(data.get("chart_type", "none")),
            highlight_target=str(data.get("highlight_target", "none")),
            chart_stage=str(data.get("chart_stage", "concept")),
            annotations=list(data.get("annotations") or []),
            animation_steps=list(data.get("animation_steps") or []),
        )


@dataclass
class FinanceEduScene:
    """分镜场景"""
    scene_id: str
    scene_type: str
    start: float
    duration: float
    title: str
    subtitle: str
    bullets: list[str]
    narration: str
    visual_style: str
    template_id: str
    chart_type: str
    chart_hint: str
    risk_note: str = ""
    visual_spec: FinanceVisualSpec = field(default_factory=FinanceVisualSpec)

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "scene_type": self.scene_type,
            "start": self.start,
            "duration": self.duration,
            "title": self.title,
            "subtitle": self.subtitle,
            "bullets": self.bullets,
            "narration": self.narration,
            "visual_style": self.visual_style,
            "template_id": self.template_id,
            "chart_type": self.chart_type,
            "chart_hint": self.chart_hint,
            "risk_note": self.risk_note,
            "visual_spec": self.visual_spec.to_dict(),
        }


@dataclass
class FinanceEduStoryboard:
    """分镜方案"""
    title: str
    scenes: list[FinanceEduScene]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "scenes": [s.to_dict() for s in self.scenes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FinanceEduStoryboard:
        scenes = [
            FinanceEduScene(
                scene_id=str(s.get("scene_id", f"s{i+1}")),
                scene_type=str(s.get("scene_type", "")),
                start=float(s.get("start", 0)),
                duration=float(s.get("duration", 5)),
                title=str(s.get("title", "")),
                subtitle=str(s.get("subtitle", "")),
                bullets=list(s.get("bullets") or []),
                narration=str(s.get("narration", "")),
                visual_style=str(s.get("visual_style", "black_gold")),
                template_id=str(s.get("template_id", "")),
                chart_type=str(s.get("chart_type", "none")),
                chart_hint=str(s.get("chart_hint", "")),
                risk_note=str(s.get("risk_note", "")),
                visual_spec=FinanceVisualSpec.from_dict(s.get("visual_spec")),
            )
            for i, s in enumerate(data.get("scenes") or [])
        ]
        return cls(
            title=str(data.get("title", "")),
            scenes=scenes,
        )


@dataclass
class FinanceComplianceIssue:
    """合规问题"""
    level: ComplianceLevel
    category: str
    text: str
    suggestion: str

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "category": self.category,
            "text": self.text,
            "suggestion": self.suggestion,
        }


@dataclass
class FinanceComplianceReport:
    """合规检查报告"""
    passed: bool
    max_risk_level: ComplianceLevel
    issues: list[FinanceComplianceIssue]
    rewritten_text: str | None = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "max_risk_level": self.max_risk_level,
            "issues": [i.to_dict() for i in self.issues],
            "rewritten_text": self.rewritten_text,
        }
