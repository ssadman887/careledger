from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    audit,
    auth,
    catalog,
    claims,
    health,
    insurance,
    invoices,
    journal,
    patients,
    payments,
    periods,
    remittances,
    reports,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
api_router.include_router(accounts.router)
api_router.include_router(periods.router)
api_router.include_router(journal.router)
api_router.include_router(reports.router)
api_router.include_router(patients.router)
api_router.include_router(catalog.router)
api_router.include_router(invoices.router)
api_router.include_router(payments.router)
api_router.include_router(insurance.router)
api_router.include_router(claims.router)
api_router.include_router(remittances.router)
