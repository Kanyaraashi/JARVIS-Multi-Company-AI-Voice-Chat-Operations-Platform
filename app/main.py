from fastapi import FastAPI

from app.accounts import router as accounts_router
from app.appointments import router as appointments_router
from app.business import router as business_router
from app.calls import router as calls_router
from app.escalations import router as escalations_router
from app.internal import router as internal_router
from app.invoices import router as invoices_router
from app.privacy import install_log_redaction
from app.dashboard import router as dashboard_router
from app.dashboard_page import router as dashboard_page_router
from app.registration import router as registration_router
from app.staff import router as staff_router
from app.usage import router as usage_router
from app.tickets import router as tickets_router

install_log_redaction()  # phone numbers, emails and keys never reach the logs

app = FastAPI(title="JARVIS API")

app.include_router(business_router)
app.include_router(registration_router)
app.include_router(tickets_router)
app.include_router(escalations_router)
app.include_router(appointments_router)
app.include_router(invoices_router)
app.include_router(staff_router)
app.include_router(calls_router)
app.include_router(dashboard_router)
app.include_router(dashboard_page_router)
app.include_router(internal_router)
app.include_router(accounts_router)
app.include_router(usage_router)


@app.get("/health")
def health():
    return {"status": "ok"}
