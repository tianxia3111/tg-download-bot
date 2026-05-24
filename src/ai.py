# -*- coding: utf-8 -*-
"""
AI-powered input analysis: classify AV vs movie, extract clean name.
Supports both OpenAI-compatible and Anthropic-compatible API formats.
Auto-detects format based on API_URL content.
"""
import json
import logging
import os

import requests

logger = logging.getLogger("tg-download-bot")

AI_API_URL = os.getenv("AI_API_URL", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")

_JSON_PROMPT = "Output ONLY raw JSON, no markdown, no explanation."


def _ai_available():
    return bool(AI_API_URL and AI_API_KEY and AI_MODEL)


def _is_anthropic():
    return "anthropic" in AI_API_URL.lower()


def _chat_completion(prompt, timeout=60):
    if _is_anthropic():
        return _anthropic_request(prompt, timeout)
    return _openai_request(prompt, timeout)


def _openai_request(prompt, timeout):
    url = AI_API_URL.rstrip("/")
    if "/chat/completions" not in url and "/messages" not in url:
        url += "/chat/completions"
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("AI API error %d: %s", resp.status_code, resp.text[:200])
            return None, None
        data = resp.json()
        for choice in data.get("choices", []):
            content = choice.get("message", {}).get("content", "")
            if content:
                thinking = ""
                idx = content.find("</think>")
                if idx != -1:
                    thinking = content[:idx].replace("<think>", "").strip()
                    content = content[idx + len("</think>"):].strip()
                return content, thinking[:500] if thinking else ""
        return None, None
    except Exception as e:
        logger.warning("AI API call failed: %s", e)
        return None, None


def _anthropic_request(prompt, timeout):
    url = AI_API_URL.rstrip("/")
    if "/messages" not in url:
        url += "/v1/messages"
    payload = {
        "model": AI_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("AI API error %d: %s", resp.status_code, resp.text[:200])
            return None, None
        data = resp.json()
        text = ""
        thinking = ""
        for block in data.get("content", []):
            if block.get("type") == "thinking":
                thinking = (thinking + "\n" + block.get("thinking", "")).strip()
            elif block.get("type") == "text":
                text = block.get("text", "").strip()
        return text, thinking[:500]
    except Exception as e:
        logger.warning("AI API call failed: %s", e)
        return None, None


def _extract_json(text):
    import re
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r'\{[^{}]*"type"\s*:\s*"(?:av|movie|tv)"[^{}]*\}', text)
    if m:
        return m.group(0)
    # Handle model mistakenly using "av|movie|tv" as key
    text = text.replace('"av|movie|tv"', '"type"')
    m = re.search(r'\{[^{}]*"type"\s*:\s*"(?:av|movie|tv)"[^{}]*\}', text)
    if m:
        return m.group(0)
    return text


def analyze_input(raw):
    if not _ai_available():
        return None

    prompt = (
        f"Input: '{raw}'\n\n"
        f"Classify as av/movie/tv. Remove junk like release groups, resolution, "
        f"codec, audio, subtitle tags, file extensions, Chinese site watermarks.\n"
        f"For AV: keep full av_code including prefix (FC2-PPV-xxx, HEYZO-xxx, etc).\n"
        f"For movie/tv: clean name without year suffix, only the title.\n"
        f'The JSON key must be literally "type", not a placeholder.\n'
        f'{_JSON_PROMPT}\n'
        f'{{"type":"av","name":"SSIS-001","av_code":"SSIS-001"}}'
    )
    try:
        result, thinking = _chat_completion(prompt, timeout=90)
        if not result:
            logger.info("AI returned empty")
            return None
        json_str = _extract_json(result)
        logger.info("AI raw: %s", result[:120])
        data = json.loads(json_str)
        data.setdefault("av_code", None)
        if data.get("type") in ("av", "movie", "tv") and data.get("name"):
            data["thinking"] = thinking
            logger.info("AI: %s -> type=%s name=%s", raw, data["type"], data["name"])
            return data
    except Exception as e:
        logger.warning("AI analyze failed: %s", e)
    return None
