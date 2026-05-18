# Prices per 1M tokens in USD — verify these match your Azure deployment pricing
_PRICES: dict[str, dict[str, float]] = {
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "gpt-5.4-mini": {"input": 0.40, "output": 1.60},
    "vision": {"input": 0.015, "output": 0.0},  # blended rate — adjust to your vision model
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    prices = _PRICES.get(model, {"input": 0.0, "output": 0.0})
    cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
    return round(cost, 8)
