"""„Znajdź w umowach”: propozycje raportów z fragmentów umów ramowych klienta.

Najpierw kod wybiera fragmenty umowy i aneksów ze słowami o raportach,
rozliczeniu i terminach (te same słowa, którymi 15.11.2026 zrobiono inwentarz
35 klientów). Potem model z rejestru (``client_report_requirements``) wypisuje
z nich obowiązki raportowe z numerem fragmentu. Wynik modelu jest dodatkiem:
gdy modelu nie ma albo się myli, DL dostaje same fragmenty i wpisuje raport
ręcznie. Każda propozycja czeka na potwierdzenie DL-a klienta.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import client_reports_schema as schema
from app.services.client_reports.registry import all_generators
from app.services.client_reports.schedule import ScheduleError, validate_due_rule

logger = logging.getLogger(__name__)

#: Słowa o raportowaniu (Postgres ``~*``). Szum (opisy ról) odsiewa model.
KEYWORDS_PG = (
    "(governance|report|raport|sprawozdan|kpi|sla|timesheet|time sheet|karta czasu|"
    "karty czasu|ewidencj|zestawieni|statystyk|kwartaln|miesięczn|quarterly|monthly|"
    "protok[oó][lł] odbioru|key performance|service level|headcount|spend|margin|marż)"
)
_KEYWORDS_PY = re.compile(KEYWORDS_PG, re.IGNORECASE)
MAX_CHUNKS = 40
SNIPPET = 280


@dataclass(frozen=True)
class Fragment:
    chunk_id: int
    contract_id: int
    amendment_id: Optional[int]
    document: str
    text: str
    hits: int


_FRAGMENTS_SQL = text(
    """
    SELECT ch.id, fc.id, ch.amendment_id,
           coalesce(a.filename, a.name, fc.filename, fc.name) AS document,
           ch.text || coalesce(' ' || left(nx.text, :tail), '') AS text
      FROM client_framework_contract_chunks ch
      JOIN client_framework_contracts fc ON fc.id = ch.framework_contract_id
      LEFT JOIN client_contract_amendments a ON a.id = ch.amendment_id
      LEFT JOIN client_framework_contract_chunks nx
        ON nx.framework_contract_id = ch.framework_contract_id
       AND nx.amendment_id IS NOT DISTINCT FROM ch.amendment_id
       AND nx.chunk_index = ch.chunk_index + 1
     WHERE fc.client_id = :client_id
       AND ch.text ~* :pattern
     ORDER BY fc.id, ch.amendment_id NULLS FIRST, ch.chunk_index
    """
)
#: Początek następnego fragmentu: termin bywa ucięty granicą fragmentu
#: („… przesłane do” | „5-tego dnia kolejnego miesiąca”).
NEXT_TAIL = 300


async def keyword_fragments(
    db: AsyncSession, client_id: int, limit: int = MAX_CHUNKS
) -> list[Fragment]:
    rows = (
        await db.execute(
            _FRAGMENTS_SQL, {"client_id": client_id, "pattern": KEYWORDS_PG}
        )
    ).all()
    fragments = [
        Fragment(
            row[0],
            row[1],
            row[2],
            row[3] or "umowa",
            row[4],
            len(_KEYWORDS_PY.findall(row[4])),
        )
        for row in rows
    ]
    # Najgęstsze fragmenty najpierw, potem kolejność w dokumencie.
    ranked = sorted(fragments, key=lambda f: -f.hits)[:limit]
    order = {f.chunk_id: i for i, f in enumerate(fragments)}
    return sorted(ranked, key=lambda f: order[f.chunk_id])


def build_prompt(fragments: Sequence[Fragment]) -> str:
    generators = "\n".join(
        f"- {g.key}: {g.label} — {g.description}" for g in all_generators()
    )
    body = "\n\n".join(
        f"[fragment {f.chunk_id}] ({f.document})\n{f.text}" for f in fragments
    )
    return f"""Jesteś analitykiem umów firmy, która dostarcza konsultantów IT klientom (my = Wykonawca, Dostawca, Insourcer, Zleceniobiorca).
Z fragmentów umowy ramowej i aneksów wypisz WYŁĄCZNIE obowiązki, w których MY mamy coś dostarczyć klientowi okresowo albo na żądanie: raporty, zestawienia, karty czasu pracy, protokoły odbioru, sprawozdania, raporty z testów ciągłości, rejestry, informacje dla klienta.
Pomiń: obowiązki klienta, opisy zadań konsultantów (np. „raportowanie postępu” w opisie roli), definicje, poufność.

