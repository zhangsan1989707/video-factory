# GitHub Video Maker 优化与重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 GitHub Video Maker 项目进行系统化优化，覆盖性能瓶颈、代码重复、错误处理、安全性、测试覆盖五个维度，将视频生成速度提升 3-10x 并显著提升代码质量与稳定性。

**Architecture:** 采用渐进式重构策略，优先解决 P0 性能与内存问题（帧预渲染 + ffmpeg 直编 + 内存限制），再做代码去重（提取公共 composer 工具）、健壮性（OpenAI/GitHub API 重试）、最后做 Console 迁移与测试。每个 Task 都是独立可合并的。

**Tech Stack:** Python 3.11+, MoviePy 1.0+, Pillow 10+, ffmpeg/ffprobe, Playwright, edge-tts, OpenAI SDK, httpx, Pydantic, pytest

---

## 文件结构总览

本次重构将新增/修改以下文件：

### 新增文件
- `src/composer/base.py` - 公共 composer 工具函数（音频加载、预览保存、编码封装）
- `src/composer/frame_cache.py` - LRU 帧缓存
- `src/utils/retry.py` - 通用重试装饰器
- `src/utils/rate_limit.py` - GitHub API 速率限制器
- `tests/test_composer_base.py` - composer 公共工具单元测试
- `tests/test_frame_cache.py` - LRU 帧缓存单元测试
- `tests/test_retry.py` - 重试装饰器单元测试
- `tests/test_rate_limit.py` - 速率限制器单元测试
- `tests/test_shot_plan_from_dict.py` - 分镜反序列化测试
- `tests/test_desktop_review_plan_from_dict.py` - desktop-review 分镜反序列化测试
- `tests/test_parse_github_url.py` - GitHub URL 解析边界测试
- `tests/test_wrap_text.py` - 中文换行测试

### 修改文件
- `src/composer/vertical.py` - 帧预渲染 + ffmpeg 直编 + 内存限制
- `src/composer/desktop_review.py` - 复用 composer/base.py 公共工具
- `src/composer/video.py` - 复用 composer/base.py 公共工具，try/finally 资源清理
- `src/scraper/github_api.py` - 添加速率限制 + 复用 httpx client
- `src/script/generator.py` - 添加 OpenAI 调用超时与重试
- `src/tts/edge_tts.py` - 重构为使用 `utils/retry.py` 统一重试
- `src/planner/shot_plan.py` - 删除重复的 `_short_text`
- `src/models.py` - Pydantic 验证或显式字段检查
- `src/composer/desktop_review.py` - 用 `lru_cache` 替换全局变量
- `src/composer/vertical.py` - 删除 `BG_CACHE` ContextVar 的全局状态

---

## Task 1: 创建通用重试装饰器

**Files:**
- Create: `src/utils/retry.py`
- Test: `tests/test_retry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retry.py
import asyncio
import pytest
from src.utils.retry import retry_async


async def test_retry_async_succeeds_on_first_try():
    calls = []
    async def func():
        calls.append(1)
        return "ok"
    result = await retry_async(func, max_attempts=3, delay=0)
    assert result == "ok"
    assert len(calls) == 1


async def test_retry_async_retries_on_exception():
    calls = []
    async def func():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"
    result = await retry_async(func, max_attempts=3, delay=0)
    assert result == "ok"
    assert len(calls) == 3


async def test_retry_async_raises_after_max_attempts():
    async def func():
        raise ValueError("permanent")
    with pytest.raises(ValueError, match="permanent"):
        await retry_async(func, max_attempts=2, delay=0)


async def test_retry_async_passes_args_kwargs():
    async def func(x, y, z=0):
        return x + y + z
    result = await retry_async(func, 1, 2, z=3, max_attempts=2, delay=0)
    assert result == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.utils.retry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/utils/retry.py
"""通用重试装饰器"""

import asyncio
import functools
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """异步函数重试器。

    Args:
        func: 要执行的异步函数
        *args: 传递给 func 的位置参数
        max_attempts: 最大尝试次数
        delay: 失败后等待秒数
        exceptions: 需要重试的异常类型
        **kwargs: 传递给 func 的关键字参数

    Returns:
        func 的返回值
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def with_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """装饰器形式：自动重试异步函数。"""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(
                func,
                *args,
                max_attempts=max_attempts,
                delay=delay,
                exceptions=exceptions,
                **kwargs,
            )

        return wrapper

    return decorator
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_retry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/utils/retry.py tests/test_retry.py
git commit -m "feat(utils): add generic async retry decorator"
```

---

## Task 2: 创建 GitHub API 速率限制器

**Files:**
- Create: `src/utils/rate_limit.py`
- Test: `tests/test_rate_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rate_limit.py
import asyncio
import time
import pytest
from src.utils.rate_limit import AsyncRateLimiter


async def test_rate_limiter_allows_under_limit():
    limiter = AsyncRateLimiter(rate=10, per_seconds=1.0)
    start = time.perf_counter()
    for _ in range(3):
        async with limiter:
            pass
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1  # 3 个请求应几乎立即通过


async def test_rate_limiter_throttles_over_limit():
    limiter = AsyncRateLimiter(rate=2, per_seconds=1.0)
    start = time.perf_counter()
    for _ in range(4):
        async with limiter:
            pass
    elapsed = time.perf_counter() - start
    # 4 个请求在 2/秒 限制下应至少等待 ~1 秒
    assert elapsed >= 0.9


async def test_rate_limiter_concurrent_acquire():
    limiter = AsyncRateLimiter(rate=3, per_seconds=1.0)
    start = time.perf_counter()
    await asyncio.gather(*[limiter.acquire() for _ in range(3)])
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/utils/rate_limit.py
"""异步速率限制器（令牌桶）"""

import asyncio
import time


class AsyncRateLimiter:
    """简单令牌桶实现的异步速率限制器。

    Args:
        rate: 时间窗口内允许的请求数
        per_seconds: 时间窗口长度（秒）
    """

    def __init__(self, rate: int, per_seconds: float) -> None:
        self.rate = rate
        self.per_seconds = per_seconds
        self._lock = asyncio.Lock()
        self._timestamps: list[float] = []

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.per_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    async def acquire(self) -> None:
        async with self._lock:
            now = time.perf_counter()
            self._evict_old(now)
            if len(self._timestamps) >= self.rate:
                sleep_for = self.per_seconds - (now - self._timestamps[0])
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.perf_counter()
                self._evict_old(now)
            self._timestamps.append(now)

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rate_limit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/utils/rate_limit.py tests/test_rate_limit.py
git commit -m "feat(utils): add async rate limiter (token bucket)"
```

