"""
Proof-of-life script for the TrueFoundry AI Gateway.

Calls the gateway with the configured Groq model and prints the response.
Run from apps/api/ with:

    uv run python scripts/test_truefoundry.py

This is not part of the runtime. It exists to verify that:
  1. The API key in .env is valid.
  2. The base URL is reachable.
  3. The model identifier matches what TrueFoundry has configured.
  4. Our request shape matches the OpenAI-compatible interface.

If this fails, nothing downstream works. Fix it here first.
"""

import asyncio
import json
import sys
import time

import httpx

from kexar.config import settings


async def call_gateway(model: str, prompt: str) -> dict:
    """Make one chat-completions call through the gateway."""
    url = f"{settings.truefoundry_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.truefoundry_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a terse SRE assistant. Answer in one sentence.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 100,
        "temperature": 0.2,
    }

    # 30s timeout matches the policy in architecture doc.
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def pretty_print_result(model: str, prompt: str, result: dict, elapsed_ms: float) -> None:
    """Render the response in a way that is easy to eyeball."""
    print("=" * 72)
    print(f"Model:    {model}")
    print(f"Prompt:   {prompt}")
    print(f"Elapsed:  {elapsed_ms:.0f} ms")
    print("-" * 72)

    # OpenAI-compatible response shape.
    try:
        message = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
        print(f"Response: {message}")
        print()
        print(f"Tokens:   prompt={usage.get('prompt_tokens')} "
              f"completion={usage.get('completion_tokens')} "
              f"total={usage.get('total_tokens')}")
    except (KeyError, IndexError) as e:
        print(f"Unexpected response shape: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(1)
    print("=" * 72)


async def main() -> None:
    model = settings.truefoundry_model_groq
    prompt = "Checkout API p99 went from 80ms to 4.2s at 02:14. One likely cause?"

    print(f"Calling TrueFoundry gateway at {settings.truefoundry_base_url}")
    print(f"Using model: {model}\n")

    start = time.perf_counter()
    try:
        result = await call_gateway(model, prompt)
    except httpx.HTTPStatusError as e:
        print(f"HTTP {e.response.status_code} from gateway")
        print(f"Response body: {e.response.text}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request failed: {type(e).__name__}: {e}")
        sys.exit(1)

    elapsed_ms = (time.perf_counter() - start) * 1000
    pretty_print_result(model, prompt, result, elapsed_ms)


if __name__ == "__main__":
    asyncio.run(main())
