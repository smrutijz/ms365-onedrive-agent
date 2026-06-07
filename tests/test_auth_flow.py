import requests

BASE_URL = "https://wap-ms365-onedrive-agent-g3d7azg6b4apf8cg.eastasia-01.azurewebsites.net"
EMAIL = "smrutijz@outlook.com"

# Paste a fresh JWT from /callback here before running
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InNtcnV0aWp6QG91dGxvb2suY29tIiwiZXhwIjoxNzgwODQ1MzYwfQ.r7rRyrvLqYfSNI84tU8JpcTjWUX6XB6cg3jzQtPbO0c"

headers = {"Authorization": f"Bearer {JWT}"}

# Refresh the token
r = requests.post(f"{BASE_URL}/refresh", headers=headers)
print("refresh:", r.status_code, r.json())
JWT = r.json()["access_token"]
headers = {"Authorization": f"Bearer {JWT}"}

# Send an email to self
r = requests.post(
    f"{BASE_URL}/mail/send",
    headers=headers,
    json={
        "to": [EMAIL],
        "subject": "Test email from API",
        "body": "Hello, this is a test email sent to myself.",
        "body_type": "Text",
    },
)
print("send mail:", r.status_code, r.json())

# Logout
r = requests.post(f"{BASE_URL}/logout", headers=headers)
print("logout:", r.status_code, r.json())
