"""Reguła „kandydat pasuje do rekrutacji na tyle, żeby system dodał go sam”.

Jedno źródło dla importera JJIT i autonomicznego dopasowania po odczycie CV
(`services/auto_match_service.py`). Dwie kopie progu rozjechałyby się przy
pierwszym strojeniu — i jeden automat dodawałby ludzi, których drugi odrzuca.
"""

from __future__ import annotations


def is_good_match(rec: dict, *, min_score: float, require_must: bool) -> bool:
    """Próg + rekrutacja opublikowana + ≥1 trafione must-have, gdy oferta je ma."""
    if rec["score"] < min_score or rec["status"] not in ("", "published"):
        return False
    if (
        require_must
        and (rec["gap_must"] or rec["matching_must"])
        and not rec["matching_must"]
    ):
        return False
    return True
