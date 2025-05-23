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

    # Fetch sheet data
    index = fetch_sheet_data("index").get("data", [])
    extractor = fetch_sheet_data("extractor").get("data", [])
    manager = fetch_sheet_data("manager").get("data", [])

    # Smart context summarization
    def smart_preview(data, label):
        summary = f"--- {label} ---\n"
        if not data:
            return summary + "No data found.\n"
        for row in data[:5]:
            summary += str(row) + "\n"
        return summary + "\n"

    # Define full LLM context
    context = (
        "You are a highly analytical Project Governance & Client Success Assistant.\n"
        "Use the following structured sheet data to answer queries about:\n"
        "- Project risks\n- Scope creep\n- Overburn\n- Client pulse\n- Internal & client email discussions\n\n"
        f"{smart_preview(index, 'Index Sheet')}"
        f"{smart_preview(extractor, 'Email Extractor Sheet')}"
        f"{smart_preview(manager, 'Email Manager Sheet')}"
    )

    # GROQ call
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
        return {"response": response.json()["choices"][0]["message"]["content"]}
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

