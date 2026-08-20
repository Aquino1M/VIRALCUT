from __future__ import annotations

import json
import re
import httpx

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT


def enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_MODEL)


def chat_json(system: str, user: str) -> dict | None:
    if not enabled():
        return None
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            r = client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start:end+1]
        return json.loads(text)
    except Exception:
        return None
