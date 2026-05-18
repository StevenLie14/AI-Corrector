from config import embed_client


def get_embedding(text: str) -> list:
    response = embed_client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
    )
    return response.data[0].embedding
