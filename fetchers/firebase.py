import requests

def get_email_logs():
    url = "https://db-meshboard-database-default-rtdb.asia-southeast1.firebasedatabase.app/emailLogs.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

