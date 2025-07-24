from fastapi import FastAPI, HTTPException
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
import re
import traceback

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

def truncate_text(text, max_chars=15000):
    return text[:max_chars]

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

def summarize_insight_llm(row):
    api_key = os.getenv("GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt_text = (
        f"You are a governance analyst. Summarize the below communication into a 1-line conversational insight:\n"
        f"Project: {row.get('Project Name', row.get('project', ''))}\n"
        f"Subject: {row.get('Subject', '')}\n"
        f"From: {row.get('From', '')}\n"
        f"To: {row.get('To', '')}\n"
        f"Date: {row.get('Date', row.get('date', ''))}\n"
        f"Body: {row.get('Body', '')}\n"
        f"Remark: {row.get('Insights', row.get('insights', row.get('Summary', '')))}\n"
    )
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "Be concise and summarize the project update clearly. Avoid quoting raw text."},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.4
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=7)
        res.raise_for_status()
        summary = res.json()["choices"][0]["message"]["content"].strip()
        return summary
    except Exception:
        return row.get('Summary', row.get('Subject','No Subject')) + " (" + row.get('Date', row.get('date','')) + ")"

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

def extract_completion_percent(all_data, project_name=None):
    percent_re = re.compile(r'(\d{1,3})\s*%')
    for row in sorted(all_data, key=lambda x: x.get("Date", ""), reverse=True):
        text = " ".join([str(row.get(k, "")) for k in row.keys()])
        if project_name and project_name.lower() not in text.lower():
            continue
        matches = percent_re.findall(text)
        if matches:
            for match in matches:
                try:
                    pct = int(match)
                    if pct != 100 or len(matches) == 1:
                        return f"{pct}%"
                except Exception:
                    continue
    return None

def find_best_project_update(data, project_name=None):
    for row in sorted(data, key=lambda x: x.get("Date", ""), reverse=True):
        text = " ".join([str(row.get(k, "")) for k in row.keys()]).lower()
        if project_name and project_name.lower() not in text:
            continue
        if "%" in text or "completion" in text or "milestone" in text or "demo" in text:
            return row
    if data:
        return sorted(data, key=lambda x: x.get("Date", ""), reverse=True)[0]
    return None

def format_row(row):
    keys = ["Email Record ID", "Date", "From", "Subject", "Body", "Project Name", "BU", "Solution Center", "Mode", "Insights"]
    return {k: row.get(k, "") for k in keys if k in row}

def safe_fetch(tabname, mode=None, summary_field=None, date_fields=None):
    raw = fetch_sheet_data(tabname)
    if not raw or "data" not in raw or not isinstance(raw["data"], list):
        print(f"⚠️ Sheet/tab '{tabname}' missing or empty! Raw: {raw}")
        return []
    rows = raw["data"]
    if mode and summary_field:
        out = []
        for row in rows:
            d = dict(row)
            d["Mode"] = mode
            d["Insights"] = row.get(summary_field, "")
            d["Date"] = row.get(date_fields[0], "") if date_fields else row.get("Date", "")
            for field in date_fields or []:
                if row.get(field):
                    d["Date"] = row.get(field)
                    break
            out.append(d)
        return out
    elif mode:
        return [dict(row, Mode=mode) for row in rows]
    else:
        return [dict(row) for row in rows]

