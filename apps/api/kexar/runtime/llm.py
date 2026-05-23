"""
LLM gateway client with cascading failover.

This is the only module that talks to TrueFoundry. Nothing else in the
codebase should call httpx against the gateway. All providers route
through here.

The big idea:
  * One call_llm() entry point. Takes a list of messages, returns the
    chosen model's response.
  * Internally: walk the cascade. For each model, try the gateway with
    retry + timeout. If all retries fail, emit llm.failover and move
    to the next model. If the entire cascade is exhausted, raise
    AllProvidersExhaustedError.
  * Every meaningful moment is an event on the bus (llm.call.start,
    llm.call.success, llm.call.failure, llm.failover).
  * Simulated models (config.is_simulated_model) raise UpstreamUnavailableError
    without an HTTP call. The cascade falls through to Groq. Real failover
    events fire end to end.

Errors are typed. The orchestrator catches the specific class it cares
about, not bare Exception. No try/except Exception anywhere downstream.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from kexar.config import settings
from kexar.runtime.events import (
    LlmCallFailure,
    LlmCallStart,
    LlmCallSuccess,
    LlmFailover,
    bus,
)
from kexar.runtime.policy import (
    DEFAULT_LLM_POLICY,
    LlmPolicy,
    cascade,
    estimate_cost_usd,
)
from kexar.runtime.state import Budget

# -----------------------------------------------------------------------------
# Typed exceptions
# -----------------------------------------------------------------------------


class LlmError(Exception):
    """Base for all LLM-layer failures. Orchestrator catches this."""


class UpstreamUnavailableError(LlmError):
    """One model is unreachable: 5xx, network error, or simulated stub.

    Retryable in the sense that the cascade should try the next model.
    Not retryable as the same model in a tight loop (we already tried).
    """


class LlmCallTimeoutError(LlmError):
    """One call exceeded the configured timeout."""


class RateLimitedError(LlmError):
    """Gateway returned 429 for this model. Move to next."""


class BadGatewayResponseError(LlmError):
    """Response shape was not the OpenAI-compatible JSON we expect."""


class AllProvidersExhaustedError(LlmError):
    """Every model in the cascade failed. Run cannot continue."""


# -----------------------------------------------------------------------------
# Response container
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LlmResponse:
    """What the orchestrator gets back from call_llm()."""

    content: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------


async def call_llm(
    run_id: str,
    step: int,
    messages: list[dict[str, str]],
    *,
    budget: Budget,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    policy: LlmPolicy = DEFAULT_LLM_POLICY,
) -> LlmResponse:
    """Call the LLM cascade. Returns the first successful response.

    Emits llm.call.start before each attempt, llm.call.success on the
    winning attempt, llm.call.failure on each failed attempt, and
    llm.failover when moving from one model to the next.

    Raises AllProvidersExhaustedError only when the entire cascade fails.
    The orchestrator handles that by aborting the run.

    The Budget object is updated in-place with tokens and cost on success.
    """
    models = cascade()
    last_error: Exception | None = None
    last_failover_started_at: float | None = None

    for index, model in enumerate(models):
        is_first = index == 0
        if not is_first:
            # Emit failover event for the model we are about to try.
            # latency_ms_added is the time spent failing through the prior
            # model (its retries + timeouts).
            now = time.perf_counter()
            added = (
                int((now - last_failover_started_at) * 1000)
                if last_failover_started_at is not None
                else 0
            )
            await bus.publish(
                run_id,
                LlmFailover(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "from_model": models[index - 1],
                        "to_model": model,
                        "reason": _describe_failure(last_error),
                        "latency_ms_added": added,
                    },
                ),
            )

        last_failover_started_at = time.perf_counter()
        try:
            response = await _call_one_model(
                run_id=run_id,
                step=step,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                policy=policy,
            )
        except LlmError as e:
            last_error = e
            continue

        # Success. Update the budget and return.
        budget.tokens_used += response.total_tokens
        budget.cost_usd += response.cost_usd
        return response

    # All four exhausted.
    raise AllProvidersExhaustedError(
        f"All {len(models)} providers in the cascade failed. "
        f"Last error: {_describe_failure(last_error)}"
    )


# -----------------------------------------------------------------------------
# One-model call with retry and backoff
# -----------------------------------------------------------------------------


async def _call_one_model(
    *,
    run_id: str,
    step: int,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    policy: LlmPolicy,
) -> LlmResponse:
    """Try a single model with up to policy.retries retries.

    Raises an LlmError subclass on terminal failure for this model.
    Successful return means tokens are not yet recorded in the budget;
    the caller (call_llm) does that.
    """
    last_error: Exception | None = None

    for attempt in range(1, policy.retries + 2):  # 1 initial + N retries
        await bus.publish(
            run_id,
            LlmCallStart(
                seq=0,
                run_id="",
                step=step,
                data={"model": model, "attempt": attempt},
            ),
        )

        # Simulated models: skip the HTTP call entirely, raise immediately.
        # This is how we get a real failover event end-to-end without
        # paying for OpenAI/Anthropic/Gemini credentials.
        if settings.is_simulated_model(model):
            err = UpstreamUnavailableError(f"{model} is a simulated upstream stub")
            await bus.publish(
                run_id,
                LlmCallFailure(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "model": model,
                        "attempt": attempt,
                        "reason": "simulated_upstream_unavailable",
                        "retryable": False,
                    },
                ),
            )
            # Do not retry a simulated stub. Move on immediately.
            raise err

        # Real HTTP call.
        try:
            start = time.perf_counter()
            response = await _http_call(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                policy=policy,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            cost = estimate_cost_usd(
                model, response.prompt_tokens, response.completion_tokens
            )
            final = LlmResponse(
                content=response.content,
                model_used=model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )

            await bus.publish(
                run_id,
                LlmCallSuccess(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "model": model,
                        "latency_ms": latency_ms,
                        "tokens_prompt": response.prompt_tokens,
                        "tokens_completion": response.completion_tokens,
                        "cost_usd": cost,
                    },
                ),
            )
            return final

        except LlmError as e:
            last_error = e
            retryable = isinstance(e, LlmCallTimeoutError | UpstreamUnavailableError)
            await bus.publish(
                run_id,
                LlmCallFailure(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "model": model,
                        "attempt": attempt,
                        "reason": _describe_failure(e),
                        "retryable": retryable,
                    },
                ),
            )
            # Rate-limit and bad-response failures are NOT worth retrying
            # against the same model. Move to the next one in the cascade.
            if not retryable:
                raise

            if attempt <= policy.retries:
                delay = _compute_backoff(attempt, policy)
                await asyncio.sleep(delay)
                continue

    # Exhausted retries on this model.
    raise last_error if last_error else UpstreamUnavailableError(f"{model} failed")


# -----------------------------------------------------------------------------
# Low-level HTTP
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _ParsedResponse:
    """Internal shape extracted from the gateway's JSON response."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


