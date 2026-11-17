"""Selection, feature extraction, hook generation, narration, and publish pack for console jobs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.console import jobs as _jobs


def save_selection(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    _jobs._require_stage(job, {"awaiting_project_confirmation", "generating_script"}, "当前阶段不能确认项目")
    items = payload.get("items") or []
    if not items:
        raise ValueError("至少需要选择 1 个项目")

    project_count = int(job.get("project_count") or 5)
    if len(items) > project_count:
        raise ValueError(f"最多只能选择 {project_count} 个项目，当前选择 {len(items)} 个")
    selected = _jobs._selected_from_candidate_snapshot(job_id, items)
    selected = _jobs._ensure_feature_extracts(job_id, selected)
    _jobs._clear_plan_artifacts(job_id)
    _jobs._clear_script_metadata(job_id)
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {"items": selected})
    _jobs.append_log(job_id, f"已确认 {len(selected)} 个入选项目。")
    _jobs._sync_selection_to_lark(job_id, selected)
    return _jobs._generate_script_for_selection(job_id, selected)


def regenerate_script(job_id: str) -> dict[str, Any]:
    _jobs._require_regenerable_job(job_id)
    selected = _jobs.read_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    if not selected:
        raise ValueError("请先确认项目列表，再重新生成口播脚本")
    _jobs.append_log(job_id, "已请求重新生成口播脚本；将清除已确认口播后的计划文件和视频产物。")
    _jobs._clear_plan_artifacts(job_id)
    _jobs._clear_script_metadata(job_id)
    return _jobs._generate_script_for_selection(job_id, selected)


def _generate_script_for_selection(job_id: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    _jobs.update_job(job_id, status="running", stage="generating_script", error="")
    selected = _jobs._ensure_feature_extracts(job_id, selected)
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {"items": selected})

    hook = _jobs._generate_hook(job_id, selected)
    narrations = _jobs._model_narrations(job_id, selected)
    if narrations is None:
        narrations = _jobs._default_narrations(selected)
    narrations = _jobs._polish_narrations(job_id, selected, narrations)
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "narration.json", {"segments": narrations})
    _jobs.append_log(job_id, "已生成初版口播脚本，等待人工确认。")
    _jobs.update_job(
        job_id,
        status="awaiting_input",
        stage="awaiting_script_confirmation",
        plan_validation={"status": "not_run", "error": ""},
    )
    return {"job": _jobs.read_job(job_id), "segments": narrations, "hook": hook}


def save_script(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _jobs._job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return _jobs._save_pipeline_job_script(job_id, job, payload)
    _jobs._require_stage(job, {"awaiting_script_confirmation", "preparing_plan"}, "当前阶段不能确认口播")
    selected = _jobs.read_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    if not selected:
        raise ValueError("请先确认项目列表")
    segments = payload.get("segments") or []
    if not segments:
        raise ValueError("口播脚本不能为空")
    _jobs._validate_script_segments(selected, segments)
    _jobs.update_job(job_id, status="running", stage="awaiting_script_confirmation", error="")
    _jobs._clear_plan_artifacts(job_id)
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "narration.json", {"segments": segments})
    _jobs.append_log(job_id, "口播脚本已确认。")
    _jobs._quality_check_script(job_id, segments, selected)
    quality = _jobs.read_json(_jobs.JOBS_DIR / job_id / "quality_report.json", {})
    ignored = bool(payload.get("ignore_quality_risk"))
    if _jobs._quality_blocks_render(quality) and not ignored:
        publish_pack = _jobs._write_publish_pack(job_id, selected, segments)
        _jobs.update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            error="脚本质检未通过，请复核风险项或手动忽略后继续。",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": _jobs.read_job(job_id),
            "segments": segments,
            "quality_report": quality,
            "publish_pack": publish_pack,
        }
    if ignored and _jobs._quality_blocks_render(quality):
        quality = _jobs._apply_quality_override(job_id, quality)
    publish_pack = _jobs._write_publish_pack(job_id, selected, segments)
    _jobs.update_job(
        job_id,
        status="awaiting_render",
        stage="preparing_plan",
        error="",
        plan_validation={"status": "not_run", "error": ""},
    )
    return {
        "job": _jobs.read_job(job_id),
        "segments": segments,
        "quality_report": _jobs.read_json(_jobs.JOBS_DIR / job_id / "quality_report.json", {}),
        "publish_pack": publish_pack,
    }


def _save_pipeline_job_script(job_id: str, job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _jobs._require_stage(job, {"awaiting_script_confirmation", "preparing_plan"}, "当前阶段不能确认口播")
    segments = payload.get("segments") or []
    if not segments:
        raise ValueError("口播脚本不能为空")
    projects = _jobs._pipeline_job_projects(job_id, job)
    _jobs._validate_pipeline_script_segments(segments)
    _jobs.update_job(job_id, status="running", stage="awaiting_script_confirmation", error="")
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "narration.json", {"segments": segments})
    _jobs._write_script_from_console_segments(job_id, segments)
    _jobs.append_log(job_id, "口播脚本已确认。")
    _jobs._quality_check_script(job_id, segments, projects)
    quality = _jobs.read_json(_jobs.JOBS_DIR / job_id / "quality_report.json", {})
    ignored = bool(payload.get("ignore_quality_risk"))
    if _jobs._quality_blocks_render(quality) and not ignored:
        publish_pack = _jobs._write_pipeline_publish_pack(job_id, job, projects, segments)
        _jobs.update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            error="脚本质检未通过，请复核风险项或手动忽略后继续。",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": _jobs.read_job(job_id),
            "segments": segments,
            "quality_report": quality,
            "publish_pack": publish_pack,
        }
    if ignored and _jobs._quality_blocks_render(quality):
        quality = _jobs._apply_quality_override(job_id, quality)
    publish_pack = _jobs._write_pipeline_publish_pack(job_id, job, projects, segments)
    _jobs.update_job(
        job_id,
        status="awaiting_validation",
        stage="preparing_plan",
        error="",
        plan_validation={"status": "not_run", "error": ""},
    )
    return {
        "job": _jobs.read_job(job_id),
        "segments": segments,
        "quality_report": _jobs.read_json(_jobs.JOBS_DIR / job_id / "quality_report.json", {}),
        "publish_pack": publish_pack,
    }


def _validate_script_segments(projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    expected = ["intro", *[f"project-{index}" for index in range(1, len(projects) + 1)], "outro"]
    by_id = {str(segment.get("id") or ""): segment for segment in segments if isinstance(segment, dict)}
    missing = [segment_id for segment_id in expected if not str((by_id.get(segment_id) or {}).get("text") or "").strip()]
    if missing:
        raise ValueError(f"口播脚本缺少段落: {', '.join(missing)}")


def _validate_pipeline_script_segments(segments: list[dict[str, Any]]) -> None:
    missing = [
        str(segment.get("id") or f"segment-{index}")
        for index, segment in enumerate(segments, start=1)
        if not str((segment or {}).get("text") or "").strip()
    ]
    if missing:
        raise ValueError(f"口播脚本缺少段落: {', '.join(missing)}")


def _console_segments_from_script(job_dir: Path) -> list[dict[str, str]]:
    script = _jobs.read_json(job_dir / "script.json", {})
    raw_segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    segments = []
    total = len(raw_segments)
    for index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, dict):
            continue
        if index == 1:
            segment_id = "intro"
            label = "开场"
        elif index == total:
            segment_id = "outro"
            label = "结尾"
        else:
            segment_id = f"project-{index - 1}"
            label = f"段落 {index - 1}"
        segments.append({
            "id": segment_id,
            "label": label,
            "text": str(segment.get("narration") or ""),
        })
    return segments


def _write_script_from_console_segments(job_id: str, console_segments: list[dict[str, Any]]) -> None:
    script_path = _jobs.JOBS_DIR / job_id / "script.json"
    script = _jobs.read_json(script_path, {})
    raw_segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    by_id = {str(segment.get("id") or ""): str(segment.get("text") or "") for segment in console_segments if isinstance(segment, dict)}
    patched = []
    total = len(raw_segments)
    for index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, dict):
            continue
        if index == 1:
            segment_id = "intro"
        elif index == total:
            segment_id = "outro"
        else:
            segment_id = f"project-{index - 1}"
        item = dict(segment)
        if segment_id in by_id:
            item["narration"] = by_id[segment_id]
        patched.append(item)
    script["segments"] = patched
    _jobs.write_json(script_path, script)


def _selected_from_candidate_snapshot(job_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = _jobs.read_json(_jobs.JOBS_DIR / job_id / "candidates.json", {}).get("items") or []
    by_key = {}
    for candidate in candidates:
        key = _jobs._candidate_key(candidate)
        if key:
            by_key[key] = candidate
    if not by_key:
        raise ValueError("候选快照不存在，请先生成候选项目")
    selected = []
    seen = set()
    for item in items:
        key = _jobs._candidate_key(item)
        if not key or key not in by_key:
            raise ValueError(f"候选快照中不存在: {item.get('full_name') or item.get('name') or 'unknown'}")
        if key in seen:
            raise ValueError(f"不能重复选择同一个项目: {item.get('full_name') or item.get('name') or key}")
        seen.add(key)
        selected.append(dict(by_key[key]))
    return selected


def _clear_script_metadata(job_id: str) -> None:
    job_dir = _jobs.JOBS_DIR / job_id
    for name in ("quality_report.json", "publish_pack.json", "narration_source.json"):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()


def _narration_project_context(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for index, project in enumerate(projects, start=1):
        feature = project.get("feature_extract") or {}
        benefit = str(feature.get("quantified_benefit") or "").strip()
        items.append({
            "rank": index,
            "name": project.get("name"),
            "full_name": project.get("full_name"),
            "description_zh": project.get("description_zh"),
            "feature_extract": feature,
            "core_problem": feature.get("core_problem") or _jobs._viewer_pain(project),
            "core_action": feature.get("core_action") or _jobs._viewer_highlight(project),
            "quantified_benefit": benefit,
            "quantified_benefit_or_tech_point": benefit or _jobs._viewer_highlight(project),
            "recommendation": project.get("recommendation"),
            "project_highlight": project.get("project_highlight"),
            "viewer_benefit": project.get("viewer_benefit"),
            "audience": project.get("audience"),
            "visual_potential": project.get("visual_potential"),
            "stars": project.get("stars"),
            "viewer_pain": _jobs._viewer_pain(project),
            "viewer_outcome": _jobs._viewer_outcome(project),
            "safe_highlight": _jobs._viewer_highlight(project),
            "safe_audience": _jobs._viewer_audience(project),
            "risk": project.get("risk"),
            "daily_growth": project.get("daily_growth"),
            "growth_note": project.get("growth_note") or _jobs.ESTIMATED_GROWTH_NOTE,
        })
    return items


def _ensure_feature_extracts(job_id: str, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = []
    missing = []
    for index, project in enumerate(projects, start=1):
        patched = dict(project)
        feature = _jobs._sanitize_feature_extract(project.get("feature_extract"))
        if not feature:
            missing.append((index, patched))
            feature = _jobs._fallback_feature_extract(patched)
        patched["feature_extract"] = feature
        _jobs._apply_feature_to_project_copy(patched, feature)
        updated.append(patched)
    if missing:
        _jobs._extract_features_with_model(job_id, updated, [index for index, _project in missing])
    return updated


def _extract_features_with_model(job_id: str, projects: list[dict[str, Any]], indexes: list[int]) -> None:
    route = _jobs.route_snapshot("feature_extraction")
    if not _jobs._route_available(route):
        _jobs.append_log(job_id, f"项目功能摘要使用启发式提取：{_jobs._route_skip_reason(route)}。")
        return
    prompt = {
        "instruction": (
            "为 GitHub 热榜入选项目提取事实型功能摘要。只能根据 description、topics、README 摘要判断，"
            "不要写营销话术，不要把视频画面建议当功能。"
        ),
        "items": [
            {
                "index": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description": project.get("description"),
                "description_zh": project.get("description_zh"),
                "topics": project.get("topics"),
                "readme_excerpt": _jobs._readme_excerpt(project),
            }
            for index, project in enumerate(projects, start=1)
            if index in indexes
        ],
        "schema": {
            "items": [
                {
                    "index": 1,
                    "core_problem": "15字内具体痛点",
                    "core_action": "用户用它做什么，一句话动作",
                    "quantified_benefit": "可量化效果；没有就空字符串",
                }
            ]
        },
    }
    try:
        detail = _jobs.chat_json_detail(
            "feature_extraction",
            "你是克制的开源项目功能摘要编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=1800,
        )
        items = (detail.get("data") or {}).get("items", []) if isinstance(detail.get("data"), dict) else []
        by_index = {int(item.get("index") or 0): _jobs._sanitize_feature_extract(item) for item in items if isinstance(item, dict)}
        changed = 0
        for index, project in enumerate(projects, start=1):
            feature = by_index.get(index)
            if feature:
                project["feature_extract"] = feature
                _jobs._apply_feature_to_project_copy(project, feature)
                changed += 1
        if changed:
            _jobs._record_model_call(job_id, "feature_extraction", detail, "success")
            used_route = detail.get("route") or {}
            _jobs.append_log(
                job_id,
                f"已为 {changed} 个项目提取功能摘要：{used_route.get('provider_name') or used_route.get('provider') or ''} / {used_route.get('model') or ''}。",
            )
        else:
            _jobs._write_ai_raw_response(job_id, "feature_extraction", detail)
            _jobs._record_model_call(job_id, "feature_extraction", detail, "invalid_json")
            _jobs.append_log(job_id, "功能摘要模型未返回可用 JSON，保留启发式摘要。")
    except Exception as exc:
        _jobs._record_model_call(job_id, "feature_extraction", {"route": route, "error": str(exc)}, "failed")
        _jobs.append_log(job_id, f"功能摘要模型失败，保留启发式摘要: {exc}")


def _ranking_overview_line(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "先看榜单：这期按真实使用价值来拆。"
    count = len(projects)
    audiences = []
    for project in projects:
        audience = _jobs._viewer_audience(project)
        if audience and audience not in audiences:
            audiences.append(audience)
        if len(audiences) == 2:
            break
    audience_text = "、".join(audiences) if audiences else "开发者"
    return f"先看整体趋势：这 {count} 个项目分别在帮{audience_text}缩短上手路径。"


def _generate_hook(job_id: str, projects: list[dict[str, Any]]) -> dict[str, Any]:
    route = _jobs.route_snapshot("hook_generation")
    hook_path = _jobs.JOBS_DIR / job_id / "hook.json"
    if not _jobs._route_available(route):
        reason = _jobs._route_skip_reason(route)
        hook = _jobs._default_hook(projects, route, "skipped", reason)
        _jobs.write_json(hook_path, hook)
        _jobs.append_log(job_id, f"标题钩子生成跳过：{reason}。")
        return hook
    is_skills = _jobs._is_skills_hotlist(projects)
    topic_label = "AI Skills 热榜" if is_skills else "GitHub 热榜"
    item_label = "技能" if is_skills else "项目"
    prompt = {
        "instruction": f"为 {topic_label} 竖屏短视频生成克制标题和开场钩子。不要夸大，不要承诺收益，只基于输入{item_label}。",
        "projects": [
            {
                "rank": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description_zh": project.get("description_zh"),
                "feature_extract": project.get("feature_extract") or {},
                "recommendation": project.get("recommendation"),
                "audience": project.get("audience"),
                "stars": project.get("stars"),
            }
            for index, project in enumerate(projects, start=1)
        ],
        "schema": {
            "title": "适合文件名和视频标题的中文标题，12 到 28 字",
            "opening_hook": "开头 1 句话，20 到 45 字",
            "closing_cta": "结尾互动提示，15 到 40 字",
        },
    }
    try:
        detail = _jobs.chat_json_detail(
            "hook_generation",
            "你是克制的中文短视频标题编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=1000,
        )
        hook = _jobs._sanitize_hook(detail["data"], detail.get("route") or {}, "", "success")
        if not hook:
            _jobs._write_ai_raw_response(job_id, "hook_generation", detail)
            _jobs._record_model_call(job_id, "hook_generation", detail, "invalid_json")
            hook = _jobs._default_hook(projects, detail.get("route") or {}, "invalid_json", detail.get("error") or "模型未返回可用 JSON")
            _jobs.write_json(hook_path, hook)
            _jobs.append_log(job_id, "标题钩子模型未返回可用 JSON，保留默认标题。")
            return hook
        _jobs.write_json(hook_path, hook)
        _jobs.update_job(job_id, title=hook["title"])
        _jobs._record_model_call(job_id, "hook_generation", detail, "success")
        _jobs.append_log(job_id, f"标题钩子已使用 {hook['provider']} / {hook['model']}。")
        return hook
    except Exception as exc:
        _jobs._record_model_call(job_id, "hook_generation", {"route": route, "error": str(exc)}, "failed")
        hook = _jobs._default_hook(projects, route, "failed", str(exc))
        _jobs.write_json(hook_path, hook)
        _jobs.append_log(job_id, f"标题钩子生成失败，保留默认标题: {exc}")
        return hook


def _sanitize_hook(
    data: dict[str, Any] | None,
    route: dict[str, Any],
    error: str,
    status: str,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    title = _jobs._short_text(str(data.get("title") or ""), 36)
    opening_hook = _jobs._short_text(str(data.get("opening_hook") or ""), 90)
    closing_cta = _jobs._short_text(str(data.get("closing_cta") or ""), 80)
    if not title or not opening_hook:
        return None
    return {
        "status": status,
        "title": title,
        "opening_hook": opening_hook,
        "closing_cta": closing_cta,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
    }


def _default_hook(
    projects: list[dict[str, Any]],
    route: dict[str, Any],
    status: str,
    error: str,
) -> dict[str, Any]:
    is_skills = _jobs._is_skills_hotlist(projects)
    if is_skills:
        title = f"AI Skills热榜{len(projects)}个技能" if projects else "AI Skills热榜视频"
        names = "、".join(str(project.get("name") or project.get("full_name") or "这个技能") for project in projects[:3])
        return {
            "status": status,
            "title": title,
            "opening_hook": f"这期看 {names or 'AI Skills 热榜'}，只挑真正能省掉工作流步骤的技能。",
            "closing_cta": "想看哪个技能接入真实工作流实测，评论区直接留名字。",
            "provider": route.get("provider_name") or route.get("provider") or "",
            "model": route.get("model") or "",
            "error": error,
        }
    title = f"GitHub热榜{len(projects)}个项目" if projects else "GitHub热榜视频"
    names = "、".join(str(project.get("name") or project.get("full_name") or "这个项目") for project in projects[:3])
    return {
        "status": status,
        "title": title,
        "opening_hook": f"这期看 {names or 'GitHub 热榜'}，只挑真正值得停下来的项目。",
        "closing_cta": "想看哪个项目实操拆解，评论区直接留名字。",
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
    }


def _write_publish_pack(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    job = _jobs.read_job(job_id) or {}
    is_skills = _jobs._is_skills_hotlist(projects) or _jobs._job_type(job) == "skills_hotlist"
    hook = _jobs.read_json(_jobs.JOBS_DIR / job_id / "hook.json", {})
    default_title = "AI Skills 热榜视频" if is_skills else "GitHub 热榜视频"
    title = _jobs._short_text(str(hook.get("title") or job.get("title") or default_title), 40)
    opening = _jobs._short_text(str(hook.get("opening_hook") or (segments[0].get("text") if segments else "")), 90)
    closing = _jobs._short_text(str(hook.get("closing_cta") or _jobs._outro_line(projects)), 80)
    project_names = [
        str(project.get("full_name") or project.get("name") or "")
        for project in projects
        if project.get("full_name") or project.get("name")
    ]
    section_label = "本期技能：" if is_skills else "本期项目："
    data_note = _jobs.SKILLS_SOURCE_NOTE if is_skills else _jobs.ESTIMATED_GROWTH_NOTE
    description_lines = [
        opening or title,
        "",
        section_label,
        *[f"{index}. {name}" for index, name in enumerate(project_names, start=1)],
        "",
        "数据说明：",
        data_note,
        "",
        closing,
    ]
    pack = {
        "title": title,
        "title_options": _jobs._title_options(title, projects, is_skills=is_skills),
        "description": _jobs._clip_multiline("\n".join(description_lines), 900),
        "hashtags": _jobs._hashtags(projects),
        "cover_text": _jobs._cover_text(title, projects),
        "comment_guide": _jobs._comment_guide(projects, is_skills=is_skills),
        "source_projects": project_names,
        "data_note": data_note,
    }
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "publish_pack.json", pack)
    _jobs.append_log(job_id, "发布辅助包已生成。")
    return pack


def _title_options(title: str, projects: list[dict[str, Any]], *, is_skills: bool = False) -> list[str]:
    count = len(projects)
    first_name = str((projects[0] if projects else {}).get("name") or (projects[0] if projects else {}).get("full_name") or "")
    candidates = [title]
    if is_skills:
        candidates.extend([
            f"能直接塞进工作流的{count}个AI Skills（{first_name or '本期精选'}）" if count else "能直接塞进工作流的AI Skills精选",
            f"本周AI Skills热榜：{count}个省步骤的Agent技能实测盘点" if count else "本周AI Skills热榜实测盘点",
        ])
    else:
        candidates.extend([
            f"GitHub近期值得看的{count}个开源项目（含{first_name or '实战工具'}）" if count else "GitHub近期值得看的开源项目",
            f"别光收藏不跑：这{count}个GitHub项目解决真痛点" if count else "别光收藏不跑：GitHub实用开源项目盘点",
        ])
    unique: list[str] = []
    for item in candidates:
        cleaned = _jobs._short_text(str(item or "").strip(), 40)
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique[:3]


def _comment_guide(projects: list[dict[str, Any]], *, is_skills: bool = False) -> str:
    names = " / ".join(
        str(project.get("name") or project.get("full_name") or "")
        for project in projects[:3]
        if project.get("name") or project.get("full_name")
    )
    if is_skills:
        target = f"（如 {names}）" if names else ""
        return f"想看本期哪个 AI Skill 接入真实工作流实测？评论区直接回复序号或技能名{target}，下期按真实任务拆解。"
    target = f"（如 {names}）" if names else ""
    return f"想看本期哪个开源项目的完整实操教程？评论区直接回复序号或项目名{target}，下期优先拆解。"


def _pipeline_job_projects(job_id: str, job: dict[str, Any]) -> list[dict[str, Any]]:
    info = _jobs.read_json(_jobs.JOBS_DIR / job_id / "info.json", {})
    if isinstance(info.get("projects"), list):
        raw = info["projects"]
    else:
        raw = [info]
    projects = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "").strip()
        if not full_name and item.get("owner") and item.get("name"):
            full_name = f"{item.get('owner')}/{item.get('name')}"
        repo_url = str(item.get("repo_url") or job.get("repo_url") or job.get("plan_path") or "").strip()
        name = str(item.get("name") or full_name or f"project-{index}")
        projects.append({
            **item,
            "name": name,
            "full_name": full_name or name,
            "repo_url": repo_url,
            "description": str(item.get("description") or ""),
            "description_zh": str(item.get("description_zh") or item.get("description") or ""),
            "stars": item.get("stars") or 0,
            "language": item.get("language") or "",
            "daily_growth": item.get("daily_growth") or "",
            "growth_note": item.get("growth_note") or "",
        })
    if projects:
        return projects
    source = str(job.get("repo_url") or job.get("plan_path") or job_id)
    return [{
        "name": Path(source).name or job_id,
        "full_name": Path(source).name or job_id,
        "repo_url": source,
        "description": str(job.get("title") or ""),
        "description_zh": str(job.get("title") or ""),
        "stars": 0,
        "language": "",
    }]


def _write_pipeline_publish_pack(
    job_id: str,
    job: dict[str, Any],
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    title = _jobs._short_text(str(_jobs.read_job(job_id).get("title") or _jobs._job_type_label(job)), 40)
    source_names = [str(project.get("full_name") or project.get("name") or "") for project in projects if project]
    narration = "\n".join(str(segment.get("text") or "") for segment in segments if segment.get("text"))
    description = _jobs._clip_multiline("\n".join([
        title,
        "",
        _jobs._short_text(narration, 520),
        "",
        "来源：",
        *[f"- {name}" for name in source_names],
    ]), 900)
    pack = {
        "title": title,
        "description": description,
        "hashtags": _jobs._hashtags(projects),
        "cover_text": {"headline": title, "subhead": _jobs._short_text(source_names[0] if source_names else title, 48)},
        "source_projects": source_names,
        "data_note": "单项目或计划文件任务使用本地计划快照与仓库元数据，不使用热榜增长估算。",
    }
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "publish_pack.json", pack)
    _jobs.append_log(job_id, "发布辅助包已生成。")
    return pack


def _hashtags(projects: list[dict[str, Any]]) -> list[str]:
    is_skills = _jobs._is_skills_hotlist(projects)
    tags = ["AISkills", "AI工具", "Agent工作流"] if is_skills else ["GitHub", "开源项目", "开发者工具"]
    text = _jobs._project_text({"topics": [], "description": " ".join(_jobs._project_text(project) for project in projects)})
    if _jobs._has_keyword(text, ("ai", "agent", "llm", "rag", "model")):
        tags.append("AI工具")
    if _jobs._has_keyword(text, ("cli", "terminal", "shell", "developer")):
        tags.append("效率工具")
    if _jobs._has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        tags.append("前端开发")
    if _jobs._has_keyword(text, ("data", "database", "analytics", "sql")):
        tags.append("数据工具")
    seen = set()
    return [tag for tag in tags if not (tag in seen or seen.add(tag))]


def _cover_text(title: str, projects: list[dict[str, Any]]) -> dict[str, str]:
    if _jobs._is_skills_hotlist(projects):
        first = projects[0] if projects else {}
        top = str(first.get("name") or first.get("full_name") or "AI Skill")
        sources = " / ".join(first.get("sources") or []) or str(first.get("source_label") or "")
        feature = first.get("feature_extract") or {}
        step = str(first.get("workflow_step") or feature.get("core_action") or first.get("description_zh") or "").strip("。")
        subhead = f"焦点技能：{top}"
        if sources:
            subhead += f" · {sources}"
        if step:
            subhead += f" · {step}"
        return {
            "headline": title,
            "subhead": _jobs._short_text(subhead, 48),
        }
    top_project = _jobs._fastest_growth_project(projects)
    top = str((top_project or {}).get("name") or (top_project or {}).get("full_name") or "开源项目") if projects else "开源项目"
    growth = str((top_project or {}).get("daily_growth") or "")
    feature = (top_project or {}).get("feature_extract") or {}
    hook = str(feature.get("core_problem") or (top_project or {}).get("description_zh") or "").strip("。")
    subhead = f"本周黑马：{top}"
    if growth:
        subhead += f" · {growth}"
    if hook:
        subhead += f" · {hook}"
    return {
        "headline": title,
        "subhead": _jobs._short_text(subhead, 48),
    }


def _fastest_growth_project(projects: list[dict[str, Any]]) -> dict[str, Any]:
    if not projects:
        return {}
    return max(projects, key=lambda item: _jobs._growth_value(str(item.get("daily_growth") or item.get("stars_delta") or "")))


def _growth_value(text: str) -> int:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([kK千万]?)", text.replace(",", ""))
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"k", "千"}:
        value *= 1000
    elif unit == "万":
        value *= 10000
    return max(0, int(value))


def _model_narrations(job_id: str, projects: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    route = _jobs.route_snapshot("narration_generation")
    if not _jobs._route_available(route):
        reason = _jobs._route_skip_reason(route)
        _jobs._update_narration_source(job_id, route, "model_skipped", reason)
        _jobs.append_log(job_id, f"口播生成使用默认模板：{reason}。")
        return None
    project_context = _jobs._narration_project_context(projects)
    is_skills = _jobs._is_skills_hotlist(projects)
    topic_label = "AI Skills 热榜视频" if is_skills else "GitHub 热榜视频"
    item_label = "技能" if is_skills else "项目"
    opening_rule = (
        "开场必须在 3 秒内抓住人，用一个本期技能选择标准或具体工作流痛点切入，不要直接复述第 1 名技能名。"
        if is_skills
        else "开场必须在 3 秒内抓住人，用一个本期判断或反常识观点切入，不要直接复述第一名项目名。"
    )
    heat_rule = (
        "如果要提热度，只能说“多源收录”“社区推荐”或“来源榜单靠前”，禁止编造安装量、收藏数或真实增长。"
        if is_skills
        else (
            "daily_growth / growth_note 只表示按当前总 stars 和项目年龄折算的估算日均 star，不是真实新增 star。"
            "如果要提热度，只能说“估算日均 star”或“热度估算”，禁止说“今天涨了”“新增了”“真实增长”。"
        )
    )
    prompt = {
        "instruction": (
            f"你是一个为「{topic_label}」撰写口播文案的专家。为 {topic_label} 竖屏短视频生成中文口播。"
            f"单个{item_label}口播要吸引人、有场景感、避免套路；克制、具体、面向观众价值，不要喊口号。"
            f"{opening_rule}"
            f"榜单总览只讲整体趋势和选择标准，不能展开第 1 名细节；每个{item_label}详情再按痛点、它怎么解决、适合谁、为什么值得看展开。"
            "结尾要留下讨论空间或下一期期待，不要只说点赞关注。"
            "每个 project-* 段落控制在 60 到 100 个中文字符左右。"
            f"每个 project-* 必须使用对应{item_label} feature_extract 里的 core_problem 和 core_action；"
            "quantified_benefit 非空时必须自然写入，空时不要编造数字。"
            "禁止使用以下开头句式：如果你纠结、如果你觉得、如果你在找、如果你卡在、先看看它、先看它。"
            "禁止空洞评价：很有价值、值得关注、适合开发者、适合开源项目关注者。"
            "每个 project-* 必须包含：一个反常识或场景化开头；一句具体痛点或爽点；一句锁定目标人群，格式可以用「适合：被 X 折磨的人」。"
            "visual_potential 是制作侧画面建议，禁止直接写入口播；不要把 README 可展示、仓库页做信息卡片、"
            "终端截图可展示、截图可展示、画面潜力、信息卡片当成项目亮点。"
            f"{heat_rule}"
        ),
        "projects": project_context,
        "content_strategy": {
            "opening": "一句 20 到 45 字的钩子，讲本期判断，不复述第 1 名详情",
            "overview": "榜单总览负责建立选择标准和整体趋势，不能重复 project-1 的介绍",
            "per_project": f"每个{item_label}按反常识/场景开头 -> 具体痛点或爽点 -> 被什么问题折磨的人组织",
            "closing": f"留下讨论钩子，让观众选择想看哪个{item_label}的实操拆解",
        },
        "project_copy_template": (
            "{{core_problem}} 不是靠收藏项目解决的。{{name}} 的核心动作是：{{core_action}}。"
            "{{quantified_benefit_or_tech_point}}。适合：被 {{core_problem}} 折磨的 {{safe_audience}}。"
        ),
        "schema": {
            "segments": [
                {"id": "intro", "label": "开场", "text": "20 到 45 字"},
                {"id": "project-1", "label": "第 1 名", "text": "60 到 100 字，纯文本，不要序号、标题、Markdown"},
                {"id": "outro", "label": "结尾", "text": "20 到 45 字"},
            ]
        },
    }
    try:
        detail = _jobs.chat_json_detail(
            "narration_generation",
            "你是中文短视频口播编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        used_route = detail["route"]
        segments = _jobs._sanitize_model_segments(projects, data.get("segments", []) if data else [])
        if not segments:
            _jobs._write_ai_raw_response(job_id, "narration_generation", detail)
            _jobs._record_model_call(job_id, "narration_generation", detail, "invalid_json")
            _jobs._update_narration_source(
                job_id,
                detail.get("route") or route,
                "ai_failed_fallback",
                detail.get("error") or "模型未返回可用 JSON",
            )
            _jobs.append_log(job_id, "口播模型未返回可用 JSON，改用默认模板。")
            return None
        _jobs._record_model_call(job_id, "narration_generation", detail, "success")
        _jobs._update_narration_source(job_id, used_route, "ai_success", "")
        _jobs.append_log(job_id, f"口播生成已使用 {used_route['provider_name']} / {used_route['model']}。")
        return segments
    except Exception as exc:
        _jobs._record_model_call(job_id, "narration_generation", {"route": route, "error": str(exc)}, "failed")
        _jobs._update_narration_source(job_id, route, "ai_failed_fallback", str(exc))
        _jobs.append_log(job_id, f"口播模型失败，改用默认模板: {exc}")
        return None


def _polish_narrations(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    route = _jobs.route_snapshot("script_polishing")
    if not _jobs._route_available(route):
        reason = _jobs._route_skip_reason(route)
        _jobs._patch_narration_source(job_id, {"polishing_status": "skipped", "polishing_reason": reason})
        _jobs.append_log(job_id, f"脚本润色跳过：{reason}。")
        return segments
    prompt = {
        "instruction": (
            "润色 GitHub 热榜中文口播，保持 segment id 不变。只改表达，不新增输入里没有的事实。"
            "每个 project-* 段落要有反差或场景感、具体痛点/爽点、明确目标人群。"
            "禁止使用：如果你纠结、如果你觉得、如果你在找、如果你卡在、先看看它、先看它、很有价值、值得关注、适合开发者、适合开源项目关注者。"
            "保留项目真实能力和观众收益，删除制作侧画面话术；禁止出现 README 可展示、仓库页做信息卡片、"
            "终端截图可展示、截图可展示、画面潜力、信息卡片作为亮点。"
            "daily_growth 仅表示估算日均 star，不是真实新增 star；禁止润色成“新增了”“暴涨了”“今天涨了”等事实口吻。"
        ),
        "projects": [
            {
                "rank": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description_zh": project.get("description_zh"),
                "recommendation": project.get("recommendation"),
                "project_highlight": project.get("project_highlight"),
                "viewer_benefit": project.get("viewer_benefit"),
                "audience": project.get("audience"),
                "risk": project.get("risk"),
                "visual_potential": project.get("visual_potential"),
                "stars": project.get("stars"),
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
            "segments": [
                {"id": "intro", "label": "开场", "text": "保留信息、节奏更顺的中文口播"}
            ]
        },
    }
    try:
        detail = _jobs.chat_json_detail(
            "script_polishing",
            "你是克制的中文短视频脚本润色编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        polished = _jobs._sanitize_polished_segments(segments, data.get("segments", []) if data else [])
        if not polished:
            _jobs._write_ai_raw_response(job_id, "script_polishing", detail)
            _jobs._record_model_call(job_id, "script_polishing", detail, "invalid_json")
            _jobs._patch_narration_source(job_id, {
                "polishing_status": "invalid_json",
                "polishing_reason": detail.get("error") or "模型未返回可用 JSON",
            })
            _jobs.append_log(job_id, "脚本润色模型未返回可用 JSON，保留原稿。")
            return segments
        _jobs._record_model_call(job_id, "script_polishing", detail, "success")
        used_route = detail["route"]
        _jobs._patch_narration_source(job_id, {
            "polishing_status": "success",
            "polishing_provider": used_route.get("provider_name") or used_route.get("provider") or "",
            "polishing_model": used_route.get("model") or "",
            "polishing_reason": "",
        })
        _jobs.append_log(job_id, f"脚本润色已使用 {used_route['provider_name']} / {used_route['model']}。")
        return polished
    except Exception as exc:
        _jobs._record_model_call(job_id, "script_polishing", {"route": route, "error": str(exc)}, "failed")
        _jobs._patch_narration_source(job_id, {"polishing_status": "failed", "polishing_reason": str(exc)})
        _jobs.append_log(job_id, f"脚本润色失败，保留原稿: {exc}")
        return segments


def _sanitize_polished_segments(
    original: list[dict[str, Any]],
    polished: list[dict[str, Any]],
) -> list[dict[str, str]]:
    expected = [str(segment.get("id") or "") for segment in original]
    by_id = {str(segment.get("id")): segment for segment in polished}
    cleaned = []
    for source in original:
        segment_id = str(source.get("id") or "")
        segment = by_id.get(segment_id)
        text = _jobs._clean_narration_text(str(segment.get("text") or "")) if segment else ""
        if not segment_id or not text or _jobs._contains_producer_visual_jargon(text) or _jobs._contains_forbidden_narration(text):
            return []
        cleaned.append({
            "id": segment_id,
            "label": str(segment.get("label") or source.get("label") or _jobs._segment_label(segment_id)),
            "text": text,
        })
    return cleaned if [segment["id"] for segment in cleaned] == expected else []


def _sanitize_model_segments(projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    expected = ["intro", *[f"project-{index}" for index in range(1, len(projects) + 1)], "outro"]
    by_id = {str(segment.get("id")): segment for segment in segments}
    cleaned = []
    for segment_id in expected:
        segment = by_id.get(segment_id)
        text = _jobs._clean_narration_text(str(segment.get("text") or "")) if segment else ""
        if not text or _jobs._contains_producer_visual_jargon(text) or _jobs._contains_forbidden_narration(text):
            return []
        cleaned.append({
            "id": segment_id,
            "label": str(segment.get("label") or _jobs._segment_label(segment_id)),
            "text": text,
        })
    return cleaned


def _clean_narration_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _segment_label(segment_id: str) -> str:
    if segment_id == "intro":
        return "开场"
    if segment_id == "outro":
        return "结尾"
    return f"第 {segment_id.removeprefix('project-')} 名"


def _update_narration_source(job_id: str, route: dict[str, Any], status: str, reason: str) -> None:
    source = {
        "status": status,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "reason": reason,
    }
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "narration_source.json", source)
    _jobs.update_job(job_id, narration_source=source)


def _patch_narration_source(job_id: str, patch: dict[str, Any]) -> None:
    job = _jobs.read_job(job_id) or {}
    source = dict(job.get("narration_source") or _jobs.read_json(_jobs.JOBS_DIR / job_id / "narration_source.json", {}))
    source.update(patch)
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "narration_source.json", source)
    _jobs.update_job(job_id, narration_source=source)


def _default_narrations(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = [
        {
            "id": "intro",
            "label": "开场",
            "text": _jobs._intro_line(projects),
        }
    ]
    for index, project in enumerate(projects, start=1):
        segments.append({
            "id": f"project-{index}",
            "label": f"第 {index} 名",
            "text": _jobs._default_project_narration(project),
        })
    segments.append({
        "id": "outro",
        "label": "结尾",
        "text": _jobs._outro_line(projects),
    })
    return segments


def _intro_line(projects: list[dict[str, Any]]) -> str:
    count = len(projects)
    if _jobs._is_skills_hotlist(projects):
        return (
            f"今天不比参数，挑 {count} 个能直接塞进工作流的 AI Skills，"
            f"看它们分别省掉哪一步。"
        )
    return (
        f"别再只按 Star 收藏项目了。今天这 {count} 个 GitHub 项目，"
        f"我只看它能不能帮你少走一步弯路。"
    )


def _outro_line(projects: list[dict[str, Any]]) -> str:
    is_skills = _jobs._is_skills_hotlist(projects)
    fallback_name = "这个技能" if is_skills else "这个项目"
    names = "、".join(str(project.get("name") or fallback_name) for project in projects[:3])
    if is_skills:
        return (
            f"这期最值得回看的，不是排名，而是你现在最想自动化哪一步。"
            f"如果你想让我实测 {names} 里面某一个，评论区直接打技能名；"
            f"我下一期按真实工作流拆给你看。"
        )
    return (
        f"这期最值得回看的，不是排名，而是你现在卡在哪一步。"
        f"如果你想让我把 {names} 里面某一个拆成实操教程，评论区直接打项目名；"
        f"我下一期就按真实使用场景拆给你看。"
    )


def _default_project_narration(project: dict[str, Any]) -> str:
    is_skill = _jobs._is_skill_item(project)
    name = project.get("name") or project.get("full_name") or ("这个技能" if is_skill else "这个项目")
    feature = _jobs._sanitize_feature_extract(project.get("feature_extract")) or _jobs._fallback_feature_extract(project)
    pain = feature["core_problem"]
    highlight = feature["core_action"]
    benefit = feature.get("quantified_benefit") or "重点是把一个具体流程缩短"
    audience = _jobs._viewer_audience(project)
    if is_skill:
        return (
            f"{pain} 不是靠多写提示词解决的。"
            f"{name} 的核心动作是：{highlight}。"
            f"{benefit}。"
            f"适合：被「{pain}」折磨的{_jobs._audience_phrase(audience)}。"
        )
    return (
        f"{pain} 不是靠多收藏几个项目解决的。"
        f"{name} 的核心动作是：{highlight}。"
        f"{benefit}。"
        f"适合：被「{pain}」折磨的{_jobs._audience_phrase(audience)}。"
    )


def _is_skills_hotlist(projects: list[dict[str, Any]]) -> bool:
    return bool(projects) and all(_jobs._is_skill_item(project) for project in projects)


def _is_skill_item(project: dict[str, Any]) -> bool:
    return (
        str(project.get("data_source") or "") == "skills_hotlist"
        or str(project.get("source") or "") in {"skillhub", "clawhub"}
        or bool(project.get("sources")) and not str(project.get("repo_url") or "").startswith("https://github.com/")
    )


def _description_phrase(description: str) -> str:
    if re.match(r"^[A-Za-z0-9]", description):
        return f" {description}"
    return description


def _audience_phrase(audience: str) -> str:
    if re.match(r"^[A-Za-z0-9]", audience):
        return f" {audience}"
    return audience