@app.post("/chat")
async def chat_with_context(prompt: ChatPrompt):
    try:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return {"error": "⚠️ GROQ_API_KEY not set in environment"}

        index_data      = safe_fetch("index", mode="meta")
        extractor_data  = safe_fetch("extractor", mode="email")
        manager_data    = safe_fetch("manager", mode="email")
        tldv_manager_data = safe_fetch("tldv Manager", mode="call", summary_field="Summary", date_fields=["Date", "Timestamp"])
        all_data = index_data + extractor_data + manager_data + tldv_manager_data

        project_keywords = list({
            str(row.get("Project Name", "")).strip()
            for row in all_data
            if row.get("Project Name")
        })

        user_query = prompt.message.strip().lower()
        matched_keywords = [kw for kw in project_keywords if kw.lower() in user_query]
        keywords_to_check = matched_keywords if matched_keywords else user_query.split()

        # 👇👇 Always show latest call summary if the user asks about call/meeting
        if "call" in user_query or "meeting" in user_query:
            # Find calls for matching project(s)
            matching_calls = []
            for kw in keywords_to_check:
                matching_calls += [
                    row for row in tldv_manager_data
                    if kw.lower() in row.get("Project Name", "").lower()
                ]
            if not matching_calls:
                # fallback: any calls for any project
                matching_calls = tldv_manager_data
            if matching_calls:
                latest_call = sorted(matching_calls, key=lambda x: x.get("Date", ""), reverse=True)[0]
                summary = latest_call.get("Summary", latest_call.get("Insights", ""))
                date = latest_call.get("Date", "")
                pname = latest_call.get("Project Name", "")
                meeting_title = latest_call.get("Meeting Title", "")
                return {
                    "response": f"Latest call/meeting for '{pname}'{f' ({meeting_title})' if meeting_title else ''} was on {date}.\nKey points:\n{summary}"
                }

        # If not a direct call/meeting question, proceed with LLM
        expanded_query = prompt.message
        if "scope creep" in user_query:
            expanded_query += (
                "\n\nPlease check if the project has introduced features, flows, or changes "
                "that were not listed in the original scope document, or if any approvals are missing."
            )

        best_row = None
        for kw in keywords_to_check:
            best_row = find_best_project_update(all_data, project_name=kw)
            if best_row:
                break
        if not best_row:
            best_row = find_best_project_update(all_data)

        completion_percent = extract_completion_percent(all_data, project_name=matched_keywords[0] if matched_keywords else None)
        doc_context = get_scope_summary(matched_keywords[0]) if matched_keywords else ""
        doc_summary = f"--- 📄 Scope Document: {matched_keywords[0]} ---\n{doc_context.strip()}\n\n" if doc_context else ""

        context = ""
        if completion_percent:
            context += f"\n--- 📊 % COMPLETION FOUND ---\nOverall Completion: {completion_percent}\n\n"
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

        if not best_row and not doc_context and not completion_percent:
            context += (
                "You are a project governance and client success assistant.\n\n"
                "The user asked a question, but no relevant scope or email/call records were found.\n"
                "Kindly advise them to follow up with the project team for more information."
            )
        else:
            context = (
                f"{doc_summary}"
                f"{context}"
                f"{summarize(index_data, 'Index')}"
                f"{summarize(extractor_data, 'Email Extractor')}"
                f"{summarize(manager_data, 'Email Manager')}"
                f"{summarize(tldv_manager_data, 'Call Manager')}"
            )

        instruction_header = (
            "You are an intelligent project governance and client success assistant AI.\n"
            "You have access to all project emails, calls, and logs. Search for *any* evidence, even if not in the latest updates. "
            "If you see a percentage completion (such as '80%'), ALWAYS report it and quote the source. "
            "Be specific in your findings. When a user asks about any kind of event (appreciation, bugs, risks, etc.), "
            "scan ALL available records and answer with the best evidence you can find. Quote from emails/calls if possible.\n"
            "Your goals:\n"
            "1. Detect scope creep from scope vs email/call.\n"
            "2. Identify delays, risks, and new requests.\n"
            "3. Read tone of communication to understand client pulse.\n"
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

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return {"response": result["choices"][0]["message"]["content"]}
    except Exception as e:
        print("Chat endpoint error:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Error: {e}")

@app.get("/data/index-sheet")
async def get_index_sheet_data():
    return fetch_sheet_data("index")

@app.get("/data/email-extractor")
async def get_email_extractor_data():
    return fetch_sheet_data("extractor")

@app.get("/data/email-manager")
async def get_email_manager_data():
    return fetch_sheet_data("manager")

@app.get("/data/tldv-manager")
async def get_tldv_manager_data():
    return fetch_sheet_data("tldv Manager")

@app.get("/risk-report/scope-creep/summary")
async def get_scope_creep_summary():
    index_data      = safe_fetch("index", mode="meta")
    extractor_data  = safe_fetch("extractor", mode="email")
    manager_data    = safe_fetch("manager", mode="email")
    tldv_manager_data = safe_fetch("tldv Manager", mode="call", summary_field="Summary", date_fields=["Date", "Timestamp"])

    all_rows = index_data + extractor_data + manager_data + tldv_manager_data
    project_names = set(row.get("Project Name", "") for row in index_data if row.get("Project Name", ""))
    summary = []
    signals = []
    corrective = []

    def unique_entries(rows):
        seen = set()
        result = []
        for row in rows:
            key = (
                row.get("Project Name", ""),
                row.get("Email Record ID", ""),
                row.get("Mode", ""),
                row.get("Date", ""),
                row.get("Subject", ""),
                row.get("Insights", ""),
            )
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result

    creep_rows = {p: [] for p in project_names}
    resolution_rows = {p: [] for p in project_names}
    for row in all_rows:
        pname = row.get("Project Name", "")
        text = " ".join([str(v).lower() for v in row.values()])
        if pname:
            if any(k in text for k in keywords) and len(text) > 20:
                creep_rows.setdefault(pname, []).append(row)
            if any(k in text for k in resolutions) and len(text) > 10:
                resolution_rows.setdefault(pname, []).append(row)

    for pname in project_names:
        creep = creep_rows.get(pname, [])
        status = "YES" if creep else "NO" if pname and not creep else "TBD"
        base_row = next((row for row in index_data if row.get("Project Name", "") == pname), {})
        summary.append({
            "project": pname,
            "bu": base_row.get("BU", ""),
            "solution_center": base_row.get("Solution Center", ""),
            "status": status
        })

    for pname, rows in creep_rows.items():
        deduped = sorted(unique_entries(rows), key=lambda x: x.get("Date", ""), reverse=True)
        count = 0
        for r in deduped:
            if r.get("Subject") or r.get("Body") or r.get("Insights") or r.get("Summary"):
                insight_text = summarize_insight_llm(r)
                signals.append({
                    "project": pname,
                    "bu": r.get("BU", ""),
                    "solution_center": r.get("Solution Center", ""),
                    "mode": r.get("Mode", ""),
                    "date": r.get("Date", ""),
                    "insights": insight_text,
                })
                count += 1
                if count >= 2:
                    break

    for pname, rows in resolution_rows.items():
        if creep_rows.get(pname):
            deduped = sorted(unique_entries(rows), key=lambda x: x.get("Date", ""), reverse=True)
            if deduped:
                r = deduped[0]
                if r.get("Subject") or r.get("Body") or r.get("Insights") or r.get("Summary"):
                    insight_text = summarize_insight_llm(r)
                    corrective.append({
                        "project": pname,
                        "bu": r.get("BU", ""),
                        "solution_center": r.get("Solution Center", ""),
                        "mode": r.get("Mode", ""),
                        "date": r.get("Date", ""),
                        "insights": insight_text,
                    })

    return JSONResponse(content={
        "summary": summary,
        "signals": signals,
        "corrective": corrective
    })

@app.get("/risk-report/scope-creep/pdf")
async def generate_scope_creep_pdf():
    index_data      = safe_fetch("index", mode="meta")
    extractor_data  = safe_fetch("extractor", mode="email")
    manager_data    = safe_fetch("manager", mode="email")
    tldv_manager_data = safe_fetch("tldv Manager", mode="call", summary_field="Summary", date_fields=["Date", "Timestamp"])

    all_rows = index_data + extractor_data + manager_data + tldv_manager_data
    project_names = set(row.get("Project Name", "") for row in index_data if row.get("Project Name", ""))
    summary = []
    signals = []
    corrective = []

    def unique_entries(rows):
        seen = set()
        result = []
        for row in rows:
            key = (
                row.get("Project Name", ""),
                row.get("Email Record ID", ""),
                row.get("Mode", ""),
                row.get("Date", ""),
                row.get("Subject", ""),
                row.get("Insights", ""),
            )
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result

    creep_rows = {p: [] for p in project_names}
    resolution_rows = {p: [] for p in project_names}
    for row in all_rows:
        pname = row.get("Project Name", "")
        text = " ".join([str(v).lower() for v in row.values()])
        if pname:
            if any(k in text for k in keywords) and len(text) > 20:
                creep_rows.setdefault(pname, []).append(row)
            if any(k in text for k in resolutions) and len(text) > 10:
                resolution_rows.setdefault(pname, []).append(row)

    for pname in project_names:
        creep = creep_rows.get(pname, [])
        status = "YES" if creep else "NO" if pname and not creep else "TBD"
        base_row = next((row for row in index_data if row.get("Project Name", "") == pname), {})
        summary.append({
            "Project Name": pname,
            "BU": base_row.get("BU", ""),
            "Solution Center": base_row.get("Solution Center", ""),
            "SCOPE CREEP SIGNAL": status
        })

    for pname, rows in creep_rows.items():
        deduped = sorted(unique_entries(rows), key=lambda x: x.get("Date", ""), reverse=True)
        count = 0
        for r in deduped:
            if r.get("Subject") or r.get("Body") or r.get("Insights") or r.get("Summary"):
                insight_text = summarize_insight_llm(r)
                signals.append({
                    "Project Name": pname,
                    "BU": r.get("BU", ""),
                    "Solution Center": r.get("Solution Center", ""),
                    "Mode": r.get("Mode", ""),
                    "Date": r.get("Date", ""),
                    "Insights": insight_text,
                })
                count += 1
                if count >= 2:
                    break

    for pname, rows in resolution_rows.items():
        if creep_rows.get(pname):
            deduped = sorted(unique_entries(rows), key=lambda x: x.get("Date", ""), reverse=True)
            if deduped:
                r = deduped[0]
                if r.get("Subject") or r.get("Body") or r.get("Insights") or r.get("Summary"):
                    insight_text = summarize_insight_llm(r)
                    corrective.append({
                        "Project Name": pname,
                        "BU": r.get("BU", ""),
                        "Solution Center": r.get("Solution Center", ""),
                        "Mode": r.get("Mode", ""),
                        "Date": r.get("Date", ""),
                        "Insights": insight_text,
                    })

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
        x_pos = [40, 150, 260, 370, 480, 580, 680]
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
                c.drawString(x_pos[i], y, t[:22])
            y -= 15

    def draw_log(title, rows, log_headers):
        nonlocal y
        draw_header(title)
        x_pos = [40, 150, 260, 370, 480, 580, 680]
        c.setFont("Helvetica-Bold", 11)
        for i, h in enumerate(log_headers):
            c.drawString(x_pos[i], y, h)
        y -= 18
        c.setFont("Helvetica", 10)
        for row in rows:
            if y < 100:
                c.showPage()
                y = height - 50
            for i, k in enumerate(log_headers):
                c.drawString(x_pos[i], y, str(row.get(k, ""))[:22])
            y -= 15

    draw_header("Scope Creep Summary Report")
    draw_header("A.1 Summary View")
    draw_table(
        ["Project Name", "BU", "Solution Center", "SCOPE CREEP SIGNAL"],
        summary,
        bullet_colors={"YES": colors.red, "NO": colors.green, "TBD": colors.gray}
    )
    draw_log("A.2 Scope Creep Signal Log", signals, ["Project Name", "BU", "Solution Center", "Mode", "Date", "Insights"])
    draw_log("A.3 Corrective Measures Taken Log", corrective, ["Project Name", "BU", "Solution Center", "Mode", "Date", "Insights"])

    c.showPage()
    c.save()
    return FileResponse(temp_file.name, filename="ScopeCreepSummary.pdf", media_type="application/pdf")