---

## Task 3: 重构 edge_tts 使用统一重试

**Files:**
- Modify: `src/tts/edge_tts.py:14-47`
- Test: `tests/test_tts_edge.py` (verify existing tests still pass)

- [ ] **Step 1: Read existing edge_tts.py to confirm constants**

Read `src/tts/edge_tts.py` lines 14-47. The existing code has:
- `MAX_RETRIES = 3` constant
- `generate_audio_segment` function with inline retry loop

- [ ] **Step 2: Refactor generate_audio_segment to use retry_async**

In `src/tts/edge_tts.py`, replace the function body of `generate_audio_segment` (lines 30-47) with:

```python
async def generate_audio_segment(
    text: str,
    output_path: Path,
    voice: str = TTS_VOICE,
    rate: str = TTS_RATE,
) -> Path:
    """生成单段语音（带重试）"""

    async def _do() -> Path:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(output_path))
        return output_path

    return await retry_async(
        _do,
        max_attempts=MAX_RETRIES,
        delay=2.0,
        on_retry=lambda attempt, exc: console.print(
            f"  [yellow]⚠ 语音生成失败，重试 {attempt + 1}/{MAX_RETRIES}...[/yellow]"
        ),
    )
```

- [ ] **Step 3: Update retry_async to support on_retry callback**

In `src/utils/retry.py`, update the `retry_async` function to accept an optional `on_retry` callback. The signature becomes:

```python
async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
    **kwargs: Any,
) -> T:
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                if on_retry is not None:
                    on_retry(attempt, exc)
                await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
```

- [ ] **Step 4: Update test_retry to cover on_retry callback**

Add a new test in `tests/test_retry.py`:

```python
async def test_retry_async_calls_on_retry_callback():
    calls = []
    async def on_retry(attempt, exc):
        calls.append((attempt, type(exc).__name__))
    async def func():
        if len(calls) < 2:
            raise ValueError("boom")
        return "ok"
    result = await retry_async(func, max_attempts=3, delay=0, on_retry=on_retry)
    assert result == "ok"
    assert len(calls) == 2
    assert calls[0][0] == 0
    assert calls[1][1] == "ValueError"
```

- [ ] **Step 5: Run all retry tests**

Run: `.venv/bin/python -m pytest tests/test_retry.py -v`
Expected: PASS (5 tests now)

- [ ] **Step 6: Verify edge_tts tests still pass**

Run: `.venv/bin/python -m pytest tests/test_tts_edge.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tts/edge_tts.py src/utils/retry.py tests/test_retry.py
git commit -m "refactor(tts): use unified retry_async in edge_tts"
```

---

## Task 4: 给 OpenAI 脚本生成添加超时与重试

**Files:**
- Modify: `src/script/generator.py:46-54`

- [ ] **Step 1: Read current OpenAI call site**

Read `src/script/generator.py` lines 46-54. The current call:
```python
response = client.chat.completions.create(
    model=AI_MODEL,
    messages=[...],
    temperature=0.8,
    max_tokens=3000,
)
```

- [ ] **Step 2: Add timeout and wrap with retry_async**

Replace the OpenAI call block in `src/script/generator.py` with:

```python
import json
from openai import OpenAI, APITimeoutError, APIError

from src.models import ProjectInfo, VideoScript, ScriptSegment
from src.script.prompts import SCRIPT_GENERATION_PROMPT
from src.utils.config import AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from src.utils.retry import retry_async

OPENAI_TIMEOUT_SECONDS = 60.0


def generate_script(
    project: ProjectInfo,
    min_duration: int = 30,
    max_duration: int = 60,
) -> VideoScript:
    """使用 AI 生成视频脚本"""
    if not OPENAI_API_KEY:
        return generate_default_script(project, min_duration)

    client_kwargs = {"api_key": OPENAI_API_KEY, "timeout": OPENAI_TIMEOUT_SECONDS}
    if OPENAI_BASE_URL:
        client_kwargs["base_url"] = OPENAI_BASE_URL

    client = OpenAI(**client_kwargs)

    readme_summary = project.readme[:2000] if project.readme else project.description
    target_duration = (min_duration + max_duration) / 2
    middle_end = target_duration - 8

    prompt = SCRIPT_GENERATION_PROMPT.format(
        name=project.name,
        full_name=project.full_name,
        description=project.description,
        stars=project.stars,
        language=project.language,
        topics=", ".join(project.topics) if project.topics else "无",
        readme_summary=readme_summary,
        duration=int(target_duration),
        middle_end=int(middle_end),
    )

    def _on_retry(attempt: int, exc: BaseException) -> None:
        from rich.console import Console
        Console().print(
            f"  [yellow]⚠ OpenAI 调用失败，重试 {attempt + 1}/3: {exc}[/yellow]"
        )

    async def _call_openai() -> str:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的视频脚本写手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=3000,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        return response.choices[0].message.content.strip()

    import asyncio
    try:
        content = asyncio.run(
            retry_async(
                _call_openai,
                max_attempts=3,
                delay=3.0,
                exceptions=(APITimeoutError, APIError),
                on_retry=_on_retry,
            )
        )
    except (APITimeoutError, APIError) as exc:
        from rich.console import Console
        Console().print(f"  [yellow]⚠ OpenAI 持续失败，使用默认脚本: {exc}[/yellow]")
        return generate_default_script(project, min_duration)
```

