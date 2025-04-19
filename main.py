import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatPrompt(BaseModel):
    message: str

# Simple in-memory chat history (use user/session ID in production)
chat_history = []

@app.post("/chat")
async def chat_with_llm(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "\u26a0\ufe0f GROQ_API_KEY not set in environment"}

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Add the user's message to history
    chat_history.append({"role": "user", "content": prompt.message})

    # Persona system prompt
    system_prompt = {
        "role": "system",
        "content": (
            "You are a project governance and client success expert at a software company. "
            "You specialize in identifying project risks like scope creep, overburn, client dissatisfaction, and delivery slippages. "
            "When a user asks about project health, always ask for context like project name, delivery timelines, and recent risks. "
            "Your job is to read project data and give insightful, actionable responses. "
            "Keep answers short, sharp, and use simple language suitable for COOs and Delivery Heads."
        )
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [system_prompt] + chat_history,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        print("== Request Payload ==")
        print(payload)
        print("== Response Text ==")
        print(response.text)
        response.raise_for_status()
        result = response.json()

        # Append assistant's reply to history
        assistant_reply = result["choices"][0]["message"]["content"]
        chat_history.append({"role": "assistant", "content": assistant_reply})

        return {"response": assistant_reply}

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

