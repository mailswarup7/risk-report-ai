import os
import requests
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("dbmeshboard-firebase.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://db-meshboard-database-default-rtdb.asia-southeast1.firebasedatabase.app'
    })

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Context for message memory
chat_history = []

class ChatPrompt(BaseModel):
    message: str

@app.post("/chat")
async def chat_with_llm(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    # Maintain chat memory
    chat_history.append({"role": "user", "content": prompt.message})

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "You are a highly experienced Project Governance and Client Success Officer. Be detailed, analytical, and focused on client retention and project health."},
            *chat_history
        ],
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        message = result["choices"][0]["message"]["content"]
        chat_history.append({"role": "assistant", "content": message})
        return {"response": message}
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "debug_payload": payload,
            "response_text": response.text,
            "status_code": response.status_code
        }
    except KeyError:
        return {
            "error": "KeyError: 'choices' missing in Groq response",
            "full_response": response.text
        }

@app.get("/data/email-logs")
async def get_email_logs():
    try:
        ref = db.reference("/email-logs")  # Change this to your actual node
        data = ref.get()
        return {"data": data}
    except Exception as e:
        return {"error": str(e)}

