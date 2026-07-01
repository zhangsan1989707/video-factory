"""财经网站抓取模块 - 股票科普内容获取"""

import re
from typing import Any
from urllib.parse import urlparse

import httpx


# 支持的财经网站
FINANCE_SITES = {
    "eastmoney": "东方财富",
    "xueqiu": "雪球",
    "ths": "同花顺",
}


_EASTMONEY_SELECTORS = ("#ContentBody", ".stockcodec", ".article-body", ".txt-data")
_XUEQIU_SELECTORS = (".article__bd__detail", ".detail", ".article-content")
_THS_SELECTORS = (".newsText", ".news-text", ".content", "#main")


def _detect_source(url: str) -> str:
    """根据 URL 域名判断来源。"""
    host = urlparse(url).netloc.lower()
    if "eastmoney.com" in host:
        return "eastmoney"
    if "xueqiu.com" in host:
        return "xueqiu"
    if "10jqka.com.cn" in host or "hexin.cn" in host or "ths123.com" in host:
        return "ths"
    return "unknown"


def _strip_html(html: str) -> str:
    """用正则去除 HTML 标签、脚本与样式，返回纯文本。"""
    # 移除 script / style
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    # 移除标签
    text = re.sub(r"<[^>]+>", "", text)
    # 处理 HTML 实体
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    # 合并空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_article_text(html: str, source: str) -> str:
    """尝试从 HTML 中提取正文；失败时返回整页文本。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # 优先移除 script / style
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        selectors = {
            "eastmoney": _EASTMONEY_SELECTORS,
            "xueqiu": _XUEQIU_SELECTORS,
            "ths": _THS_SELECTORS,
        }.get(source, ())

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                return re.sub(r"\s+", " ", element.get_text(separator=" ", strip=True))

        # 未命中选择器，返回 body 文本
        body = soup.find("body")
        if body:
            return re.sub(r"\s+", " ", body.get_text(separator=" ", strip=True))
    except Exception:
        pass

    return _strip_html(html)


async def fetch_finance_content(
    url: str,
    topic: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """从财经网站抓取内容

    Args:
        url: 财经文章 URL；如果以 http 开头则直接抓取，否则作为搜索关键词处理
        topic: 主题关键词
        timeout: 请求超时

    Returns:
        包含 topic, content, source 的字典
    """
    url = url.strip()
    if not url.startswith("http"):
        # 非 URL 输入：尝试按关键词搜索，返回第一个结果的内容；失败时返回空内容
        topics = await search_finance_topics(url or topic, source="eastmoney", limit=1)
        if topics:
            first = topics[0]
            return {
                "topic": topic,
                "content": first.get("content") or first.get("summary") or first.get("title") or "",
                "source": first.get("source", "unknown"),
                "url": first.get("url", ""),
            }
        return {
            "topic": topic,
            "content": "",
            "source": "unknown",
            "url": "",
        }

    source = _detect_source(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        return {
            "topic": topic,
            "content": "",
            "source": source,
            "url": url,
            "error": str(exc),
        }

    content = _extract_article_text(html, source)
    # 如果解析后正文过短，保留原始 HTML 文本作为兜底
    if len(content) < 60:
        raw_text = _strip_html(html)
        content = raw_text if len(raw_text) > len(content) else content

    return {
        "topic": topic,
        "content": content,
        "source": source,
        "url": url,
    }


async def search_finance_topics(
    keyword: str,
    source: str = "eastmoney",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """搜索财经相关主题

    当前实现为轻量版本：当目标站点返回可解析结果时返回列表，
    网络不可用或解析失败时优雅降级为空列表，避免阻塞下游流水线。

    Args:
        keyword: 搜索关键词
        source: 数据源 (eastmoney/xueqiu/ths)
        limit: 返回数量

    Returns:
        主题列表，每个元素至少包含 title / url / summary / source
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    if source == "eastmoney":
        return await _search_eastmoney(keyword, limit)
    if source == "xueqiu":
        return await _search_xueqiu(keyword, limit)
    if source == "ths":
        return await _search_ths(keyword, limit)
    return []


async def _search_eastmoney(keyword: str, limit: int) -> list[dict[str, Any]]:
    """东方财富搜索（基于搜索页面 HTML 的轻量解析）。"""
    try:
        from urllib.parse import quote

        url = f"https://so.eastmoney.com/web/s?keyword={quote(keyword)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text

        # 尝试从页面内嵌的 JSON 数据中提取文章列表
        results: list[dict[str, Any]] = []
        for match in re.finditer(
            r'["\']title["\']\s*:\s*["\'](.*?)["\'].*?["\']url["\']\s*:\s*["\'](.*?)["\']',
            text,
            re.IGNORECASE,
        ):
            title = match.group(1).encode("utf-8").decode("unicode_escape")
            link = match.group(2).encode("utf-8").decode("unicode_escape")
            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "summary": "",
                    "source": "eastmoney",
                })
            if len(results) >= limit:
                break

        return results[:limit]
    except Exception:
        return []


async def _search_xueqiu(keyword: str, limit: int) -> list[dict[str, Any]]:
    """雪球搜索（基于搜索页面 HTML 的轻量解析）。"""
    try:
        from urllib.parse import quote

        url = f"https://xueqiu.com/k?q={quote(keyword)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text

        results: list[dict[str, Any]] = []
        # 从页面中抓取文章标题与链接
        for match in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]{5,200})</a>', text):
            link = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if title and link:
                if link.startswith("/"):
                    link = f"https://xueqiu.com{link}"
                if "xueqiu.com" in link:
                    results.append({
                        "title": title,
                        "url": link,
                        "summary": "",
                        "source": "xueqiu",
                    })
            if len(results) >= limit:
                break

        return results[:limit]
    except Exception:
        return []


async def _search_ths(keyword: str, limit: int) -> list[dict[str, Any]]:
    """同花顺搜索（基于搜索页面 HTML 的轻量解析）。"""
    try:
        from urllib.parse import quote

        url = f"http://search.10jqka.com.cn/?tid=info&qs=stock&w={quote(keyword)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text

        results: list[dict[str, Any]] = []
        for match in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]{5,200})</a>', text):
            link = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if title and link:
                if link.startswith("/"):
                    link = f"http://search.10jqka.com.cn{link}"
                results.append({
                    "title": title,
                    "url": link,
                    "summary": "",
                    "source": "ths",
                })
            if len(results) >= limit:
                break

        return results[:limit]
    except Exception:
        return []
