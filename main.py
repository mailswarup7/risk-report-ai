from fastapi import FastAPI
from pydantic import BaseModel
import os
import requests

app = FastAPI()

class ChatPrompt(BaseModel):
    message: str

@app.post("/chat")
def chat_with_llm(prompt: ChatPrompt):
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    if not GROQ_API_KEY:
        return {"error": "Missing GROQ_API_KEY environment variable."}

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mixtral-8x7b-32768",
            "messages": [{"role": "user", "content": prompt.message}],
            "temperature": 0.5
        }

        response = requests.post(url, headers=headers, json=data)
        result = response.json()

        return {"reply": result["choices"][0]["message"]["content"]}

    except Exception as e:
        return {"error": str(e)}

