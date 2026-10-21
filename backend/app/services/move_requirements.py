"""Wymagania przejścia karty na Tablicy (Rekrutacja v5, 24.09.2026).

`GET /api/pipeline/move-requirements` mówi, CO jest potrzebne, żeby osoba
weszła do kolumny docelowej, zanim ktokolwiek kliknie „Przesuń" — i co z tego
już jest. Do 23.09.2026 rekruter dowiadywał się o braku stawki, CV albo
debriefu dopiero z odmowy serwera (422/409) po upuszczeniu karty.

Dwie warstwy:

* ``build_requirements`` — czysta funkcja z faktów pary (bez bazy); tu żyje
  reguła „co jest potrzebne do której kolumny" i testuje się ją bez Postgresa.
* ``load_pair_facts`` — zbiera fakty jednym przejściem po bazie.

Ruch przez kilka kolumn naraz (np. „Nowi" → „QC CV") sumuje wymagania
wszystkich kolumn po drodze — pominięta kolumna nie zwalnia z jej wymagań.
Ruch wstecz i zamknięcie procesu niczego nie wymagają.

Lista jest podpowiedzią dla ekranu, nie bramką: bramki (stawka przy
„Zweryfikowanym", QC CV przed wysłaniem, debrief przed umową, wysyłka do
klienta tylko z uprawnieniem) egzekwuje `POST /api/pipeline/move`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

# Pola karty, które klient może dołożyć do minimum (karta klienta, D3) — jedno
# wejście dla modułów spoza listy czytelników kart rekomendacji.
from app.services.recommendation_card_rules import CLIENT_EXTRA_FIELDS

from app.services.board_stage_badges import (
    BOARD_COLUMN_ORDER,
    board_column_for,
    cpro_enabled_for_client,
    is_cpro_stage,
)

OK = "ok"
MISSING = "missing"
WAITING = "waiting"

COLUMN_LABEL: dict[str, str] = {
    "new": "Nowi",
    "screening": "Screening",
    "verified": "Zweryfikowany",
    "cv_qc": "QC CV",
    "cv_sent": "CV wysłane",
    "client_interview": "Rozmowa u klienta",
    "contract": "Akceptacja i umowa",
    "hired": "Zatrudniony",
    "closed": "Zamknięci",
}
# U Nordei wysłanie CV do klienta TO JEST wysłanie do Cpro (22.09.2026).
CPRO_SENT_LABEL = "Wysłane do Cpro"

QC_OK_STATUSES = frozenset({"passed", "overridden"})


def column_label(column: str, *, nordea: bool = False) -> str:
    if column == "cv_sent" and nordea:
        return CPRO_SENT_LABEL
    return COLUMN_LABEL.get(column, column)


def sheet_filled(payload: object) -> bool:
    """Czy arkusz screeningu ma treść — lustro `_sheet_filled` w `api/pipeline`.

    `ScreeningAnswers` zapisuje domyślnie `{"answers": [], ...}`, więc samo
    `bool(dict)` dałoby fałszywe „wypełniony".
    """

    if not isinstance(payload, dict) or not payload:
        return False
    answers = payload.get("answers")
    if isinstance(answers, (list, dict)):
        return len(answers) > 0
    return any(value not in (None, "", [], {}) for value in payload.values())


def answer_has_content(item: Mapping[str, Any]) -> bool:
    """Odpowiedź z rozmowy: tekst, pominięcie albo trafienie deal-breakera."""
    return (
        bool(str(item.get("response") or "").strip())
        or bool(item.get("skipped"))
        or bool(item.get("deal_breaker_hit"))
    )


def sheet_answered(payload: object) -> bool:
    """Czy arkusz ma choć jedną odpowiedź z rozmowy — bramka „Zweryfikowany”.

    Do 14.10.2026 bramka czytała ``sheet_filled``, które liczy pozycje listy.
    Formularz wysyła każde pytanie (także puste), więc arkusz z samym
    sprawdzeniem doświadczenia spełniał bramkę bez żadnej odpowiedzi (audyt
    13.10.2026, pkt 5). Reguła („Arkusz z samymi sprawdzeniami doświadczenia
    zapisuje się, ale bramki nie spełnia”) wymaga odpowiedzi, nie kompletu
    — pytania bez odpowiedzi nadal da się zostawić puste. ``sheet_filled``
    zostaje dla pytania „czy arkusz jest zapisany”.
    """
    if not isinstance(payload, dict):
        return False
    answers = payload.get("answers")
    if not isinstance(answers, list):
        # Kształt sprzed `ScreeningAnswers` — znaczenie bez zmian.
        return sheet_filled(payload)
    return any(
        isinstance(item, Mapping) and answer_has_content(item) for item in answers
    )


@dataclass(frozen=True)
class PairFacts:
    """Wszystko, co trzeba wiedzieć o parze (kandydat, rekrutacja)."""

    from_column: Optional[str]
    # Najnowszy wiersz etapu pary — do niego prowadzą akcje („Otwórz QC").
    stage_id: Optional[int] = None
    screening_done: bool = False
    screening_stage_id: Optional[int] = None
    candidate_rate: bool = False
    availability_known: bool = False
    # 0413: karta rekomendacji — nazwy brakujących pól i czy notatka niesie
    # odpowiedzi na pytania (wtedy arkusz screeningu nie jest brakiem).
    card_missing: tuple[str, ...] = ()
    card_exists: bool = False
    card_answers: bool = False
    # 12.10.2026: rekrutacja bez pytań screeningowych (przeniesiona z Traffita,
    # bez Profilu Championa) nie ma arkusza do wypełnienia — przed
    # „Zweryfikowany” wystarcza wtedy „Dlaczego ten kandydat”
    # (`screening_requirement`).
    has_screening_questions: bool = True
    card_recommendation: bool = False
    # Karta zna dostępność albo stawkę kandydata (PLN/h) — „Przesuń dalej”
    # nie może wtedy mówić, że tego nie wiemy.
    card_availability: bool = False
    card_rate_hourly: Optional[float] = None
    # 21.10.2026: pola karty z treścią i pola, które klient dokłada do
    # minimum dla DL (karta klienta). `minimum_enabled` = wyłącznik.
    card_present: frozenset[str] = frozenset()
    client_required_fields: tuple[str, ...] = ()
    client_name: Optional[str] = None
    minimum_enabled: bool = True
    company_cv: bool = False
    qc_status: str = "unchecked"
    qc_blocking_failed: int = 0
    client_rate: bool = False
    # Użytkownik może wysłać CV do klienta (uprawnienie „Rekrutacje:
    # zakładanie, zamykanie, wysyłka CV do klienta”).
    is_client_sender: bool = False
    nordea: bool = False
    cpro_stage_def_id: Optional[int] = None
    qc_stage_def_id: Optional[int] = None
    on_cpro_stage: bool = False
    can_send_to_cpro: bool = False
    cpro_sender_name: Optional[str] = None
    client_slot: bool = False
    debrief_missing: bool = False
    debrief_pending: bool = False
    # Rozmowa u klienta, pod którą zapisuje się debrief.
    debrief_event_id: Optional[int] = None
    client_decision: bool = False
    signed: bool = False
    # Runda 9 (R9-V2-6): wyłącznik `CV_QC_GATE_ENABLED` — przy wyłączonym QC
    # serwer nie odmawia wysyłki bez QC ani CV firmowego, więc okno też nie.
    qc_gate_enabled: bool = True
    # 04.10.2026: odpowiedzi z arkusza screeningu oznaczone jako trafienie
    # deal-breakera — `{number, question, response, deal_breaker}`. Ruch za
    # „Screening” dostaje ostrzeżenie (nie blokadę) i akcję „Odrzuć z powodem”.
    deal_breaker_hits: tuple[dict[str, Any], ...] = ()


@dataclass
class _Item:
    column: str
    key: str
    label: str
    status: str
    blocking: bool
    detail: Optional[str] = None
    action: Optional[dict[str, Any]] = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "detail": self.detail,
            "status": self.status,
            "blocking": self.blocking,
            "action": self.action,
            # Kolumna, której dotyczy wymaganie — ekran grupuje po niej listę
            # przy ruchu przez kilka kolumn.
            "column": self.column,
        }

    @property
    def blocks(self) -> bool:
        return self.blocking and self.status == MISSING


def _action(kind: str, label: str, stage_id: Optional[int]) -> dict[str, Any]:
    return {"kind": kind, "label": label, "stage_id": stage_id}


_DEAL_BREAKER_SNIPPET = 200


def _snippet(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= _DEAL_BREAKER_SNIPPET:
        return text
    return text[: _DEAL_BREAKER_SNIPPET - 1].rstrip() + "…"


def deal_breaker_hits(sheet: Any, champion_profile: Any) -> tuple[dict[str, Any], ...]:
    """Odpowiedzi arkusza z ``deal_breaker_hit`` — z treścią pytania i warunku.

    Pytanie bierzemy z odpowiedzi (``question_text`` stemplowany przy zapisie),
    a dla arkuszy sprzed 02.10.2026 z profilu Championa po identyfikatorze.
    „Odpada, gdy…” zawsze z bieżącego profilu. Numer = pozycja pytania
    w profilu (jak w arkuszu), a bez niej — pozycja odpowiedzi.
    """

    from app.services import champion_view  # noqa: PLC0415

    if not isinstance(sheet, dict):
        return ()
    answers = sheet.get("answers")
    if not isinstance(answers, list):
        return ()
    questions: dict[str, tuple[int, dict[str, Any]]] = {}
    for position, question in enumerate(
        champion_view.screening_questions(champion_profile), start=1
    ):
        if isinstance(question, dict) and str(question.get("id") or "").strip():
            questions[str(question["id"]).strip()] = (position, question)
    hits: list[dict[str, Any]] = []
    for position, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict) or answer.get("deal_breaker_hit") is not True:
            continue
        question_id = str(answer.get("question_id") or "").strip()
        number, question = questions.get(question_id, (position, {}))
        hits.append(
            {
                "number": number,
                "question_id": question_id or None,
                "question": _snippet(
                    answer.get("question_text") or question.get("question")
                ),
                "response": _snippet(answer.get("response")),
                "deal_breaker": _snippet(question.get("deal_breaker")) or None,
            }
        )
    return tuple(hits)


def deal_breaker_text(hits: Iterable[dict[str, Any]]) -> str:
    """„Pytanie N: „…” — odpowiedź: „…”. Odpada, gdy: „…”.” — po jednej linii."""

    lines: list[str] = []
    for hit in hits:
        question = hit.get("question") or "pytanie bez treści"
        response = hit.get("response")
        answer = f"„{response}”" if response else "brak zapisanej odpowiedzi"
        line = f"Pytanie {hit.get('number')}: „{question}” — odpowiedź: {answer}."
        if hit.get("deal_breaker"):
            line += f" Odpada, gdy: „{hit['deal_breaker']}”."
        lines.append(line)
    return "\n".join(lines)


def _deal_breaker_item(column: str, f: PairFacts) -> Optional[_Item]:
    if not f.deal_breaker_hits:
        return None
    text = deal_breaker_text(f.deal_breaker_hits)
    return _Item(
        column,
        "deal_breaker",
        "Odpowiedź narusza deal-breaker",
        MISSING,
        False,
        text,
        {
            **_action("reject", "Odrzuć z powodem", f.stage_id),
            # Treść do wpisania w notatkę okna odrzucenia.
            "note": text,
        },
    )


def _index(column: Optional[str]) -> int:
    """Pozycja kolumny; brak etapu i „Zamknięci" liczą się jak „Nowi" —
    powrót zamkniętej osoby do procesu przechodzi całą drogę od początku."""

    if column in BOARD_COLUMN_ORDER:
        return BOARD_COLUMN_ORDER.index(column)
    return 0


def _items_for_cpro_upload(column: str, f: PairFacts) -> list[_Item]:
    return [
        _Item(
            column,
            "cpro_upload",
            "Wrzucenie do Cpro",
            WAITING,
            False,
            (
                f"wrzuca {f.cpro_sender_name}"
                if f.cpro_sender_name
                else "nikt nie jest ustawiony do wysyłki do Cpro"
            ),
        )
    ]


def _missing_rate_detail(f: PairFacts) -> str:
    """Stawka z notatki nie zastępuje stawki etapu — okno stawki ją podpowie."""
    if f.card_rate_hourly is None:
        return "brak stawki w profilu i w procesie"
    return f"z notatki: {f.card_rate_hourly:g} zł/h — potwierdź w oknie stawki"


SCREENING_SHEET = "screening_sheet"
WHY_CANDIDATE = "why_candidate"


def screening_requirement(f: PairFacts) -> tuple[str, bool]:
    """Zapis rozmowy wymagany przed „Zweryfikowany”: (klucz, czy spełniony).

    Rekrutacja z pytaniami: arkusz screeningu albo odpowiedzi w notatce.
    Rekrutacja bez pytań nie ma czego zapisać w arkuszu (12.10.2026: 33 z 206
    otwartych rekrutacji, wszystkie z Traffita — bramka zatrzymywała tam
    każdego), więc zapisem rozmowy jest „Dlaczego ten kandydat” (decyzja
    Artura 12.10.2026). Jedna reguła dla bramki ruchu i okna „Przesuń dalej”.
    """
    return _screening_requirement(
        has_questions=f.has_screening_questions,
        sheet=f.screening_done,
        note_answers=f.card_answers,
        recommendation=f.card_recommendation,
    )


def _screening_requirement(
    *, has_questions: bool, sheet: bool, note_answers: bool, recommendation: bool
) -> tuple[str, bool]:
    answered = sheet or note_answers
    if has_questions:
        return SCREENING_SHEET, answered
    return WHY_CANDIDATE, answered or recommendation


def required_card_fields(f: PairFacts) -> tuple[str, ...]:
    """Pola karty wymagane przed „Zweryfikowany” — minimum + pola klienta."""
    from app.services.recommendation_card_rules import (  # noqa: PLC0415
        VERIFIED_MINIMUM_FIELDS,
    )

    if not f.minimum_enabled:
        return ()
    extra = tuple(
        key for key in f.client_required_fields if key not in VERIFIED_MINIMUM_FIELDS
    )
    return (*VERIFIED_MINIMUM_FIELDS, *extra)


async def client_required_fields(
    db: AsyncSession, client_id: Optional[int]
) -> tuple[tuple[str, ...], Optional[str]]:
    """Pola dołożone do minimum w karcie klienta (D3, 21.10.2026) i nazwa klienta.

    Jedno zapytanie; brak karty albo pustej listy = ``((), None)``. Klucze
    spoza ``CLIENT_EXTRA_FIELDS`` (stary zapis) pomijamy.
    """
    from app.models.client import Client  # noqa: PLC0415
    from app.models.client_playbook import ClientPlaybook  # noqa: PLC0415
    from app.services.recommendation_card_rules import (  # noqa: PLC0415
        CLIENT_EXTRA_FIELDS,
    )

    if client_id is None:
        return (), None
    row = (
        await db.execute(
            select(
                ClientPlaybook.verified_required_fields,
                Client.display_name,
                Client.name,
            )
            .join(Client, Client.id == ClientPlaybook.client_id)
            .where(ClientPlaybook.client_id == client_id)
        )
    ).first()
    if row is None or not isinstance(row.verified_required_fields, list):
        return (), None
    fields = tuple(
        key for key in CLIENT_EXTRA_FIELDS if key in row.verified_required_fields
    )
    if not fields:
        return (), None
    name = (row.display_name or "").strip() or row.name
    return fields, name


def card_field_label(key: str) -> str:
    """Nazwa pola karty na ekranie („Dlaczego ten kandydat”, „Lokalizacja”)."""
    from app.services.recommendation_card_rules import (  # noqa: PLC0415
        DISPLAY_LABELS,
    )

    return DISPLAY_LABELS.get(key, key)


def minimum_missing(f: PairFacts) -> list[str]:
    """Pola minimum dla DL bez treści (decyzja Artura 21.10.2026).

    Dostępność liczy się też z profilu (data dostępności). W rekrutacji bez
    pytań „Dlaczego ten kandydat” jest już wymaganiem rozmowy
    (`why_candidate`) — nie wymieniamy go drugi raz.
    """
    present = set(f.card_present)
    if f.availability_known or f.card_availability:
        present.add("availability")
    missing = [key for key in required_card_fields(f) if key not in present]
    if _why_candidate_reported(f):
        missing = [key for key in missing if key != "recommendation"]
    return missing


def _why_candidate_reported(f: PairFacts) -> bool:
    """„Dlaczego” stoi już na liście jako niespełnione `why_candidate`.

    Tylko wtedy minimum go pomija. Rekrutacja bez pytań, w której rozmowę
    zapisały odpowiedzi z notatki albo stary arkusz, spełnia `why_candidate`
    bez oceny — minimum dalej jej wymaga (przegląd 21.10.2026).
    """
    key, met = screening_requirement(f)
    return key == WHY_CANDIDATE and not met


def board_minimum_missing(
    card: Optional[Mapping[str, Any]],
    *,
    has_questions: bool,
    availability_known: bool,
    screening_met: bool,
    client_required: Sequence[str] = (),
) -> list[str]:
    """Braki minimum dla DL karty Tablicy — z podsumowania karty, bez zapytań.

    Ta sama reguła co ``minimum_missing`` (bramka i okno „Przesuń dalej”).
    ``screening_met`` = ``screening_done`` karty (`card_screening_state`).
    """
    from app.core.config import settings  # noqa: PLC0415

    return minimum_missing(
        PairFacts(
            from_column=None,
            availability_known=availability_known,
            card_availability=bool(card and card.get("availability")),
            card_present=frozenset((card or {}).get("present") or ()),
            has_screening_questions=has_questions,
            screening_done=screening_met,
            client_required_fields=tuple(client_required),
            minimum_enabled=settings.VERIFIED_MINIMUM_FIELDS_ENABLED,
        )
    )


def _card_recommended(card: Optional[Mapping[str, Any]]) -> bool:
    """Karta (``recommendation_cards.card_summary``) ma „Dlaczego ten kandydat”."""
    return bool(card) and "recommendation" not in (card.get("missing") or ())


def missing_screening_requirement(
    *, has_questions: bool, sheet: bool, card: Optional[Mapping[str, Any]]
) -> Optional[str]:
    """Klucz niespełnionego wymagania rozmowy pary albo ``None``.

    Ta sama reguła co bramka — dla list, które nie ładują pełnych faktów pary
    („Czeka na Ciebie”): arkusz albo odpowiedzi w notatce, a w rekrutacji bez
    pytań także „Dlaczego ten kandydat”.
    """
    key, met = _screening_requirement(
        has_questions=has_questions,
        sheet=sheet,
        note_answers=bool(card and int(card.get("answers") or 0)),
        recommendation=_card_recommended(card),
    )
    return None if met else key


def card_screening_state(
    *, has_questions: bool, sheet: bool, card: Optional[Mapping[str, Any]]
) -> tuple[bool, Optional[str]]:
    """``screening_done`` i ``screening_requirement`` karty Tablicy.

    Rekrutacja z pytaniami: jak dotąd — „arkusz zapisany” i brak pola
    wymagania. Rekrutacja bez pytań (13.10.2026): po poprawce bramki karta
    w „Screeningu” dalej prosiła o arkusz, którego tam nie ma; teraz mówi
    o „Dlaczego ten kandydat”, a „zrobione” znaczy to samo co w bramce.
    """
    if has_questions:
        return sheet, None
    missing = missing_screening_requirement(has_questions=False, sheet=sheet, card=card)
    return missing is None, WHY_CANDIDATE


def _screening_item(column: str, f: PairFacts) -> _Item:
    key, met = screening_requirement(f)
    if key == WHY_CANDIDATE:
        return _Item(
            column,
            WHY_CANDIDATE,
            "Dlaczego ten kandydat",
            OK if met else MISSING,
            True,
            None
            if met
            else "rekrutacja nie ma pytań screeningowych — wpisz ocenę w screeningu",
            None if met else _action("open_card", "Uzupełnij w screeningu", f.stage_id),
        )
    return _Item(
        column,
        SCREENING_SHEET,
        "Arkusz screeningu",
        OK if met else MISSING,
        True,
        (
            None
            if f.screening_done
            else "odpowiedzi są w notatce rekrutera"
            if f.card_answers
            else "odpowiedzi jeszcze nie zapisane"
        ),
        None
        if met
        else _action(
            "open_screening", "Otwórz screening", f.screening_stage_id or f.stage_id
        ),
    )


def _minimum_items(column: str, f: PairFacts) -> list[_Item]:
    """Pozycje minimum dla DL (21.10.2026) — blokują jak bramka serwera.

    Przy wyłączniku zostaje dawna, nieblokująca „Dostępność”.
    """
    availability_ok = f.availability_known or f.card_availability
    availability_detail = (
        None
        if f.availability_known
        else "jest w screeningu"
        if f.card_availability
        else "nie wiemy, od kiedy może zacząć"
    )
    if not f.minimum_enabled:
        return [
            _Item(
                column,
                "availability",
                "Dostępność",
                OK if availability_ok else MISSING,
                False,
                availability_detail,
            )
        ]
    missing = set(minimum_missing(f))
    client_extra = set(f.client_required_fields)
    items: list[_Item] = []
    for key in required_card_fields(f):
        if key == "recommendation" and _why_candidate_reported(f):
            continue  # już jako niespełnione wymaganie rozmowy (`why_candidate`)
        absent = key in missing
        if key == "availability":
            detail = availability_detail
        elif absent and key in client_extra and f.client_name:
            detail = f"wymaga {f.client_name}"
        elif absent:
            detail = "Delivery Lead potrzebuje tego przed wysłaniem CV"
        else:
            detail = None
        items.append(
            _Item(
                column,
                key,
                card_field_label(key),
                MISSING if absent else OK,
                True,
                detail,
                _action("open_card", "Uzupełnij w screeningu", f.stage_id)
                if absent
                else None,
            )
        )
    return items


def _items_for(column: str, f: PairFacts) -> list[_Item]:
    sid = f.stage_id
    if column == "verified":
        return [
            _screening_item(column, f),
            _Item(
                column,
                "candidate_rate",
                "Stawka kandydata",
                OK if f.candidate_rate else MISSING,
                True,
                None if f.candidate_rate else _missing_rate_detail(f),
                None
                if f.candidate_rate
                else _action("set_candidate_rate", "Wpisz stawkę", sid),
            ),
            *_minimum_items(column, f),
            # Pozostałe pola nie blokują ruchu — Delivery Lead zobaczy je
            # przed wysłaniem CV. Od 0424 uzupełnia się je w formularzu
            # screeningu (akcja `open_card` otwiera panel na screeningu); od
            # 09.10.2026 ekran nie używa nazwy „karta rekomendacji”.
            _Item(
                column,
                "recommendation_card",
                "Warunki i ocena",
                OK if f.card_exists and not f.card_missing else MISSING,
                False,
                (
                    "brakuje: " + ", ".join(f.card_missing)
                    if f.card_missing
                    else None
                    if f.card_exists
                    else "jeszcze nic nie wpisano"
                ),
                None
                if f.card_exists and not f.card_missing
                else _action("open_card", "Uzupełnij w screeningu", sid),
            ),
        ]
    if column == "cv_qc":
        return [
            _Item(
                column,
                "company_cv",
                "CV firmowe „Pod rekrutację”",
                OK if f.company_cv else MISSING,
                f.qc_gate_enabled,
                None if f.company_cv else "jeszcze nie wygenerowane",
                None
                if f.company_cv
                else _action("generate_cv", "Wygeneruj teraz", sid),
            )
        ]
    if column == "cv_sent":
        qc_ok = f.qc_status in QC_OK_STATUSES
        # Osoba już w kolejce Cpro przeszła QC przy wejściu do niej — serwer
        # przy „✓ Wrzucone" QC nie liczy drugi raz (`_assert_cv_qc_gate`),
        # więc okno nie może go blokować (audyt 25.09.2026).
        if f.nordea and f.on_cpro_stage and not qc_ok:
            return [
                _Item(
                    column,
                    "cv_qc",
                    "QC CV",
                    OK,
                    False,
                    "sprawdzone przy przekazaniu do kolejki Cpro",
                ),
                *_items_for_cpro_upload(column, f),
            ]
        if f.qc_status == "overridden":
            qc_detail: Optional[str] = "przepuszczone mimo QC (z powodem)"
        elif f.qc_status == "failed":
            qc_detail = f"do poprawy: {max(1, f.qc_blocking_failed)}"
        elif f.qc_status == "unchecked":
            qc_detail = "QC jeszcze nie policzone"
        else:
            qc_detail = None
        if not f.qc_gate_enabled and not qc_ok:
            qc_detail = "QC CV jest wyłączone — nie blokuje wysyłki"
        items = [
            _Item(
                column,
                "cv_qc",
                "QC CV",
                OK if qc_ok else (MISSING if f.qc_gate_enabled else WAITING),
                f.qc_gate_enabled,
                qc_detail,
                None if qc_ok else _action("open_qc", "Otwórz QC CV", sid),
            )
        ]
        if f.nordea:
            # Od 13.10.2026 do kolejki Cpro wkłada Delivery Lead po akceptacji
            # i wpisuje stawkę do Cpro (`pipeline_move_rules.requires_dl_client_rate`).
            if f.is_client_sender:
                items.append(
                    _Item(
                        column,
                        "client_rate",
                        "Stawka do Cpro",
                        OK if f.client_rate else WAITING,
                        False,
                        None if f.client_rate else "wpiszesz ją przy akceptacji",
                        None
                        if f.client_rate
                        else _action("set_client_rate", "Przejrzyj i zaakceptuj", sid),
                    )
                )
            else:
                items.append(
                    _Item(
                        column,
                        "dl_acceptance",
                        "Akceptacja Delivery Leada",
                        WAITING,
                        False,
                        "Delivery Lead akceptuje i wpisuje stawkę do Cpro",
                    )
                )
            items.extend(_items_for_cpro_upload(column, f))
        elif f.is_client_sender:
            items.append(
                _Item(
                    column,
                    "client_rate",
                    "Stawka do klienta",
                    # Brak nie blokuje: okno stawki pyta o nią w samym ruchu
                    # (test na produkcji 24.09.2026 — czerwony krzyżyk przy
                    # „wpiszesz ją przy wysyłce” czytał się jak blokada).
                    OK if f.client_rate else WAITING,
                    False,
                    None if f.client_rate else "wpiszesz ją przy wysyłce",
                    None
                    if f.client_rate
                    else _action("set_client_rate", "Wpisz stawkę do klienta", sid),
                )
            )
        else:
            items.append(
                _Item(
                    column,
                    "client_rate",
                    "Stawka do klienta",
                    WAITING,
                    False,
                    "ustala Delivery Lead przy wysyłce",
                )
            )
        return items
    if column == "client_interview":
        return [
            _Item(
                column,
                "client_slot",
                "Termin od klienta",
                OK if f.client_slot else WAITING,
                False,
                None if f.client_slot else "czekamy na terminy od klienta",
                None
                if f.client_slot
                else _action("request_slots", "Dodaj terminy od klienta", sid),
            )
        ]
    if column == "contract":
        if f.debrief_pending:
            debrief_detail: Optional[str] = "rozmowa u klienta jeszcze się nie odbyła"
        elif f.debrief_missing:
            debrief_detail = "zapisz pytania klienta po rozmowie"
        else:
            debrief_detail = None
        return [
            _Item(
                column,
                "debrief",
                "Debrief po rozmowie u klienta",
                MISSING if f.debrief_missing else OK,
                True,
                debrief_detail,
                {
                    **_action("open_debrief", "Uzupełnij debrief", sid),
                    "event_id": f.debrief_event_id,
                }
                if f.debrief_missing and not f.debrief_pending
                else None,
            ),
            _Item(
                column,
                "client_decision",
                "Decyzja klienta",
                OK if f.client_decision else WAITING,
                False,
                None if f.client_decision else "brak zapisanej decyzji klienta",
            ),
        ]
    if column == "hired":
        return [
            _Item(
                column,
                "signature",
                "Podpis umowy przez obie strony",
                OK if f.signed else WAITING,
                False,
                None if f.signed else "umowa jeszcze niepodpisana",
            )
        ]
    return []


def build_requirements(facts: PairFacts, to_column: str) -> dict[str, Any]:
    """Lista wymagań i główna akcja dla ruchu na ``to_column``."""

    from_column = facts.from_column
    to_label = column_label(to_column, nordea=facts.nordea)
    forward = to_column in BOARD_COLUMN_ORDER and (
        from_column not in BOARD_COLUMN_ORDER or _index(to_column) > _index(from_column)
    )
    result: dict[str, Any] = {
        "from_column": from_column,
        "to_column": to_column,
        "skipped_columns": [],
        "items": [],
        "primary": {"kind": "move", "label": f"Przesuń na „{to_label}”"},
        "owner_note": None,
    }
    if not forward:
        return result

    start, stop = _index(from_column), _index(to_column)
    path = list(BOARD_COLUMN_ORDER[start + 1 : stop + 1])
    result["skipped_columns"] = path[:-1]
    items = [item for column in path for item in _items_for(column, facts)]
    # Ruch za „Screening” z odpowiedzią, która narusza „Odpada, gdy…”:
    # ostrzeżenie (nie bramka) z akcją odrzucenia — 04.10.2026. Na prodzie
    # 2 z 3 takich osób wysłano do klienta, bo nic o tym nie mówiło.
    if _index(to_column) >= _index("verified"):
        warning = _deal_breaker_item(to_column, facts)
        if warning is not None:
            items.append(warning)
    result["items"] = [item.as_dict() for item in items]

    primary: dict[str, Any] = {"kind": "move", "label": f"Przesuń na „{to_label}”"}
    owner_note: Optional[str] = None
    blocking = [item for item in items if item.blocks]

    if to_column == "cv_sent" and facts.nordea:
        if facts.on_cpro_stage:
            # Osoba już czeka w kolejce Cpro — „✓ Wrzucone" to zwykły ruch,
            # ale robi go osoba od Cpro, admin, DL albo HoR.
            if not facts.can_send_to_cpro:
                primary = {"kind": "blocked", "label": "Czeka w kolejce Cpro"}
                owner_note = (
                    f"Do Cpro wrzuca {facts.cpro_sender_name}."
                    if facts.cpro_sender_name
                    else "Nikt nie jest ustawiony do wysyłki do Cpro."
                )
        elif facts.is_client_sender and from_column == "cv_qc":
            # Delivery Lead akceptuje osobę do kolejki Cpro w przeglądzie
            # (stawka do Cpro wymagana) — front otwiera przegląd, nie goły ruch.
            primary = {
                "kind": "hand_to_cpro",
                "label": "Przejrzyj i zaakceptuj do Cpro",
                "target_stage_def_id": facts.cpro_stage_def_id,
            }
            owner_note = (
                f"Po akceptacji osoba trafi do kolejki Cpro — wrzuca {facts.cpro_sender_name}."
                if facts.cpro_sender_name
                else (
                    "Po akceptacji osoba trafi do kolejki Cpro. Nikt nie jest "
                    "ustawiony do wysyłki do Cpro — ustaw osobę w kolejce Cpro."
                )
            )
        else:
            # Rekruter przekazuje osobę Delivery Leadowi (13.10.2026) — do
            # kolejki Cpro wkłada dopiero DL po akceptacji. Delivery Lead
            # z kolumny sprzed „QC CV” najpierw przenosi tam kartę: przegląd
            # i akceptacja są w „QC CV”. Blokuje tylko to, co potrzebne do
            # wejścia do „QC CV”.
            qc_index = BOARD_COLUMN_ORDER.index("cv_qc")
            blocking = [
                item
                for item in blocking
                if BOARD_COLUMN_ORDER.index(item.column) <= qc_index
            ]
            primary = {
                "kind": "hand_to_dl",
                "label": (
                    "Przenieś do „QC CV” do akceptacji"
                    if facts.is_client_sender
                    else "Przekaż Delivery Leadowi"
                ),
                "target_stage_def_id": (
                    None if from_column == "cv_qc" else facts.qc_stage_def_id
                ),
            }
            owner_note = (
                "Akceptuje Delivery Lead — po akceptacji osoba trafi do kolejki "
                + (
                    f"Cpro (wrzuca {facts.cpro_sender_name})."
                    if facts.cpro_sender_name
                    else "Cpro."
                )
            )
    elif to_column == "cv_sent" and not facts.is_client_sender:
        # Wysyłka do klienta należy do Delivery Leada: rekruter przekazuje
        # osobę do „QC CV" (tam DL ją przegląda; na pulpicie DL-a to pas „Do
        # wysłania do klienta"). Blokuje więc tylko to, co jest potrzebne do
        # wejścia do „QC CV".
        qc_index = BOARD_COLUMN_ORDER.index("cv_qc")
        blocking = [
            item
            for item in blocking
            if BOARD_COLUMN_ORDER.index(item.column) <= qc_index
        ]
        primary = {
            "kind": "hand_to_dl",
            "label": "Przekaż Delivery Leadowi",
            "target_stage_def_id": (
                None if from_column == "cv_qc" else facts.qc_stage_def_id
            ),
        }
        # 14.10.2026: sekcji „Czeka na Ciebie” z przeglądami DL-a już nie ma
        # (pas „Do wysłania do klienta”, 13.10.2026) — zdanie mówi, gdzie
        # osoba faktycznie czeka.
        owner_note = (
            "Osoba czeka u Delivery Leada w kolumnie „QC CV” — CV do klienta wysyła on."
        )

    if blocking and primary["kind"] != "blocked":
        primary = {
            "kind": "blocked",
            # Nazwa wymagania bywa własną nazwą („QC CV”), więc bez `.lower()`.
            "label": f"Najpierw uzupełnij: {blocking[0].label}",
        }
    result["primary"] = primary
    result["owner_note"] = owner_note
    return result


# ── Fakty z bazy ─────────────────────────────────────────────────────────────


async def company_cv_refs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, Any]]:
    """CV firmowe par — hurtem, bez pobierania plików.

    Kolejność źródeł jak w przeglądzie QC: CV firmowe etapu (zatwierdzone
    przed szkicem), gotowe CV z generatora, plik „…B2B…" kandydata (CV
    zrobione poza generatorem). Brak pary w wyniku = brak CV.
    """

    from app.models.candidate_document import CandidateDocument  # noqa: PLC0415
    from app.models.candidate_stage_cv import CandidateStageCV  # noqa: PLC0415
    from app.models.cv_generated_document import CvGeneratedDocument  # noqa: PLC0415
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415

    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    out: dict[tuple[int, int], dict[str, Any]] = {}

    branded = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStageCV.candidate_stage_id,
                CandidateStageCV.generated_document_id,
                CandidateStageCV.branded_status,
            )
            .join(
                CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id
            )
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
                CandidateStageCV.branded_draft_html.is_not(None),
            )
            .order_by(
                (CandidateStageCV.branded_status == "finalized").desc(),
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
        )
    ).all()
    for cand, job, stage_id, gen_id, status in branded:
        out.setdefault(
            (cand, job),
            {
                "source": f"branded_{status}",
                "stage_id": stage_id,
                "generated_document_id": gen_id,
                "document_id": None,
            },
        )

    missing = [p for p in wanted if p not in out]
    if missing:
        generated = (
            await db.execute(
                select(
                    CvGeneratedDocument.candidate_id,
                    CvGeneratedDocument.job_id,
                    CvGeneratedDocument.id,
                )
                .where(
                    tuple_(
                        CvGeneratedDocument.candidate_id, CvGeneratedDocument.job_id
                    ).in_(missing),
                    CvGeneratedDocument.status == "ready",
                    CvGeneratedDocument.render_payload.is_not(None),
                )
                .order_by(
                    CvGeneratedDocument.created_at.desc(),
                    CvGeneratedDocument.id.desc(),
                )
            )
        ).all()
        for cand, job, doc_id in generated:
            out.setdefault(
                (cand, job),
                {
                    "source": "generated",
                    "stage_id": None,
                    "generated_document_id": doc_id,
                    "document_id": None,
                },
            )

    missing = [p for p in wanted if p not in out]
    if missing:
        # Runda 8 (R8-N8-1): plik wybiera ta sama reguła co QC CV
        # (`dz_review.pick_document_cv` — nazwa klienta rekrutacji w nazwie
        # pliku, potem najnowszy), inaczej kolejka Cpro dawała do pobrania
        # inny plik niż ten, który przeszedł QC.
        from app.models.client import Client  # noqa: PLC0415
        from app.models.job import Job  # noqa: PLC0415
        from app.services.dz_review import (  # noqa: PLC0415
            document_cv_ambiguous,
            document_cv_conditions,
            pick_document_cv,
        )

        candidate_ids = sorted({c for c, _ in missing})
        documents = (
            await db.execute(
                select(
                    CandidateDocument.candidate_id,
                    CandidateDocument.id,
                    CandidateDocument.filename,
                    CandidateDocument.uploaded_at,
                    CandidateDocument.created_at,
                ).where(
                    CandidateDocument.candidate_id.in_(candidate_ids),
                    *document_cv_conditions(),
                )
            )
        ).all()
        by_candidate: dict[int, list[tuple]] = {}
        for cand, doc_id, filename, uploaded_at, created_at in documents:
            by_candidate.setdefault(cand, []).append(
                (doc_id, filename, uploaded_at, created_at)
            )
        client_names: dict[int, Optional[str]] = {}
        job_ids = sorted({j for c, j in missing if c in by_candidate})
        if job_ids:
            for job_id, display_name, name in (
                await db.execute(
                    select(Job.id, Client.display_name, Client.name)
                    .join(Client, Client.id == Job.client_id)
                    .where(Job.id.in_(job_ids))
                )
            ).all():
                client_names[job_id] = display_name or name
        for cand, job in missing:
            rows = by_candidate.get(cand, [])
            doc_id = pick_document_cv(rows, client_names.get(job))
            if doc_id is not None:
                out[(cand, job)] = {
                    "source": "document",
                    "stage_id": None,
                    "generated_document_id": None,
                    "document_id": doc_id,
                    # Kilka plików tego klienta — do sprawdzenia (R9-V2-5).
                    "ambiguous": document_cv_ambiguous(rows, client_names.get(job)),
                }
    return out


async def qc_statuses(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict]:
    """Wynik QC CV par (`cv_qc.pair_statuses`) — jedno zapytanie hurtowe.

    Import leniwy: moduł QC ciągnie generator CV i parsery dokumentów, a ta
    funkcja jest wołana przy każdym odczycie kolejki i okna ruchu.
    """

    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    from app.services.cv_qc import pair_statuses  # noqa: PLC0415

    return await pair_statuses(db, wanted)


def _enum(value: Any) -> Optional[str]:
    return getattr(value, "value", value)


def stage_def_column(stage_def: Any) -> str:
    """Kolumna Tablicy etapu docelowego — liczona z etapu, nie z wiersza pary
    (etap docelowy bywa z innego szablonu niż bieżący wiersz)."""

    return board_column_for(
        stage_def.name,
        stage_def.legacy_enum_value,
        category=_enum(stage_def.category),
        terminal_type=_enum(stage_def.terminal_type),
    )


async def load_pair_facts(
    db: AsyncSession, *, candidate: Any, job: Any, user: Any
) -> PairFacts:
    """Fakty pary dla ``build_requirements`` — kilka zapytań, bez plików."""

    from sqlalchemy import exists  # noqa: PLC0415

    from app.models.b2b_generated_contract import (  # noqa: PLC0415
        B2BGeneratedContract,
    )
    from app.models.calendar_event import (  # noqa: PLC0415
        CalendarEvent,
        EventStatus,
        EventType,
    )
    from app.models.client_interview_slot_request import (  # noqa: PLC0415
        ClientInterviewSlotRequest,
    )
    from app.models.interview_feedback import (  # noqa: PLC0415
        FeedbackSource,
        InterviewFeedback,
    )
    from app.models.pipeline_template import (  # noqa: PLC0415
        PipelineStageDef,
        PipelineTemplate,
    )
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services import candidate_claim, cpro_sender  # noqa: PLC0415
    from app.services.board_tasks import classify_template  # noqa: PLC0415
    from app.services.debrief_gate import missing_debrief  # noqa: PLC0415
    from app.core.config import settings  # noqa: PLC0415
    from app.services.action_permissions import (  # noqa: PLC0415
        ProductAction,
        has_permission,
    )

    pair = (candidate.id, job.id)
    rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == candidate.id,
                    CandidateStage.job_id == job.id,
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = rows[0] if rows else None
    from_column = (
        await candidate_claim.stage_column(db, latest) if latest is not None else None
    )
    # Arkusz tylko bieżącej próby procesu (audyt 05.10.2026): osoba, która
    # wraca do rekrutacji po długiej przerwie, nie przechodzi na
    # „Zweryfikowany” arkuszem sprzed roku. Ta sama reguła przenosi arkusz
    # przy ruchu (``recruitment_process_commands.screening_window``).
    from app.services.recruitment_process_commands import (  # noqa: PLC0415
        screening_window,
    )

    process = await candidate_claim.load_process(
        db, candidate_id=candidate.id, job_id=job.id
    )
    window = screening_window(process)
    # Arkusz z odpowiedzią, nie sam zapisany arkusz (audyt 13.10.2026, pkt 5).
    screening_row = next(
        (
            r
            for r in rows
            if sheet_answered(r.screening_answers) and window.covers(r.moved_at)
        ),
        None,
    )
    from app.services.candidate_rate_from import effective_rate

    candidate_rate = effective_rate(candidate)[0] is not None or any(
        r.expected_rate_value is not None for r in rows
    )
    client_rate = any(r.client_rate_value is not None for r in rows)

    on_cpro_stage = False
    if latest is not None and latest.stage_def_id is not None:
        latest_name = await db.scalar(
            select(PipelineStageDef.name).where(
                PipelineStageDef.id == latest.stage_def_id
            )
        )
        on_cpro_stage = is_cpro_stage(latest_name)

    template_id = job.pipeline_template_id or await db.scalar(
        select(PipelineTemplate.id)
        .where(PipelineTemplate.is_default.is_(True))
        .order_by(PipelineTemplate.id)
        .limit(1)
    )
    stages = None
    if template_id is not None:
        defs = (
            await db.scalars(
                select(PipelineStageDef).where(
                    PipelineStageDef.template_id == template_id
                )
            )
        ).all()
        stages = classify_template(defs)

    nordea = cpro_enabled_for_client(job.client_id)
    sender_name: Optional[str] = None
    can_cpro = False
    if nordea:
        sender = await cpro_sender.effective_sender(db)
        # Bez osoby na firmę kolejka należy do osoby zapasowej rekrutacji —
        # ta sama reguła co bramka ruchu i `board_tasks._sees_cpro`.
        # Martwe konto nie jest osobą zapasową (lustro `board_tasks._LATEST_SQL`).
        active = await cpro_sender.active_user_ids(
            db,
            (
                getattr(job, "cpro_sender_id", None),
                latest.task_assignee_id if latest is not None else None,
            ),
        )
        fallback_ids = tuple(
            uid
            for uid in (
                getattr(job, "cpro_sender_id", None),
                latest.task_assignee_id if latest is not None else None,
            )
            if uid in active
        )
        shown_sender = sender.user_id or next(
            (uid for uid in fallback_ids if uid is not None), None
        )
        if shown_sender is not None:
            sender_name = (await cpro_sender.user_names(db, {shown_sender})).get(
                shown_sender
            )
        can_cpro = await cpro_sender.can_send_to_cpro(
            db, user, fallback_sender_ids=fallback_ids
        )

    cv = (await company_cv_refs(db, [pair])).get(pair)
    qc = (await qc_statuses(db, [pair])).get(pair) or {}
    debrief = await missing_debrief(db, candidate_id=candidate.id, job_id=job.id)

    client_slot = bool(
        await db.scalar(
            select(
                exists().where(
                    ClientInterviewSlotRequest.candidate_id == candidate.id,
                    ClientInterviewSlotRequest.job_id == job.id,
                    ClientInterviewSlotRequest.status == "confirmed",
                )
            )
        )
    ) or bool(
        await db.scalar(
            select(
                exists().where(
                    CalendarEvent.candidate_id == candidate.id,
                    CalendarEvent.job_id == job.id,
                    CalendarEvent.event_type == EventType.client_interview,
                    CalendarEvent.status != EventStatus.cancelled,
                )
            )
        )
    )
    client_decision = bool(
        await db.scalar(
            select(
                exists().where(
                    InterviewFeedback.candidate_id == candidate.id,
                    InterviewFeedback.job_id == job.id,
                    InterviewFeedback.feedback_source == FeedbackSource.client_side,
                    InterviewFeedback.decision.is_not(None),
                )
            )
        )
    )
    signed = bool(
        await db.scalar(
            select(
                exists().where(
                    B2BGeneratedContract.candidate_id == candidate.id,
                    B2BGeneratedContract.job_id == job.id,
                    B2BGeneratedContract.signature_status == "signed_both",
                )
            )
        )
    )

    # 0413: karta rekomendacji pary — braki są podpowiedzią, nie bramką.
    from app.services import recommendation_cards

    card_row = await recommendation_cards.load_card(
        db, candidate_id=candidate.id, job_id=job.id
    )
    stage_rate = any(r.expected_rate_value is not None for r in rows)
    card = None
    if card_row is not None or stage_rate:
        card = recommendation_cards.card_summary(
            (card_row.fields_notes if card_row else None) or {},
            (card_row.fields_manual if card_row else None) or {},
            card_row.note_answers if card_row else None,
            started=recommendation_cards.attempt_started(process),
            stage_rate=stage_rate,
        )
    # Import leniwy: arkusz screeningu importuje ten moduł (`sheet_filled`).
    from app.services import screening_sheets  # noqa: PLC0415

    client_fields, client_fields_owner = await client_required_fields(db, job.client_id)

    return PairFacts(
        from_column=from_column,
        stage_id=latest.id if latest is not None else None,
        screening_done=screening_row is not None,
        screening_stage_id=(
            screening_row.id
            if screening_row is not None
            else (latest.id if latest is not None else None)
        ),
        candidate_rate=candidate_rate,
        availability_known=candidate.availability_date is not None,
        card_missing=tuple(card["missing_labels"]) if card else (),
        card_exists=card is not None and card["status"] != "empty",
        card_answers=bool(card and card["answers"]),
        # Te same pytania, na które formularz przyjmuje odpowiedź
        # (`validate_save`): z identyfikatorem i treścią.
        has_screening_questions=bool(
            screening_sheets.question_texts(job.champion_profile)
        ),
        # Jak arkusz: ocena z próby zamkniętej dawno temu się nie liczy
        # (`screening_window`) — `attempt_started` odcina tylko próby 2+.
        card_recommendation=bool(
            window.counts and card and "recommendation" not in card["missing"]
        ),
        card_availability=bool(card and card["availability"]),
        card_rate_hourly=card["rate_hourly"] if card else None,
        card_present=frozenset(card["present"]) if card else frozenset(),
        client_required_fields=client_fields,
        client_name=client_fields_owner,
        minimum_enabled=settings.VERIFIED_MINIMUM_FIELDS_ENABLED,
        company_cv=cv is not None,
        qc_status=qc.get("status") or "unchecked",
        qc_blocking_failed=int(qc.get("blocking_failed") or 0),
        client_rate=client_rate,
        is_client_sender=has_permission(user, ProductAction.recruitment_manage),
        nordea=nordea,
        cpro_stage_def_id=stages.cpro_id if stages is not None else None,
        qc_stage_def_id=stages.qc_id if stages is not None else None,
        on_cpro_stage=on_cpro_stage,
        can_send_to_cpro=can_cpro,
        cpro_sender_name=sender_name,
        client_slot=client_slot,
        debrief_missing=debrief is not None,
        debrief_pending=bool(debrief and debrief.get("interview_pending")),
        debrief_event_id=debrief.get("event_id") if debrief else None,
        client_decision=client_decision,
        signed=signed,
        qc_gate_enabled=settings.CV_QC_GATE_ENABLED,
        deal_breaker_hits=(
            deal_breaker_hits(screening_row.screening_answers, job.champion_profile)
            if screening_row is not None
            else ()
        ),
    )


__all__ = [
    "CLIENT_EXTRA_FIELDS",
    "COLUMN_LABEL",
    "PairFacts",
    "answer_has_content",
    "build_requirements",
    "card_screening_state",
    "column_label",
    "company_cv_refs",
    "deal_breaker_hits",
    "deal_breaker_text",
    "load_pair_facts",
    "missing_screening_requirement",
    "qc_statuses",
    "screening_requirement",
    "sheet_answered",
    "sheet_filled",
    "stage_def_column",
]
