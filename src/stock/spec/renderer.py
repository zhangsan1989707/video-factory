"""video-spec-builder 封装 - 渲染股票科普视频分镜"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from src.utils.config import ROOT_DIR
from src.utils.render import get_font


# video-spec-builder 默认路径（子目录/子模块）
DEFAULT_VSB_PATH = ROOT_DIR / "third_party" / "video-spec-builder"


def _parse_color(color_value: Any, default: str = "#FFFFFF") -> str:
    """将 spec 中的颜色值统一转换为 #RRGGBB 字符串。"""
    if isinstance(color_value, str):
        color_value = color_value.strip()
        if color_value.startswith("#"):
            return color_value
        if color_value.lower().startswith("rgb"):
            try:
                nums = [int(x.strip()) for x in color_value.strip("rgb() ").split(",")]
                return f"#{nums[0]:02x}{nums[1]:02x}{nums[2]:02x}"
            except Exception:
                return default
    if isinstance(color_value, (list, tuple)) and len(color_value) >= 3:
        return f"#{int(color_value[0]):02x}{int(color_value[1]):02x}{int(color_value[2]):02x}"
    return default


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """将 #RRGGBB 转为 RGB 元组。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


class StockRenderer:
    """股票科普视频渲染器

    封装 video-spec-builder 的调用与 ffmpeg 视频合成。
    当 video-spec-builder 未安装或没有渲染入口时，自动降级为 PIL 生成基础帧。
    """

    def __init__(self, video_spec_builder_path: str | Path | None = None):
        if video_spec_builder_path is None:
            self.video_spec_builder_path = DEFAULT_VSB_PATH
        else:
            self.video_spec_builder_path = Path(video_spec_builder_path)

    def _find_vsb_render_script(self) -> Path | None:
        """查找 video-spec-builder 的可执行渲染脚本。"""
        candidates = [
            self.video_spec_builder_path / "render.py",
            self.video_spec_builder_path / "bin" / "render.py",
            self.video_spec_builder_path / "bin" / "render",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _is_vsb_available(self) -> bool:
        """检查 video-spec-builder 是否具备可调用渲染能力。"""
        return self.video_spec_builder_path.exists() and self._find_vsb_render_script() is not None

    def render_shots(
        self,
        spec: dict[str, Any],
        output_dir: Path,
    ) -> list[Path]:
        """渲染分镜规范为帧序列

        Args:
            spec: 分镜规范 JSON（含 version / resolution / duration / theme / shots）
            output_dir: 帧序列输出目录

        Returns:
            按文件名排序的帧图片路径列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 写入 spec JSON
        spec_file = output_dir / "shot_spec.json"
        with open(spec_file, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)

        # 2. 尝试调用 video-spec-builder
        render_script = self._find_vsb_render_script()
        if render_script is not None:
            python_cmd = shutil.which("python") or shutil.which("python3") or "python"
            result = subprocess.run(
                [
                    python_cmd,
                    str(render_script),
                    "--spec",
                    str(spec_file),
                    "--output",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return sorted(output_dir.glob("frame_*.png"))
            # 调用失败时不直接抛错，降级 fallback，保留错误信息供排查

        # 3. 降级：使用 PIL 生成基础帧
        return self._fallback_render_frames(spec, output_dir)

    def _fallback_render_frames(
        self,
        spec: dict[str, Any],
        output_dir: Path,
    ) -> list[Path]:
        """video-spec-builder 不可用时，使用 PIL 生成简单杂志风帧。"""
        output_dir.mkdir(parents=True, exist_ok=True)

        resolution = spec.get("resolution", [1080, 1920])
        width, height = int(resolution[0]), int(resolution[1])
        theme = spec.get("theme", {})
        bg_color = _parse_color(theme.get("background", "#0F0F1A"))
        text_color = _parse_color(theme.get("text", "#FFFFFF"))
        accent_color = _parse_color(theme.get("accent", "#E8B04B"))
        fps = spec.get("fps", 30)

        frames: list[Path] = []
        frame_index = 1

        for shot in spec.get("shots", []):
            duration = float(shot.get("end", 0)) - float(shot.get("start", 0))
            if duration <= 0:
                duration = 1.0
            frame_count = max(1, int(duration * fps))

            for _ in range(frame_count):
                img = Image.new("RGB", (width, height), _hex_to_rgb(bg_color))
                draw = ImageDraw.Draw(img)
                self._draw_fallback_shot(
                    draw,
                    shot,
                    width,
                    height,
                    text_color,
                    accent_color,
                )
                frame_path = output_dir / f"frame_{frame_index:04d}.png"
                img.save(frame_path)
                frames.append(frame_path)
                frame_index += 1

        return frames

    def _draw_fallback_shot(
        self,
        draw: ImageDraw.ImageDraw,
        shot: dict[str, Any],
        width: int,
        height: int,
        text_color: str,
        accent_color: str,
    ) -> None:
        """在画布上绘制单个 fallback 分镜。"""
        shot_type = shot.get("type", "")
        content = shot.get("content", {})
        text_rgb = _hex_to_rgb(text_color)
        accent_rgb = _hex_to_rgb(accent_color)

        font_large = get_font(72)
        font_medium = get_font(48)
        font_small = get_font(32)

        if shot_type == "title":
            main = content.get("main", "")
            sub = content.get("sub", "")
            if isinstance(font_large, ImageFont.FreeTypeFont):
                draw.text((width // 2, height // 2 - 80), main, font=font_large, fill=text_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), sub, font=font_medium, fill=accent_rgb, anchor="mm")
            else:
                draw.text((width // 2, height // 2 - 80), main, fill=text_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), sub, fill=accent_rgb, anchor="mm")

        elif shot_type == "definition":
            term = content.get("term", "")
            definition = content.get("definition", "")
            if isinstance(font_large, ImageFont.FreeTypeFont):
                draw.text((width // 2, height // 2 - 100), term, font=font_large, fill=accent_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), definition, font=font_medium, fill=text_rgb, anchor="mm")
            else:
                draw.text((width // 2, height // 2 - 100), term, fill=accent_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), definition, fill=text_rgb, anchor="mm")

        elif shot_type == "chart":
            chart_type = content.get("chart_type", "line")
            if isinstance(font_large, ImageFont.FreeTypeFont):
                draw.text((width // 2, height // 2 - 80), chart_type.upper(), font=font_large, fill=accent_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), "[Chart Data]", font=font_medium, fill=text_rgb, anchor="mm")
            else:
                draw.text((width // 2, height // 2 - 80), chart_type.upper(), fill=accent_rgb, anchor="mm")
                draw.text((width // 2, height // 2 + 40), "[Chart Data]", fill=text_rgb, anchor="mm")

        elif shot_type == "comparison":
            left = content.get("left", {})
            right = content.get("right", {})
            left_label = left.get("label", "")
            right_label = right.get("label", "")
            if isinstance(font_medium, ImageFont.FreeTypeFont):
                draw.text((width // 4, height // 2), left_label, font=font_medium, fill=text_rgb, anchor="mm")
                draw.text((width * 3 // 4, height // 2), right_label, font=font_medium, fill=accent_rgb, anchor="mm")
            else:
                draw.text((width // 4, height // 2), left_label, fill=text_rgb, anchor="mm")
                draw.text((width * 3 // 4, height // 2), right_label, fill=accent_rgb, anchor="mm")

        elif shot_type == "summary":
            points = content.get("points", [])
            closing = content.get("closing", "")
            y = height // 2 - 80
            if isinstance(font_medium, ImageFont.FreeTypeFont):
                for point in points[:3]:
                    draw.text((width // 2, y), f"• {point}", font=font_medium, fill=text_rgb, anchor="mm")
                    y += 70
                draw.text((width // 2, y + 40), closing, font=font_small, fill=accent_rgb, anchor="mm")
            else:
                for point in points[:3]:
                    draw.text((width // 2, y), f"• {point}", fill=text_rgb, anchor="mm")
                    y += 70
                draw.text((width // 2, y + 40), closing, fill=accent_rgb, anchor="mm")

        else:
            # 通用兜底
            label = f"{shot.get('id', '?')} · {shot_type}"
            if isinstance(font_large, ImageFont.FreeTypeFont):
                draw.text((width // 2, height // 2), label, font=font_large, fill=text_rgb, anchor="mm")
            else:
                draw.text((width // 2, height // 2), label, fill=text_rgb, anchor="mm")

    def render_video_from_frames(
        self,
        frames: list[Path],
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        fps: int = 30,
    ) -> Path:
        """合成帧序列 + 音频 + 字幕为最终视频

        Args:
            frames: 帧图片路径列表
            audio_path: TTS 音频文件
            subtitle_path: SRT 字幕文件
            output_path: 输出视频路径
            fps: 帧率

        Returns:
            输出视频路径
        """
        if not frames:
            raise ValueError("No frames to render")

        frames_dir = frames[0].parent
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 确保帧文件名连续（ffmpeg 使用 frame_%04d.png 模式）
        self._normalize_frame_names(frames)

        input_pattern = str(frames_dir / "frame_%04d.png")
        audio_path = Path(audio_path)
        subtitle_path = Path(subtitle_path)

        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            input_pattern,
            "-i",
            str(audio_path),
        ]

        if subtitle_path.exists():
            vf = f"subtitles={subtitle_path}:force_style='FontSize=24,PrimaryColour=&HFFFFFF&'"
            cmd.extend(["-vf", vf])

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_path),
            ]
        )

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg video composition failed: {result.stderr}")

        return output_path

    def _normalize_frame_names(self, frames: list[Path]) -> None:
        """将帧序列重命名为连续的 frame_%04d.png，便于 ffmpeg 读取。"""
        for i, frame in enumerate(sorted(frames), start=1):
            target = frame.parent / f"frame_{i:04d}.png"
            if frame.resolve() != target.resolve():
                frame.rename(target)


def get_renderer_version() -> str:
    """获取渲染器版本"""
    return "0.2.0"
