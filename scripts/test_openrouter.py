"""Quick diagnostic script for OpenRouter connectivity."""
import json
import os
import sys
from typing import Any, Dict

import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m2:free")
    url = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
    referer = os.getenv("OPENROUTER_REFERRER", "https://example.com")
    title = os.getenv("OPENROUTER_TITLE", "WhatsAppTelegramBridge")

    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": title,
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "diag"},
            {"role": "user", "content": "ping"},
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
