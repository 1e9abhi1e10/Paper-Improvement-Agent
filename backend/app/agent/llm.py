"""Thin OpenAI wrapper. Every call returns validated JSON.

The LLM is never the source of citations: it only ranks, judges, and
rewrites around candidates that came from the search APIs. Prompts are
small and single-purpose; there is no one giant prompt.
"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..config import OPENAI_API_KEY, OPENAI_MODEL


class LLMUnavailable(Exception):
    pass


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if not OPENAI_API_KEY:
        raise LLMUnavailable(
            "OPENAI_API_KEY is not set. Add it to backend/.env to enable "
            "peer review and agentic editing."
        )
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def chat_json(system: str, user: str, max_tokens: int = 2000) -> dict[str, Any]:
    client = _get_client()
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system + "\nRespond with a single valid JSON object only."},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Model returned invalid JSON: {exc}") from exc
