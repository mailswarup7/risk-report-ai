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

    relevant_index = [row for row in index_data if row_matches_query(row, keywords_to_check)]
    relevant_extractor = [row for row in extractor_data if row_matches_query(row, keywords_to_check)]
    relevant_manager = [row for row in manager_data if row_matches_query(row, keywords_to_check)]

    doc_context = get_scope_summary(matched_keywords[0]) if matched_keywords else ""
    doc_summary = f"--- 📄 Scope Document: {matched_keywords[0]} ---\n{doc_context.strip()}\n\n" if doc_context else ""

    def summarize(data, label):
        if not data:
            return f"No data available in {label}.\n"

        try:
            data_sorted = sorted(data, key=lambda x: x.get("Date", ""), reverse=True)
        except Exception:
            data_sorted = data

        latest_updates = []
        open_concerns = []
        completed_milestones = []

        for row in data_sorted[:10]:
            row_str = str(row)
            row_lower = row_str.lower()

            if any(k in row_lower for k in ["completed", "100%", "signed off", "finalized"]):
                completed_milestones.append(row_str)
            elif any(k in row_lower for k in ["issue", "delay", "pending", "concern", "blocked", "escalated"]):
                open_concerns.append(row_str)
            else:
                latest_updates.append(row_str)

        sectioned_output = f"--- 📬 {label} ---\n"
        if latest_updates:
            sectioned_output += "\n📊 Latest Status Updates:\n" + "\n".join(latest_updates[:3]) + "\n"
        if open_concerns:
            sectioned_output += "\n⚠️ Open Concerns:\n" + "\n".join(open_concerns[:3]) + "\n"
        if completed_milestones:
            sectioned_output += "\n✅ Completed Milestones:\n" + "\n".join(completed_milestones[:3]) + "\n"

        return sectioned_output + "\n"

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

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": instruction_header + context},
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

    scope_creep_keywords = [
        "scope creep", "not in scope", "out of scope", "added",
        "new module", "new flow", "change request", "requirement changed",
        "change in plan", "beyond agreed", "expanded scope"
    ]

    resolution_keywords = [
        "phase 2", "not included", "taken care", "will be done later",
        "approved", "acknowledged", "follow-up", "client approved", "deferred"
    ]

    def evaluate_scope_creep_status(row):
        combined_text = " ".join([str(v).lower() for v in row.values()])
        if any(k in combined_text for k in scope_creep_keywords):
            return "YES"
        elif any(k in combined_text for k in resolution_keywords):
            return "NO"
        return "TBD"

    summary_view = [
        {
            "project": row.get("Project Name", ""),
            "bu": row.get("BU", ""),
            "solution_center": row.get("Solution Center", ""),
            "status": evaluate_scope_creep_status(row)
        }
        for row in index_data
    ]

    scope_creep_signals = [
        {
            "project": row.get("Project", ""),
            "mode": row.get("Mode", ""),
            "date": row.get("Date", ""),
            "insights": row.get("Insights", "")
        }
        for row in extractor_data + manager_data
        if any(k in str(row.get("Insights", "")).lower() for k in scope_creep_keywords)
    ]

    corrective_measures = [
        {
            "project": row.get("Project", ""),
            "mode": row.get("Mode", ""),
            "date": row.get("Date", ""),
            "insights": row.get("Insights", "")
        }
        for row in extractor_data + manager_data
        if any(k in str(row.get("Insights", "")).lower() for k in resolution_keywords)
    ]

    return JSONResponse(content={
        "summary": summary_view,
        "signals": scope_creep_signals,
        "corrective": corrective_measures
    })

@app.get("/risk-report/scope-creep/pdf")
async def generate_scope_creep_pdf():
    index_data = fetch_sheet_data("index")["data"]
    extractor_data = fetch_sheet_data("extractor")["data"]
    manager_data = fetch_sheet_data("manager")["data"]

    scope_creep_keywords = [
        "scope creep", "not in scope", "out of scope", "added",
        "new module", "new flow", "change request", "requirement changed",
        "change in plan", "beyond agreed", "expanded scope"
    ]

    resolution_keywords = [
        "phase 2", "not included", "taken care", "will be done later",
        "approved", "acknowledged", "follow-up", "client approved", "deferred"
    ]

    def evaluate_scope_creep_status(row):
        combined_text = " ".join([str(v).lower() for v in row.values()])
        if any(k in combined_text for k in scope_creep_keywords):
            return "YES"
        elif any(k in combined_text for k in resolution_keywords):
            return "NO"
        return "TBD"

    summary_data = [
        {
            "Project Name": row.get("Project Name", ""),
            "BU": row.get("BU", ""),
            "Solution Center": row.get("Solution Center", ""),
            "SCOPE CREEP SIGNAL": evaluate_scope_creep_status(row)
        }
        for row in index_data
    ]

    signal_log = [
        row for row in extractor_data + manager_data
        if any(k in str(row.get("Insights", "")).lower() for k in scope_creep_keywords)
    ]

    corrective_log = [
        row for row in extractor_data + manager_data
        if any(k in str(row.get("Insights", "")).lower() for k in resolution_keywords)
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
        x_positions = [40, 200, 350, 480]
        for i, header in enumerate(headers):
            c.drawString(x_positions[i], y, header)
        y -= 18
        c.setFont("Helvetica", 10)
        for row in rows:
            if y < 100:
                c.showPage()
                y = height - 50
            for i, key in enumerate(headers):
                text = str(row.get(key, ""))
                if bullet_colors and i == len(headers) - 1:
                    color = bullet_colors.get(text, colors.grey)
                    c.setFillColor(color)
                    c.circle(x_positions[i] - 10, y + 3, 5, fill=1)
                    c.setFillColor(colors.black)
                c.drawString(x_positions[i], y, text)
            y -= 15

    def draw_log_table(title, data):
        nonlocal y
        draw_header(title)
        headers = ["Project", "Mode", "Date", "Insights"]
        x_pos = [40, 150, 250, 320]
        c.setFont("Helvetica-Bold", 11)
        for i, h in enumerate(headers):
            c.drawString(x_pos[i], y, h)
        y -= 18
        c.setFont("Helvetica", 10)
        for row in data:
            if y < 100:
                c.showPage()
                y = height - 50
            c.drawString(x_pos[0], y, row.get("Project", ""))
            c.drawString(x_pos[1], y, row.get("Mode", ""))
            c.drawString(x_pos[2], y, row.get("Date", ""))
            c.drawString(x_pos[3], y, str(row.get("Insights", ""))[:80])
            y -= 15

    draw_header("Scope Creep Summary Report")
    draw_header("A.1 Summary View")
    draw_table(
        headers=["Project Name", "BU", "Solution Center", "SCOPE CREEP SIGNAL"],
        rows=summary_data,
        bullet_colors={"YES": colors.red, "NO": colors.green, "TBD": colors.gray}
    )
    draw_log_table("A.2 Scope Creep Signal Log", signal_log)
    draw_log_table("A.3 Corrective Measures Taken Log", corrective_log)

    c.showPage()
    c.save()

    return FileResponse(
        path=temp_file.name,
        filename="ScopeCreepSummary.pdf",
        media_type="application/pdf"
    )
