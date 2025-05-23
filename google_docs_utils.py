from google.oauth2 import service_account
from googleapiclient.discovery import build
import os

# ✅ Define scopes for Sheets, Docs, and Drive
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

# ✅ Load credentials with scopes
credentials = service_account.Credentials.from_service_account_file(
    "google-sheets-access.json",
    scopes=SCOPES
)

# ✅ Connect to Google Drive and Docs
drive_service = build("drive", "v3", credentials=credentials)
docs_service = build("docs", "v1", credentials=credentials)

def get_doc_content_by_project(project_name: str) -> str:
    """Given a project name, fetch content from the corresponding Google Doc in the Drive folder."""
    folder_id = os.getenv("1a-qYT2xDpwVHLNPgsZos1wn8poMU4MOH")
    if not folder_id:
        return ""

    query = f"mimeType='application/vnd.google-apps.document' and '{folder_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    for file in files:
        if project_name.lower() in file["name"].lower():
            doc_id = file["id"]
            doc = docs_service.documents().get(documentId=doc_id).execute()
            content = doc.get("body", {}).get("content", [])
            text = "\n".join(
                elem.get("paragraph", {}).get("elements", [{}])[0].get("textRun", {}).get("content", "")
                for elem in content if "paragraph" in elem
            )
            return text.strip()

    return ""

