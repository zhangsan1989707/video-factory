"""Capture visual assets for V2 videos."""

from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from rich.console import Console

from src.models import AssetManifest, VisualAsset

console = Console()


def _safe_name(asset: VisualAsset, suffix: str = ".png") -> str:
    return f"{asset.id}-{asset.type}{suffix}"


def _placeholder(path: Path, title: str, detail: str) -> Path:
    img = Image.new("RGB", (1280, 900), (246, 248, 250))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 52)
        font_body = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 30)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    draw.rounded_rectangle((80, 90, 1200, 810), radius=28, fill=(255, 255, 255), outline=(208, 215, 222), width=2)
    draw.text((130, 160), title[:32], fill=(36, 41, 47), font=font_title)
    y = 260
    for line in [detail[i:i + 34] for i in range(0, len(detail), 34)][:8]:
        draw.text((130, y), line, fill=(87, 96, 106), font=font_body)
        y += 48
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


async def _download_image(asset: VisualAsset, output_dir: Path) -> Path:
    ext = Path(urlparse(asset.source).path).suffix
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    path = output_dir / _safe_name(asset, ext)
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(asset.source)
            response.raise_for_status()
        path.write_bytes(response.content)
        return path
    except Exception as exc:
        return _placeholder(path.with_suffix(".png"), asset.caption, f"图片抓取失败: {exc}")


async def _capture_page(browser, asset: VisualAsset, output_dir: Path) -> Path:
    path = output_dir / _safe_name(asset)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        device_scale_factor=1,
        locale="zh-CN",
        extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"},
    )
    page = await context.new_page()
    try:
        await page.goto(asset.source, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1800)
        for label in ("中文", "简体中文", "简中"):
            try:
                option = page.get_by_text(label, exact=True).first
                if await option.count() > 0 and await option.is_visible():
                    await option.click(timeout=1200)
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                pass
        await page.screenshot(path=str(path), full_page=False)
        return path
    except Exception as exc:
        return _placeholder(path, asset.caption, f"网页截图失败: {exc}")
    finally:
        await context.close()


async def capture_assets(manifest: AssetManifest, output_dir: Path) -> AssetManifest:
    """Download or screenshot assets and update their local paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    browser = None

    async with async_playwright() as playwright:
        for asset in manifest.assets:
            console.print(f"  采集素材 {asset.id}: {asset.caption}")
            if asset.type == "image":
                local_path = await _download_image(asset, output_dir)
            else:
                if browser is None:
                    browser = await playwright.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                    )
                local_path = await _capture_page(browser, asset, output_dir)
            asset.path = str(local_path)

        if browser is not None:
            await browser.close()

    return manifest
