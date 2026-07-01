"""股票科普视频分镜类型定义"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShotSpec:
    """分镜规范基类"""
    id: int
    start: float      # 开始时间（秒）
    end: float        # 结束时间（秒）
    shot_type: str = ""  # title | definition | chart | comparison | timeline | summary

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "type": self.shot_type,
        }


@dataclass
class TitleShot(ShotSpec):
    """封面标题分镜"""
    main_title: str = ""          # 主标题
    sub_title: str = ""           # 副标题
    style: str = "magazine_cover" # magazine_cover | minimal | bold

    def __post_init__(self):
        self.shot_type = "title"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "main": self.main_title,
                "sub": self.sub_title,
                "style": self.style,
            },
            "animation": {
                "enter": "fade_in_scale",
                "exit": "fade_out",
            },
        }


@dataclass
class DefinitionShot(ShotSpec):
    """名词定义分镜"""
    term: str = ""
    definition: str = ""
    translation: str = ""

    def __post_init__(self):
        self.shot_type = "definition"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "term": self.term,
                "definition": self.definition,
                "translation": self.translation,
            },
            "animation": {
                "enter": "slide_up",
                "elements": ["term", "definition", "translation"],
            },
        }


@dataclass
class ChartShot(ShotSpec):
    """图表展示分镜"""
    chart_type: str = "line"  # line | bar | pie | kline
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        self.shot_type = "chart"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "chart_type": self.chart_type,
                "data": self.data,
            },
            "animation": {
                "enter": "draw_in",
            },
        }


@dataclass
class ComparisonShot(ShotSpec):
    """对比展示分镜"""
    left_label: str = ""
    right_label: str = ""
    left_content: str = ""
    right_content: str = ""

    def __post_init__(self):
        self.shot_type = "comparison"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "left": {"label": self.left_label, "text": self.left_content},
                "right": {"label": self.right_label, "text": self.right_content},
            },
            "animation": {
                "enter": "slide_in",
                "direction": "left_right",
            },
        }


@dataclass
class TimelineShot(ShotSpec):
    """时间线分镜"""
    events: list[dict] = field(default_factory=list)  # [{"time": "", "event": ""}]

    def __post_init__(self):
        self.shot_type = "timeline"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "events": self.events,
            },
            "animation": {
                "enter": "sequential_reveal",
            },
        }


@dataclass
class SummaryShot(ShotSpec):
    """总结收尾分镜"""
    points: list[str] = field(default_factory=list)
    closing_text: str = ""

    def __post_init__(self):
        self.shot_type = "summary"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "content": {
                "points": self.points,
                "closing": self.closing_text,
            },
            "animation": {
                "enter": "fade_in",
            },
        }


# 分镜类型映射
SHOT_TYPES = {
    "title": TitleShot,
    "definition": DefinitionShot,
    "chart": ChartShot,
    "comparison": ComparisonShot,
    "timeline": TimelineShot,
    "summary": SummaryShot,
}
