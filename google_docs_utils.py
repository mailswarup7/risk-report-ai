from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import requests

# ✅ Define scopes
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

# ✅ Load credentials
credentials = service_account.Credentials.from_service_account_file(
    "google-sheets-access.json", scopes=SCOPES
)

# ✅ Build clients
drive_service = build("drive", "v3", credentials=credentials)
docs_service = build("docs", "v1", credentials=credentials)

def summarize_with_llm(raw_text: str) -> str:
    """Send raw doc content to Groq for summary"""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return raw_text[:1500]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    summarizer_prompt = (
        "You are a project scope summarizer. Summarize the following scope document clearly, preserving module names, flows, business goals, timelines, and deliverables.\n"
        + raw_text[:6000]
    )

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json={
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": "You are a scope summarizer for project governance."},
                {"role": "user", "content": summarizer_prompt}
            ],
            "temperature": 0.3
        }
    )

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        return raw_text[:1500]  # fallback

def get_scope_summary(project_name: str) -> str:
    """Finds the doc by project name and returns summarized content"""
    folder_id = os.getenv("GOOGLE_DOCS_FOLDER_ID")
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
            raw_text = "\n".join(
                elem.get("paragraph", {}).get("elements", [{}])[0].get("textRun", {}).get("content", "")
                for elem in content if "paragraph" in elem
            )
            return summarize_with_llm(raw_text.strip())

    return ""
