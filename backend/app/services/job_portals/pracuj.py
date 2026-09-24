"""Pracuj.pl — adapter czekający na dokumentację API (flaga ``PORTAL_PRACUJ_ENABLED``)."""

from __future__ import annotations

from app.models.job_posting import Portal
from app.services.job_portals.base import PendingDocumentationAdapter


class PracujAdapter(PendingDocumentationAdapter):
    portal = Portal.pracuj_pl
    label = "Pracuj.pl"
