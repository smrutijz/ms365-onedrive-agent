import requests
import json


def search_drive_items(
    access_token,
    query_string,
    query_template=None,
    semantic_query=None,
    region="APAC",
    size=25,
    offset=0,
    fields=None
):
    """
    Search OneDrive/SharePoint using Microsoft Graph Beta Search API.

    :param access_token: OAuth token
    :param query_string: The search text (e.g., "smruti")
    :param query_template: Optional KQL template (e.g., "filename:{searchTerms}")
    :param semantic_query: Optional semantic search text (beta only)
    :param region: Data region (e.g., "APAC", "NAM", "EMEA", "JPN" Default "APAC")
    :param size: Number of results to return
    :param offset: Pagination offset
    :param fields: Optional list of fields to return
    """

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Build query object
    query_obj = {"queryString": query_string}

    if query_template:
        query_obj["queryTemplate"] = query_template #KQL template using {searchTerms}

    # Base request
    request_obj = {
        "entityTypes": ["driveItem"],
        "query": query_obj,
        "region": region,
        "from": offset,
        "size": size
    }

    # ✅ Add semanticQuery only if provided
    if semantic_query:
        request_obj["semanticQuery"] = {
            "query": semantic_query
        }

    # ✅ Add fields if provided
    if fields:
        request_obj["fields"] = fields

    body = {"requests": [request_obj]}

    response = requests.post(
        "https://graph.microsoft.com/beta/search/query",
        headers=headers,
        json=body
        )

    if response.status_code != 200:
        raise Exception(
            f"Graph API Error {response.status_code}: {response.text}"
        )

    return response.json()


# ✅ Example usage
if __name__ == "__main__":
    ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"


    results = search_drive_items(
        access_token=ACCESS_TOKEN,
        query_string="smruti",  # the user’s search terms
        query_template=(
            "path:\"/Documents/Projects/\" AND filetype:pdf "
            "AND (filename:{searchTerms} OR content:{searchTerms})"
        ),
        semantic_query="documents related to smruti resume",
        region="APAC",
        size=50,
        offset=0,
        fields=["name", "webUrl", "lastModifiedDateTime", "createdBy"]
    )
    print(json.dumps(results, indent=4))