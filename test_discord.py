import os
import requests

print("WEBHOOK:", os.environ.get("DISCORD_WEBHOOK_URL"))
webhook = os.environ.get("DISCORD_WEBHOOK_URL")
if not webhook:
    raise SystemExit("DISCORD_WEBHOOK_URL not set in environment")

resp = requests.post(
    webhook, json={"content": "Test message from workout agent (Python)"},
    timeout=5)
print("status:", resp.status_code)
print("body:", resp.text)