Odpowiedz samym JSON-em: lista obiektów z polami
- "name": krótka nazwa raportu po polsku (do 120 znaków),
- "family": "settlement" (dowód pracy do faktury: karta czasu, protokół odbioru), "management" (raport okresowy z danych o zespole, zamówieniach, obrocie), "compliance" (sprawozdania finansowe, ciągłość działania, incydenty, podwykonawcy, RODO) albo "on_request",
- "rhythm": "weekly", "monthly", "quarterly", "semiannual", "annual", "contract_year", "event" albo "on_request",
- "due_rule": {{"type": "day_of_month", "day": N}} | {{"type": "business_days_after", "days": N}} | {{"type": "days_after", "days": N}} | {{"type": "fixed", "month": M, "day": D}} | {{"type": "end_of_period"}} | {{"type": "none"}},
- "recipient": rola po stronie klienta (bez imion i nazwisk), albo null,
- "channel": np. "e-mail", "papier", "portal", albo null,
- "preparer": "dl", "finance", "board", "iod", "consultant" albo "client",
- "generator_key": jeden z kluczy niżej, jeśli pasuje dokładnie, inaczej null,
- "chunk_id": numer fragmentu, z którego wynika obowiązek,
- "source_ref": paragraf, ustęp albo załącznik, jeśli widać, inaczej null.

Generatory NEXUSA:
{generators}

Fragmenty:
{body}
"""


_JSON_ARRAY = re.compile(r"\[.*\]", re.S)


def parse_proposals(raw: str, allowed_chunks: set[int]) -> list[dict[str, Any]]:
    """Waliduje odpowiedź modelu; zły wpis odpada, reszta zostaje."""
    match = _JSON_ARRAY.search(raw or "")
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    known_generators = {g.key: g for g in all_generators()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[: schema.NAME_MAX]
        family, rhythm = item.get("family"), item.get("rhythm")
        preparer = item.get("preparer") or "dl"
        chunk_id = item.get("chunk_id")
        if (
            not name
            or family not in schema.FAMILIES
            or rhythm not in schema.RHYTHMS
            or preparer not in schema.PREPARERS
            or not isinstance(chunk_id, int)
            or chunk_id not in allowed_chunks
        ):
            continue
        try:
            due_rule = validate_due_rule(item.get("due_rule") or {})
        except ScheduleError:
            due_rule = {"type": "none"}
        generator_key = item.get("generator_key")
        generator = (
            known_generators.get(generator_key)
            if isinstance(generator_key, str)
            else None
        )
        if generator is None or rhythm not in generator.rhythms:
            generator_key = None
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "family": family,
                "rhythm": rhythm,
                "due_rule": due_rule,
                "recipient": _short(item.get("recipient"), schema.RECIPIENT_MAX),
                "channel": _short(item.get("channel"), schema.CHANNEL_MAX),
                "preparer": preparer,
                "generator_key": generator_key,
                "source_chunk_id": chunk_id,
                "source_ref": _short(item.get("source_ref"), schema.SOURCE_REF_MAX),
            }
        )
    return out


def normalize_name(name: str) -> str:
    return re.sub(r"\W+", " ", name.casefold()).strip()


def is_known(name: str, known: set[str]) -> bool:
    """Ta sama nazwa albo jedna zawiera drugą („Zestawienie zaangażowania”
    i „Zestawienie zaangażowania (liczba osób w miesiącu)”)."""
    key = normalize_name(name)
    if key in known:
        return True
    return any(
        min(len(other), len(key)) >= 12 and (other in key or key in other)
        for other in known
    )


def _short(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def snippet(fragment: Fragment) -> str:
    """Krótki wycinek wokół pierwszego słowa kluczowego (do okna DL-a)."""
    match = _KEYWORDS_PY.search(fragment.text)
    start = max(0, (match.start() if match else 0) - SNIPPET // 3)
    cut = re.sub(r"\s+", " ", fragment.text[start : start + SNIPPET]).strip()
    return ("…" if start else "") + cut + "…"


def call_model(chain: list[str], prompt: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=chain[1:] or None,
        max_tokens=4000,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def existing_names(db: AsyncSession, client_id: int) -> tuple[set[str], set[int]]:
    from app.models.client_report import ClientReportDefinition

    rows = (
        await db.execute(
            select(
                ClientReportDefinition.name, ClientReportDefinition.source_chunk_id
            ).where(ClientReportDefinition.client_id == client_id)
        )
    ).all()
    return {normalize_name(name) for name, _ in rows}, {
        c for _, c in rows if c is not None
    }
