from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fetchers.firebase import get_email_logs
from analyzers.risk_llm import prompt_llm_with_email_data
import subprocess

app = FastAPI()

# Allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to ["http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chat prompt structure
class ChatPrompt(BaseModel):
    message: str

@app.post("import os
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 🌐 Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔐 Groq LLM Key
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "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"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_prompt = data.get("message", "")

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {"role": "system", "content": "You're a smart assistant that helps understand project risks, client pulse, and scope creep."},
                    {"role": "user", "content": user_prompt}
                ]
            }
        )
        content = response.json()["choices"][0]["message"]["content"]
        return {"response": content}
    except Exception as e:
        return {"error": str(e)}
")
def chat_with_llm(prompt: ChatPrompt):
    system_prompt = f"""
You are a helpful assistant. Answer the following user prompt concisely.

Prompt: {prompt.message}
"""

    process = subprocess.Popen(["ollama", "run", "mistral"],
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(system_prompt.encode())
    return {"response": stdout.decode("utf-8")}

@app.get("/risk-report/email")
def get_risk_report_from_email():
    email_logs = get_email_logs()
    if not email_logs:
        return {"risk_analysis": []}
    risk_report = prompt_llm_with_email_data(email_logs)
    return {"risk_analysis": risk_report}

@app.get("/debug/email-data")
def debug_email_logs():
    email_logs = get_email_logs()
    return {"email_logs": email_logs}