async def _http_call(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    policy: LlmPolicy,
) -> _ParsedResponse:
    """One real HTTP call to the TrueFoundry gateway."""
    url = f"{settings.truefoundry_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.truefoundry_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    timeout = httpx.Timeout(policy.timeout_s, connect=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        raise LlmCallTimeoutError(f"{model} timed out after {policy.timeout_s}s") from e
    except httpx.RequestError as e:
        raise UpstreamUnavailableError(f"{model} network error: {e}") from e

    if response.status_code == 429:
        raise RateLimitedError(f"{model} returned 429")
    if 500 <= response.status_code < 600:
        raise UpstreamUnavailableError(
            f"{model} returned {response.status_code}: {response.text[:200]}"
        )
    if response.status_code >= 400:
        raise BadGatewayResponseError(
            f"{model} returned {response.status_code}: {response.text[:200]}"
        )

    try:
        body = response.json()
    except ValueError as e:
        raise BadGatewayResponseError(f"{model} returned non-JSON: {response.text[:200]}") from e

    try:
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return _ParsedResponse(
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
        )
    except (KeyError, IndexError, TypeError) as e:
        raise BadGatewayResponseError(f"{model} unexpected JSON shape: {body}") from e


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _compute_backoff(attempt: int, policy: LlmPolicy) -> float:
    """Exponential backoff with jitter, capped at policy.backoff_max_s."""
    base = min(policy.backoff_initial_s * (2 ** (attempt - 1)), policy.backoff_max_s)
    jitter = random.uniform(-policy.backoff_jitter_s, policy.backoff_jitter_s)  # noqa: S311
    return max(0.0, base + jitter)


def _describe_failure(err: Exception | None) -> str:
    """Short string for logging and event payloads."""
    if err is None:
        return "unknown"
    name = type(err).__name__
    return f"{name}: {err}"
