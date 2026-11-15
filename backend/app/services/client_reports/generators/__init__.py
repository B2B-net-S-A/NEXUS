"""Generatory raportów klienta — każdy moduł rejestruje się przy imporcie."""

from app.services.client_reports.generators import (  # noqa: F401
    annual_spend,
    annual_statistics,
    bnp_recruitment,
    contract_realisation,
    engagement,
    headcount,
    orders_quarterly,
)