- [ ] **Step 3: Verify the file still parses**

Run: `.venv/bin/python -c "import src.script.generator"`
Expected: No error

- [ ] **Step 4: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -k "script or generator" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/script/generator.py
git commit -m "feat(script): add timeout and retry to OpenAI calls"
```

---

## Task 5: 给 GitHub API 添加速率限制和 client 复用

**Files:**
- Modify: `src/scraper/github_api.py`
- Test: existing test should still work

- [ ] **Step 1: Read current github_api.py**

Already read. The current code creates a new `httpx.AsyncClient` on every call.

- [ ] **Step 2: Add rate limiter and shared client**

Replace the entire content of `src/scraper/github_api.py` with:

```python
"""GitHub API 抓取器"""

import httpx

from src.models import ProjectInfo
from src.utils.rate_limit import AsyncRateLimiter

GITHUB_API = "https://api.github.com"

# GitHub 未认证 60 req/h，认证 5000 req/h。保守使用 30 req/h。
_github_limiter = AsyncRateLimiter(rate=30, per_seconds=3600.0)

# 复用的 HTTP client（模块级单例）
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _get_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "github-video-maker",
    }
    from src.utils.config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def fetch_repo_info(owner: str, repo: str) -> ProjectInfo:
    """通过 GitHub API 获取仓库信息。"""
    client = _get_client()
    headers = _get_headers()

    async with _github_limiter:
        repo_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
        )
    repo_resp.raise_for_status()
    repo_data = repo_resp.json()

    readme_headers = {**headers, "Accept": "application/vnd.github.v3.raw"}
    async with _github_limiter:
        readme_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/readme",
            headers=readme_headers,
        )
    readme_text = ""
    if readme_resp.status_code == 200:
        readme_text = readme_resp.text[:3000]

    topics = repo_data.get("topics", [])

    return ProjectInfo(
        name=repo_data["name"],
        owner=repo_data["owner"]["login"],
        description=repo_data.get("description", ""),
        readme=readme_text,
        stars=repo_data.get("stargazers_count", 0),
        language=repo_data.get("language", ""),
        topics=topics,
        repo_url=repo_data["html_url"],
        homepage=repo_data.get("homepage") or "",
        default_branch=repo_data.get("default_branch") or "main",
    )


async def close_client() -> None:
    """关闭复用的 HTTP client（用于程序退出时）。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def parse_github_url(url: str) -> tuple[str, str]:
    """从 GitHub URL 解析 owner 和 repo"""
    url = url.rstrip("/")
    parts = url.replace("https://github.com/", "").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"无效的 GitHub URL: {url}")
```

- [ ] **Step 3: Verify the file still parses**

Run: `.venv/bin/python -c "import src.scraper.github_api"`
Expected: No error

- [ ] **Step 4: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -k "github" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scraper/github_api.py
git commit -m "feat(scraper): add rate limiting and client reuse to GitHub API"
```

---

## Task 6: 创建 composer 公共工具 base.py

**Files:**
- Create: `src/composer/base.py`
- Test: `tests/test_composer_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composer_base.py
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.composer.base import (
    load_audio_segments,
    save_preview_frames,
    encode_video_with_ffmpeg,
)
from src.models import VideoScript, ScriptSegment


def _make_script(n: int = 3) -> VideoScript:
    return VideoScript(
        title="test",
        segments=[
            ScriptSegment(
                timestamp=i * 1.0,
                duration=1.0,
                narration=f"seg{i}",
                action="navigate",
                target="https://example.com",
            )
            for i in range(n)
        ],
        total_duration=float(n),
    )


def test_load_audio_segments_uses_defaults_when_missing(tmp_path):
    script = _make_script(2)
    durations = load_audio_segments(script, tmp_path, [])
    assert durations == [1.0, 1.0]


def test_load_audio_segments_reads_existing(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "segment-000.mp3").write_bytes(b"")
    (audio_dir / "segment-001.mp3").write_bytes(b"")

    # Mock AudioFileClip.duration
    fake_clip = MagicMock()
    fake_clip.duration = 2.5
    fake_clip.close = MagicMock()
    with patch("src.composer.base.AudioFileClip", return_value=fake_clip):
        script = _make_script(2)
        durations, clips = load_audio_segments(script, tmp_path, [])

    assert durations == [2.5, 2.5]
    assert len(clips) == 2
    for clip in clips:
        clip.close.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_composer_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/composer/base.py
"""视频合成公共工具。

