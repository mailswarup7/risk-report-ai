from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
import requests

app = FastAPI()

# Allow all frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatPrompt(BaseModel):
    message: str

@app.post("/chat")
def chat_with_llm(prompt: ChatPrompt):
    try:
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            return {"response": "⚠️ GROQ_API_KEY not set in environment"}

        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {"role": "system", "content": "You are an AI that helps project managers avoid risks."},
                    {"role": "user", "content": prompt.message}
                ],
                "temperature": 0.5
            }
        )

        response_data = res.json()
        return {
            "response": response_data["choices"][0]["message"]["content"]
        }

    except Exception as e:
        return {"response": f"Error: {str(e)}"}

