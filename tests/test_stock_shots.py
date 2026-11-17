"""股票科普分镜类型测试"""

import pytest
from src.stock.spec.shots import (
    TitleShot,
    DefinitionShot,
    ChartShot,
    ComparisonShot,
    SummaryShot,
    SHOT_TYPES,
)


def test_title_shot_to_dict():
    shot = TitleShot(
        id=1,
        start=0,
        end=5,
        main_title="60秒带你看懂",
        sub_title="MACD指标",
    )
    data = shot.to_dict()
    assert data["id"] == 1
    assert data["start"] == 0
    assert data["end"] == 5
    assert data["type"] == "title"
    assert data["content"]["main"] == "60秒带你看懂"
    assert data["content"]["sub"] == "MACD指标"


def test_definition_shot():
    shot = DefinitionShot(
        id=2,
        start=5,
        end=12,
        term="MACD",
        definition="Moving Average Convergence Divergence",
        translation="指数平滑异同移动平均线",
    )
    data = shot.to_dict()
    assert data["type"] == "definition"
    assert data["content"]["term"] == "MACD"


def test_shot_duration_property():
    shot = TitleShot(id=1, start=0, end=5, main_title="测试", sub_title="")
    assert shot.duration == 5


def test_shot_types_mapping():
    assert SHOT_TYPES["title"] == TitleShot
    assert SHOT_TYPES["definition"] == DefinitionShot
    assert SHOT_TYPES["chart"] == ChartShot
    assert SHOT_TYPES["comparison"] == ComparisonShot
    assert SHOT_TYPES["summary"] == SummaryShot
