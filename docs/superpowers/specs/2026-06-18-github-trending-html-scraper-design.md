# GitHub Trending HTML 抓取接入

## 背景

控制台当前通过 `src/console/github_hotlist.py` 调 GitHub Search API 拉取候选项目，搜索口径是
`created:>=N 天 stars:>10 archived:false`，按 stars 倒序。这本质上是「近期新建且高 star 的仓库
榜」，**不是 GitHub Trending（按日增 star 排序）**，导致榜单头部相对稳定、变化慢，每天看起
来「没变」。

## 目标

让 `collect_candidates_with_meta` 默认走 GitHub Trending 页面（HTML 抓取），拿到真实「日增
star」（`stars_today`），替换现有「估算日均 star」字段。Search API 路径降级为 Trending 抓取
失败时的 fallback。

## 关键决策（已对齐）

1. **数据源切换**：默认走 Trending HTML 抓取，Search API 降级 fallback。
2. **新字段处理**：`stars_today` 只加到 candidate dict 字段里（不展示），保持现有
   `daily_growth` 估算字段的行为不变。
3. **语言筛选**：支持常见语言筛选（`/trending/{language}?since={daily|weekly|monthly}`）。

## 设计

### 新增 `src/scraper/github_trending.py`

公开 API：

```python
async def fetch_trending_html(
    language: str | None = None,
    since: str = "daily",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """抓取 GitHub Trending 页面并解析。

    Returns: [
        {"full_name": "owner/name", "description": "...", "language": "Python",
         "stars_today": 123, "stars_period": "today", "repo_url": "https://..."},
        ...
    ]
    """
```

实现要点：
- `https://github.com/trending` 或 `https://github.com/trending/{language}`，query 为
  `?since={daily|weekly|monthly}`。
- 设置常见浏览器 User-Agent，避免被反爬。
- 使用 `re` 正则（不引入 bs4）解析 `article.Box-row` 块。
- 提取字段：
  - `full_name`: `href="/owner/name"`。
  - `description`: `p.col-9` 文本。
  - `language`: `span[itemprop="programmingLanguage"]`。
  - `stars_today`: 文本 `(\d+(?:,\d+)*) stars (today|this week|this month)`。
- 异常时（HTTP 4xx/5xx、解析不到 article）抛 `ValueError`，由调用方决定降级。

### 改造 `src/console/github_hotlist.py`

`collect_candidates_with_meta` 主流程调整：

1. **抓 trending HTML**（主路径），得到 `(full_name, description, language, stars_today)` 列表。
2. **用 GitHub `/repos/{full_name}` 批量补全元数据**（仅当前 N 个，N = `limit`），并发调用，
   拿到 `stargazers_count / forks_count / open_issues_count / created_at / updated_at / topics /
   homepage`。
3. **应用现有评分 / 过滤 / LLM 增强** 流程。
4. **在 candidate dict 里加 `stars_today`**（来自 trending）+ `data_source: "trending" | "search_api"`。
5. **抓取失败时降级** 到现有 Search API 路径，标记 `data_source: "search_api"` 并在 result
   metadata 里加 `data_source` 和 `degraded: true`。
6. 缓存 TTL 调整：trending 抓取 + 补全成本较高，daily=30min / weekly=2h / monthly=6h。
   cache key 加入 `language` 维度。
7. 补全 step 失败（非致命）时仍返回 trending 拿到的子集，缺失字段填空字符串。

签名扩展：
```python
async def collect_candidates_with_meta(
    time_window: str,
    token: str = "",
    limit: int = 30,
    force_refresh: bool = True,
    enrich_with_llm: bool = True,
    llm_limit: int = 10,
    language: str | None = None,         # NEW
) -> dict[str, Any]:
```

`result` 新增字段：
- `data_source: "trending" | "search_api"`
- `degraded: bool`（trending 抓取失败但 fallback 成功时为 True）
- `degraded_reason: str`（失败原因）

### 前端

**不动**。新字段是后向兼容的（前端忽略未知字段），符合"保持现状，只在 metadata 里加字段"。

### 错误处理

| 场景 | 行为 |
|---|---|
| Trending 抓取网络错误 | fallback 到 Search API，标记 `degraded=True` |
| Trending 解析失败（无 article） | 同上 |
| 补全 API 401/403 | 降级时不再补全，trending 字段照常返回 |
| 补全 API 429（限流） | 已补全的正常返回，剩余的留空 |
| LLM 增强失败 | 走关键词 fallback（已有） |

### 缓存

```python
# src/console/github_hotlist.py
CACHE_TTL_SECONDS = {
    "daily": 30 * 60,        # 30 分钟（trending 抓取成本高）
    "weekly": 2 * 60 * 60,   # 2 小时
    "monthly": 6 * 60 * 60,  # 6 小时
}
CACHE_SCHEMA_VERSION = 6  # bump
```

cache key 加入 `language`。

### 测试

- `tests/test_github_trending.py`：
  - mock HTML 解析：验证 stars_today / language / description 抽取正确。
  - HTTP 错误抛 `ValueError`。
  - 各 `since` 参数对应文案（today / this week / this month）。
- `tests/test_github_hotlist.py`：
  - trending 抓取成功：result `data_source="trending"`，candidate 包含 `stars_today`。
  - trending 抓取失败：fallback 到 Search API，`degraded=True`。
  - 缓存命中：trending 路径不发起 HTTP。
  - 补全 API 失败：trending 字段照常返回，元数据留空。

### 兼容性 / 迁移

- `CACHE_SCHEMA_VERSION` 5 → 6，旧缓存自动失效。
- candidate dict 是**扩展**（新增字段），不是破坏性变更。
- 现有调用方（`jobs.py` / `hotlist_v2/render.py`）不需改。
- `read_github_token` 已在 `jobs.py` 用，trending 补全复用。
