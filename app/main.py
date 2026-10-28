from fastapi import FastAPI

from app.business import router as business_router
from app.tickets import router as tickets_router

app = FastAPI(title="JARVIS API")

app.include_router(business_router)
app.include_router(tickets_router)


@app.get("/health")
def health():
    return {"status": "ok"}
