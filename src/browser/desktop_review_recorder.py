"""Browser recorder for desktop review style."""

from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console

from src.models import DesktopReviewPlan

console = Console()


async def _goto(page, url: str) -> None:
    """导航到 URL，处理重定向问题"""
    # 先尝试直接访问
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)

    # 检查是否被重定向到登录页
    current_url = page.url
    if "login" in current_url or "join" in current_url:
        console.print(f"    ⚠️  检测到登录页，尝试绕过...")
        # 等待一下，然后重新访问
        await page.wait_for_timeout(1000)
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 如果还是登录页，尝试访问项目主页
        if "login" in page.url or "join" in page.url:
            console.print(f"    ⚠️  仍然在登录页，尝试访问项目主页")
            # 提取项目主页 URL
            if "/blob/" in url:
                base_url = url.split("/blob/")[0]
                await page.goto(base_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)


async def _find_target(page, selector: str):
    for part in [item.strip() for item in selector.split(",") if item.strip()]:
        try:
            locator = page.locator(part).first
            if await locator.count() > 0:
                await locator.scroll_into_view_if_needed(timeout=2500)
                await page.wait_for_timeout(600)
                box = await locator.bounding_box()
                if box:
                    return box
        except Exception:
            continue
    return None


async def record_desktop_review(plan: DesktopReviewPlan, output_dir: Path) -> list[dict]:
    """Capture one representative browser frame for each desktop review shot."""
    frames_dir = output_dir / "desktop_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            color_scheme="dark",
            locale="zh-CN",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"},
        )

        # 注入脚本绕过自动化检测
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()
        current_url = ""

        for index, shot in enumerate(plan.shots):
            console.print(f"  录制桌面镜头 {index + 1}: {shot.cursor_label}")

            # 检查是否需要导航到新 URL
            if shot.url != current_url:
                await _goto(page, shot.url)
                current_url = shot.url

                # 最终检查：如果还是登录页，记录警告
                if "login" in page.url or "join" in page.url:
                    console.print(f"    ❌ 无法绕过登录页，将使用当前页面截图")

            # 滚动到目标元素
            box = await _find_target(page, shot.selector)
            if box is None and shot.action == "scroll":
                # 如果找不到目标，尝试滚动页面
                await page.evaluate("window.scrollBy(0, 400)")
                await page.wait_for_timeout(800)
                box = await _find_target(page, shot.selector)

            # 等待页面稳定
            await page.wait_for_timeout(500)

            frame_path = frames_dir / f"shot-{index + 1:02d}.png"
            await page.screenshot(path=str(frame_path), full_page=False)
            frames.append({
                "path": str(frame_path),
                "bounds": box,
                "shot_index": index,
            })

        await context.close()
        await browser.close()

    return frames
