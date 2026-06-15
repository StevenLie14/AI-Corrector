from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import embed_client
from config.constants import EMBED_MODEL

_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def get_embedding(text: str) -> tuple[list, int]:
    response = embed_client.embeddings.create(input=text, model=EMBED_MODEL)
    return response.data[0].embedding, response.usage.total_tokens


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def get_embeddings_batch(texts: list[str]) -> tuple[list[list], int]:
    response = embed_client.embeddings.create(input=texts, model=EMBED_MODEL)
    vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    return vectors, response.usage.total_tokens
