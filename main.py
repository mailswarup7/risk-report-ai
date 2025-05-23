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

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    # Lowercased version of the user query for fuzzy project match
    user_query = prompt.message.lower()

    def filter_data_by_project(rows, sheet_name):
        matches = []
        for row in rows:
            for cell in row.values():
                if isinstance(cell, str) and any(token in cell.lower() for token in user_query.split()):
                    matches.append(row)
                    break
        return matches

    index_matches = filter_data_by_project(index_data, "Index")
    extractor_matches = filter_data_by_project(extractor_data, "Email Extractor")
    manager_matches = filter_data_by_project(manager_data, "Email Manager")

    def summarize(data, label):
        if not data:
            return f"No relevant rows found in {label}.\n"
        preview = "\n".join([str(row) for row in data[:5]])  # Top 5 matching rows
        return f"--- {label} ---\n{preview}\n\n"

    context = (
        "You are a project governance and client success assistant.\n"
        "Use only the following filtered data to answer the user's current question.\n"
        "The data is extracted from Google Sheets and has been pre-filtered for relevance to the user query.\n\n"
        f"{summarize(index_matches, 'Index')}"
        f"{summarize(extractor_matches, 'Email Extractor')}"
        f"{summarize(manager_matches, 'Email Manager')}"
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
