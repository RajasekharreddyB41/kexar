"""
Runtime policy: the magic numbers and ordering rules in one place.

Every resilience knob the runtime cares about lives here. Timeouts,
retries, cascade order, circuit breaker thresholds. Importers should
read from this module, never hardcode.

Numbers come from the architecture doc, section "LLM failover policy"
and "Tool resilience policy". Keep them in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kexar.config import settings

# -----------------------------------------------------------------------------
# LLM policy
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LlmPolicy:
    """Per-model resilience configuration.

    timeout_s:           how long to wait for one HTTP call before giving up.
    retries:             how many times to retry the same model on a
                         transient failure before failing over to the next.
    backoff_initial_s:   first retry delay. Subsequent retries scale.
    backoff_max_s:       cap on retry delay even with exponential growth.
    backoff_jitter_s:    +/- random component added to backoff.
    """

    timeout_s: float = 30.0
    retries: int = 2
    backoff_initial_s: float = 1.0
    backoff_max_s: float = 3.0
    backoff_jitter_s: float = 0.25


# Default policy used by every model unless overridden.
DEFAULT_LLM_POLICY = LlmPolicy()


def cascade() -> list[str]:
    """Ordered list of model identifiers to try.

    Cascade order, locked by the architecture doc:
        1. Claude Sonnet 4.5 (reasoning quality)
        2. GPT-4o            (close substitute)
        3. Gemini 2.5 Flash  (speed and cost)
        4. Groq Llama 3.3    (always-works backstop)

    For the hackathon, the first three are simulated stubs (we have no
    real provider credentials wired into TrueFoundry yet). The runtime
    raises UpstreamUnavailable for those, cascade falls through to Groq.
    The control panel renders real failover events end-to-end. See
    config.Settings.is_simulated_model.
    """
    return [
        settings.truefoundry_model_claude,
        settings.truefoundry_model_gpt4o,
        settings.truefoundry_model_gemini,
        settings.truefoundry_model_groq,
    ]


# -----------------------------------------------------------------------------
# Tool policy
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolPolicy:
    """Per-tool resilience configuration.

    timeout_s:               how long to wait for one tool call.
    retries:                 retries before giving up and emitting failure.
    backoff_initial_s:       first retry delay.
    circuit_failure_threshold:
                             consecutive failures within `circuit_window_s`
                             that open the circuit. Once open, subsequent
                             calls fail fast for `circuit_cooldown_s`.
    circuit_window_s:        sliding window for counting failures.
    circuit_cooldown_s:      how long the circuit stays open after tripping.
    """

    timeout_s: float = 8.0
    retries: int = 1
    backoff_initial_s: float = 0.5
    circuit_failure_threshold: int = 3
    circuit_window_s: float = 60.0
    circuit_cooldown_s: float = 30.0


DEFAULT_TOOL_POLICY = ToolPolicy()


# -----------------------------------------------------------------------------
# Budget policy
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetPolicy:
    """Per-run hard caps. Pulled from config so deployment can tune them."""

    max_steps: int = field(default_factory=lambda: settings.kexar_max_steps)
    max_tokens: int = field(default_factory=lambda: settings.kexar_max_tokens)
    max_cost_usd: float = field(default_factory=lambda: settings.kexar_max_cost_usd)

    # Warn at this fraction of any axis. Used by budget.warn events.
    warn_pct: float = 0.80


DEFAULT_BUDGET_POLICY = BudgetPolicy()


# -----------------------------------------------------------------------------
# Per-1k-token pricing estimates (USD).
#
# Used only for the cost meter in the control panel. We do not get exact
# cost back from the gateway, so we estimate from token counts. Real
# numbers come from each provider's pricing page; values here are rough
# averages as of May 2026 and are intentionally pessimistic (we would
# rather overstate cost than understate it).
# -----------------------------------------------------------------------------

PRICING_USD_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # model_id: (input_per_1k, output_per_1k)
    settings.truefoundry_model_claude: (0.003, 0.015),
    settings.truefoundry_model_gpt4o: (0.0025, 0.010),
    settings.truefoundry_model_gemini: (0.000075, 0.0003),
    settings.truefoundry_model_groq: (0.00059, 0.00079),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the dollar cost of one LLM call.

    Falls back to the most expensive entry in the table if the model is
    unknown, on the principle that overstating is safer than understating.
    """
    if model in PRICING_USD_PER_1K_TOKENS:
        in_per_1k, out_per_1k = PRICING_USD_PER_1K_TOKENS[model]
    else:
        # Unknown model. Use the highest input/output rates we know about.
        in_per_1k = max(v[0] for v in PRICING_USD_PER_1K_TOKENS.values())
        out_per_1k = max(v[1] for v in PRICING_USD_PER_1K_TOKENS.values())
    return (prompt_tokens / 1000.0) * in_per_1k + (completion_tokens / 1000.0) * out_per_1k
