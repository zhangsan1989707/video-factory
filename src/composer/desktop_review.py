"""Desktop-review style video composer."""

from pathlib import Path

from moviepy import AudioClip, AudioFileClip, VideoClip, concatenate_audioclips
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
from rich.console import Console

from src.models import DesktopReviewPlan, VideoScript
from src.utils.config import VIDEO_FPS
from src.utils.render import get_font, ease_out, create_cursor

console = Console()

CANVAS_W = 1592
CANVAS_H = 1080
PAGE_W = 1380
PAGE_H = 880



def _draw_text_stroke(draw: ImageDraw.ImageDraw, pos, text: str, font, fill, stroke, width: int) -> None:
    draw.text(pos, text, font=font, fill=fill, stroke_width=width, stroke_fill=stroke)


def _cursor() -> Image.Image:
    """创建更显眼的鼠标指针（比参考视频大 1.5 倍）"""
    return create_cursor(96)


def _render_intro_card(project_name: str, hook_text: str, progress: float) -> Image.Image:
    """渲染开场卡：中文大标题 + 项目核心价值"""
    canvas = _get_desktop_background().convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # 标题字体
    title_font = get_font(88)
    hook_font = get_font(48)
    sub_font = get_font(36)

    # 标题：项目名称
    title_text = project_name
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (CANVAS_W - title_w) // 2
    title_y = 280

    # 副标题：核心价值
    hook_bbox = draw.textbbox((0, 0), hook_text, font=hook_font)
    hook_w = hook_bbox[2] - hook_bbox[0]
    hook_x = (CANVAS_W - hook_w) // 2
    hook_y = title_y + 120

    # 底部提示
    sub_text = "看看它能做什么"
    sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_x = (CANVAS_W - sub_w) // 2
    sub_y = hook_y + 100

    # 动画：淡入效果
    alpha = int(255 * min(1.0, progress / 0.3)) if progress < 0.3 else 255
    if progress > 0.8:
        alpha = int(255 * (1.0 - (progress - 0.8) / 0.2))

    # 绘制标题
    _draw_text_stroke(draw, (title_x, title_y), title_text, title_font,
                      (255, 255, 255, alpha), (235, 0, 72, alpha), 6)

    # 绘制副标题
    draw.text((hook_x, hook_y), hook_text, font=hook_font,
              fill=(255, 238, 0, alpha), stroke_width=3, stroke_fill=(0, 0, 0, alpha))

    # 绘制底部提示
    draw.text((sub_x, sub_y), sub_text, font=sub_font,
              fill=(200, 200, 200, alpha))

    return canvas.convert("RGB")


def _desktop_background() -> Image.Image:
    bg = Image.new("RGB", (CANVAS_W, CANVAS_H), (108, 112, 116))
    draw = ImageDraw.Draw(bg)
    for x in range(CANVAS_W):
        shade = int(122 - 42 * (x / CANVAS_W))
        draw.line((x, 0, x, CANVAS_H), fill=(shade, shade, shade))
    vignette = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    vdraw.rectangle((0, 0, 135, CANVAS_H), fill=(0, 0, 0, 70))
    vdraw.polygon([(CANVAS_W - 96, 0), (CANVAS_W, 0), (CANVAS_W, CANVAS_H), (CANVAS_W - 280, CANVAS_H)], fill=(0, 0, 0, 105))
    bg = bg.convert("RGBA")
    bg.alpha_composite(vignette.filter(ImageFilter.GaussianBlur(16)))
    return bg.convert("RGB")


_CACHED_BG = None


def _get_desktop_background():
    global _CACHED_BG
    if _CACHED_BG is None:
        _CACHED_BG = _desktop_background()
    return _CACHED_BG


