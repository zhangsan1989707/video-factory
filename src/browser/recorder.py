"""浏览器录制器"""

from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console

from src.models import VideoScript, Frame
from src.browser.actions import execute_action, get_element_bounds
from src.utils.config import VIDEO_WIDTH_H, VIDEO_HEIGHT_H

console = Console()

MAX_RETRIES = 3


async def safe_goto(page, url, timeout=60000):
    """安全导航页面（带重试）"""
    for attempt in range(MAX_RETRIES):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_timeout(2000)
            return
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                console.print(f"  [yellow]⚠ 页面加载失败，重试 {attempt + 1}/{MAX_RETRIES}...[/yellow]")
                await page.wait_for_timeout(2000)
            else:
                raise


async def record_browser(
    script: VideoScript,
    output_dir: Path,
    fps: int = 30,
    total_audio_duration: float = 0,
) -> list[dict]:
    """
    根据脚本录制浏览器截图序列
    """
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    frame_index = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": VIDEO_WIDTH_H, "height": VIDEO_HEIGHT_H},
            device_scale_factor=1,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # 先访问 GitHub 首页
        console.print("  初始化浏览器...")
        await safe_goto(page, "https://github.com")

        # 计算每个片段的实际时长
        if total_audio_duration > 0:
            scale_factor = total_audio_duration / script.total_duration
        else:
            scale_factor = 1.0

        for seg_idx, segment in enumerate(script.segments):
            console.print(f"  录制片段 {seg_idx + 1}: {segment.narration[:20]}...")

            # 执行动作
            if segment.action == "navigate":
                url = segment.target
                if not url.startswith("http"):
                    url = f"https://github.com/{url}"
                await safe_goto(page, url)
            else:
                await execute_action(page, segment.action, segment.target)
                await page.wait_for_timeout(500)

            # 获取元素位置
            bounds = None
            if segment.target and segment.action in ("highlight", "click", "zoom"):
                bounds = await get_element_bounds(page, segment.target)

            # 计算帧数
            adjusted_duration = segment.duration * scale_factor
            num_frames = max(1, int(adjusted_duration * fps))

            # 截取帧
            for i in range(num_frames):
                screenshot = await page.screenshot(type="png")
                frame_path = frames_dir / f"frame-{frame_index:04d}.png"

                with open(frame_path, "wb") as f:
                    f.write(screenshot)

                frames.append({
                    "path": frame_path,
                    "timestamp": segment.timestamp + (i / fps),
                    "segment_index": seg_idx,
                    "bounds": bounds,
                })

                frame_index += 1

        await browser.close()

    console.print(f"  ✓ 截取 {frame_index} 帧")
    return frames
