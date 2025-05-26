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

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "⚠️ GROQ_API_KEY not set in environment"}

    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    project_keywords = list({
        str(row.get("Project Name", "")).strip()
        for row in index_data + manager_data
        if row.get("Project Name")
    })

    user_query = prompt.message.strip().lower()
    matched_keywords = [kw for kw in project_keywords if kw.lower() in user_query]
    keywords_to_check = matched_keywords if matched_keywords else user_query.split()

    expanded_query = prompt.message
    if "scope creep" in user_query:
        expanded_query += (
            "\n\nPlease check if the project has introduced features, flows, or changes "
            "that were not listed in the original scope document, or if any approvals are missing."
        )

    def filter_and_limit(data, project_names):
        filtered = [row for row in data if str(row.get("Project Name", "")).lower() in [p.lower() for p in project_names]]
        return sorted(filtered, key=lambda x: x.get("Date", ""), reverse=True)[:10]

    relevant_index = filter_and_limit(index_data, matched_keywords)
    relevant_extractor = filter_and_limit(extractor_data, matched_keywords)
    relevant_manager = filter_and_limit(manager_data, matched_keywords)

    doc_context = get_scope_summary(matched_keywords[0]) if matched_keywords else ""
    doc_summary = f"--- 📄 Scope Document: {matched_keywords[0]} ---\n{doc_context.strip()}\n\n" if doc_context else ""

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

    if not relevant_index and not relevant_extractor and not relevant_manager and not doc_context:
        context = (
            "You are a project governance and client success assistant.\n\n"
            "The user asked a question, but no relevant scope or email records were found.\n"
            "Kindly advise them to follow up with the project team for more information."
        )
    else:
        context = (
            f"{doc_summary}"
            f"{summarize(relevant_index, 'Index')}"
            f"{summarize(relevant_extractor, 'Email Extractor')}"
            f"{summarize(relevant_manager, 'Email Manager')}"
        )

    instruction_header = (
        "You are an intelligent project governance and client success assistant AI.\n"
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

# ➕ Scope Summary, PDF, and Sheet APIs remain unchanged

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
    # (No changes required here. Already works as expected.)
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    keywords = ["scope creep", "not in scope", "added", "new", "expanded"]
    resolutions = ["approved", "acknowledged", "taken care", "phase 2"]

    def eval_status(row):
        t = " ".join([str(v).lower() for v in row.values()])
        if any(k in t for k in keywords): return "YES"
        if any(k in t for k in resolutions): return "NO"
        return "TBD"

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
    # (Also unchanged — generates A1, A2, A3 sectioned report as PDF)
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    keywords = ["scope creep", "not in scope", "added", "new", "expanded"]
    resolutions = ["approved", "acknowledged", "taken care", "phase 2"]

    def eval_status(row):
        t = " ".join([str(v).lower() for v in row.values()])
        if any(k in t for k in keywords): return "YES"
        if any(k in t for k in resolutions): return "NO"
        return "TBD"

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

