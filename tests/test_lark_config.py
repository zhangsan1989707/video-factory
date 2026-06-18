"""lark.json 配置 schema 扩展测试：2 个表 ID + 2 个开关。"""

from __future__ import annotations

from src.console.store import _normalize_lark, _redacted_lark


def test_normalize_lark_legacy_table_id_maps_to_selected() -> None:
    """旧 table_id 应映射到 selected_data_table_id，保持向后兼容。"""
    raw = {"enabled": True, "base_token": "bt", "table_id": "tblLegacy"}
    result = _normalize_lark(raw)
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == "tblLegacy"
    assert result["sync_all_data"] is True
    assert result["sync_selected_data"] is True


def test_normalize_lark_new_fields_default_to_empty_and_true() -> None:
    """缺少新字段时，默认值为空字符串和 True。"""
    raw = {"enabled": True, "base_token": "bt"}
    result = _normalize_lark(raw)
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == ""
    assert result["sync_all_data"] is True
    assert result["sync_selected_data"] is True


def test_redacted_lark_exposes_new_fields() -> None:
    """_redacted_lark 应暴露新增的 4 个字段。"""
    raw = {
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": "tblA",
        "selected_data_table_id": "tblS",
        "sync_all_data": True,
        "sync_selected_data": False,
    }
    redacted = _redacted_lark(raw)
    assert redacted["all_data_table_id"] == "tblA"
    assert redacted["selected_data_table_id"] == "tblS"
    assert redacted["sync_all_data"] is True
    assert redacted["sync_selected_data"] is False


def test_normalize_lark_none_returns_defaults() -> None:
    """传入 None 时应返回全部默认值。"""
    result = _normalize_lark(None)
    assert result["enabled"] is False
    assert result["base_token"] == ""
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == ""
    assert result["sync_all_data"] is True
    assert result["sync_selected_data"] is True


def test_normalize_lark_new_fields_explicit_values() -> None:
    """显式传入新字段值时应保留。"""
    raw = {
        "enabled": False,
        "base_token": "bt2",
        "all_data_table_id": "tblAll",
        "selected_data_table_id": "tblSel",
        "sync_all_data": False,
        "sync_selected_data": False,
    }
    result = _normalize_lark(raw)
    assert result["all_data_table_id"] == "tblAll"
    assert result["selected_data_table_id"] == "tblSel"
    assert result["sync_all_data"] is False
    assert result["sync_selected_data"] is False
