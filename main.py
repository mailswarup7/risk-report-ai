from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import os
import requests
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from sheets_utils import fetch_sheet_data
from google_docs_utils import get_scope_summary

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

def row_matches_query(row, keywords):
    text = " ".join([str(cell).lower() for cell in row.values()])
    return any(keyword.lower() in text for keyword in keywords)

def format_row(row):
    keys = ["Email Record ID", "Date", "From", "Subject", "Body", "Project Name", "Insights"]
    return {k: row.get(k, "") for k in keys if k in row}

def truncate_text(text, max_chars=15000):
    return text[:max_chars]

# --- ENHANCED KEYWORDS for eval_status ---
keywords = [
    "scope creep", "not in scope", "out of scope", "added", "new", "expanded", "unplanned",
    "unexpected", "extra", "missed in original scope", "client requested change", "additional work",
    "requirement change", "wasn’t discussed", "assumption mismatch", "change request",
    "increase in scope", "modification", "gap"
]
resolutions = [
    "approved", "acknowledged", "taken care", "phase 2", "will be handled later", "excluded from scope",
    "client agreed", "deprioritized", "confirmed for next phase", "signed off", "clarified", "approved change"
]

def classify_scope_creep_with_llm(text):
    api_key = os.getenv("GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert project analyst. Read the text and decide if it shows:\n"
                "1. Scope Creep (YES)\n"
                "2. Resolved or Approved Changes (NO)\n"
                "3. Not Sure or No Clear Signal (TBD)\n\n"
                "Reply with only YES, NO, or TBD."
            )
        },
        {"role": "user", "content": text[:4000]}
    ]
    payload = {"model": "llama3-8b-8192", "messages": messages, "temperature": 0.1}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        res.raise_for_status()
        result = res.json()["choices"][0]["message"]["content"].strip().upper()
        return result if result in ["YES", "NO", "TBD"] else "TBD"
    except Exception:
        return "TBD"

def find_best_project_update(data, project_name=None):
    """Finds the latest, most informative update about progress/status for a given project."""
    # Priority: % Completion, demo, milestone, status, appreciation, etc.
    for row in sorted(data, key=lambda x: x.get("Date", ""), reverse=True):
        text = " ".join([str(row.get(k, "")) for k in row.keys()]).lower()
        if project_name and project_name.lower() not in text:
            continue
        if "%" in text or "completion" in text or "milestone" in text or "demo" in text:
            return row
    # fallback: return latest
    if data:
        return sorted(data, key=lambda x: x.get("Date", ""), reverse=True)[0]
    return None

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    all_data = index_data + extractor_data + manager_data

    project_keywords = list({
        str(row.get("Project Name", "")).strip()
        for row in all_data
        if row.get("Project Name")
    })

    user_query = prompt.message.strip().lower()
    matched_keywords = [kw for kw in project_keywords if kw.lower() in user_query]
    keywords_to_check = matched_keywords if matched_keywords else user_query.split()

    # 1. Always try to find the best, latest evidence from data
    best_row = None
    for kw in keywords_to_check:
        best_row = find_best_project_update(all_data, project_name=kw)
        if best_row:
            break
    if not best_row:
        best_row = find_best_project_update(all_data)  # fallback to any

    # 2. Build doc_context if project is found
    doc_context = get_scope_summary(matched_keywords[0]) if matched_keywords else ""
    doc_summary = f"--- 📄 Scope Document: {matched_keywords[0]} ---\n{doc_context.strip()}\n\n" if doc_context else ""

    # 3. Standard context, but include actual latest evidence if possible!
    context = ""
    if best_row:
        context += "\n--- 📈 LATEST EVIDENCE ---\n"
        context += "\n".join([f"{k}: {v}" for k, v in best_row.items() if v])
        context += "\n\n"

    def summarize(data, label):
        if not data:
            return f"No data available in {label}.\n"
        try:
            data_sorted = sorted(data, key=lambda x: x.get("Date", ""), reverse=True)
        except Exception:
            data_sorted = data
        latest = [format_row(row) for row in data_sorted[:5]]
        open_concerns = [format_row(row) for row in data_sorted if any(k in str(row).lower() for k in ["issue", "delay", "blocked", "escalated"])]
        completed = [format_row(row) for row in data_sorted if any(k in str(row).lower() for k in ["100%", "completed", "finalized", "signed off"])]
        output = f"--- 📬 {label} ---\n\n📊 Latest Entries:\n" + "\n".join([str(r) for r in latest]) + "\n"
        if open_concerns:
            output += "\n⚠️ Open Concerns:\n" + "\n".join([str(r) for r in open_concerns[:3]]) + "\n"
        if completed:
            output += "\n✅ Completed Milestones:\n" + "\n".join([str(r) for r in completed[:3]]) + "\n"
        return output + "\n"

    if not best_row and not doc_context:
        context += (
            "You are a project governance and client success assistant.\n\n"
            "The user asked a question, but no relevant scope or email records were found.\n"
            "Kindly advise them to follow up with the project team for more information."
        )
    else:
        context = (
            f"{doc_summary}"
            f"{context}"
            f"{summarize(index_data, 'Index')}"
            f"{summarize(extractor_data, 'Email Extractor')}"
            f"{summarize(manager_data, 'Email Manager')}"
        )

    instruction_header = (
        "You are an intelligent project governance and client success assistant AI.\n"
        "You have access to all project emails and logs. Search for any evidence, even if not in the latest updates. "
        "Be specific in your findings. When a user asks about any kind of event (appreciation, bugs, risks, etc.), "
        "scan ALL available records and answer with the best evidence you can find. Quote from emails if possible.\n"
        "Your goals:\n"
        "1. Detect scope creep from scope vs email.\n"
        "2. Identify delays, risks, and new requests.\n"
        "3. Read tone of emails to understand client pulse.\n"
        "4. Compare assumptions vs delivery reality.\n"
        "5. Suggest PM best practices (Agile, PMP) if gaps found.\n"
        "Always back up your reasoning with facts from the content.\n\n"
    )

    final_context = truncate_text(instruction_header + context)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": final_context},
            {"role": "user", "content": expanded_query}
        ],
        "temperature": 0.3
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return {"response": result["choices"][0]["message"]["content"]}
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "payload": payload,
            "response_text": getattr(e.response, "text", ""),
            "status_code": getattr(e.response, "status_code", "")
        }

