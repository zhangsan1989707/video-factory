"""视频合成器"""

from pathlib import Path

from moviepy import (
    VideoClip,
    AudioFileClip,
    AudioClip,
    concatenate_audioclips,
    CompositeVideoClip,
    CompositeAudioClip,
    TextClip,
    ImageClip,
)
from PIL import Image, ImageDraw
import numpy as np
from rich.console import Console

from src.models import VideoScript
from src.utils.config import VIDEO_FPS, VIDEO_WIDTH_H, VIDEO_HEIGHT_H
from src.utils.render import get_font
from src.composer.effects import (
    create_title_card,
    create_info_card,
    create_feature_card,
    create_cta_card,
    create_transition_frames,
    add_particles,
)

console = Console()


def _render_subtitle_image(
    text: str,
    video_width: int,
    video_height: int,
) -> Image.Image:
    """渲染带背景和阴影的大号字幕图像"""
    font_size = 42
    margin_bottom = 80
    padding_h = 24
    padding_v = 12

    font = get_font(font_size)

    # 先测量文字尺寸
    tmp = Image.new("RGBA", (1, 1))
    tmp_draw = ImageDraw.Draw(tmp)
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 创建字幕画布（与视频同尺寸，透明背景）
    canvas = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))

    # 计算文字位置（居中，底部偏上）
    box_w = text_w + padding_h * 2
    box_h = text_h + padding_v * 2
    box_x = (video_width - box_w) // 2
    box_y = video_height - margin_bottom - box_h

    # 绘制半透明黑色背景条（圆角效果用多层矩形模拟）
    bg = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    # 主背景
    bg_draw.rounded_rectangle(
        [(0, 0), (box_w, box_h)],
        radius=12,
        fill=(0, 0, 0, 180),
    )
    canvas.paste(bg, (box_x, box_y), bg)

    # 绘制文字阴影（右下偏移）
    draw = ImageDraw.Draw(canvas)
    shadow_offset = 2
    draw.text(
        (box_x + padding_h + shadow_offset, box_y + padding_v + shadow_offset),
        text,
        fill=(0, 0, 0, 160),
        font=font,
    )

    # 绘制白色文字
    draw.text(
        (box_x + padding_h, box_y + padding_v),
        text,
        fill=(255, 255, 255, 240),
        font=font,
    )

    return canvas