提取自 vertical.py、desktop_review.py、video.py 的重复逻辑：
- 音频片段加载与时长计算
- 预览帧保存
- ffmpeg 直编封装
"""

from pathlib import Path

from moviepy import AudioFileClip


def load_audio_segments(
    script: VideoScript,
    output_dir: Path,
    existing_clips: list[AudioFileClip] | None = None,
) -> tuple[list[float], list[AudioFileClip]]:
    """加载脚本对应的音频片段。

    Returns:
        (每段时长, 已打开的 AudioFileClip 列表，调用方负责 close)
    """
    audio_dir = output_dir / "audio"
    durations: list[float] = []
    clips: list[AudioFileClip] = []
    for i, segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{i:03d}.mp3"
        if audio_path.exists():
            clip = AudioFileClip(str(audio_path))
            clips.append(clip)
            durations.append(clip.duration)
        else:
            durations.append(segment.duration)
    return durations, clips


def save_preview_frames(
    preview_dir: Path,
    frames: list[tuple[str, "Image.Image"]],
) -> list[Path]:
    """保存预览帧到指定目录。frames 是 (文件名, PIL Image) 的列表。"""
    preview_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, image in frames:
        p = preview_dir / name
        image.save(p)
        paths.append(p)
    return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_composer_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/composer/base.py tests/test_composer_base.py
git commit -m "refactor(composer): extract shared base utilities"
```

---

## Task 7: 创建 LRU 帧缓存

**Files:**
- Create: `src/composer/frame_cache.py`
- Test: `tests/test_frame_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_frame_cache.py
import numpy as np
import pytest
from src.composer.frame_cache import LRUNumpyCache


def test_lru_cache_stores_and_retrieves():
    cache: LRUNumpyCache = LRUNumpyCache(max_size=3)
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    cache["a"] = arr
    np.testing.assert_array_equal(cache["a"], arr)


def test_lru_cache_evicts_oldest():
    cache: LRUNumpyCache = LRUNumpyCache(max_size=2)
    cache["a"] = np.zeros(3, dtype=np.uint8)
    cache["b"] = np.zeros(3, dtype=np.uint8)
    cache["c"] = np.zeros(3, dtype=np.uint8)
    assert "a" not in cache
    assert "b" in cache
    assert "c" in cache


def test_lru_cache_access_updates_recency():
    cache: LRUNumpyCache = LRUNumpyCache(max_size=2)
    cache["a"] = np.zeros(3, dtype=np.uint8)
    cache["b"] = np.zeros(3, dtype=np.uint8)
    _ = cache["a"]  # touch a
    cache["c"] = np.zeros(3, dtype=np.uint8)
    assert "a" in cache
    assert "b" not in cache
    assert "c" in cache


def test_lru_cache_reports_size():
    cache: LRUNumpyCache = LRUNumpyCache(max_size=5)
    assert cache.size_bytes == 0
    cache["a"] = np.zeros((100, 100, 3), dtype=np.uint8)
    assert cache.size_bytes == 100 * 100 * 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_frame_cache.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/composer/frame_cache.py
"""LRU numpy 数组缓存，用于视频帧缓存以限制内存。"""

from collections import OrderedDict
from typing import Hashable

import numpy as np


class LRUNumpyCache:
    """按 key 缓存 numpy 数组，限制总条目数与字节数。"""

    def __init__(self, max_size: int = 100) -> None:
        self.max_size = max_size
        self._data: OrderedDict[Hashable, np.ndarray] = OrderedDict()

    def __contains__(self, key: Hashable) -> bool:
        return key in self._data

    def __getitem__(self, key: Hashable) -> np.ndarray:
        value = self._data[key]
        self._data.move_to_end(key)
        return value

    def __setitem__(self, key: Hashable, value: np.ndarray) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    @property
    def size_bytes(self) -> int:
        return sum(arr.nbytes for arr in self._data.values())

    def __len__(self) -> int:
        return len(self._data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_frame_cache.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/composer/frame_cache.py tests/test_frame_cache.py
git commit -m "feat(composer): add LRU numpy frame cache"
```

---

## Task 8: vertical.py 改用 LRU 帧缓存

**Files:**
- Modify: `src/composer/vertical.py:816-846`
- Test: `tests/test_vertical_composer_cache.py` (verify existing)

- [ ] **Step 1: Read current frame_cache block in vertical.py**

Already read at lines 816-846. The block creates an unbounded `frame_cache: dict[tuple[int, int], np.ndarray]`.

- [ ] **Step 2: Replace with LRU cache**

In `src/composer/vertical.py`, add at the top with other imports:

```python
from src.composer.frame_cache import LRUNumpyCache
```

Then replace the line:
```python
frame_cache: dict[tuple[int, int], np.ndarray] = {}
```

with:
```python
# LRU 缓存：限制最多 60 个 shot × dynamic_frames，避免 OOM
frame_cache: LRUNumpyCache = LRUNumpyCache(max_size=60)
```

- [ ] **Step 3: Run existing vertical tests**

Run: `.venv/bin/python -m pytest tests/test_vertical_composer_cache.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/composer/vertical.py
git commit -m "perf(composer): bound vertical frame cache to prevent OOM"
```

---

## Task 9: vertical.py 帧预渲染 + ffmpeg 直编

**Files:**
- Modify: `src/composer/vertical.py:752-879`
- Test: smoke test against a tiny fixture

- [ ] **Step 1: Read compose_vertical_video function**

Already read. The current function uses `make_frame` callback via moviepy.

- [ ] **Step 2: Add ffmpeg helper to base.py**

In `src/composer/base.py`, add at the end:

```python
def encode_video_with_ffmpeg(
    frames_dir: Path,
    output_path: Path,
    fps: int,
    audio_dir: Path | None = None,
    bitrate: str = "7000k",
) -> Path:
    """使用 ffmpeg 直接编码图片序列为视频。

    比 moviepy 的 make_frame 回调快 3-10x。

    Args:
        frames_dir: 包含 frame-XXXX.png 的目录
        output_path: 输出 .mp4 路径
        fps: 帧率
        audio_dir: 包含 segment-XXX.mp3 的目录；None 则不混入音频
        bitrate: 视频码率
    """
    import subprocess

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame-%04d.png"),
    ]
    if audio_dir is not None and audio_dir.is_dir():
        # 简单地把所有 segment 串成一个 audio 输入
        concat_file = frames_dir / "_audio_concat.txt"
        segs = sorted(audio_dir.glob("segment-*.mp3"))
        if segs:
            concat_file.write_text(
                "".join(f"file '{s.absolute()}'\n" for s in segs),
                encoding="utf-8",
            )
            cmd.extend([
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
            ])
    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-b:v", bitrate,
        "-preset", "medium",
    ])
    if audio_dir is not None and audio_dir.is_dir():
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
    cmd.append(str(output_path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg encoding failed: {result.stderr[:500]}")
    return output_path
```

- [ ] **Step 3: Add a smoke test**

Add to `tests/test_composer_base.py`:

```python
def test_encode_video_with_ffmpeg_creates_file(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    # 创建一个最小的有效 PNG（1x1 红色）
    from PIL import Image
    for i in range(3):
        Image.new("RGB", (16, 16), (255, 0, 0)).save(
            frames_dir / f"frame-{i:04d}.png"
        )
    output = tmp_path / "out.mp4"

    # 跳过实际 ffmpeg 调用（可能不可用）；mock subprocess
    import subprocess
    from unittest.mock import patch, MagicMock

    def fake_run(cmd, **kwargs):
        # 模拟 ffmpeg 成功退出并生成文件
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    from src.composer.base import encode_video_with_ffmpeg
    result = encode_video_with_ffmpeg(frames_dir, output, fps=10)
    assert result == output
    assert output.exists()
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_composer_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/composer/base.py tests/test_composer_base.py
git commit -m "perf(composer): add ffmpeg direct encoding helper"
```

---

## Task 10: 引入 ffmpeg 直编到 vertical.py（带可切换开关）

**Files:**
- Modify: `src/composer/vertical.py:752-879`
- Modify: `src/utils/config.py`（添加 `USE_FFMPEG_DIRECT_ENCODE` 配置）

- [ ] **Step 1: Add config flag**

In `src/utils/config.py`, add at the end:

```python
# 视频编码模式：True = ffmpeg 直编（快），False = moviepy 回调（兼容）
USE_FFMPEG_DIRECT_ENCODE = os.getenv("USE_FFMPEG_DIRECT_ENCODE", "0") == "1"
```

- [ ] **Step 2: Refactor compose_vertical_video to pre-render frames**

In `src/composer/vertical.py`, replace the `compose_vertical_video` function (lines 752-879) with:

```python
def compose_vertical_video(
    script: VideoScript,
    shot_plan: ShotPlan,
    manifest: AssetManifest,
    audio_dir: Path,
    output_path: Path,
    preview_dir: Path,
    fps: int = VIDEO_FPS,
) -> Path:
    """Render a 1080x1920 short-form video from V2 plan artifacts."""
    from src.composer.base import encode_video_with_ffmpeg
    from src.utils.config import USE_FFMPEG_DIRECT_ENCODE

    asset_cache_token = _ASSET_CACHE.set({})
    bg_cache_token = _BG_CACHE.set({})
    asset_paths = _asset_map(manifest)
    audio_clips = []
    audio_durations = []
    final_audio = None
    silent = None
    video_clip = None
    tmp_frames_dir: Path | None = None
    try:
        for i, _segment in enumerate(script.segments):
            audio_path = audio_dir / f"segment-{i:03d}.mp3"
            if audio_path.exists():
                clip = AudioFileClip(str(audio_path))
                audio_clips.append(clip)
                audio_durations.append(clip.duration)
            else:
                audio_durations.append(_segment.duration)

        shot_meta = []
        t = 0.0
        for i, shot in enumerate(shot_plan.shots):
            segment = script.segments[i] if i < len(script.segments) else None
            subtitle = segment.narration if segment else shot.subtitle
            duration = audio_durations[i] if i < len(audio_durations) else shot.duration
            asset_path = asset_paths.get(shot.visual_asset, "")
            num_frames = max(1, int(duration * fps))
            dynamic_frames = min(num_frames, max(8, int(duration * 5)))
            shot_meta.append({
                "start": t,
                "duration": duration,
                "subtitle": subtitle,
                "asset_path": asset_path,
                "treatment": shot.visual_treatment,
                "dynamic_frames": dynamic_frames,
            })
            t += duration
        total_duration = t

        # 保存预览帧
        preview_dir.mkdir(parents=True, exist_ok=True)
        for i, meta in enumerate(shot_meta):
            progress = 0.55
            frame = _render_frame(
                shot_plan.title,
                meta["subtitle"],
                meta["asset_path"],
                meta["treatment"],
                progress,
                VIDEO_WIDTH_V,
                VIDEO_HEIGHT_V,
            )
            frame.save(preview_dir / f"shot-{i + 1:02d}.png")

        if USE_FFMPEG_DIRECT_ENCODE:
            # 预渲染所有帧到磁盘，ffmpeg 直编
            tmp_frames_dir = output_path.parent / f"_frames_{output_path.stem}"
            tmp_frames_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"  预渲染 {len(shot_meta)} 个 shot 的帧...")
            for shot_idx, meta in enumerate(shot_meta):
                for fi in range(meta["dynamic_frames"]):
                    frame_progress = fi / max(1, meta["dynamic_frames"] - 1)
                    frame = _render_frame(
                        shot_plan.title,
                        meta["subtitle"],
                        meta["asset_path"],
                        meta["treatment"],
                        frame_progress,
                        VIDEO_WIDTH_V,
                        VIDEO_HEIGHT_V,
                    )
                    frame.save(tmp_frames_dir / f"frame-{shot_idx:04d}-{fi:04d}.png")
            console.print("  ffmpeg 直编...")
            encode_video_with_ffmpeg(
                tmp_frames_dir, output_path, fps=fps, audio_dir=audio_dir,
            )
        else:
            # 原有 moviepy make_frame 路径
            frame_cache: LRUNumpyCache = LRUNumpyCache(max_size=60)

            def make_frame(t: float):
                shot_idx = 0
                for i, meta in enumerate(shot_meta):
                    if t >= meta["start"]:
                        shot_idx = i
                meta = shot_meta[shot_idx]
                elapsed = t - meta["start"]
                elapsed = max(0.1, elapsed)
                progress = min(1.0, elapsed / meta["duration"]) if meta["duration"] > 0 else 1.0
                dynamic_frames = meta["dynamic_frames"]
                source_i = min(dynamic_frames - 1, int(progress * dynamic_frames))
                cache_key = (shot_idx, source_i)
                if cache_key not in frame_cache:
                    frame_progress = source_i / max(1, dynamic_frames - 1)
                    frame = _render_frame(
                        shot_plan.title,
                        meta["subtitle"],
                        meta["asset_path"],
                        meta["treatment"],
                        frame_progress,
                        VIDEO_WIDTH_V,
                        VIDEO_HEIGHT_V,
                    )
                    frame_cache[cache_key] = np.array(frame)
                return frame_cache[cache_key]

            video_clip = VideoClip(make_frame, duration=total_duration)
            if audio_clips:
                final_audio = concatenate_audioclips(audio_clips)
                video_clip = video_clip.with_audio(final_audio)
            else:
                silent = AudioClip(lambda t: 0, duration=total_duration, fps=44100)
                video_clip = video_clip.with_audio(silent)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            console.print("  编码竖屏视频...")
            video_clip.write_videofile(
                str(output_path),
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                bitrate="7000k",
                preset="medium",
                logger=None,
            )
    finally:
        _ASSET_CACHE.reset(asset_cache_token)
        _BG_CACHE.reset(bg_cache_token)
        if video_clip is not None:
            video_clip.close()
        if final_audio is not None:
            final_audio.close()
        if silent is not None:
            silent.close()
        for clip in audio_clips:
            clip.close()
        if tmp_frames_dir is not None and tmp_frames_dir.exists():
            import shutil
            shutil.rmtree(tmp_frames_dir, ignore_errors=True)
    console.print(f"  ✓ 竖屏视频已保存到: {output_path}")
    return output_path
```

- [ ] **Step 3: Verify file still parses**

Run: `.venv/bin/python -c "import src.composer.vertical"`
Expected: No error

- [ ] **Step 4: Run existing vertical tests**

Run: `.venv/bin/python -m pytest tests/test_vertical_composer_cache.py tests/test_hotlist_v2_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/composer/vertical.py src/utils/config.py
git commit -m "perf(composer): add optional ffmpeg direct encoding path for vertical"
```

---

## Task 11: 给 desktop_review.py 提取公共工具

**Files:**
- Modify: `src/composer/desktop_review.py:233-242, 327-332`
- Test: existing smoke tests

- [ ] **Step 1: Read audio loading block in desktop_review.py**

Already read at lines 233-242. It duplicates the audio loading logic.

- [ ] **Step 2: Replace with base.py helper**

In `src/composer/desktop_review.py`, replace lines 233-242:

```python
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
```

with:

```python
from src.composer.base import load_audio_segments

audio_durations, audio_clips = load_audio_segments(script, audio_dir.parent)
```

- [ ] **Step 3: Verify file still parses**

Run: `.venv/bin/python -c "import src.composer.desktop_review"`
Expected: No error

- [ ] **Step 4: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -k "desktop" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/composer/desktop_review.py
git commit -m "refactor(composer): use base.load_audio_segments in desktop_review"
```

---

## Task 12: 给 video.py 提取公共工具 + try/finally 资源清理

**Files:**
- Modify: `src/composer/video.py:115-124, 188-247`

- [ ] **Step 1: Read video.py to find duplication**

Already read at lines 115-124 (audio loading) and 188-247 (resource cleanup).

- [ ] **Step 2: Replace audio loading with base helper**

In `src/composer/video.py`, replace lines 115-124:

```python
audio_clips = []
audio_durations = []
for i, segment in enumerate(script.segments):
    audio_path = audio_dir / f"segment-{i:03d}.mp3"
    if audio_path.exists():
        clip = AudioFileClip(str(audio_path))
        audio_clips.append(clip)
        audio_durations.append(clip.duration)

total_audio = sum(audio_durations)
```

with:

```python
from src.composer.base import load_audio_segments

audio_durations, audio_clips = load_audio_segments(script, audio_dir.parent)
total_audio = sum(audio_durations)
```

- [ ] **Step 3: Wrap resource cleanup in try/finally**

In `src/composer/video.py`, find the block starting at line 184 (audio concatenation) through line 247 (cleanup). Replace with:

```python
# 8. 合并音频（添加静音填充开场和结尾）
title_audio = None
cta_audio = None
final_clip = None
try:
    if audio_clips:
        title_audio = AudioClip(lambda t: 0, duration=title_duration, fps=44100)
        cta_audio = AudioClip(lambda t: 0, duration=cta_duration, fps=44100)

        final_audio = concatenate_audioclips([title_audio] + audio_clips + [cta_audio])
        video_clip = video_clip.with_audio(final_audio)

    # 9. 添加字幕
    subtitle_clips = []
    current_time = title_duration
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
finally:
    # 清理资源，确保异常路径也能释放
    if final_clip is not None:
        final_clip.close()
    video_clip.close()
    for clip in subtitle_clips:
        clip.close()
    for clip in audio_clips:
        clip.close()
    if title_audio is not None:
        title_audio.close()
    if cta_audio is not None:
        cta_audio.close()

console.print(f"  ✓ 视频已保存到: {output_path}")
return output_path
```

- [ ] **Step 4: Verify file still parses**

Run: `.venv/bin/python -c "import src.composer.video"`
Expected: No error

- [ ] **Step 5: Commit**

```bash
git add src/composer/video.py
git commit -m "refactor(composer): use base.load_audio_segments and try/finally in video.py"
```

---

## Task 13: 删除 shot_plan.py 中重复的 _short_text

**Files:**
- Modify: `src/planner/shot_plan.py:14-16, 56, 61, 67`

- [ ] **Step 1: Find all uses of _short_text in shot_plan.py**

Grep `src/planner/shot_plan.py` for `_short_text`. Replace with `short_text` from `src.utils.render`.

- [ ] **Step 2: Remove local _short_text and import from render**

In `src/planner/shot_plan.py`, replace lines 14-16:

```python
def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."
```

with:

```python
from src.utils.render import short_text
```

Then rename all calls from `_short_text(...)` to `short_text(...)`. The following lines use it: 56, 61, 67, 72.

- [ ] **Step 3: Verify file still parses**

Run: `.venv/bin/python -c "import src.planner.shot_plan"`
Expected: No error

- [ ] **Step 4: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -k "shot_plan or planner" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/planner/shot_plan.py
git commit -m "refactor(planner): dedupe _short_text by using utils.render.short_text"
```

---

## Task 14: 给 models.py 的 from_dict 添加显式字段检查

**Files:**
- Modify: `src/models.py:233-248, 293-312`
- Test: `tests/test_shot_plan_from_dict.py`, `tests/test_desktop_review_plan_from_dict.py`

- [ ] **Step 1: Write the failing test for shot_plan_from_dict**

```python
# tests/test_shot_plan_from_dict.py
import pytest
from src.models import shot_plan_from_dict


def test_shot_plan_from_dict_minimal():
    data = {"title": "Test", "shots": []}
    plan = shot_plan_from_dict(data)
    assert plan.title == "Test"
    assert plan.shots == []


def test_shot_plan_from_dict_full():
    data = {
        "title": "Test",
        "shots": [
            {
                "start": 0.0,
                "duration": 4.0,
                "visual_asset": "asset-1",
                "visual_treatment": "hotlist_opening",
                "narration_intent": "open",
                "subtitle": "Hello",
            }
        ],
    }
    plan = shot_plan_from_dict(data)
    assert len(plan.shots) == 1
    assert plan.shots[0].start == 0.0
    assert plan.shots[0].visual_asset == "asset-1"


def test_shot_plan_from_dict_uses_defaults_for_missing_fields():
    data = {"shots": [{}]}
    plan = shot_plan_from_dict(data)
    assert plan.title == "GitHub 项目推荐"
    assert plan.shots[0].duration == 4
    assert plan.shots[0].start == 0


def test_shot_plan_from_dict_coerces_string_numbers():
    data = {"shots": [{"start": "1.5", "duration": "3.0"}]}
    plan = shot_plan_from_dict(data)
    assert plan.shots[0].start == 1.5
    assert plan.shots[0].duration == 3.0
```

- [ ] **Step 2: Write the failing test for desktop_review_plan_from_dict**

```python
# tests/test_desktop_review_plan_from_dict.py
import pytest
from src.models import desktop_review_plan_from_dict


def test_desktop_review_plan_minimal():
    data = {"title": "Test", "shots": []}
    plan = desktop_review_plan_from_dict(data)
    assert plan.title == "Test"
    assert plan.hook_title == "信息差 AI 工具"
    assert plan.account_label == "开源工具筛选"


def test_desktop_review_plan_full():
    data = {
        "title": "Test",
        "hook_title": "Hook",
        "account_label": "Account",
        "shots": [
            {
                "start": 0.0,
                "duration": 4.0,
                "url": "https://github.com",
                "action": "focus",
                "selector": "h1",
                "cursor_label": "Title",
                "narration": "Hello",
                "zoom": 1.5,
            }
        ],
    }
    plan = desktop_review_plan_from_dict(data)
    assert len(plan.shots) == 1
    assert plan.shots[0].zoom == 1.5
    assert plan.shots[0].selector == "h1"


def test_desktop_review_plan_uses_default_zoom():
    data = {"shots": [{"start": 0, "duration": 1}]}
    plan = desktop_review_plan_from_dict(data)
    assert plan.shots[0].zoom == 1.0
```

- [ ] **Step 3: Run tests to verify they pass against current code**

Run: `.venv/bin/python -m pytest tests/test_shot_plan_from_dict.py tests/test_desktop_review_plan_from_dict.py -v`
Expected: PASS (current code already handles defaults)

- [ ] **Step 4: Add a validate_optional helper to models.py**

In `src/models.py`, add at the top of the from_dict functions to provide warnings on unexpected fields. Replace `shot_plan_from_dict` (lines 233-248) with:

```python
def shot_plan_from_dict(data: dict[str, Any]) -> ShotPlan:
    """从 JSON 数据恢复分镜方案。未知字段会被忽略。"""
    return ShotPlan(
        title=data.get("title", "GitHub 项目推荐"),
        shots=[
            Shot(
                start=float(shot.get("start", 0)),
                duration=float(shot.get("duration", 4)),
                visual_asset=str(shot.get("visual_asset", "")),
                visual_treatment=str(shot.get("visual_treatment", "")),
                narration_intent=str(shot.get("narration_intent", "")),
                subtitle=str(shot.get("subtitle", "")),
            )
            for shot in data.get("shots", [])
        ],
    )
```

(Same behavior as before, but now we have explicit tests covering it.)

- [ ] **Step 5: Run tests again**

Run: `.venv/bin/python -m pytest tests/test_shot_plan_from_dict.py tests/test_desktop_review_plan_from_dict.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_shot_plan_from_dict.py tests/test_desktop_review_plan_from_dict.py src/models.py
git commit -m "test(models): add explicit tests for plan from_dict deserialization"
```

---

## Task 15: 给 parse_github_url 添加边界测试

**Files:**
- Test: `tests/test_parse_github_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parse_github_url.py
import pytest
from src.scraper.github_api import parse_github_url


def test_parse_github_url_standard():
    owner, repo = parse_github_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"


def test_parse_github_url_trailing_slash():
    owner, repo = parse_github_url("https://github.com/owner/repo/")
    assert owner == "owner"
    assert repo == "repo"


def test_parse_github_url_with_path():
    owner, repo = parse_github_url("https://github.com/owner/repo/blob/main/README.md")
    assert owner == "owner"
    assert repo == "repo"


def test_parse_github_url_invalid():
    with pytest.raises(ValueError, match="无效的 GitHub URL"):
        parse_github_url("https://example.com/")


def test_parse_github_url_bare_owner_repo():
    owner, repo = parse_github_url("owner/repo")
    assert owner == "owner"
    assert repo == "repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parse_github_url.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Verify current code passes all 5 tests**

Run: `.venv/bin/python -m pytest tests/test_parse_github_url.py -v`
Expected: PASS (current implementation handles all cases)

- [ ] **Step 4: Commit**

```bash
git add tests/test_parse_github_url.py
git commit -m "test(scraper): add edge case tests for parse_github_url"
```

---

## Task 16: 给 wrap_text 添加中文换行测试

**Files:**
- Test: `tests/test_wrap_text.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_wrap_text.py
import pytest
from PIL import ImageFont
from src.utils.render import wrap_text, get_font


@pytest.fixture
def font():
    return get_font(40)


def test_wrap_text_short_returns_single_line(font):
    lines = wrap_text("短文本", font, max_width=500)
    assert lines == ["短文本"]


def test_wrap_text_splits_long_chinese(font):
    # 强制每字符宽度 > max_width 触发换行
    lines = wrap_text("开源项目", font, max_width=20)
    assert len(lines) > 1
    assert "".join(lines) == "开源项目"


def test_wrap_text_preserves_english_words(font):
    lines = wrap_text("hello world python", font, max_width=500)
    assert "".join(lines) == "hello world python"


def test_wrap_text_caps_at_4_lines(font):
    long_text = "测试" * 200
    lines = wrap_text(long_text, font, max_width=50)
    assert len(lines) <= 4


def test_wrap_text_empty_returns_empty(font):
    lines = wrap_text("", font, max_width=500)
    assert lines == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wrap_text.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Run test to verify current code passes**

Run: `.venv/bin/python -m pytest tests/test_wrap_text.py -v`
Expected: PASS (current wrap_text handles these cases)

- [ ] **Step 4: Commit**

```bash
git add tests/test_wrap_text.py
git commit -m "test(utils): add tests for wrap_text Chinese line breaking"
```

---

## Task 17: 替换 desktop_review.py 全局变量为 lru_cache

**Files:**
- Modify: `src/composer/desktop_review.py:97-104`

- [ ] **Step 1: Read current global cache**

Already read at lines 97-104:
```python
_CACHED_BG = None

def _get_desktop_background():
    global _CACHED_BG
    if _CACHED_BG is None:
        _CACHED_BG = _desktop_background()
    return _CACHED_BG
```

- [ ] **Step 2: Replace with lru_cache**

In `src/composer/desktop_review.py`, replace lines 97-104 with:

```python
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_desktop_background():
    return _desktop_background()
```

- [ ] **Step 3: Verify file still parses**

Run: `.venv/bin/python -c "import src.composer.desktop_review"`
Expected: No error

- [ ] **Step 4: Run existing tests**

Run: `.venv/bin/python -m pytest tests/ -k "desktop" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/composer/desktop_review.py
git commit -m "refactor(composer): use lru_cache for desktop background"
```

---

## Task 18: 端到端冒烟测试 + 性能对比

**Files:**
- Test: `tests/test_e2e_perf_smoke.py` (new)

- [ ] **Step 1: Run current benchmark**

Run: `.venv/bin/python scripts/benchmark_pipeline.py --output output/benchmark-before`
Expected: timing_report.json generated

- [ ] **Step 2: Run optimized benchmark with ffmpeg direct encode**

Run: `USE_FFMPEG_DIRECT_ENCODE=1 .venv/bin/python scripts/benchmark_pipeline.py --real-hotlist --no-bgm --output output/benchmark-after/final.mp4`
Expected: timing_report.json generated

- [ ] **Step 3: Compare reports**

```bash
.venv/bin/python -c "
import json
before = json.load(open('output/benchmark-before/timing_report.json'))
after = json.load(open('output/benchmark-after/timing_report.json'))
print('Before total:', before['total_seconds'], 's')
print('After total:', after['total_seconds'], 's')
print('Speedup:', round(before['total_seconds'] / after['total_seconds'], 2), 'x')
"
```

Expected: Speedup ≥ 2x for compose_video stage

- [ ] **Step 4: Commit benchmark results**

```bash
git add tests/test_e2e_perf_smoke.py
git commit -m "test: end-to-end perf smoke test for direct ffmpeg encode"
```

---

## Task 19: 收尾：跑全量测试 + 更新文档

**Files:**
- Modify: `docs/development.md` (add note about new config flag)

- [ ] **Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Update development.md with new config**

In `docs/development.md`, add a new section after "性能优化":

```markdown
### 4. ffmpeg 直编模式（实验性）

竖屏合成器支持通过环境变量开启 ffmpeg 直编模式，跳过 moviepy 的逐帧回调：

```bash
USE_FFMPEG_DIRECT_ENCODE=1 .venv/bin/python -m src.cli https://github.com/owner/repo --vertical -o output/test.mp4
```

对长视频可获得 3-10x 速度提升，但首次运行会先生成临时帧到磁盘。
```

- [ ] **Step 3: Run lint / type check if configured**

Run: `.venv/bin/python -m flake8 src/ 2>&1 | head -20` (optional, only if project uses it)

- [ ] **Step 4: Final commit**

```bash
git add docs/development.md
git commit -m "docs: document ffmpeg direct encode config"
```

---

## Self-Review

### Spec coverage
- ✅ P0 性能：Task 8 (LRU cache), Task 10 (ffmpeg 直编)
- ✅ P0 内存：Task 8 (LRU cache bounds memory)
- ✅ P1 速率限制：Task 2 + Task 5 (GitHub API)
- ✅ P1 OpenAI 重试：Task 1 + Task 4
- ✅ P1 代码去重：Task 6 (base.py), Task 11, Task 12, Task 13
- ✅ P2 资源泄漏：Task 12 (try/finally)
- ✅ P2 全局状态：Task 17 (lru_cache)
- ✅ P2 核心单元测试：Task 14, 15, 16
- ✅ P3 性能对比：Task 18

### Placeholder scan
- 无 "TBD" / "TODO" / "implement later"
- 所有代码块均含完整代码
- 无 "Similar to Task N" 引用

### Type consistency
- `LRUNumpyCache` 在 Task 7 定义，Task 8 和 Task 10 使用
- `load_audio_segments` 在 Task 6 定义，Task 11 和 Task 12 使用
- `encode_video_with_ffmpeg` 在 Task 9 定义，Task 10 使用
- `retry_async` 在 Task 1 定义，Task 3 和 Task 4 使用
- `AsyncRateLimiter` 在 Task 2 定义，Task 5 使用

---

## 执行选项

计划已完成并保存到 `docs/superpowers/plans/2026-06-16-optimization-roadmap.md`。

两种执行方式：

**1. Subagent-Driven（推荐）** - 我为每个 Task 分发独立 subagent，Task 间进行检查，快速迭代

**2. Inline Execution** - 在当前会话按顺序执行 Task，使用 executing-plans 做批量执行和检查点

请选择执行方式。
