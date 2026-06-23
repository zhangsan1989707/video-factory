"""lark.json 配置 schema 扩展测试：2 个表 ID + 2 个开关。"""

from __future__ import annotations

import functools
import tempfile
from pathlib import Path

from src.console.store import DEFAULT_LARK, _normalize_lark, _redacted_lark, write_json


def _with_isolated_config(func):
    """Decorator: run func with CONFIG_DIR pointing to a temp dir."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from src.console import store as store_mod
        orig = str(store_mod.CONFIG_DIR)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            write_json(config_dir / "lark.json", dict(DEFAULT_LARK))
            store_mod.CONFIG_DIR = config_dir
            try:
                return func(*args, **kwargs)
            finally:
                store_mod.CONFIG_DIR = Path(orig)
    return wrapper


@_with_isolated_config
def test_normalize_lark_legacy_table_id_maps_to_selected() -> None:
    """旧 table_id 应映射到 selected_data_table_id，保持向后兼容。"""
    raw = {"enabled": True, "base_token": "bt", "table_id": "tblLegacy"}
    result = _normalize_lark(raw)
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == "tblLegacy"
    assert result["sync_all_data"] is True
    assert result["sync_selected_data"] is True


@_with_isolated_config
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


@_with_isolated_config
def test_normalize_lark_none_returns_defaults() -> None:
    """传入 None 时应返回全部默认值。"""
    result = _normalize_lark(None)
    assert result["enabled"] is False
    assert result["base_token"] == ""
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == ""
    assert result["sync_all_data"] is True
    assert result["sync_selected_data"] is True


@_with_isolated_config
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


@_with_isolated_config
def test_normalize_lark_clear_table_ids_with_empty_string() -> None:
    """用户通过传入空字符串应能清空 all_data_table_id 和 selected_data_table_id。

    回归测试：data.get("key") or current.get("key") 链中空字符串被 or 跳过，
    导致用户无法清空字段。恢复 "key in data" 语义后，空字符串应生效。
    """
    # 先写入一个有值的配置（模拟 update_config 的完整流程）
    first = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": "tblOld",
        "selected_data_table_id": "tblOldSel",
    })
    from src.console import store as store_mod
    write_json(store_mod.CONFIG_DIR / "lark.json", first)
    # 用空字符串清空
    result = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": "",
        "selected_data_table_id": "",
    })
    assert result["all_data_table_id"] == ""
    assert result["selected_data_table_id"] == ""


@_with_isolated_config
def test_normalize_lark_omit_table_ids_preserves_current() -> None:
    """不传入 table_id 字段时应保留当前值，不清空。"""
    # 先写入有值的配置（模拟 update_config 的完整流程）
    first = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": "tblKeep",
        "selected_data_table_id": "tblKeepSel",
    })
    from src.console import store as store_mod
    write_json(store_mod.CONFIG_DIR / "lark.json", first)
    # 不传 table_id 字段，应保留磁盘上的值
    result = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
    })
    assert result["all_data_table_id"] == "tblKeep"
    assert result["selected_data_table_id"] == "tblKeepSel"


@_with_isolated_config
def test_normalize_lark_null_values_treated_as_empty() -> None:
    """传入 null (Python None) 时应等同于空字符串，不应变成 'None' 字符串。

    回归测试：str(None) 会产生 'None' 字符串导致数据损坏。
    修复后 None 值应回落到当前值或空字符串。
    """
    # 先写入有值的配置
    first = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": "tblExisting",
        "selected_data_table_id": "tblExistingSel",
    })
    from src.console import store as store_mod
    write_json(store_mod.CONFIG_DIR / "lark.json", first)
    # 传入 null 值，应回落到当前值（与不传入字段行为一致）
    result = _normalize_lark({
        "enabled": True,
        "base_token": "bt",
        "all_data_table_id": None,
        "selected_data_table_id": None,
    })
    assert result["all_data_table_id"] == "tblExisting", f"Expected 'tblExisting', got '{result['all_data_table_id']}'"
    assert result["selected_data_table_id"] == "tblExistingSel", f"Expected 'tblExistingSel', got '{result['selected_data_table_id']}'"
