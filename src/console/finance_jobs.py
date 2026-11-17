"""Stock and finance education video pipeline jobs for console orchestration."""

from __future__ import annotations

from typing import Any

from src.console import jobs as _jobs
from src.console.background import JobCancelled, raise_if_cancelled


async def run_stock_pipeline_job(job_id: str) -> dict[str, Any]:
    """执行股票科普视频流水线"""
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")

    if _jobs._job_type(job) == "finance_edu":
        return await _jobs._run_finance_edu_pipeline(job_id, job)

    from src.stock.pipeline import run_stock_pipeline

    theme = str(job.get("theme") or "")
    content_source = str(job.get("content_source") or "llm")
    source_input = str(job.get("source_input") or "")
    voice = _jobs._tts_voice(job)
    rate = _jobs._tts_rate(job)

    output_dir = _jobs.JOBS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        _jobs.update_job(job_id, status="running", stage="generating_script", error="")
        _jobs.append_log(job_id, f"开始生成股票科普视频: {theme}")

        final_path = await run_stock_pipeline(
            theme=theme,
            content_source=content_source,
            source_input=source_input,
            output_dir=output_dir,
            voice=voice,
            rate=rate,
        )

        _jobs.update_job(job_id, status="completed", stage="completed", error="")
        _jobs.append_log(job_id, f"视频生成完成: {final_path}")

        return _jobs.finalize_stock_output(job_id, theme)
    except JobCancelled as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "generating_script")
        _jobs.append_log(job_id, str(exc))
        # 清理可能写了一半的 final.mp4，避免下次 finalize_stock_output 把坏文件复制到正式目录
        _jobs._clear_current_video_output(job_id)
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "已取消",
            },
        )
        raise
    except Exception as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "generating_script")
        _jobs.append_log(job_id, f"视频生成失败: {exc}")
        _jobs._clear_current_video_output(job_id)
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "渲染失败",
            },
        )
        raise


async def _run_finance_edu_pipeline(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    """执行 finance_edu 炒股科普视频流水线"""
    from src.finance_edu.models import FinanceEduTopic
    from src.finance_edu.pipeline import run_finance_edu_video

    topic_text = str(job.get("topic") or job.get("theme") or "")
    topic_type = str(job.get("topic_type") or "indicator")
    audience = str(job.get("audience") or "beginner")
    visual_style = str(job.get("visual_style") or "black_gold")
    voice = _jobs._tts_voice(job)
    rate = _jobs._tts_rate(job)

    output_dir = _jobs.JOBS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    def on_stage(stage: str, message: str) -> None:
        raise_if_cancelled(job_id)
        _jobs.update_job(job_id, status="running", stage=stage)
        _jobs.append_log(job_id, message)

    try:
        raise_if_cancelled(job_id)
        _jobs.update_job(job_id, status="running", stage="generating_script", error="")
        _jobs.append_log(job_id, f"开始生成炒股科普视频: {topic_text}")

        finance_topic = FinanceEduTopic(
            topic=topic_text,
            topic_type=topic_type,
            audience=audience,
            visual_style=visual_style,
        )

        result_dir = await run_finance_edu_video(
            topic=finance_topic,
            output_dir=output_dir,
            voice=voice,
            rate=rate,
            dry_run=False,
            stage_callback=on_stage,
        )

        raise_if_cancelled(job_id)
        _jobs.update_job(job_id, status="completed", stage="completed", error="")
        _jobs.append_log(job_id, f"炒股科普视频生成完成: {result_dir}")

        return _jobs.finalize_stock_output(job_id, topic_text)
    except JobCancelled as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "generating_script")
        _jobs.append_log(job_id, str(exc))
        _jobs._clear_current_video_output(job_id)
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "已取消",
            },
        )
        raise
    except Exception as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "generating_script")
        _jobs.append_log(job_id, f"炒股科普视频生成失败: {exc}")
        _jobs._clear_current_video_output(job_id)
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "渲染失败",
            },
        )
        raise


def finalize_stock_output(job_id: str, theme: str) -> dict[str, Any]:
    """生成股票科普视频正式输出"""
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")

    job_dir = _jobs.JOBS_DIR / job_id
    source = job_dir / "final.mp4"
    if not source.exists():
        raise ValueError("final.mp4 不存在")

    safe_title = _jobs._safe_filename(f"60秒带你看懂{theme}")
    base_name = f"{_jobs._job_date_prefix(job_id)}-{safe_title}"
    target = _jobs._write_to_official_output_dir(job, source, base_name)

    _jobs.append_log(job_id, f"正式视频已输出: {target}")
    _jobs.update_job(
        job_id,
        status="completed",
        stage="completed",
        official_video=str(target),
        render_progress={
            "stage": "completed",
            "stage_index": len(_jobs.RENDER_STAGE_ORDER),
            "stage_total": len(_jobs.RENDER_STAGE_ORDER),
            "step_current": 1,
            "step_total": 1,
            "percent": 100,
            "message": "渲染完成",
        },
    )
    return {"job": _jobs.read_job(job_id), "artifacts": _jobs.job_artifacts(job_id)}
