import os
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

load_dotenv()

embed_client = AzureOpenAI(
    azure_endpoint=os.getenv("EMBED_URL"),
    api_key=os.getenv("EMBED_KEY"),
    api_version="2024-12-01-preview"
)

credential = AzureKeyCredential(os.getenv("VECTORDB_KEY"))
search_client = SearchClient(
    endpoint=os.getenv("VECTORDB_URL"),
    index_name="lms-materials",
    credential=credential
)