"""浏览器动作定义"""

from playwright.async_api import Page


async def execute_action(page: Page, action: str, target: str) -> None:
    """执行浏览器动作"""
    if action == "navigate":
        await page.goto(target, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

    elif action == "scroll":
        try:
            element = page.locator(target).first
            if await element.count() > 0:
                await element.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
        except Exception:
            # 找不到目标，向下滚动一屏
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(500)

    elif action == "click":
        try:
            element = page.locator(target).first
            if await element.count() > 0:
                # 不真正点击，只滚动到可见
                await element.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
        except Exception:
            pass

    elif action == "highlight":
        try:
            element = page.locator(target).first
            if await element.count() > 0:
                await element.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
        except Exception:
            pass

    elif action == "zoom":
        try:
            element = page.locator(target).first
            if await element.count() > 0:
                await element.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def get_element_bounds(page: Page, target: str) -> dict | None:
    """获取元素的位置和大小"""
    try:
        element = page.locator(target).first
        if await element.count() > 0:
            box = await element.bounding_box()
            if box:
                return {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                }
    except Exception:
        pass
    return None
