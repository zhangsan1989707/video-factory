"""视频合成器"""

from pathlib import Path

from moviepy import (
    ImageSequenceClip,
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
    from PIL import ImageFont

    font_size = 42
    margin_bottom = 80
    padding_h = 24
    padding_v = 12

    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

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
    # 1. 加载帧序列
    frame_files = sorted(mouse_frames_dir.glob("mouse-*.png"))
    if not frame_files:
        raise ValueError("没有找到鼠标动效帧")

    console.print(f"  加载 {len(frame_files)} 帧...")

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

    # 3. 创建开场标题卡片
    console.print(f"  生成开场动画...")
    project_name = script.title.replace("介绍 ", "")
    title_frames = create_title_card(
        title=project_name,
        subtitle="GitHub 项目推荐",
        width=VIDEO_WIDTH_H,
        height=VIDEO_HEIGHT_H,
        duration_frames=int(2.5 * fps),  # 2.5秒
    )

    # 4. 创建结尾CTA卡片
    console.print(f"  生成结尾动画...")
    cta_card = create_cta_card("⭐ Star 收藏，支持开源")
    cta_frames = []
    for i in range(int(2 * fps)):  # 2秒
        # 淡入效果
        progress = min(1, i / (fps * 0.5))
        alpha = int(255 * progress)
        frame = Image.new('RGB', (VIDEO_WIDTH_H, VIDEO_HEIGHT_H), (15, 23, 42))
        cta_with_alpha = cta_card.copy()
        cta_with_alpha.putalpha(int(alpha * cta_with_alpha.getextrema()[3][1] / 255))
        # 居中粘贴
        x = (VIDEO_WIDTH_H - cta_card.width) // 2
        y = (VIDEO_HEIGHT_H - cta_card.height) // 2
        frame.paste(cta_with_alpha, (x, y), cta_with_alpha)
        cta_frames.append(frame)

    # 5. 合并所有帧：开场 + 主体 + 结尾
    all_frames = []

    # 开场帧
    for frame in title_frames:
        all_frames.append(np.array(frame))

    # 主体帧（添加粒子效果）
    for i, frame_file in enumerate(frame_files):
        frame = Image.open(frame_file)
        # 每隔30帧添加一次粒子效果
        if i % 30 == 0:
            frame = add_particles(frame, num_particles=15)
        all_frames.append(np.array(frame))

    # 结尾帧
    for frame in cta_frames:
        all_frames.append(np.array(frame))

    # 6. 创建视频片段
    video_clip = ImageSequenceClip(all_frames, fps=fps)

    # 7. 合并音频（添加静音填充开场和结尾）
    if audio_clips:
        # 开场静音
        title_audio = AudioClip(lambda t: 0, duration=2.5, fps=44100)
        # 结尾静音
        cta_audio = AudioClip(lambda t: 0, duration=2, fps=44100)

        final_audio = concatenate_audioclips([title_audio] + audio_clips + [cta_audio])
        video_clip = video_clip.with_audio(final_audio)

    # 8. 添加字幕（使用 Pillow 渲染带背景的大号字幕）
    subtitle_clips = []
    current_time = 2.5  # 从开场结束后开始
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

    # 9. 合成最终视频
    if subtitle_clips:
        final_clip = CompositeVideoClip([video_clip] + subtitle_clips)
    else:
        final_clip = video_clip

    # 10. 输出视频
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
    for clip in audio_clips:
        clip.close()

    console.print(f"  ✓ 视频已保存到: {output_path}")
    return output_path
