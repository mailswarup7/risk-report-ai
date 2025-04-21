import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS so frontend can access the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the expected request body structure
class ChatMessage(BaseModel):
    sender: str  # 'user' or 'ai'
    text: str

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

    # Convert frontend sender/text to valid OpenAI role/content format
    converted_msgs = []
    for m in prompt.messages:
        role = "user" if m["sender"] == "user" else "assistant"
        converted_msgs.append({"role": role, "content": m["text"]})

    # Add a system prompt to guide the LLM’s persona
    full_messages = [
        {
            "role": "system",
            "content": (
                "You are a highly experienced Project Governance and Client Success Officer. "
                "Your job is to assess project health, scope risk, and delivery outcomes. "
                "Use structured insights, talk like a seasoned governance expert, and keep context from previous user messages."
            )
        }
    ] + converted_msgs

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

