import contextvars
from typing import Any

token_tracker: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "interview_token_tracker", default=None
)


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> dict[str, float]:
    """Estimate model cost in USD based on input/output tokens."""
    input_rate = 0.00000015
    output_rate = 0.00000060

    name_lower = model_name.lower()
    if "gemma-3-27b" in name_lower:
        input_rate = 0.00000027
        output_rate = 0.00000027
    elif "gemma" in name_lower:
        input_rate = 0.00000010
        output_rate = 0.00000010
    elif "llama-3-8b" in name_lower or "llama3-8b" in name_lower or "llama-3.1-8b" in name_lower:
        input_rate = 0.00000005
        output_rate = 0.00000008
    elif "llama-3-70b" in name_lower or "llama3-70b" in name_lower or "llama-3.1-70b" in name_lower:
        input_rate = 0.00000035
        output_rate = 0.00000040
    elif "claude-3-5-sonnet" in name_lower:
        input_rate = 0.00000300
        output_rate = 0.00001500
    elif "claude-3-haiku" in name_lower:
        input_rate = 0.00000025
        output_rate = 0.00000125

    input_cost = (input_tokens or 0) * input_rate
    output_cost = (output_tokens or 0) * output_rate
    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
    }
