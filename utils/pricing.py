import os

from config.constants import EMBED_MODEL, LLM_MODEL, VISION_MODEL_KEY


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


_PRICES: dict[str, dict[str, float]] = {
    EMBED_MODEL: {
        "input": _env_float("PRICE_EMBED_INPUT", 0.022),
        "output": _env_float("PRICE_EMBED_OUTPUT", 0.0),
    },
    LLM_MODEL: {
        "input": _env_float("PRICE_LLM_INPUT", 0.75),
        "output": _env_float("PRICE_LLM_OUTPUT", 4.50),
    },
    VISION_MODEL_KEY: {
        "input": _env_float("PRICE_VISION_INPUT", 2.50),
        "output": _env_float("PRICE_VISION_OUTPUT", 10.0),
    },
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    p = _PRICES.get(model, {"input": 0.0, "output": 0.0})
    cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
    return round(cost, 8)
