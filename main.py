from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import requests
from sheets_utils import fetch_sheet_data

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatPrompt(BaseModel):
    message: str

def extract_relevant_rows(sheet, keywords):
    """Filter rows where any cell contains one of the keywords (case insensitive)"""
    if not sheet:
        return []

    filtered = []
    for row in sheet:
        row_text = " ".join([str(cell).lower() for cell in row.values()])
        if any(kw.lower() in row_text for kw in keywords):
            filtered.append(row)
    return filtered

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    # Load raw data from sheets
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    # Project name keywords to detect weak signals like 'Gro Digital'
    keywords = ["gro", "gro digital", "letsgo", "letsgro", "freight", "fleet", "bss narayan", "abhishek srivastava"]

    # Apply filtering for keyword matching rows (low visibility project boosting)
    relevant_manager_rows = extract_relevant_rows(manager_data, keywords)
    relevant_extractor_rows = extract_relevant_rows(extractor_data, keywords)
    relevant_index_rows = extract_relevant_rows(index_data, keywords)

    def summarize(data, label):
        if not data:
            return f"No data available in {label}.\n"
        preview = "\n".join([str(row) for row in data[:3]])  # First 3 rows
        return f"--- {label} ---\n{preview}\n\n"

    # Assemble the LLM context
    context = (
        "You are a project governance and client success assistant.\n"
        "Use the following extracted context from internal email/project logs to answer user questions "
        "about project risks, scope creep, client status, SPOC, and delivery progress.\n"
        "Even if the project has only one email reference, try to use that context if it's relevant.\n\n"
        f"{summarize(relevant_index_rows, 'Index Sheet (filtered)')}"
        f"{summarize(relevant_extractor_rows, 'Email Extractor (filtered)')}"
        f"{summarize(relevant_manager_rows, 'Email Manager (filtered)')}"
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": context},
            {"role": "user", "content": prompt.message}
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

@app.get("/data/index-sheet")
async def get_index_sheet_data():
    return fetch_sheet_data("index")

@app.get("/data/email-extractor")
async def get_email_extractor_data():
    return fetch_sheet_data("extractor")

@app.get("/data/email-manager")
async def get_email_manager_data():
    return fetch_sheet_data("manager")

