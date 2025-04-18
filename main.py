import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

app = FastAPI()

class ChatPrompt(BaseModel):
    message: str

@app.post("/chat")
def chat_with_llm(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    body = {
        "model": "mixtral-8x7b-32768",
        "messages": [
            {"role": "system", "content": "You are an AI project advisor. Help the user with tips about managing project risks and delivery."},
            {"role": "user", "content": prompt.message}
        ]
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=body
        )
        response.raise_for_status()
        data = response.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            return {"response": data["choices"][0]["message"]["content"]}
        else:
            return {"error": "⚠️ Unexpected response format from Groq API"}

    except Exception as e:
        return {"error": str(e)}

