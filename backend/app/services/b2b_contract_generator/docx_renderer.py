"""Render umowy B2B do DOCX (docxtpl na oryginalnym szablonie prawnym).

Zachowuje dokładne formatowanie umowy (token-replacement, nie odbudowa).
`autoescape=True` w środowisku Jinja zapewnia poprawne escapowanie wartości
do XML (& < >), a `RichText` (scope) jest wstawiany przez docxtpl z pominięciem
escapowania.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment

from app.models.contract import Contract
from app.services.b2b_contract_generator.clause_overrides import (
    ClauseOverrideError,
    apply_ops_docx,
    ops_fingerprint,
    overrides_for_key,
    resolve_override,
)
from app.services.b2b_contract_generator.field_mapping import build_docx_context
from app.services.b2b_contract_generator.formatting import pl_date

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "contract"

# Sentinel: „rozstrzygnij rejestr po nazwie Klienta TERAZ". Odróżniony od
# ``None``, które znaczy „snapshot mówi: żaden override nie był zastosowany" —
# przy ponownym pobraniu te dwa przypadki muszą dać różne dokumenty.
RESOLVE_BY_CLIENT_NAME = "__resolve_by_client_name__"


def normalize_language(language: str | None) -> str:
    return "en" if (language or "pl").lower().startswith("en") else "pl"


def template_path(language: str | None) -> Path:
    return TEMPLATE_DIR / f"umowa_b2b_{normalize_language(language)}.docx"


def _jinja_env() -> Environment:
    env = Environment(autoescape=True)
    env.filters["pl_date"] = pl_date
    return env


def render_from_context(
    context: dict,
    *,
    language: str | None = "pl",
    clause_override_key: str | None = RESOLVE_BY_CLIENT_NAME,
) -> bytes:
    """Render gotowego kontekstu (do testów bez DB).

    ``clause_override_key`` przypina wpis rejestru klauzul zapisany przy
    generacji (patrz `resolve_override`). Domyślny sentinel rozstrzyga rejestr
    po bieżącej nazwie Klienta — poprawne przy PIERWSZYM wydaniu dokumentu,
    niebezpieczne przy ponownym pobraniu już wydanej umowy."""
    path = template_path(language)
    if not path.is_file():
        raise FileNotFoundError(f"Brak szablonu DOCX: {path}")
    tpl = DocxTemplate(str(path))
    # Binarny szablon prawny w Załączniku nr 3 ma historyczny placeholder
    # ``contract.start_date``. Podstawiamy mu tę samą pełną frazę co w §13,
    # dzięki czemu tryb „nie wcześniej/później niż" nie ginie w załączniku.
    # Kopia zapobiega mutowaniu kontekstu używanego także przez podgląd HTML.
    render_context = {**context, "contract": dict(context.get("contract") or {})}
    start = (context.get("b2b") or {}).get("start_clause")
    if start:
        render_context["contract"]["start_date"] = start
    tpl.render(render_context, jinja_env=_jinja_env())
    # Per-klient modyfikacje umowy (np. § 10 Centrum e-Zdrowia/PFRON, § 4 BNP,
    # Załączniki CA/BIK) — podmiana w już wyrenderowanym dokumencie; brak
    # operacji = render bez zmian.
    lang = normalize_language(language)
    client = context.get("client") or {}
    client_name = client.get("name") or client.get("legal_name")
    if clause_override_key == RESOLVE_BY_CLIENT_NAME:
        key, ops = resolve_override(client_name, lang)
    else:
        key, ops = clause_override_key, overrides_for_key(clause_override_key, lang)
    # Log przy KAŻDEJ generacji, niezależnie od wyniku — to jedyny ślad tego,
    # który zestaw klauzul trafił do wydanego dokumentu (wiersz rejestru nie
    # zapisywał tego, więc po incydencie Cardif nie dało się wylistować umów
    # wydanych z błędnym §4).
    logger.info(
        "b2b_clause_override lang=%s key=%s ops=%d fingerprint=%s client=%r",
        lang,
        key,
        len(ops),
        ops_fingerprint(ops),
        client_name,
    )
    if ops:
        applied = apply_ops_docx(tpl.docx, ops)
        if applied != len(ops):
            # Głośna porażka zamiast cichego pominięcia: brak wynegocjowanej
            # klauzuli w dokumencie, który wygląda na kompletny, jest gorszy niż
            # nieudane pobranie. Ląduje w Sentry przez logger.error.
            logger.error(
                "b2b_clause_override_incomplete lang=%s key=%s applied=%d expected=%d",
                lang,
                key,
                applied,
                len(ops),
            )
            raise ClauseOverrideError(
                f"Nie udało się wstawić wszystkich klauzul Klienta do umowy "
                f"(zastosowano {applied} z {len(ops)}; rejestr „{key}”). "
                f"Dokument NIE został wydany — zgłoś to, szablon umowy "
                f"rozjechał się z rejestrem klauzul."
            )
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def render_contract_docx(contract: Contract, *, language: str | None = "pl") -> bytes:
    """Wyrenderuj DOCX umowy B2B dla danego kontraktu."""
    return render_from_context(build_docx_context(contract), language=language)
