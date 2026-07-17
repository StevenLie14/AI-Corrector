"""One-off index migration: add the filterable `resource_id` field to the Azure AI Search index.

Run once per environment before deploying the idempotent feed:

    python scripts/add_resource_id_field.py

Adding a field to an existing index is non-destructive; existing documents keep
`resource_id = null` until they are re-fed.
"""

import os
import sys

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchField, SearchFieldDataType
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    endpoint = os.getenv("VECTORDB_URL")
    key = os.getenv("VECTORDB_KEY")
    if not endpoint or not key:
        print("VECTORDB_URL and VECTORDB_KEY must be set")
        return 1

    index_name = os.getenv("VECTORDB_INDEX", "lms-materials")
    field_name = os.getenv("VECTORDB_FIELD_RESOURCE_ID", "resource_id")

    client = SearchIndexClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    index = client.get_index(index_name)

    if any(f.name == field_name for f in index.fields):
        print(f"Field '{field_name}' already exists on index '{index_name}', nothing to do")
        return 0

    index.fields.append(
        SearchField(
            name=field_name,
            type=SearchFieldDataType.String,
            filterable=True,
            searchable=False,
            sortable=False,
            facetable=False,
        )
    )
    client.create_or_update_index(index)
    print(f"Field '{field_name}' added to index '{index_name}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
