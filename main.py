import os
import json
import requests
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

# Initialize Firebase
cred = credentials.Certificate("dbmeshboard-firebase.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://db-meshboard-database-default-rtdb.asia-southeast1.firebasedatabase.app'
})

# Initialize FastAPI
app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== FIREBASE ROUTE ==========

@app.get("/data/email-logs")
def get_email_logs():
    ref = db.reference("/emailLogs")
    data = ref.get()
    return {"data": data}

# ========== AI CHAT ROUTE ==========

class ChatPrompt(BaseModel):
    messages: List[Dict[str, str]]

@app.post("/chat")
async def chat_with_llm(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "You are a highly experienced Project Governance and Client Success Officer. Provide helpful, structured responses based on internal delivery review formats. Be concise but insightful."}
        ] + [{"role": "user" if msg["sender"] == "user" else "assistant", "content": msg["text"]} for msg in prompt.messages],
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return {
            "response": result["choices"][0]["message"]["content"]
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "debug_payload": payload,
            "response_text": response.text if 'response' in locals() else None
        }

