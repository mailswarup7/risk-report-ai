from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import os
import requests
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from sheets_utils import fetch_sheet_data
from google_docs_utils import get_scope_summary

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatPrompt(BaseModel):
    message: str

def row_matches_query(row, keywords):
    text = " ".join([str(cell).lower() for cell in row.values()])
    return any(keyword.lower() in text for keyword in keywords)

def format_row(row):
    keys = ["Email Record ID", "Date", "From", "Subject", "Body"]
    return {k: row.get(k, "") for k in keys if k in row}

def chunk_text(text, max_tokens=5000):
    return text[:max_tokens * 4]

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    project_keywords = list({
        str(row.get("Project Name", "")).strip()
        for row in index_data + manager_data
        if row.get("Project Name")
    })

    user_query = prompt.message.strip().lower()
    matched_keywords = [kw for kw in project_keywords if kw.lower() in user_query]
    keywords_to_check = matched_keywords if matched_keywords else user_query.split()

    expanded_query = prompt.message
    if "scope creep" in user_query:
        expanded_query += (
            "\n\nPlease check if the project has introduced features, flows, or changes "
            "that were not listed in the original scope document, or if any approvals are missing."
        )

    def get_relevant_rows(data, keywords):
        keyword_rows = [row for row in data if row_matches_query(row, keywords)]
        recent_rows = data[-5:] if len(data) >= 5 else data
        return list({id(row): row for row in keyword_rows + recent_rows}.values())

    relevant_index = get_relevant_rows(index_data, keywords_to_check)
    relevant_extractor = get_relevant_rows(extractor_data, keywords_to_check)
    relevant_manager = get_relevant_rows(manager_data, keywords_to_check)

    doc_context = get_scope_summary(matched_keywords[0]) if matched_keywords else ""
    doc_summary = f"--- 📄 Scope Document: {matched_keywords[0]} ---\n{doc_context.strip()}\n\n" if doc_context else ""

    def summarize(data, label):
        if not data:
            return f"No data available in {label}.\n"

        try:
            data_sorted = sorted(data, key=lambda x: x.get("Date", ""), reverse=True)
        except Exception:
            data_sorted = data

        latest_updates = []
        open_concerns = []
        completed_milestones = []
        recent_rows = []

        for row in data_sorted:
            row_str = str(format_row(row))
            row_lower = row_str.lower()
            recent_rows.append(row_str)

            if any(k in row_lower for k in ["completed", "100%", "signed off", "finalized"]):
                completed_milestones.append(row_str)
            elif any(k in row_lower for k in ["issue", "delay", "pending", "concern", "blocked", "escalated"]):
                open_concerns.append(row_str)
            else:
                latest_updates.append(row_str)

        sectioned_output = f"--- 📬 {label} ---\n"
        sectioned_output += "\n📊 Recent Entries:\n" + "\n".join(recent_rows[:5]) + "\n"
        if open_concerns:
            sectioned_output += "\n⚠️ Open Concerns:\n" + "\n".join(open_concerns[:3]) + "\n"
        if completed_milestones:
            sectioned_output += "\n✅ Completed Milestones:\n" + "\n".join(completed_milestones[:3]) + "\n"
        return sectioned_output + "\n"

    if not relevant_index and not relevant_extractor and not relevant_manager and not doc_context:
        context = (
            "You are a project governance and client success assistant.\n\n"
            "The user asked a question, but no relevant scope or email records were found.\n"
            "Kindly advise them to follow up with the project team for more information."
        )
    else:
        context = (
            f"{doc_summary}"
            f"{summarize(relevant_index, 'Index')}"
            f"{summarize(relevant_extractor, 'Email Extractor')}"
            f"{summarize(relevant_manager, 'Email Manager')}"
        )

    instruction_header = (
        "You are an intelligent project governance and client success assistant AI.\n"
        "Your goals:\n"
        "1. Detect scope creep from scope vs email.\n"
        "2. Identify delays, risks, and new requests.\n"
        "3. Read tone of emails to understand client pulse.\n"
        "4. Compare assumptions vs delivery reality.\n"
        "5. Suggest PM best practices (Agile, PMP) if gaps found.\n"
        "Always back up your reasoning with facts from the content.\n\n"
    )

    safe_context = chunk_text(context, max_tokens=5000)
    final_payload = instruction_header + safe_context
    print("Tokenized content length (approx):", len(final_payload) // 4)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": final_payload},
            {"role": "user", "content": expanded_query}
        ],
        "temperature": 0.3
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return {"response": result["choices"][0]["message"]["content"]}
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "payload": payload,
            "response_text": getattr(e.response, "text", ""),
            "status_code": getattr(e.response, "status_code", "")
        }

# All other endpoints (/data, /summary, /pdf) stay unchanged.
# Keep this as-is from your working version unless you have further edits needed.
