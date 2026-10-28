import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET")

app = FastAPI(title="JARVIS API")


class TestEvent(BaseModel):
    event: str
    message: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/trigger-n8n")
async def trigger_n8n(payload: TestEvent):
    if not N8N_WEBHOOK_URL or not N8N_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="N8N_WEBHOOK_URL or N8N_WEBHOOK_SECRET is not set",
        )

    body = {"event": payload.event, "from": "fastapi", "message": payload.message}
    headers = {"X-Jarvis-Secret": N8N_WEBHOOK_SECRET}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(N8N_WEBHOOK_URL, json=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach n8n: {exc}")

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"n8n returned {response.status_code}",
        )

    return {"fastapi_status": "ok", "n8n_response": response.json()}