"""Model routing helpers for the local console."""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import OpenAI

from src.console.store import CONFIG_DIR, DEFAULT_MODEL_ROUTING, DEFAULT_PROVIDERS, bool_value, read_json


MODEL_TIMEOUT_SECONDS = 120
JSON_RETRY_TEMPERATURES = (0.2, 0.45, 0.65)


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
    attempts = []
    for candidate in _json_candidate_routes(route):
        for temperature in JSON_RETRY_TEMPERATURES:
            try:
                content, used_route, usage = _chat_text_with_route(
                    candidate,
                    system,
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_object=True,
                )
            except Exception as exc:
                attempts.append(_json_attempt(candidate, temperature, "", str(exc)))
                continue
            if not content:
                attempts.append(_json_attempt(used_route, temperature, "", "empty response"))
                continue
            try:
                return {
                    "data": _parse_json(content),
                    "route": used_route,
                    "usage": usage,
                    "raw": content,
                    "error": "",
                    "error_details": attempts,
                }
            except Exception as exc:
                attempts.append(_json_attempt(used_route, temperature, content, str(exc), usage))
    error = attempts[-1]["error"] if attempts else "empty response"
    return {
        "data": None,
        "route": route,
        "usage": attempts[-1].get("usage", _empty_usage()) if attempts else _empty_usage(),
        "raw": attempts[-1]["raw"] if attempts else "",
        "error": error,
        "error_details": attempts,
    }


def chat_text(task: str, system: str, prompt: str, max_tokens: int = 2000) -> tuple[str, dict[str, str]]:
    route = route_snapshot(task)
    content, used_route, _usage = _chat_text_with_route(route, system, prompt, max_tokens=max_tokens, temperature=0.45, json_object=False)
    return content, used_route


def _chat_text_with_route(
    route: dict[str, str],
    system: str,
    prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.45,
    json_object: bool = False,
) -> tuple[str, dict[str, str], dict[str, int]]:
    if not route.get("available"):
        return "", route, _empty_usage()
    provider = _provider_config(route["provider"])
    if _provider_type(provider) == "anthropic":
        content, usage = _anthropic_text(provider or {}, route["model"], system, prompt, max_tokens, temperature)
        return content, route, usage
    client = _openai_client(route["provider"], provider)
    if not client:
        return "", route, _empty_usage()
    response = _openai_completion(client, route["model"], system, prompt, max_tokens, temperature, json_object)
    return str(response.choices[0].message.content or "").strip(), route, _openai_usage(response)


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
            content, _usage = _anthropic_text(provider_config or {}, model_name, "只回复 ok。", "ping", 8, 0)
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


def _openai_completion(
    client: OpenAI,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    json_object: bool,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_object:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        if not json_object or "response_format" not in str(exc):
            raise
        kwargs.pop("response_format", None)
        return client.chat.completions.create(**kwargs)


def _anthropic_text(provider: dict[str, Any], model: str, system: str, prompt: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
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
            "temperature": temperature,
        },
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    return _anthropic_content_text(data), _anthropic_usage(data)


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


def _json_candidate_routes(primary: dict[str, str]) -> list[dict[str, str]]:
    routes = [primary]
    configured = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS).get("providers", [])
    fallback_models = {"openai": "gpt-4.1-mini", "deepseek": "deepseek-chat"}
    seen = {(primary.get("provider"), primary.get("model"))}
    for provider in configured:
        provider_id = str(provider.get("id") or "")
        if provider_id not in fallback_models:
            continue
        model = str(provider.get("default_model") or fallback_models[provider_id])
        key = (provider_id, model)
        if key in seen:
            continue
        route = _route_from_provider(provider, model)
        if route.get("available"):
            routes.append(route)
            seen.add(key)
    return routes


def _route_from_provider(provider: dict[str, Any], model: str) -> dict[str, str]:
    enabled = bool_value(provider.get("enabled"))
    configured = bool(provider.get("api_key"))
    last_test = str(provider.get("last_test") or "")
    available = enabled and configured and bool(model) and last_test.startswith("连接成功")
    provider_id = str(provider.get("id") or "")
    return {
        "task": "fallback_json",
        "provider": provider_id,
        "provider_name": str(provider.get("name") or provider_id),
        "model": model,
        "enabled": "1" if enabled else "",
        "configured": "1" if configured else "",
        "last_test": last_test,
        "available": "1" if available else "",
    }


def _json_attempt(route: dict[str, str], temperature: float, raw: str, error: str, usage: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "temperature": f"{temperature:.2f}",
        "error": error,
        "raw": raw,
        "usage": usage or _empty_usage(),
    }


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _openai_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return _normalize_usage({
        "prompt_tokens": _usage_value(usage, "prompt_tokens"),
        "completion_tokens": _usage_value(usage, "completion_tokens"),
        "total_tokens": _usage_value(usage, "total_tokens"),
    })


def _anthropic_usage(data: dict[str, Any]) -> dict[str, int]:
    usage = data.get("usage") if isinstance(data, dict) else {}
    return _normalize_usage({
        "prompt_tokens": _usage_value(usage, "input_tokens"),
        "completion_tokens": _usage_value(usage, "output_tokens"),
    })


def _usage_value(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    prompt = _usage_value(usage, "prompt_tokens")
    completion = _usage_value(usage, "completion_tokens")
    total = _usage_value(usage, "total_tokens") or prompt + completion
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


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
