"""Model routing helpers for the local console."""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import OpenAI

from src.console.store import CONFIG_DIR, DEFAULT_MODEL_ROUTING, DEFAULT_PROVIDERS, bool_value, read_json


MODEL_TIMEOUT_SECONDS = 120


def route_snapshot(task: str) -> dict[str, str]:
    routing = read_json(CONFIG_DIR / "model-routing.json", DEFAULT_MODEL_ROUTING)
    route = routing.get(task) or {}
    provider_id = str(route.get("provider") or "")
    providers = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS).get("providers", [])
    provider = next((item for item in providers if item.get("id") == provider_id), {})
    model = str(route.get("model") or provider.get("default_model") or "")
    enabled = bool_value(provider.get("enabled"))
    configured = bool(provider.get("api_key"))
    last_test = str(provider.get("last_test") or "")
    available = enabled and configured and bool(model) and last_test.startswith("连接成功")
    return {
        "task": task,
        "provider": provider_id,
        "provider_name": str(provider.get("name") or provider_id),
        "model": model,
        "enabled": "1" if enabled else "",
        "configured": "1" if configured else "",
        "last_test": last_test,
        "available": "1" if available else "",
    }


def chat_json(task: str, system: str, prompt: str, max_tokens: int = 2000) -> tuple[dict[str, Any] | None, dict[str, str]]:
    detail = chat_json_detail(task, system, prompt, max_tokens=max_tokens)
    return detail["data"], detail["route"]


def chat_json_detail(task: str, system: str, prompt: str, max_tokens: int = 2000) -> dict[str, Any]:
    route = route_snapshot(task)
    content = chat_text(task, system, prompt, max_tokens=max_tokens)[0]
    if not content:
        return {"data": None, "route": route, "raw": "", "error": "empty response"}
    try:
        return {"data": _parse_json(content), "route": route, "raw": content, "error": ""}
    except Exception as exc:
        return {"data": None, "route": route, "raw": content, "error": str(exc)}


def chat_text(task: str, system: str, prompt: str, max_tokens: int = 2000) -> tuple[str, dict[str, str]]:
    route = route_snapshot(task)
    if not route.get("available"):
        return "", route
    provider = _provider_config(route["provider"])
    if _provider_type(provider) == "anthropic":
        return _anthropic_text(provider or {}, route["model"], system, prompt, max_tokens), route
    client = _openai_client(route["provider"], provider)
    if not client:
        return "", route
    response = client.chat.completions.create(
        model=route["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.45,
        max_tokens=max_tokens,
    )
    return str(response.choices[0].message.content or "").strip(), route


def test_provider(provider_id: str, model: str = "", provider_config: dict[str, Any] | None = None) -> tuple[bool, str]:
    provider_config = _merged_provider_config(provider_id, provider_config)
    model_name = model
    if not model_name:
        provider = provider_config or _provider_config(provider_id) or {}
        model_name = str(provider.get("default_model") or "")
    if not model_name:
        return False, "缺少模型名称"
    try:
        if _provider_type(provider_config) == "anthropic":
            content = _anthropic_text(provider_config or {}, model_name, "只回复 ok。", "ping", 8)
            return True, content or "ok"
        client = _openai_client(provider_id, provider_config)
        if not client:
            return False, "供应商未启用或缺少 API Key"
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "只回复 ok。"},
                {"role": "user", "content": "ping"},
            ],
            temperature=0,
            max_tokens=8,
        )
        content = str(response.choices[0].message.content or "").strip()
        return True, content or "ok"
    except Exception as exc:
        return False, str(exc)


def _openai_client(provider_id: str, provider_config: dict[str, Any] | None = None) -> OpenAI | None:
    provider = provider_config or _provider_config(provider_id)
    if not provider or not bool_value(provider.get("enabled")):
        return None
    api_key = str(provider.get("api_key") or "")
    if not api_key:
        return None
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": MODEL_TIMEOUT_SECONDS, "max_retries": 0}
    base_url = str(provider.get("base_url") or "")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _anthropic_text(provider: dict[str, Any], model: str, system: str, prompt: str, max_tokens: int) -> str:
    if not provider or not bool_value(provider.get("enabled")):
        raise ValueError("供应商未启用或缺少 API Key")
    api_key = str(provider.get("api_key") or "")
    if not api_key:
        raise ValueError("供应商未启用或缺少 API Key")
    base_url = _anthropic_base_url(str(provider.get("base_url") or ""))
    response = httpx.post(
        f"{base_url}/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.45,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return _anthropic_content_text(data)


def _anthropic_content_text(data: dict[str, Any]) -> str:
    parts = data.get("content") if isinstance(data, dict) else []
    if not isinstance(parts, list):
        return ""
    return "\n".join(str(part.get("text") or "").strip() for part in parts if isinstance(part, dict) and part.get("type") == "text").strip()


def _anthropic_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/") or "https://api.anthropic.com"
    return value if value.endswith("/v1") else f"{value}/v1"


def _provider_type(provider: dict[str, Any] | None) -> str:
    return str((provider or {}).get("type") or "")


def _provider_config(provider_id: str) -> dict[str, Any] | None:
    providers = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS).get("providers", [])
    return next((item for item in providers if item.get("id") == provider_id), None)


def _merged_provider_config(provider_id: str, provider_config: dict[str, Any] | None) -> dict[str, Any] | None:
    saved = _provider_config(provider_id)
    if provider_config is None:
        return saved
    merged = dict(saved or {})
    merged.update(provider_config)
    if not provider_config.get("api_key") and saved:
        merged["api_key"] = saved.get("api_key", "")
    return merged


def _parse_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    return json.loads(text)
