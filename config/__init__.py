import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

_REQUIRED_VARS = ["EMBED_URL", "EMBED_KEY", "VECTORDB_KEY", "VECTORDB_URL", "MODEL_URL", "MODEL_KEY"]
_missing = [k for k in _REQUIRED_VARS if not os.getenv(k)]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {_missing}")

embed_client = AzureOpenAI(
    azure_endpoint=os.getenv("EMBED_URL"),
    api_key=os.getenv("EMBED_KEY"),
    api_version="2024-12-01-preview",
)

credential = AzureKeyCredential(os.getenv("VECTORDB_KEY"))
search_client = SearchClient(
    endpoint=os.getenv("VECTORDB_URL"),
    index_name="lms-materials",
    credential=credential,
)
