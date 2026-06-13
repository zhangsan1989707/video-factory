"""腳本質量檢查 — 事實一致性、誇大表達、可讀性評分。

從 jobs.py 拆分出來，保持與 jobs.py 的鬆散耦合：quality.py 不導入 jobs.py。
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.console import model_router
from src.console.github_hotlist import ESTIMATED_GROWTH_NOTE
from src.console.shared import (
    _contains_growth_overclaim,
    _fact_similarity,
    _fallback_feature_extract,
    _normalize_fact_text,
    _readme_excerpt,
    _record_model_call,
    _route_available,
    _route_skip_reason,
    _sanitize_feature_extract,
    _short_text,
    _write_ai_raw_response,
)
from src.console import store


# ---------------------------------------------------------------------------
# 渲染門控
# ---------------------------------------------------------------------------

def _quality_blocks_render(report: dict[str, Any]) -> bool:
    return bool(report) and not _quality_allows_render(report)


def _quality_allows_render(report: dict[str, Any]) -> bool:
    if not report:
        return True
    if report.get("manual_override"):
        return True
    if report.get("status") == "pass" and report.get("passed") is True:
        return True
    return report.get("status") in {"unverified", "skipped"}


def _quality_verified(report: dict[str, Any]) -> bool:
    if not report:
        return False
    if report.get("manual_override"):
        return True
    return report.get("status") == "pass" and report.get("passed") is True


def _ensure_quality_gate(job_id: str) -> None:
    quality = store.read_json(store.JOBS_DIR / job_id / "quality_report.json", {})
    if _quality_blocks_render(quality):
        raise ValueError("脚本质检未通过，请在控制台复核风险项，或手动忽略风险后再渲染。")


def _apply_quality_override(job_id: str, report: dict[str, Any]) -> dict[str, Any]:
    patched = dict(report)
    patched["manual_override"] = True
    patched["passed"] = True
    patched["override_note"] = "用户已在控制台确认忽略质检风险。"
    store.write_json(store.JOBS_DIR / job_id / "quality_report.json", patched)
    store.append_log(job_id, "用户已手动忽略脚本质检风险，允许继续准备出片。")
    return patched


# ---------------------------------------------------------------------------
# 主質檢入口
# ---------------------------------------------------------------------------

def _quality_check_script(
    job_id: str,
    segments: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> None:
    route = model_router.route_snapshot("fact_check")
    report_path = store.JOBS_DIR / job_id / "quality_report.json"
    if not _route_available(route):
        reason = _route_skip_reason(route)
        store.write_json(report_path, {
            "status": "unverified",
            "passed": False,
            "summary": reason,
            "risk_flags": [],
            "factual_notes": [],
            "overclaim_notes": [],
            "issues": [],
            "readability_score": None,
            "provider": route.get("provider_name") or route.get("provider") or "",
            "model": route.get("model") or "",
            "error": "",
            "error_details": [],
            "verified": False,
        })
        store.append_log(job_id, f"脚本质检未验证：{reason}。")
        return

    prompt = {
        "instruction": (
            "检查 GitHub 热榜短视频中文口播是否存在事实风险、夸大承诺、表达不清。只根据输入字段判断，不能补充外部事实。"
            "daily_growth / growth_note 仅表示按当前总 stars 和仓库创建时间折算的估算日均 star，不是真实新增 star。"
            "如果口播把这类估算说成真实新增、单日暴涨、今天上涨等事实，必须标成风险。"
        ),
        "projects": [
            {
                "rank": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description": project.get("description"),
                "description_zh": project.get("description_zh"),
                "feature_extract": project.get("feature_extract") or {},
                "recommendation": project.get("recommendation"),
                "risk": project.get("risk"),
                "stars": project.get("stars"),
                "daily_growth": project.get("daily_growth"),
                "growth_note": project.get("growth_note") or ESTIMATED_GROWTH_NOTE,
            }
            for index, project in enumerate(projects, start=1)
        ],
        "segments": [
            {
                "id": segment.get("id"),
                "label": segment.get("label"),
                "text": segment.get("text"),
            }
            for segment in segments
        ],
        "schema": {
            "status": "pass | caution",
            "summary": "一句中文结论",
            "risk_flags": ["需要人工复核的风险点"],
            "factual_notes": ["事实或来源不足的句子"],
            "overclaim_notes": ["过度承诺或夸大的句子"],
            "readability_score": 85,
        },
    }
    try:
        detail = model_router.chat_json_detail(
            "fact_check",
            "你是克制的中文视频脚本质检编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=1800,
        )
        data = detail["data"]
        report = _sanitize_quality_report(data, detail.get("route") or {}, "", detail.get("error_details") or [])
        if not report:
            _write_ai_raw_response(job_id, "fact_check", detail)
            _record_model_call(job_id, "fact_check", detail, "invalid_json")
            report = _quality_report_error("invalid_json", detail.get("route") or {}, detail.get("error") or "模型未返回可用 JSON", detail.get("error_details") or [])
            report = _with_local_fact_checks(report, projects, segments)
            store.write_json(report_path, report)
            store.append_log(job_id, "脚本质检模型未返回可用 JSON，已保留原始响应。")
            return
        report = _with_local_fact_checks(report, projects, segments)
        store.write_json(report_path, report)
        _record_model_call(job_id, "fact_check", detail, "success")
        store.append_log(job_id, f"脚本质检完成：{report['summary']}")
    except Exception as exc:
        _record_model_call(job_id, "fact_check", {"route": route, "error": str(exc)}, "failed")
        report = _with_local_fact_checks(_quality_report_error("failed", route, str(exc), []), projects, segments)
        store.write_json(report_path, report)
        store.append_log(job_id, f"脚本质检失败，已要求人工复核: {exc}")


# ---------------------------------------------------------------------------
# 報告整理
# ---------------------------------------------------------------------------

def _sanitize_quality_report(
    data: dict[str, Any] | None,
    route: dict[str, Any],
    error: str,
    error_details: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    summary = _short_text(str(data.get("summary") or ""), 160)
    if not summary:
        return None
    status = str(data.get("status") or "caution").strip().lower()
    if status not in {"pass", "caution"}:
        status = "caution"
    risk_flags = _short_list(data.get("risk_flags"), 8, 160)
    factual_notes = _short_list(data.get("factual_notes"), 8, 180)
    overclaim_notes = _short_list(data.get("overclaim_notes"), 8, 180)
    return {
        "status": status,
        "passed": status == "pass",
        "verified": status == "pass",
        "summary": summary,
        "risk_flags": risk_flags,
        "factual_notes": factual_notes,
        "overclaim_notes": overclaim_notes,
        "issues": [
            *[_quality_issue("风险", text) for text in risk_flags],
            *[_quality_issue("事实", text) for text in factual_notes],
            *[_quality_issue("夸大", text) for text in overclaim_notes],
        ][:8],
        "readability_score": _score_or_none(data.get("readability_score")),
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
        "error_details": _short_error_details(error_details or []),
    }


def _quality_report_error(status: str, route: dict[str, Any], error: str, error_details: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": status,
        "passed": False,
        "verified": False,
        "summary": "脚本质检未完成，请人工检查事实和夸大表达。",
        "risk_flags": [],
        "factual_notes": [],
        "overclaim_notes": [],
        "issues": [],
        "readability_score": None,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
        "error_details": _short_error_details(error_details),
    }


# ---------------------------------------------------------------------------
# 本地事實檢查
# ---------------------------------------------------------------------------

def _with_local_fact_checks(
    report: dict[str, Any],
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    report = _bind_quality_issues(report, projects, segments)
    local_flags = _local_fact_flags(projects, segments)
    if local_flags:
        # 区分硬错误（daily_growth 事实问题）和软建议（相似度问题）
        hard_flags = [f for f in local_flags if "daily_growth" in str(f.get("text", ""))]
        soft_flags = [f for f in local_flags if f not in hard_flags]
        if hard_flags:
            # 明确的事实错误：硬否决
            report = dict(report)
            report["risk_flags"] = [*report.get("risk_flags", []), *[flag["text"] for flag in hard_flags]][:8]
            report["issues"] = [*report.get("issues", []), *hard_flags][:8]
            report["status"] = "caution"
            report["passed"] = False
            report["summary"] = "脚本存在需要人工复核的事实一致性风险。"
        if soft_flags:
            # 相似度/表达建议：仅追加到 issues 和 risk_flags，不覆盖 AI 模型的 status/passed
            report = dict(report)
            report["risk_flags"] = [*report.get("risk_flags", []), *[flag["text"] for flag in soft_flags]][:8]
            report["issues"] = [*report.get("issues", []), *soft_flags][:8]
            # 注意：不再强制 status=caution / passed=False
    elif report.get("status") == "pass":
        report["passed"] = True
    return report


def _local_fact_flags(projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_id = {str(segment.get("id") or ""): str(segment.get("text") or "") for segment in segments}
    flags: list[dict[str, str]] = []
    for index, project in enumerate(projects, start=1):
        feature = _sanitize_feature_extract(project.get("feature_extract")) or _fallback_feature_extract(project)
        action = feature.get("core_action") or ""
        if not action.strip():
            # core_action 为空时跳过相似度检查（没有可比较的内容）
            continue
        source = " ".join([
            str(project.get("description") or ""),
            str(project.get("description_zh") or ""),
            str(project.get("project_highlight") or ""),
            str(project.get("viewer_benefit") or ""),
            str(project.get("recommendation") or ""),
            " ".join(str(topic) for topic in project.get("topics") or []),
            _readme_excerpt(project),
        ])
        support = _fact_similarity(action, source)
        segment_id = f"project-{index}"
        narration = by_id.get(segment_id, "")
        mention = _fact_similarity(action, narration)
        # 阈值放低：只有当相似度极低时才提示（避免误判）
        if support < 0.08:
            flags.append(_quality_issue(
                "风险",
                f"{project.get('full_name') or project.get('name')}: core_action 与项目描述/README 支撑不足，请复核。",
                segment_id,
            ))
        elif mention < 0.06 and narration:
            flags.append(_quality_issue(
                "建议",
                f"{project.get('full_name') or project.get('name')}: 口播未明显使用 core_action，可以更贴近项目核心能力。",
                segment_id,
            ))
        if _contains_growth_overclaim(narration):
            flags.append(_quality_issue(
                "风险",
                f"{project.get('full_name') or project.get('name')}: daily_growth 仅为估算日均 star，口播不应表述为真实新增 star。",
                segment_id,
            ))
    return flags


def _bind_quality_issues(
    report: dict[str, Any],
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    issues = []
    for issue in report.get("issues") or []:
        normalized = _normalize_quality_issue(issue, projects, segments)
        if normalized:
            issues.append(normalized)
    if not issues:
        return report
    patched = dict(report)
    patched["issues"] = issues[:8]
    return patched


def _normalize_quality_issue(
    issue: Any,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, str] | None:
    if isinstance(issue, str):
        issue_type = "风险"
        text = _short_text(issue, 180)
        segment_id = ""
    elif isinstance(issue, dict):
        issue_type = _short_text(str(issue.get("type") or "风险"), 16) or "风险"
        text = _short_text(str(issue.get("text") or ""), 180)
        segment_id = _short_text(str(issue.get("segment_id") or ""), 32)
    else:
        return None
    if not text:
        return None
    if segment_id and any(str(segment.get("id") or "") == segment_id for segment in segments):
        return _quality_issue(issue_type, text, segment_id)
    matched_segment = _match_quality_segment(text, projects, segments)
    return _quality_issue(issue_type, text, matched_segment)


def _match_quality_segment(text: str, projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> str:
    normalized = _normalize_fact_text(text)
    if not normalized:
        return ""
    for index, project in enumerate(projects, start=1):
        for alias in (project.get("full_name"), project.get("name")):
            alias_text = _normalize_fact_text(str(alias or ""))
            if alias_text and alias_text in normalized:
                return f"project-{index}"
    best_segment = ""
    best_score = 0.0
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        segment_text = _normalize_fact_text(str(segment.get("text") or ""))
        if not segment_id or not segment_text:
            continue
        if segment_text in normalized or normalized in segment_text:
            return segment_id
        score = SequenceMatcher(None, normalized, segment_text).ratio()
        if score > best_score:
            best_score = score
            best_segment = segment_id
    return best_segment if best_score >= 0.2 else ""


def _quality_issue(issue_type: str, text: str, segment_id: str = "") -> dict[str, str]:
    issue = {
        "type": _short_text(issue_type, 16) or "风险",
        "text": _short_text(text, 180),
    }
    if segment_id:
        issue["segment_id"] = _short_text(segment_id, 32)
    return issue


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _short_error_details(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned = []
    for item in items[:6]:
        cleaned.append({
            "provider": _short_text(str(item.get("provider") or ""), 40),
            "model": _short_text(str(item.get("model") or ""), 60),
            "temperature": str(item.get("temperature") or ""),
            "error": _short_text(str(item.get("error") or ""), 180),
        })
    return cleaned


def _short_list(value: Any, limit: int, text_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_short_text(str(item), text_limit) for item in value[:limit] if str(item).strip()]


def _score_or_none(value: Any) -> int | None:
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return None