def compose_video(
    script: VideoScript,
    mouse_frames_dir: Path,
    audio_dir: Path,
    output_path: Path,
    fps: int = VIDEO_FPS,
    orientation: str = "horizontal",
    total_audio_duration: float = 0,
) -> Path:
    """
    将所有素材合成为最终视频
    """
    # 1. 加载帧序列文件列表
    frame_files = sorted(mouse_frames_dir.glob("mouse-*.png"))
    if not frame_files:
        raise ValueError("没有找到鼠标动效帧")

    console.print(f"  找到 {len(frame_files)} 帧...")

    # 2. 加载音频并计算每段时长
    audio_clips = []
    audio_durations = []
    for i, segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{i:03d}.mp3"
        if audio_path.exists():
            clip = AudioFileClip(str(audio_path))
            audio_clips.append(clip)
            audio_durations.append(clip.duration)

    total_audio = sum(audio_durations)

    # 3. 预计算时间边界
    title_duration = 2.5
    cta_duration = 2.0
    body_duration = total_audio
    total_duration = title_duration + body_duration + cta_duration
    num_body_frames = len(frame_files)

    # 4. 预生成开场标题卡片帧
    console.print(f"  生成开场动画...")
    project_name = script.title.replace("介绍 ", "")
    title_frames = create_title_card(
        title=project_name,
        subtitle="GitHub 项目推荐",
        width=VIDEO_WIDTH_H,
        height=VIDEO_HEIGHT_H,
        duration_frames=int(title_duration * fps),
    )

    # 5. 预生成结尾CTA卡片
    console.print(f"  生成结尾动画...")
    cta_card = create_cta_card("⭐ Star 收藏，支持开源")

    # 6. 创建 make_frame 回调（按需加载帧，避免内存爆炸）
    def make_frame(t):
        if t < title_duration:
            # 开场标题卡片 - 跳过前 0.1s 避免黑屏
            adjusted_t = max(0.1, t)
            frame_idx = min(int(adjusted_t * fps), len(title_frames) - 1)
            return np.array(title_frames[frame_idx])
        elif t < title_duration + body_duration:
            # 主体帧（从磁盘按需加载）- 跳过前 0.1s 避免黑屏
            body_t = t - title_duration
            body_t = max(0.1, body_t)
            frame_idx = min(int(body_t * fps), num_body_frames - 1)
            frame = Image.open(frame_files[frame_idx])
            if frame_idx % 30 == 0:
                frame = add_particles(frame, num_particles=15)
            return np.array(frame)
        else:
            # 结尾CTA卡片 - 跳过前 0.1s 避免黑屏
            cta_t = t - title_duration - body_duration
            cta_t = max(0.1, cta_t)
            frame_idx = min(int(cta_t * fps), int(cta_duration * fps) - 1)
            progress = min(1, frame_idx / (fps * 0.5))
            alpha = int(255 * progress)
            frame = Image.new('RGB', (VIDEO_WIDTH_H, VIDEO_HEIGHT_H), (15, 23, 42))
            cta_with_alpha = cta_card.copy()
            if cta_with_alpha.mode != "RGBA":
                cta_with_alpha = cta_with_alpha.convert("RGBA")
            cta_with_alpha.putalpha(int(alpha * cta_with_alpha.getextrema()[3][1] / 255))
            x = (VIDEO_WIDTH_H - cta_card.width) // 2
            y = (VIDEO_HEIGHT_H - cta_card.height) // 2
            frame.paste(cta_with_alpha, (x, y), cta_with_alpha)
            return np.array(frame)

    # 7. 创建视频片段
    video_clip = VideoClip(make_frame=make_frame, duration=total_duration)

    # 8. 合并音频（添加静音填充开场和结尾）
    title_audio = None
    cta_audio = None
    if audio_clips:
        title_audio = AudioClip(lambda t: 0, duration=title_duration, fps=44100)
        cta_audio = AudioClip(lambda t: 0, duration=cta_duration, fps=44100)

        final_audio = concatenate_audioclips([title_audio] + audio_clips + [cta_audio])
        video_clip = video_clip.with_audio(final_audio)

    # 9. 添加字幕（使用 Pillow 渲染带背景的大号字幕）
    subtitle_clips = []
    current_time = title_duration  # 从开场结束后开始
    for i, segment in enumerate(script.segments):
        if i < len(audio_durations):
            actual_duration = audio_durations[i]
        else:
            actual_duration = segment.duration

        try:
            sub_img = _render_subtitle_image(
                segment.narration, VIDEO_WIDTH_H, VIDEO_HEIGHT_H,
            )
            sub_clip = (
                ImageClip(np.array(sub_img))
                .with_start(current_time)
                .with_duration(actual_duration)
                .with_position((0, 0))
            )
            subtitle_clips.append(sub_clip)
        except Exception as e:
            console.print(f"  [yellow]⚠ 字幕生成失败: {e}[/yellow]")

        current_time += actual_duration

    # 10. 合成最终视频
    if subtitle_clips:
        final_clip = CompositeVideoClip([video_clip] + subtitle_clips)
    else:
        final_clip = video_clip

    # 11. 输出视频
    console.print(f"  编码输出视频...")
    final_clip.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        bitrate="8000k",
        preset="medium",
        logger=None,
    )

    # 清理
    video_clip.close()
    final_clip.close()
    for clip in subtitle_clips:
        clip.close()
    for clip in audio_clips:
        clip.close()
    if title_audio:
        title_audio.close()
    if cta_audio:
        cta_audio.close()

    console.print(f"  ✓ 视频已保存到: {output_path}")
    return output_path
