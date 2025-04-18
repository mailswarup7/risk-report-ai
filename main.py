import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI()

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic model
class ChatPrompt(BaseModel):
    message: str

@app.post("/chat")
async def chat_with_llm(prompt: ChatPrompt):
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    if not GROQ_API_KEY:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mixtral-8x7b-32768",  # or use mixtral-8x7b if that's supported
        "messages": [
            {"role": "system", "content": "You are a project risk advisor AI. Keep responses concise and insightful."},
            {"role": "user", "content": prompt.message}
        ],
        "temperature": 0.7
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
        return {"response": data["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"error": str(e)}