@app.get("/data/index-sheet")
async def get_index_sheet_data():
    return fetch_sheet_data("index")

@app.get("/data/email-extractor")
async def get_email_extractor_data():
    return fetch_sheet_data("extractor")

@app.get("/data/email-manager")
async def get_email_manager_data():
    return fetch_sheet_data("manager")

@app.get("/risk-report/scope-creep/summary")
async def get_scope_creep_summary():
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    def eval_status(row):
        t = " ".join([str(v).lower() for v in row.values()])
        if any(k in t for k in keywords): return "YES"
        if any(k in t for k in resolutions): return "NO"
        return classify_scope_creep_with_llm(t)

    summary = [
        {
            "project": row.get("Project Name", ""),
            "bu": row.get("BU", ""),
            "solution_center": row.get("Solution Center", ""),
            "status": eval_status(row)
        }
        for row in index_data
    ]

    signals = [
        {k: r.get(k, "") for k in ["Project", "Mode", "Date", "Insights"]}
        for r in extractor_data + manager_data
        if any(k in str(r.get("Insights", "")).lower() for k in keywords)
    ]

    corrective = [
        {k: r.get(k, "") for k in ["Project", "Mode", "Date", "Insights"]}
        for r in extractor_data + manager_data
        if any(k in str(r.get("Insights", "")).lower() for k in resolutions)
    ]

    return JSONResponse(content={
        "summary": summary,
        "signals": signals,
        "corrective": corrective
    })

@app.get("/risk-report/scope-creep/pdf")
async def generate_scope_creep_pdf():
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    def eval_status(row):
        t = " ".join([str(v).lower() for v in row.values()])
        if any(k in t for k in keywords): return "YES"
        if any(k in t for k in resolutions): return "NO"
        return classify_scope_creep_with_llm(t)

    summary = [
        {
            "Project Name": row.get("Project Name", ""),
            "BU": row.get("BU", ""),
            "Solution Center": row.get("Solution Center", ""),
            "SCOPE CREEP SIGNAL": eval_status(row)
        }
        for row in index_data
    ]

    signals = [
        r for r in extractor_data + manager_data
        if any(k in str(r.get("Insights", "")).lower() for k in keywords)
    ]

    corrective = [
        r for r in extractor_data + manager_data
        if any(k in str(r.get("Insights", "")).lower() for k in resolutions)
    ]

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(temp_file.name, pagesize=A4)
    width, height = A4
    y = height - 50

    def draw_header(title):
        nonlocal y
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, title)
        y -= 30

    def draw_table(headers, rows, bullet_colors=None):
        nonlocal y
        c.setFont("Helvetica-Bold", 11)
        x_pos = [40, 200, 350, 480]
        for i, h in enumerate(headers):
            c.drawString(x_pos[i], y, h)
        y -= 18
        c.setFont("Helvetica", 10)
        for row in rows:
            if y < 100:
                c.showPage()
                y = height - 50
            for i, k in enumerate(headers):
                t = str(row.get(k, ""))
                if bullet_colors and i == len(headers) - 1:
                    c.setFillColor(bullet_colors.get(t, colors.grey))
                    c.circle(x_pos[i] - 10, y + 3, 5, fill=1)
                    c.setFillColor(colors.black)
                c.drawString(x_pos[i], y, t)
            y -= 15

    def draw_log(title, rows):
        nonlocal y
        draw_header(title)
        headers = ["Project", "Mode", "Date", "Insights"]
        x_pos = [40, 150, 250, 320]
        c.setFont("Helvetica-Bold", 11)
        for i, h in enumerate(headers):
            c.drawString(x_pos[i], y, h)
        y -= 18
        c.setFont("Helvetica", 10)
        for row in rows:
            if y < 100:
                c.showPage()
                y = height - 50
            for i, k in enumerate(headers):
                c.drawString(x_pos[i], y, str(row.get(k, ""))[:90])
            y -= 15

    draw_header("Scope Creep Summary Report")
    draw_header("A.1 Summary View")
    draw_table(
        ["Project Name", "BU", "Solution Center", "SCOPE CREEP SIGNAL"],
        summary,
        bullet_colors={"YES": colors.red, "NO": colors.green, "TBD": colors.gray}
    )
    draw_log("A.2 Scope Creep Signal Log", signals)
    draw_log("A.3 Corrective Measures Taken Log", corrective)

    c.showPage()
    c.save()
    return FileResponse(temp_file.name, filename="ScopeCreepSummary.pdf", media_type="application/pdf")

