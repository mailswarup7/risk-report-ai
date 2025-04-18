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

@app.post("/chat")
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

