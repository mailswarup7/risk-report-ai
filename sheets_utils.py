import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load credentials
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SERVICE_ACCOUNT_FILE = 'google-sheets-access.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

service = build('sheets', 'v4', credentials=credentials)

# Sheet configuration
SPREADSHEET_ID = '1icAbeQevZL6A-_glzEk3f6uF9OaAZfyqnUHgQVjRMPY'
SHEET_NAMES = {
    "index": "Index",
    "extractor": "Email Extractor",
    "manager": "Email Manager"
}

def fetch_sheet_data(sheet_name_key):
    try:
        sheet_name = SHEET_NAMES.get(sheet_name_key)
        if not sheet_name:
            return {"error": f"Invalid sheet name key: {sheet_name_key}"}

        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=sheet_name
        ).execute()

        values = result.get("values", [])
        if not values:
            return {"data": []}

        headers = values[0]
        rows = values[1:]
        data = [dict(zip(headers, row)) for row in rows]

        return {"data": data}
    except Exception as e:
        return {"error": str(e)}

