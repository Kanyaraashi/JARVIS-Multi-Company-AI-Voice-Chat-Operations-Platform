from fastapi import FastAPI

from app.appointments import router as appointments_router
from app.business import router as business_router
from app.escalations import router as escalations_router
from app.invoices import router as invoices_router
from app.registration import router as registration_router
from app.staff import router as staff_router
from app.tickets import router as tickets_router

app = FastAPI(title="JARVIS API")

app.include_router(business_router)
app.include_router(registration_router)
app.include_router(tickets_router)
app.include_router(escalations_router)
app.include_router(appointments_router)
app.include_router(invoices_router)
app.include_router(staff_router)


@app.get("/health")
def health():
    return {"status": "ok"}