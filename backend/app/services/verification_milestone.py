"""Weryfikacja liczy się od wejścia pary na „QC CV” albo dalej (0797).

Decyzja Artura 27.11.2026: kamień milowy ``verified`` (cele, Liga, Insights)
to pierwsze wejście pary na kolumnę QC CV albo dowolną dalszą po
zaakceptowanej weryfikacji. Kolumnę poznaje się po nazwie etapu, dlatego
część reguły zależna od nazwy jest kolumną generowaną
``pipeline_stage_defs.board_reach`` (funkcja SQL ``stage_def_board_reach``),
a tu stoi reszta: kod ruchu. Razem to lustro ``board_column_for``
w ``board_stage_badges.py`` — pilnuje ``tests/test_verification_from_qc_cv_db.py``.
"""

from __future__ import annotations

# Kody ruchu, które bez nazwy etapu leżą za QC CV (lustro `_COLUMN_BY_ENUM`).
LATER_CODES: tuple[str, ...] = (
    "cv_sent",
    "client_interview",
    "acceptance",
    "negotiation",
    "onboarding",
)


def reaches_cv_qc_sql(move: str, stage_def: str) -> str:
    """Warunek SQL: ruch ``move`` (wiersz ``candidate_stages``) z etapem
    ``stage_def`` (LEFT JOIN ``pipeline_stage_defs``) leży w QC CV albo dalej."""

    codes = ", ".join(f"'{c}'" for c in LATER_CODES)
    return (
        f"({stage_def}.board_reach = 'later'"
        f" OR ({move}.stage::text = 'hired'"
        f" AND {stage_def}.board_reach IS DISTINCT FROM 'closed')"
        f" OR ({stage_def}.board_reach IS NULL"
        f" AND {move}.stage::text IN ({codes})))"
    )
