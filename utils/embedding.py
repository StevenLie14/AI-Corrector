from config import embed_client

_EMBEDDING_MODEL = "text-embedding-3-small"


def get_embedding(text: str) -> tuple[list, int]:
    response = embed_client.embeddings.create(input=text, model=_EMBEDDING_MODEL)
    return response.data[0].embedding, response.usage.total_tokens


def get_embeddings_batch(texts: list[str]) -> tuple[list[list], int]:
    response = embed_client.embeddings.create(input=texts, model=_EMBEDDING_MODEL)
    vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    return vectors, response.usage.total_tokens