def _crop_for_zoom(page: Image.Image, bounds: dict | None, zoom: float, progress: float) -> tuple[Image.Image, tuple[int, int]]:
    if zoom <= 1.02:
        mouse = (PAGE_W // 2, PAGE_H // 2)
        if bounds:
            mouse = (int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2))
        return page, mouse

    target_zoom = 1 + (zoom - 1) * ease_out(progress)
    crop_w = int(PAGE_W / target_zoom)
    crop_h = int(PAGE_H / target_zoom)
    if bounds:
        cx = int(bounds["x"] + bounds["width"] / 2)
        cy = int(bounds["y"] + bounds["height"] / 2)
    else:
        cx, cy = PAGE_W // 2, PAGE_H // 2
    left = max(0, min(cx - crop_w // 2, PAGE_W - crop_w))
    top = max(0, min(cy - crop_h // 2, PAGE_H - crop_h))
    cropped = page.crop((left, top, left + crop_w, top + crop_h)).resize((PAGE_W, PAGE_H), Image.Resampling.LANCZOS)
    mouse = (int((cx - left) * PAGE_W / crop_w), int((cy - top) * PAGE_H / crop_h))
    return cropped, mouse


def _render_frame(
    plan: DesktopReviewPlan,
    page_path: str,
    bounds: dict | None,
    shot_index: int,
    progress: float,
) -> Image.Image:
    shot = plan.shots[shot_index]
    try:
        page = Image.open(page_path).convert("RGB").resize((PAGE_W, PAGE_H), Image.Resampling.LANCZOS)
    except Exception:
        page = Image.new("RGB", (PAGE_W, PAGE_H), (13, 17, 23))

    page, mouse_pos = _crop_for_zoom(page, bounds, shot.zoom, progress)
    canvas = _get_desktop_background().convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    top_font = get_font(70)
    account_font = get_font(52)
    bottom_font = get_font(68)
    label_font = get_font(28)

    _draw_text_stroke(draw, (24, 8), plan.hook_title, top_font, (255, 255, 255), (235, 0, 72), 8)
    account = plan.account_label
    account_bbox = draw.textbbox((0, 0), account, font=account_font)
    draw.text((CANVAS_W - (account_bbox[2] - account_bbox[0]) - 42, 24), account, font=account_font, fill=(255, 255, 255), stroke_width=4, stroke_fill=(72, 72, 72))

    win_x = 80
    win_y = 90
    shadow = Image.new("RGBA", (PAGE_W + 64, PAGE_H + 72), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((26, 26, PAGE_W + 38, PAGE_H + 48), radius=24, fill=(0, 0, 0, 140))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)), (win_x - 32, win_y - 32))

    mask = Image.new("L", (PAGE_W, PAGE_H), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle((0, 0, PAGE_W, PAGE_H), radius=18, fill=255)
    canvas.paste(page, (win_x, win_y), mask)
    draw.rounded_rectangle((win_x, win_y, win_x + PAGE_W, win_y + PAGE_H), radius=18, outline=(255, 255, 255, 32), width=2)

    # 如果有 bounds，添加高亮框（只在 bounds 不太大时显示）
    if bounds and progress > 0.15 and progress < 0.85:
        hl_w = int(bounds["width"])
        hl_h = int(bounds["height"])
        # 只在元素不太大时显示高亮框（避免整个 README 区域都被框住）
        if hl_w < PAGE_W * 0.6 and hl_h < PAGE_H * 0.4:
            highlight_alpha = int(120 * min(1.0, (progress - 0.15) / 0.2)) if progress < 0.35 else int(120 * max(0.0, (0.85 - progress) / 0.2))
            hl_x = win_x + int(bounds["x"])
            hl_y = win_y + int(bounds["y"])
            draw.rounded_rectangle(
                (hl_x - 3, hl_y - 3, hl_x + hl_w + 3, hl_y + hl_h + 3),
                radius=4,
                outline=(255, 235, 20, highlight_alpha),
                width=2,
            )

    # 标签位置：优先放在 bounds 上方，如果没有足够空间则放在下方
    label = shot.cursor_label
    label_w = draw.textbbox((0, 0), label, font=label_font)[2] + 36
    if bounds:
        # 标签放在 bounds 上方
        label_x = win_x + int(bounds["x"]) + int(bounds["width"]) // 2 - label_w // 2
        label_y = win_y + int(bounds["y"]) - 54
        # 确保标签不超出窗口
        label_x = max(win_x + 12, min(label_x, win_x + PAGE_W - label_w - 12))
        label_y = max(win_y + 12, label_y)
    else:
        # 默认位置：靠近鼠标
        label_x = max(win_x + 24, min(win_x + mouse_pos[0] - 42, win_x + PAGE_W - label_w - 24))
        label_y = max(win_y + 24, min(win_y + mouse_pos[1] - 70, win_y + PAGE_H - 110))
    draw.rounded_rectangle((label_x, label_y, label_x + label_w, label_y + 46), radius=14, fill=(255, 235, 20, 235))
    draw.text((label_x + 18, label_y + 8), label, font=label_font, fill=(18, 18, 18))

    # 鼠标动画：从右下角移动到目标位置
    start = (CANVAS_W - 160, CANVAS_H - 200)
    end = (win_x + mouse_pos[0] - 18, win_y + mouse_pos[1] - 12)
    move = min(1.0, progress / 0.42)
    cursor_x = int(start[0] + (end[0] - start[0]) * ease_out(move))
    cursor_y = int(start[1] + (end[1] - start[1]) * ease_out(move))

    # 鼠标到达后，添加点击/指向效果
    if progress > 0.58:
        ring = int(18 + 38 * (progress - 0.58) / 0.42)
        draw.ellipse((cursor_x - ring, cursor_y - ring, cursor_x + ring, cursor_y + ring), outline=(255, 235, 20, 180), width=5)
    canvas.alpha_composite(_cursor(), (cursor_x, cursor_y))

    bottom_text = plan.title
    bottom_x = 44
    bottom_y = CANVAS_H - 126
    _draw_text_stroke(draw, (bottom_x, bottom_y), bottom_text, bottom_font, (255, 238, 0), (0, 0, 0), 7)

    return canvas.convert("RGB")


def compose_desktop_review_video(
    plan: DesktopReviewPlan,
    script: VideoScript,
    frames_info: list[dict],
    audio_dir: Path,
    output_path: Path,
    preview_dir: Path,
    fps: int = VIDEO_FPS,
) -> Path:
    """Compose a desktop-review style video."""
    audio_clips = []
    audio_durations = []
    for i, segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{i:03d}.mp3"
        if audio_path.exists():
            clip = AudioFileClip(str(audio_path))
            audio_clips.append(clip)
            audio_durations.append(clip.duration)
        else:
            audio_durations.append(segment.duration)

    preview_dir.mkdir(parents=True, exist_ok=True)

    # 开场卡：2 秒
    intro_duration = 2.0
    project_name = plan.title.split(":")[0] if ":" in plan.title else plan.title
    hook_text = plan.shots[0].narration[:20] + "..." if len(plan.shots[0].narration) > 20 else plan.shots[0].narration

    # 预计算每个 shot 的时长和动态帧数
    shot_durations = []
    shot_dynamic_counts = []
    for i, info in enumerate(frames_info):
        duration = audio_durations[i] if i < len(audio_durations) else plan.shots[i].duration
        shot_durations.append(duration)
        total_frames = max(1, int(duration * fps))
        dynamic_frames = min(total_frames, max(8, int(duration * 6)))
        shot_dynamic_counts.append(dynamic_frames)

    total_duration = intro_duration + sum(shot_durations)

    # 保存预览帧
    console.print("  生成预览帧...")
    intro_preview = _render_intro_card(project_name, hook_text, 0.5)
    intro_preview.save(preview_dir / "desktop-shot-00-intro.png")

    for i, info in enumerate(frames_info):
        dynamic_frames = shot_dynamic_counts[i]
        preview_progress = min(1.0, max(0.0, 0.55))
        preview_frame_i = min(dynamic_frames - 1, max(0, int(dynamic_frames * 0.55)))
        progress = preview_frame_i / max(1, dynamic_frames - 1)
        frame = _render_frame(plan, info["path"], info.get("bounds"), i, progress)
        frame.save(preview_dir / f"desktop-shot-{i + 1:02d}.png")

    # 构建 make_frame 回调
    def make_frame(t: float):
        if t < intro_duration:
            # 开场卡区域
            progress = t / intro_duration if intro_duration > 0 else 1.0
            frame = _render_intro_card(project_name, hook_text, progress)
            return np.array(frame)

        # 正常 shot 区域
        remaining = t - intro_duration
        shot_index = 0
        for i, dur in enumerate(shot_durations):
            if remaining < dur:
                shot_index = i
                break
            remaining -= dur
        else:
            shot_index = len(shot_durations) - 1
            remaining = shot_durations[-1] if shot_durations else 0

        duration = shot_durations[shot_index]
        progress = min(1.0, remaining / duration) if duration > 0 else 1.0
        info = frames_info[shot_index]
        frame = _render_frame(plan, info["path"], info.get("bounds"), shot_index, progress)
        return np.array(frame)

    video_clip = VideoClip(make_frame, duration=total_duration)

    # 开场卡没有音频，需要添加静音
    intro_audio = AudioClip(lambda t: 0, duration=intro_duration, fps=44100)
    all_audio = None
    if audio_clips:
        all_audio = concatenate_audioclips([intro_audio] + audio_clips)
        video_clip = video_clip.with_audio(all_audio)
    else:
        video_clip = video_clip.with_audio(intro_audio)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    console.print("  编码 desktop-review 视频...")
    video_clip.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        bitrate="6000k",
        preset="medium",
        logger=None,
    )
    video_clip.close()
    intro_audio.close()
    if all_audio is not None:
        all_audio.close()
    for clip in audio_clips:
        clip.close()
    console.print(f"  ✓ desktop-review 视频已保存到: {output_path}")
    return output_path
