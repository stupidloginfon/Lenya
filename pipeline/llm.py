"""Единая точка вызова LLM для анализа хука и генерации сценария.

Поддерживает Claude и любые OpenAI-совместимые сервисы (Groq, Gemini,
OpenRouter, локальный Ollama) — переключение через LLM_PROVIDER в .env.
Так пайплайн работает и бесплатно, и на платном Claude без правок кода.
"""
import json
import os
import re

import config

# Пресеты бесплатных/локальных провайдеров (все OpenAI-совместимые).
# Переопределить модель/URL/ключ можно через LLM_MODEL / LLM_BASE_URL / LLM_API_KEY.
PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_env": "OPENROUTER_API_KEY",
    },
    "ollama": {  # локально, ключ не нужен
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5",
        "key_env": "OLLAMA_API_KEY",
    },
}


def _resolve() -> dict:
    """Собрать конфиг текущего провайдера с учётом пресета и переопределений."""
    provider = config.LLM_PROVIDER.lower()
    if provider == "claude":
        return {"provider": "claude", "model": config.CLAUDE_MODEL,
                "api_key": config.ANTHROPIC_API_KEY}
    preset = PRESETS.get(provider)
    if preset is None:
        raise RuntimeError(
            f"Неизвестный LLM_PROVIDER={provider}. "
            f"Доступно: claude, {', '.join(PRESETS)}"
        )
    return {
        "provider": provider,
        "base_url": config.LLM_BASE_URL or preset["base_url"],
        "model": config.LLM_MODEL or preset["model"],
        "api_key": config.LLM_API_KEY or os.getenv(preset["key_env"], "")
                   or ("ollama" if provider == "ollama" else ""),
    }


def is_ready() -> tuple[bool, str]:
    """Готов ли провайдер (есть ли ключ). Возвращает (ок, подсказка)."""
    cfg = _resolve()
    if cfg["provider"] == "ollama":
        return True, ""
    if cfg["api_key"]:
        return True, ""
    if cfg["provider"] == "claude":
        return False, "Нет ANTHROPIC_API_KEY"
    key_env = PRESETS[cfg["provider"]]["key_env"]
    return False, f"Нет ключа: задай {key_env} (или LLM_API_KEY) в .env"


def _extract_json(text: str) -> dict:
    """Достать JSON из ответа модели (на случай обёрток ```json ... ```)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def complete_json(system: str, user: str, schema: dict, max_tokens: int = 2000) -> dict:
    """Запросить у LLM ответ строго в JSON по заданной схеме."""
    cfg = _resolve()
    if cfg["provider"] == "claude":
        return _claude_json(cfg, system, user, schema, max_tokens)
    return _openai_json(cfg, system, user, schema, max_tokens)


def _claude_json(cfg, system, user, schema, max_tokens) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["api_key"])
    resp = client.messages.create(
        model=cfg["model"],
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _openai_json(cfg, system, user, schema, max_tokens) -> dict:
    from openai import OpenAI

    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"] or "x")
    # Бесплатные модели не всегда поддерживают строгую json_schema, поэтому
    # просим JSON-объект и кладём схему прямо в подсказку.
    sys_prompt = (
        system
        + "\n\nОтвечай ТОЛЬКО валидным JSON по этой JSON-схеме, без пояснений:\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
    )
    return _extract_json(resp.choices[0].message.content)
