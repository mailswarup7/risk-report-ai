import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Message structure for context memory
chat_memory = []

class ChatPrompt(BaseModel):
    message: str

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

    # Maintain chat context
    chat_memory.append({"role": "user", "content": prompt.message})

    full_messages = [
        {
            "role": "system",
            "content": (
                "You are a highly experienced Project Governance and Client Success Officer. "
                "Your role is to identify risks, delivery gaps, or performance concerns in projects. "
                "Format responses cleanly using bullet points, bold section headers, or short readable paragraphs. "
                "If the user asks about project risks, delays, or quality issues, give answers that can be directly shown in a dashboard. "
                "Avoid long paragraphs. Focus on clarity, structure, and executive-summary-style reporting."
            )
        }
    ] + chat_memory[-5:]  # Keep only the last 5 for brevity

    payload = {
        "model": "llama3-8b-8192",
        "messages": full_messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        chat_memory.append({"role": "assistant", "content": reply})
        return {"response": reply}

    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "debug_payload": payload,
            "response_text": response.text if 'response' in locals() else "No response",
            "status_code": response.status_code if 'response' in locals() else "No status"
        }
    except KeyError:
        return {
            "error": "KeyError: 'choices' missing in Groq response",
            "full_response": response.text if 'response' in locals() else "No response"
        }

