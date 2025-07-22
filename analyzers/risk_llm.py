def prompt_llm_with_email_data(email_data: list[str]) -> dict:
    import subprocess
    import json

    # Load governance rules
    with open("governance.txt", "r") as f:
        governance_rules = f.read()

    # Combine prompt
    full_prompt = f"""
You are an AI assistant trained to assess project risk and governance compliance.
You MUST strictly follow the organization's governance policies provided below.

=== Governance Rules ===
{governance_rules}

=== Project Communication Data ===
{email_data}

Based on the above, analyze scope creep, escalation risk, timeline delays, sentiment issues, and non-compliance.
Respond in structured JSON like this:

{{
  "risk_analysis": [
    {{
      "type": "Scope Creep",
      "reason": "...",
      "reference": "Row 3",
      "excerpt": "..."
    }},
    ...
  ]
}}
"""

    # Run LLM (Mistral via Ollama)
    process = subprocess.Popen(["ollama", "run", "mistral"],
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

    stdout, stderr = process.communicate(full_prompt.encode())
    decoded = stdout.decode("utf-8")

    # Extract only the JSON from the response
    try:
        parsed = json.loads(decoded.strip())
        if "risk_analysis" in parsed:
            return parsed
        else:
            return {"risk_analysis": [{"type": "Unknown", "reason": "Could not parse LLM response"}]}
    except Exception:
        return {"risk_analysis": [{"type": "Parse Error", "reason": decoded}]}

