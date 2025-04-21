import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chat schema that supports message history
class ChatPrompt(BaseModel):
    messages: List[Dict[str, str]]  # expects list of dicts like {"role": "user", "content": "..."}

@app.post("/chat")
async def chat_with_llm(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    url = "https://api.groq.com/openai/v1/chat/completions"

    # Add system prompt for governance assistant
    full_messages = [
        {"role": "system", "content": "You are a highly experienced Project Governance and Client Success Officer. Your job is to assess project health, risk of scope creep, client satisfaction, and delivery quality using governance best practices. Respond only based on project data and patterns."}
    ] + prompt.messages

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": full_messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return {"response": result["choices"][0]["message"]["content"]}
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

