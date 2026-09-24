"""JustJoinIT — adapter czekający na dokumentację API (flaga ``PORTAL_JJIT_ENABLED``)."""

from __future__ import annotations

from app.models.job_posting import Portal
from app.services.job_portals.base import PendingDocumentationAdapter


class JjitAdapter(PendingDocumentationAdapter):
    portal = Portal.justjoinit
    label = "JustJoinIT"
