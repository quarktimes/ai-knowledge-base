"""Lightweight LLM model client for workflow use.

Provides:
    chat: Send a prompt and return (text, usage) tuple.
    chat_json: Send a prompt and receive parsed JSON response.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx


logger = logging.getLogger(__name__)

PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
}

DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_DELAY = 2.0

_provider_cache: dict[str, Any] | None = None


def _get_provider() -> dict[str, Any]:
    global _provider_cache
    if _provider_cache is not None:
        return _provider_cache

    provider_name = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    config = PROVIDER_CONFIGS.get(provider_name)
    if config is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. "
            f"Supported: {', '.join(PROVIDER_CONFIGS)}"
        )
    api_key = os.environ.get(config["env_key"])
    if not api_key:
        raise ValueError(
            f"{config['env_key']} is not set for provider '{provider_name}'"
        )
    _provider_cache = {
        "provider": provider_name,
        "base_url": config["base_url"],
        "model": config["model"],
        "api_key": api_key,
    }
    return _provider_cache


def chat(prompt: str, system: str | None = None) -> tuple[str, dict[str, int]]:
    """Send a prompt to the LLM and return (text, usage).

    Args:
        prompt: The user message.
        system: Optional system instruction.

    Returns:
        A tuple of (response_text, usage_dict).

    Raises:
        RuntimeError: If all retry attempts fail.
    """
    provider = _get_provider()
    url = f"{provider['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": provider["model"],
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage: dict[str, int] = data.get("usage", {})
                if content:
                    return content, usage
                logger.warning("Attempt %d: empty response", attempt)
        except httpx.HTTPStatusError as e:
            last_error = e
            logger.warning("Attempt %d: HTTP %d", attempt, e.response.status_code)
        except httpx.RequestError as e:
            last_error = e
            logger.warning("Attempt %d: request failed - %s", attempt, e)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            last_error = e
            logger.warning("Attempt %d: bad response - %s", attempt, e)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"chat failed after {MAX_RETRIES} attempts") from last_error


def chat_json(
    prompt: str, system: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Send a prompt and parse the response as JSON.

    Automatically retries if the response is not valid JSON.

    Args:
        prompt: The user message.
        system: Optional system instruction.

    Returns:
        A tuple of (parsed_json_dict, usage_dict).

    Raises:
        RuntimeError: If JSON parsing fails after all retries.
    """
    json_system = (
        (system + "\n\n") if system else ""
    ) + "You must respond with valid JSON only. No markdown fences, no extra text."

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            text, usage = chat(prompt, system=json_system)
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return json.loads(cleaned), usage
        except (json.JSONDecodeError, ValueError, RuntimeError) as e:
            last_error = e
            logger.warning("chat_json attempt %d: %s", attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"chat_json failed after {MAX_RETRIES} attempts") from last_error


def _ensure_tracker(tracker: dict[str, Any] | None) -> dict[str, Any]:
    if tracker is None or "total_calls" not in tracker:
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_provider": {},
        }
    return tracker


def accumulate_usage(
    tracker: dict[str, Any] | None,
    usage: dict[str, int] | None,
) -> dict[str, Any]:
    """Accumulate token usage into a cost tracker dict.

    Args:
        tracker: Existing cost tracker, or None to create new.
        usage: Usage dict from chat()/chat_json() response.

    Returns:
        Updated cost tracker with totals and per-provider breakdown.
    """
    tracker = _ensure_tracker(tracker)
    if usage is None:
        return tracker

    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    tokens = prompt_tokens + completion_tokens

    provider = _get_provider()
    provider_name = provider["provider"]

    tracker["total_calls"] += 1
    tracker["total_tokens"] += tokens

    pp = tracker["by_provider"].setdefault(provider_name, {
        "calls": 0, "tokens": 0, "cost": 0.0,
    })
    pp["calls"] += 1
    pp["tokens"] += tokens

    return tracker
