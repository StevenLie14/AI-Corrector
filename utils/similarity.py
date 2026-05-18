import math

from .embedding import get_embeddings_batch
from .extraction import chunk_text

_SHORT_WORD_THRESHOLD = 500
_TOP_K = 10


def _cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def select_relevant_chunks(text: str, question: str, top_k: int = _TOP_K) -> tuple[str, int]:
    """
    Returns (relevant_text, embedding_tokens_used).
    If the text is short enough, returns it as-is with 0 tokens used.
    Otherwise chunks it, embeds question + chunks, and returns the top-k
    most semantically similar chunks (order preserved).
    """
    if len(text.split()) <= _SHORT_WORD_THRESHOLD:
        return text, 0

    chunks = chunk_text(text)
    if len(chunks) <= top_k:
        return text, 0

    all_vectors, tokens = get_embeddings_batch([question] + chunks)
    question_vector = all_vectors[0]
    chunk_vectors = all_vectors[1:]

    similarities = [_cosine_similarity(question_vector, cv) for cv in chunk_vectors]

    top_indices = sorted(
        sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)[:top_k]
    )

    return "\n\n".join(chunks[i] for i in top_indices), tokens
