"""Provider-agnostic HTML → PDF rendering for the signing rail.

The renderer itself (WeasyPrint) has zero coupling to any signing provider —
it just turns the contract draft HTML into a print-ready PDF. It currently
lives under :mod:`app.services.autenti.pdf_renderer`; this module re-exports it
under the provider-neutral ``signing`` package so new code imports from here.

When Autenti is finally removed (Faza 5) the implementation moves here and the
old path keeps a re-export for any lingering importers.
"""

from __future__ import annotations

from app.services.autenti.pdf_renderer import render_contract_pdf

__all__ = ["render_contract_pdf"]
