from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os

app = FastAPI()

VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")

@app.get("/webhook/facebook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        return PlainTextResponse(content="Verification failed", status_code=403)

@app.post("/webhook/facebook")
async def webhook(request: Request):
    data = await request.json()
    print("📩 Webhook event:", data)
    return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)
