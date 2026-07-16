#!/usr/bin/env python3
"""Small connectivity/protocol probe for raw vLLM, relay, or local gateway."""

import argparse
import json
import sys

import httpx


def normalize_base(value: str) -> str:
    base = value.rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1/responses", "/responses"):
        if base.endswith(suffix):
            base = base[:-len(suffix)].rstrip("/")
            break
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="Server root or /v1 API base")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    base = normalize_base(args.base)
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    print(f"API base: {base}")
    with httpx.Client(timeout=args.timeout, headers=headers) as client:
        try:
            response = client.get(f"{base}/models")
            print(f"GET /models: HTTP {response.status_code}")
            print(response.text[:500])
        except Exception as exc:
            print(f"GET /models failed: {exc}")

        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
            "stream": False,
            "max_tokens": 16,
        }
        try:
            response = client.post(f"{base}/chat/completions", json=payload)
            print(f"POST /chat/completions: HTTP {response.status_code}")
            print(response.text[:1000])
            if response.status_code >= 400:
                return 2
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            print("Parsed content:", json.dumps(content, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(f"POST /chat/completions failed: {exc}")
            return 3


if __name__ == "__main__":
    sys.exit(main())
