"""GitHub API 抓取器"""

import httpx

from src.models import ProjectInfo

GITHUB_API = "https://api.github.com"


def _get_headers() -> dict:
    """获取 GitHub API 请求头（延迟读取 Token）"""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "github-video-maker",
    }
    from src.utils.config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def fetch_repo_info(owner: str, repo: str) -> ProjectInfo:
    """通过 GitHub API 获取仓库信息"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = _get_headers()
        # 获取仓库基本信息
        repo_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
        )
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()

        # 获取 README 内容
        readme_headers = {**headers, "Accept": "application/vnd.github.v3.raw"}
        readme_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/readme",
            headers=readme_headers,
        )
        readme_text = ""
        if readme_resp.status_code == 200:
            readme_text = readme_resp.text[:3000]  # 限制长度

        # 提取主题标签
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


def parse_github_url(url: str) -> tuple[str, str]:
    """从 GitHub URL 解析 owner 和 repo"""
    url = url.rstrip("/")
    parts = url.replace("https://github.com/", "").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"无效的 GitHub URL: {url}")
