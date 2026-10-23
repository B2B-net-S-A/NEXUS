"""Polecenie własnymi słowami dla całego CV — Edytor CV 2, PR 4 (decyzja Artura 12.10.2026).

Rekruter pisze polecenie („skróć do dwóch stron, zostaw wszystko o Kafce”)
albo wybiera gotowe. Model zwraca PLAN: listę operacji na wierszach CV. KOD
sprawdza każdą operację osobno i wypuszcza tylko te, które da się bezpiecznie
zastosować:

* usuwać, łączyć, przestawiać i przeredagować wolno zwykłą treść (punkty
  i akapity); tytuł, nagłówki, stanowisko, firma, etykieta obowiązków i lista
  technologii mają zapis, z którego serwer składa Word — znikają tylko razem
  z całą rolą albo sekcją,
* nowy tekst (przeredagowanie, połączenie) przechodzi tę samą kontrolę „bez
  nowych faktów” co AI na zaznaczeniu (`cv_selection_ai.check`),
* jeden wiersz należy do jednej operacji, więc rekruter może odznaczyć
  dowolną z nich bez psucia pozostałych.

Trasa niczego nie zapisuje: plan nakłada edytor jedną cofalną zmianą, po tym
jak rekruter wybierze operacje, a utrwala go zwykły autozapis.

Edytor CV 3, PR 4 (asystent w kolumnie, decyzje D1–D6 Artura, 14.10.2026):
rekruter pisze jak do czatu, a edytor nakłada plan OD RAZU (jedno „Cofnij” na
wiadomość). Dlatego:

* fakt, którego nie ma w zastępowanych wierszach ani w źródłach (oryginalne
  CV, notatki bez ustaleń handlowych), nie znika z planu — operacja wraca
  z ``ask: "source"`` i ``problem`` („Terraform”), a edytor pyta „Kandydat
  mówił o tym na rozmowie?”; „Tak” zapisuje notatkę pary
  (`confirm_fact`) i dopiero wtedy nakłada zmianę,
* usunięcie jedynego miejsca z wymaganiem klienta wraca z ``ask: "loses"``,
* kwoty nie trafiają do CV nigdy (odrzucenie, bez pytania),
* nowe operacje: ``add`` (punkt albo akapit za wskazanym wierszem),
  ``bold``/``unbold`` (terminy, które stoją w CV), ``considered_for`` (cel
  rekrutacji w linii „Rozważany na stanowisko:” — to decyzja rekrutera, nie
  fakt o kandydacie, więc bez kontroli faktów),
* model dostaje kilka ostatnich wiadomości rozmowy (ogrodzone) i wiersze
  zaznaczone w edytorze.

16.10.2026 (zgłoszenie rekruterki: „ułóż miejsca pracy chronologicznie” →
„żadna zmiana nie przeszła kontroli”): ``reorder_roles`` przestawia całe
stanowiska. Kolejność od najnowszego / od najstarszego liczy kod z dat w linii
stanowiska (`cv_role_order`), nie model; własną kolejność model podaje jako
permutację numerów wszystkich stanowisk.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_qc, cv_role_order, cv_selection_ai
from app.services import dz_review as dz
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import _json_object
from app.services.cv_rodo_clause import is_rodo_text
from app.services.recommendation_card_parser import CV_HIDDEN_FIELDS
from app.services.dz_review import Requirement
from app.services.llm_prompts import CV_EDITOR_COMMAND
from app.services.llm_providers import api_key_configured
from app.services.money_text import MONEY_RE, is_rate_text
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.cv_editor_command
ACTIVITY_ACTION = "cv_command_ai"

# Rodzaje wierszy, które przysyła edytor. Klauzuli zgody edytor nie wysyła wcale.
LINE_KINDS = (
    "title",
    "heading",
    "role",
    "employer",
    "label",
    "technologies",
    "bullet",
    "text",
)
# Zwykła treść — jedyne wiersze, które operacja może ruszyć pojedynczo.
EDITABLE = frozenset({"bullet", "text"})
OPERATION_TYPES = (
    "remove",
    "replace",
    "merge",
    "reorder",
    "remove_role",
    "remove_section",
    "add",
    "bold",
    "unbold",
    "considered_for",
    "reorder_roles",
)
# Operacje, które dopisują albo zmieniają treść — sprawdzane pod kątem faktów.
TEXT_OPERATIONS = frozenset({"replace", "merge", "add"})

# Granice wejścia (schemat trasy trzyma te same liczby).
LINES_MAX = 400
LINE_TEXT_MAX = 1200
# Lista poprawek rekrutera, ok. 15–20 punktów (15.10.2026; wcześniej 300 znaków).
COMMAND_MAX = 2000
OPERATIONS_MAX = 40
WHY_MAX = 200
# Asystent (PR 4): rozmowa, zaznaczenie i nowe operacje.
HISTORY_MAX = 6
HISTORY_TEXT_MAX = 500
FOCUS_MAX = 60
TERMS_MAX = 12
TERM_MAX = 60
CONSIDERED_MAX = 120
PROBLEM_MAX = 120
# Źródła, na których wolno oprzeć nowy fakt (oryginał CV + notatki) — do kontroli,
# nie do promptu; przycięte, żeby kontrola planu była tania.
SOURCES_MAX = 60_000

# Linia „Rozważany na stanowisko:” pod nagłówkiem CV (etykiety jak w
# `docx_renderer`, PL i EN).
_CONSIDERED = re.compile(
    r"^\s*(rozważany na stanowisko|considered for)\s*:", re.IGNORECASE
)
# Kwota w zapisach, których wspólny `money_text.MONEY_RE` nie bierze: kod
# waluty przed liczbą („PLN 15000”), „20000 brutto”, „100 per hour”,
# „800 za dzień” (przegląd PR 4, 14.10.2026).
_MONEY_EXTRA = re.compile(
    r"\b(?:pln|zł|zl|eur|euro|usd|chf|gbp)\s*\d(?:[\d\s.,]*\d)?"
    r"|\d[\d\s.,]*\s*(?:chf|gbp)\b"
    r"|\d[\d\s.,]*\s*(?:brutto|netto)\b"
    r"|\d[\d\s.,]*\s*(?:per|za|na)\s+(?:hour|day|month|godzin\w*|dzie[nń]\w*|miesi\w*)",
    re.IGNORECASE,
)


def has_amount(text: str) -> bool:
    """Kwota albo stawka w tekście — wspólny wzorzec `money_text` i zapisy wyżej.

    „Rate limiting”, „50k użytkowników” i „10 tys. żądań” to fakty z CV, nie
    pieniądze.
    """
    return bool(
        MONEY_RE.search(text) or _MONEY_EXTRA.search(text) or is_rate_text(text)
    )


def _amounts(text: str) -> set[str]:
    """Kwoty w tekście bez spacji i wielkości liter — do porównania ze źródłem."""
    spans = [m.group() for m in MONEY_RE.finditer(text)]
    spans += [m.group() for m in _MONEY_EXTRA.finditer(text)]
    return {"".join(span.lower().split()) for span in spans}


# Operacje, po których wiersze znikają z CV.
_REMOVING = frozenset({"remove", "remove_role", "remove_section"})

PRESETS = {
    "shorten": (
        "Skróć CV do około dwóch stron: usuń ogólniki i powtórzenia, połącz punkty "
        "o tym samym, zostaw to, co odpowiada wymaganiom klienta."
    ),
    "drop_old_roles": (
        "Usuń najstarsze stanowiska, które nie mają związku z wymaganiami klienta "
        "(zwykle starsze niż 10 lat). Nie ruszaj pozostałych."
    ),
    "order_by_requirements": (
        "W każdym stanowisku ułóż punkty tak, żeby najpierw stały te, które "
        "odpowiadają wymaganiom klienta. Nie zmieniaj treści punktów."
    ),
    "unify_sentences": (
        "Ujednolić formę punktów w całym CV (ta sama forma gramatyczna, bez "
        "pierwszej osoby). Nie zmieniaj faktów."
    ),
    # Edytor CV 3, PR 4 — podpowiedzi pod polem asystenta.
    "more_requirements": (
        "Wyeksponuj to, co w CV odpowiada wymaganiom klienta: pogrub nazwy "
        "wymagań, które nie są jeszcze pogrubione (**x**), ustaw pasujące punkty "
        "wyżej i przeredaguj punkty tak, żeby nazwy wymagań były widoczne. Nie "
        "dopisuj faktów."
    ),
    "proofread": (
        "Popraw język i styl w całym CV: literówki, interpunkcja, pisownia nazw "
        "technologii, jednolita forma punktów bez pierwszej osoby. Nie zmieniaj "
        "faktów ani kolejności."
    ),
}

MSG_UNAVAILABLE = (
    "Asystent jest chwilowo niedostępny. Popraw CV ręcznie albo spróbuj za chwilę."
)
MSG_EMPTY = "Asystent nie znalazł zmian, które odpowiadają temu poleceniu."
MSG_ALL_DROPPED = (
    "Asystent zaproponował zmiany, ale żadna nie przeszła kontroli (dopisywały "
    "fakty albo ruszały układ szablonu). Spróbuj opisać polecenie inaczej."
)
# Odmowy kolejności stanowisk mówią, o co poszło — ogólne zdanie wyżej
# („dopisywały fakty”) było przy nich nieprawdą.
MSG_ROLES_IN_ORDER = "Stanowiska już są ułożone w tej kolejności — nic nie zmieniłem."
MSG_NO_DATES = (
    "Nie widzę dat przy stanowiskach (np. 03.2020 – obecnie), więc nie ułożę ich "
    "po kolei. Przestaw je ręcznie: kursor w stanowisku, „Więcej” → wyżej / niżej."
)
MSG_ALREADY_BOLD = "Te słowa już są pogrubione — nic nie zmieniłem."
MSG_NOT_BOLD = "Te słowa nie są pogrubione — nic nie zmieniłem."
MSG_NO_ROLES = (
    "Nie rozpoznaję stanowisk w tym CV, więc nie mogę ich przestawić. Przestaw "
    "je ręcznie: kursor w stanowisku, „Więcej” → wyżej / niżej."
)
_DROPPED_MESSAGES = {
    "roles_in_order": MSG_ROLES_IN_ORDER,
    "no_dates": MSG_NO_DATES,
    "no_roles": MSG_NO_ROLES,
}


def dropped_message(dropped: list[dict]) -> str:
    """Zdanie dla planu, z którego nic nie przeszło — konkretne, gdy się da."""
    # Same pogrubienia bez zmiany: to nie odmowa kontroli, tylko nic do zrobienia.
    reasons = {item.get("reason") for item in dropped}
    if reasons == {"already_bold"}:
        return MSG_ALREADY_BOLD
    if reasons == {"not_bold"}:
        return MSG_NOT_BOLD
    for item in dropped:
        message = _DROPPED_MESSAGES.get(item.get("reason") or "")
        if message:
            return message
    return MSG_ALL_DROPPED


@dataclass(frozen=True)
class Line:
    """Wiersz CV tak, jak widzi go rekruter: blok dokumentu albo punkt listy."""

    id: int
    kind: str
    text: str
    # Sekcja (klucz szablonu) i numer stanowiska w CV — albo ``None``.
    section: Optional[str] = None
    role: Optional[int] = None


# ── Nowe słowa w przeredagowanym tekście ─────────────────────────────────────
#
# Kontrola faktów (`cv_selection_ai.check`) łapie liczby, daty, nazwy własne,
# tokeny z cyfrą i wymagania rekrutacji. Twierdzenie pisane małą literą
# („prowadził zespół”, „magister informatyki”, „kubernetes”) przechodzi. Przy
# jednej propozycji na zaznaczeniu rekruter czyta „było / będzie”; plan niesie
# do 40 operacji naraz, więc każda przeredagowana operacja dostaje listę słów,
# których nie było w zastępowanych wierszach. Edytor takiej operacji nie
# zaznacza i pokazuje te słowa (przegląd bezpieczeństwa 13.10.2026). Od
# 14.10.2026 `new_words` mieszka w `cv_selection_ai` — liczy też plakietkę
# „Zgodne ze źródłem” rozwinięcia.
new_words = cv_selection_ai.new_words


def _visible(text: str) -> str:
    """Tekst bez znaków sterujących i niewidocznych (zostają odstępy)."""
    return "".join(
        ch for ch in text if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )


class _Dropped(Exception):
    """Operacja nie przeszła kontroli (powód i ewentualny zapis, o który poszło)."""

    def __init__(self, reason: str, problem: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problem = problem


@dataclass(frozen=True)
class _Change:
    """Co operacja robi z wierszami — wynik kontroli jednej operacji."""

    ids: list[int]
    text: Optional[str] = None
    # `"source"` — fakt spoza CV i źródeł (rekruter potwierdza), `"loses"` —
    # znika jedyne miejsce z wymaganiem klienta.
    ask: Optional[str] = None
    problem: Optional[str] = None
    terms: tuple[str, ...] = field(default_factory=tuple)


def _ids(value: Any, known: dict[int, Line]) -> list[int]:
    """Lista różnych, znanych numerów wierszy — albo odmowa."""
    if not isinstance(value, list) or not value:
        raise _Dropped("bad_lines")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item not in known:
            raise _Dropped("bad_lines")
        if item in out:
            raise _Dropped("bad_lines")
        out.append(item)
    return out


class _Plan:
    """Kontrola planu na jednym zrzucie wierszy CV."""

    def __init__(
        self,
        lines: list[Line],
        requirements: tuple[Requirement, ...],
        sources: str = "",
    ):
        self.lines = {item.id: item for item in lines}
        self.requirements = requirements
        # Oryginalne CV i notatki pary (bez ustaleń handlowych): fakt, który tam
        # stoi, nie wymaga pytania rekrutera.
        self.sources = sources[:SOURCES_MAX]
        self.grounds = cv_selection_ai.Grounds(requirements=requirements)
        # Miejsce zwykłej treści: stanowisko albo sekcja (nagłówek, pod którym stoi).
        self.place: dict[int, tuple[str, int]] = {}
        self.members: dict[tuple[str, int], list[int]] = {}
        self.role_lines: dict[int, list[int]] = {}
        self.section_lines: dict[int, list[int]] = {}
        heading: Optional[int] = None
        for item in lines:
            if item.kind in ("title", "heading"):
                heading = item.id if item.kind == "heading" else None
            if heading is not None:
                self.section_lines.setdefault(heading, []).append(item.id)
            if item.role is not None:
                self.role_lines.setdefault(item.role, []).append(item.id)
            # Pusty punkt albo akapit zostawiony w edytorze nie jest treścią: nie
            # „trzyma” roli ani sekcji przy życiu i nie da się go ruszyć operacją.
            # Wiersz sekcji doświadczenia bez numeru stanowiska to CV bez
            # znaczników (starsze albo wklejone): stanowisko, firma i etykieta
            # wyglądają tam jak zwykły tekst, więc tej sekcji nie ruszamy wcale.
            # Klauzula zgody jest stała, nawet gdyby edytor ją przysłał.
            unmarked = item.section == "experience" and item.role is None
            if (
                item.kind in EDITABLE
                and item.text.strip()
                and not unmarked
                and not is_rodo_text(cv_selection_ai.plain(item.text))
            ):
                place = (
                    ("role", item.role)
                    if item.role is not None
                    else ("section", heading if heading is not None else -1)
                )
                self.place[item.id] = place
                self.members.setdefault(place, []).append(item.id)
        # Gdzie stoi każde wymaganie — raz, zamiast szukać przy każdej operacji.
        # Zbiór maleje z kolejnymi przyjętymi operacjami (`_loses`). Bez `**`:
        # „Spring **Boot**” to nadal „Spring Boot”.
        self.alive: list[tuple[Requirement, set[int]]] = []
        for requirement in requirements:
            where = {
                item.id
                for item in lines
                if dz._found(cv_selection_ai.plain(item.text), requirement)
            }
            if where:
                self.alive.append((requirement, where))
        self.used: set[int] = set()
        self.removed: set[int] = set()
        self.removed_roles: set[int] = set()
        self.removed_sections: set[int] = set()
        # Wiersze, za którymi stoi dopisany punkt, i miejsca z nową kolejnością.
        self.anchors: set[int] = set()
        self.reordered: set[tuple[str, int]] = set()

    # ── pojedyncze operacje ──

    def _editable(self, ids: list[int]) -> None:
        if any(i not in self.place for i in ids):
            raise _Dropped("not_editable")

    def _new_text(
        self, source: str, text: Any
    ) -> tuple[str, Optional[str], Optional[str]]:
        """Nowa treść po kontroli: (tekst, pytanie, o co pytamy).

        Fakt spoza zastępowanych wierszy, którego nie ma też w źródłach, nie
        odrzuca operacji — wraca z ``ask="source"``, a edytor pyta rekrutera.
        Pozostałe powody (pusto, za długo, bez zmian, kwota) odrzucają.
        """
        if text is not None and not isinstance(text, str):
            raise _Dropped("empty")
        # Akapit zaczynający się jak klauzula zgody edytor uznałby za klauzulę
        # i usunął przy zapisie — razem z treścią, którą miał zastąpić.
        if text and is_rodo_text(cv_selection_ai.plain(text)):
            raise _Dropped("not_editable")
        # Stawka nie trafia do CV dla klienta nigdy, nawet za zgodą. Inna kwota
        # (budżet projektu) tylko ta, która stała już w zastępowanym tekście —
        # liczba gdzie indziej w stanowisku niczego nie odblokowuje.
        if text:
            new = cv_selection_ai.plain(text)
            if is_rate_text(new) or not _amounts(new) <= _amounts(
                cv_selection_ai.plain(source)
            ):
                raise _Dropped("amount")
        raw = json.dumps({"text": text or ""}, ensure_ascii=False)
        checked = cv_selection_ai.check("rephrase", source, raw, self.grounds)
        if checked["status"] == "ok":
            return checked["proposed_text"], None, None
        if checked["reason"] != "new_fact":
            raise _Dropped(checked["reason"] or "new_fact", checked.get("problem"))
        problem = checked.get("problem")
        if self.sources:
            # Fakt może stać w oryginale CV albo w notatkach — wtedy bez pytania.
            again = cv_selection_ai.check(
                "rephrase", f"{source}\n{self.sources}", raw, self.grounds
            )
            if again["status"] == "ok":
                return again["proposed_text"], None, None
            if again["reason"] != "new_fact":
                raise _Dropped(again["reason"] or "new_fact", again.get("problem"))
            problem = again.get("problem") or problem
        proposed = cv_selection_ai.clean_markup(text)
        if not proposed.strip():
            raise _Dropped("empty")
        return proposed, "source", (str(problem or "")[:PROBLEM_MAX] or None)

    def remove(self, op: dict) -> _Change:
        ids = _ids(op.get("lines"), self.lines)
        self._editable(ids)
        gone = self.removed | set(ids)
        for place in {self.place[i] for i in ids}:
            if all(member in gone for member in self.members[place]):
                kind = "role" if place[0] == "role" else "section"
                raise _Dropped(f"would_empty_{kind}")
        return _Change(ids)

    def replace(self, op: dict) -> _Change:
        ids = _ids([op.get("line")], self.lines)
        self._editable(ids)
        text, ask, problem = self._new_text(self.lines[ids[0]].text, op.get("text"))
        return _Change(ids, text, ask, problem)

    def merge(self, op: dict) -> _Change:
        ids = _ids(op.get("lines"), self.lines)
        if len(ids) < 2:
            raise _Dropped("bad_lines")
        self._editable(ids)
        first = self.lines[ids[0]]
        if any(
            self.place[i] != self.place[first.id] or self.lines[i].kind != first.kind
            for i in ids
        ):
            raise _Dropped("mixed_places")
        source = " ".join(self.lines[i].text for i in ids)
        text, ask, problem = self._new_text(source, op.get("text"))
        return _Change(ids, text, ask, problem)

    def reorder(self, op: dict) -> _Change:
        ids = _ids(op.get("lines"), self.lines)
        if any(self.lines[i].kind != "bullet" or i not in self.place for i in ids):
            raise _Dropped("bad_order")
        current = [
            i
            for i in self.members[self.place[ids[0]]]
            if self.lines[i].kind == "bullet"
        ]
        if sorted(ids) != sorted(current):
            raise _Dropped("bad_order")
        if ids == current:
            raise _Dropped("unchanged")
        return _Change(ids)

    def remove_role(self, op: dict) -> _Change:
        role = op.get("role")
        if isinstance(role, bool) or not isinstance(role, int):
            raise _Dropped("unknown_role")
        if role not in self.role_lines:
            raise _Dropped("unknown_role")
        if len(self.removed_roles | {role}) >= len(self.role_lines):
            raise _Dropped("last_role")
        return _Change(list(self.role_lines[role]))

    def remove_section(self, op: dict) -> _Change:
        target = op.get("line")
        # `True` to w Pythonie liczba 1 — a wiersz 1 bywa nagłówkiem sekcji.
        numbered = isinstance(target, int) and not isinstance(target, bool)
        line = self.lines.get(target) if numbered else None
        if line is None or line.kind != "heading":
            raise _Dropped("not_a_section")
        if line.section == "experience" or any(
            self.lines[i].role is not None for i in self.section_lines[line.id]
        ):
            raise _Dropped("protected_section")
        # CV bez stanowisk: przynajmniej jedna sekcja zostaje.
        if len(self.removed_sections | {line.id}) >= len(self.section_lines):
            raise _Dropped("last_section")
        return _Change(list(self.section_lines[line.id]))

    # ── asystent (PR 4) ──

    def add(self, op: dict) -> _Change:
        """Nowy punkt (albo akapit) zaraz za wskazanym wierszem tego samego miejsca."""
        ids = _ids([op.get("after")], self.lines)
        self._editable(ids)
        if ids[0] in self.removed:
            raise _Dropped("overlap")
        # Kontrola faktów na treści całego stanowiska albo sekcji, do której
        # dopisujemy — tam stoi to, co o tym miejscu wiadomo.
        basis = " ".join(self.lines[i].text for i in self.members[self.place[ids[0]]])
        text, ask, problem = self._new_text(basis, op.get("text"))
        return _Change(ids, text, ask, problem)

    def _terms(self, op: dict, *, bold: bool) -> tuple[str, ...]:
        """Terminy do (od)pogrubienia — tylko te, które naprawdę stoją w CV
        i których pogrubienie coś zmieni.

        Termin pogrubiony w każdym miejscu CV wypada z ``bold`` (a niepogrubiony
        nigdzie — z ``unbold``). Zgłoszenie 23.10.2026: „Więcej o wymaganiach
        klienta” na CV z generatora (wymagania już pogrubione) dawało plan bez
        żadnej zmiany, a edytor mówił wtedy „CV zmieniło się w międzyczasie”.
        """
        raw = op.get("terms")
        if not isinstance(raw, list) or not raw:
            raise _Dropped("unknown_term")
        texts = [
            item.text
            for item in self.lines.values()
            if item.kind not in ("title", "heading")
            and not is_rodo_text(cv_selection_ai.plain(item.text))
        ]
        content = [cv_selection_ai.plain(text).casefold() for text in texts]
        # Tekst poza pogrubieniem i w pogrubieniu; odcinki rozdziela nowa linia,
        # żeby „**Java** i **Spring**” nie dało terminu „Java Spring”.
        outside = [re.sub(r"\*\*.*?\*\*", "\n", text).casefold() for text in texts]
        inside = [
            "\n".join(re.findall(r"\*\*(.*?)\*\*", text)).casefold() for text in texts
        ]
        found: list[str] = []
        unchanged = False
        for value in raw[:TERMS_MAX]:
            if not isinstance(value, str):
                continue
            term = " ".join(cv_selection_ai.plain(value).split())
            if not 2 <= len(term) <= TERM_MAX:
                continue
            folded = term.casefold()
            if folded in {t.casefold() for t in found}:
                continue
            if not any(folded in text for text in content):
                continue
            if not any(folded in text for text in (outside if bold else inside)):
                unchanged = True
                continue
            found.append(term)
        if not found:
            raise _Dropped(
                ("already_bold" if bold else "not_bold")
                if unchanged
                else "unknown_term"
            )
        return tuple(found)

    def bold(self, op: dict) -> _Change:
        return _Change([], terms=self._terms(op, bold=True))

    def unbold(self, op: dict) -> _Change:
        return _Change([], terms=self._terms(op, bold=False))

    def considered_for(self, op: dict) -> _Change:
        """Cel rekrutacji w linii „Rozważany na stanowisko:” — bez kontroli faktów.

        To, na jakie stanowisko rekruter przedstawia kandydata, jest decyzją
        rekrutera, nie faktem z życiorysu. Etykieta (z pogrubieniem) zostaje
        z bieżącego wiersza, zmienia się tylko wartość.
        """
        target = next(
            (
                item
                for item in self.lines.values()
                if item.kind == "text"
                and _CONSIDERED.match(cv_selection_ai.plain(item.text))
            ),
            None,
        )
        if target is None:
            raise _Dropped("no_considered_line")
        value = op.get("text")
        if not isinstance(value, str):
            raise _Dropped("empty")
        value = " ".join(
            cv_selection_ai.plain(cv_selection_ai.clean_markup(value)).split()
        )
        # Model bywa, że powtórzy etykietę — zostaje sama wartość.
        value = _CONSIDERED.sub("", value).strip()
        if not value:
            raise _Dropped("empty")
        if len(value) > CONSIDERED_MAX:
            raise _Dropped("too_long")
        if has_amount(value):
            raise _Dropped("amount")
        if is_rodo_text(value):
            raise _Dropped("not_editable")
        label_end = target.text.find(":") + 1
        label = target.text[:label_end]
        # `**Rozważany na stanowisko:**` — dwukropek bywa w środku pogrubienia.
        if target.text[label_end : label_end + 2] == "**":
            label = target.text[: label_end + 2]
        if " ".join(value.split()) == " ".join(
            cv_selection_ai.plain(target.text[len(label) :]).split()
        ):
            raise _Dropped("unchanged")
        return _Change([target.id], f"{label} {value}")

    def reorder_roles(self, op: dict) -> _Change:
        """Całe stanowiska w nowej kolejności; wiersze operacji = linie stanowisk po kolei.

        ``by`` (``newest_first`` / ``oldest_first``) — kolejność liczy kod z dat
        w linii stanowiska (bez pogrubionej nazwy roli); ``roles`` — kolejność
        podana wprost, każde stanowisko dokładnie raz.
        """
        heads = {
            role: next((i for i in ids if self.lines[i].kind == "role"), None)
            for role, ids in self.role_lines.items()
        }
        roles = sorted(role for role, head in heads.items() if head is not None)
        if len(roles) < 2 or len(roles) != len(heads):
            raise _Dropped("no_roles")
        if len({self.lines[heads[role]].section for role in roles}) != 1:
            raise _Dropped("mixed_places")
        by = op.get("by")
        if by in ("newest_first", "oldest_first"):
            texts = [_role_dates(self.lines[heads[role]].text) for role in roles]
            order = cv_role_order.newest_first(texts, newest=by == "newest_first")
            if order is None:
                raise _Dropped("no_dates")
            wanted = [roles[index] for index in order]
        else:
            raw = op.get("roles")
            if (
                not isinstance(raw, list)
                or any(isinstance(r, bool) or not isinstance(r, int) for r in raw)
                or sorted(raw) != roles
            ):
                raise _Dropped("bad_order")
            wanted = list(raw)
        if wanted == roles:
            raise _Dropped("roles_in_order")
        return _Change([heads[role] for role in wanted])

    # ── plan ──

    def _loses(self, kind: str, ids: list[int], text: Optional[str]) -> list[str]:
        """Wymagania rekrutacji, które po tej operacji znikają z CV.

        Liczone narastająco, w kolejności planu: wymaganie stojące w dwóch
        miejscach, usuwane dwiema operacjami, gubi ta, która zabiera ostatnie
        miejsce. Liczone osobno dla każdej operacji żadna by go nie „gubiła”,
        a obie przychodziłyby zaznaczone. Odznaczenie wcześniejszej operacji
        zostawia ostrzeżenie przy późniejszej — na wyrost, czyli bezpiecznie.
        """
        if kind in (
            "reorder",
            "reorder_roles",
            "add",
            "bold",
            "unbold",
            "considered_for",
        ):
            return []
        touched = set(ids)
        new = cv_selection_ai.plain(text or "")
        lost: list[str] = []
        for requirement, where in self.alive:
            if not where & touched:
                continue
            where -= touched
            if new and dz._found(new, requirement):
                # Nowa treść trafia do pierwszego wiersza operacji.
                where.add(ids[0])
            elif not where:
                lost.append(requirement.label)
        return lost

    def accept(self, raw: Any) -> dict:
        if not isinstance(raw, dict) or raw.get("type") not in OPERATION_TYPES:
            raise _Dropped("unknown_type")
        kind = raw["type"]
        change: _Change = getattr(self, kind)(raw)
        ids, text = change.ids, change.text
        if kind == "add":
            # Dopisany punkt nie zmienia wiersza, za którym staje: ten wiersz może
            # dostać drugi punkt albo nową treść. Nie może za to zniknąć ani
            # zmienić miejsca w liście — edytor nie miałby gdzie wstawić punktu.
            if self.place[ids[0]] in self.reordered:
                raise _Dropped("overlap")
            self.anchors.add(ids[0])
        else:
            gone = ids[1:] if kind == "merge" else ids if kind in _REMOVING else []
            if self.used.intersection(ids) or self.anchors.intersection(gone):
                raise _Dropped("overlap")
            if kind == "reorder":
                place = self.place[ids[0]]
                if any(self.place[anchor] == place for anchor in self.anchors):
                    raise _Dropped("overlap")
                self.reordered.add(place)
            self.used.update(ids)
        if kind in ("remove", "remove_section"):
            self.removed.update(ids)
            if kind == "remove_section":
                self.removed_sections.add(ids[0])
        elif kind == "merge":
            self.removed.update(ids[1:])
        elif kind == "remove_role":
            self.removed.update(ids)
            self.removed_roles.add(raw["role"])
        why = cv_selection_ai.plain(cv_selection_ai.clean_markup(raw.get("why")))
        # Dopisany punkt nie zastępuje wiersza, za którym staje.
        replaced = "" if kind == "add" else " ".join(self.lines[i].text for i in ids)
        loses = self._loses(kind, ids, text)
        ask = change.ask or ("loses" if loses else None)
        return {
            "type": kind,
            "lines": ids,
            "text": text,
            "why": " ".join(why.split())[:WHY_MAX],
            # Słowa nowej treści, których nie było w zastępowanych wierszach.
            "new_words": (
                new_words(text, replaced) if text and kind in TEXT_OPERATIONS else []
            ),
            "loses": loses,
            "ask": ask,
            "problem": change.problem,
            "terms": list(change.terms),
        }


def _role_dates(text: str) -> str:
    """Linia stanowiska bez pogrubionej nazwy roli — tam stoją daty.

    Linia z edytora to „**Senior Java Developer** 03.2020 – obecnie”. Rok w nazwie
    roli („Windows Server 2019”) nie jest datą stanowiska. Linia bez pogrubienia
    (wpisana ręcznie, z Worda) idzie cała — `cv_role_order` bierze dwie ostatnie daty.
    """
    rest = re.sub(r"\*\*.*?\*\*", " ", text)
    return cv_role_order.dates_text(rest, cv_selection_ai.plain(text))


def verify_plan(
    raw: str,
    lines: list[Line],
    requirements: tuple[Requirement, ...],
    sources: str = "",
) -> dict:
    """Odpowiedź modelu → operacje, które przeszły kontrolę, i odrzucone z powodem.

    ``raw`` to JSON ``{"operations": [...]}``. ``ValueError`` znaczy „model nie
    odpowiedział w umówionym kształcie” — wołający zgłasza to jako chwilową
    niedostępność. Pusta albo zła lista operacji to pusty plan.
    """
    data = _json_object(raw)
    proposed = data.get("operations")
    plan = _Plan(lines, tuple(requirements), sources)
    operations: list[dict] = []
    dropped: list[dict] = []
    proposed = proposed if isinstance(proposed, list) else []
    for item in proposed[:OPERATIONS_MAX]:
        try:
            accepted = plan.accept(item)
        except _Dropped as refusal:
            kind = item.get("type") if isinstance(item, dict) else None
            dropped.append(
                {
                    "type": kind if kind in OPERATION_TYPES else None,
                    "reason": refusal.reason,
                    "problem": refusal.problem,
                }
            )
            continue
        operations.append({"id": len(operations), **accepted})
    # Nadmiar ponad OPERATIONS_MAX nie przepada po cichu: asystent mówi,
    # że zrobił tylko część listy (15.10.2026).
    return {
        "operations": operations,
        "dropped": dropped,
        "truncated": len(proposed) > OPERATIONS_MAX,
    }


# ── Wywołanie modelu ─────────────────────────────────────────────────────────


def _unavailable(message: str = MSG_UNAVAILABLE, status: str = "unavailable") -> dict:
    return {"status": status, "operations": [], "dropped": [], "message": message}


def command_text(payload: dict) -> str:
    """Treść polecenia: gotowe (z kodu) albo własne słowa rekrutera."""
    preset = payload.get("preset")
    if preset in PRESETS:
        return PRESETS[preset]
    return str(payload.get("command") or "").strip()[:COMMAND_MAX]


def _history(payload: dict) -> list[dict]:
    """Ostatnie wiadomości rozmowy z edytora — dane, nie polecenia."""
    out: list[dict] = []
    for item in (payload.get("history") or [])[-HISTORY_MAX:]:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        text = _visible(str(item.get("text") or "")).strip()[:HISTORY_TEXT_MAX]
        if text:
            out.append(
                {
                    "kto": "rekruter" if item["role"] == "user" else "asystent",
                    "tekst": text,
                }
            )
    return out


def _focus(payload: dict, lines: list[Line]) -> list[int]:
    known = {item.id for item in lines}
    out: list[int] = []
    for value in (payload.get("focus") or [])[:FOCUS_MAX]:
        if isinstance(value, int) and not isinstance(value, bool) and value in known:
            if value not in out:
                out.append(value)
    return out


def build_prompt(payload: dict, lines: list[Line], requirements: tuple) -> str:
    """Prompt z danymi w znacznikach, których nie da się zamknąć od środka."""
    rows = [
        {
            "id": item.id,
            "rodzaj": item.kind,
            **({"stanowisko": item.role} if item.role is not None else {}),
            # Znaki niewidoczne z CV kandydata nie idą do modelu.
            "tekst": _visible(item.text)[:LINE_TEXT_MAX],
        }
        for item in lines
    ]
    own = payload.get("preset") not in PRESETS
    command = command_text(payload)
    focus = _focus(payload, lines)
    return CV_EDITOR_COMMAND.render(
        # Gotowe polecenie pochodzi z kodu; własne słowa rekrutera to dane.
        command=fence("recruiter_command", command) if own else command,
        history=fence("conversation", json_for_prompt(_history(payload))),
        focus=fence("selected_lines", json_for_prompt(focus)),
        requirements=fence(
            "cv_requirements",
            json_for_prompt([r.label for r in requirements][:60]),
        ),
        lines=fence("cv_lines", json_for_prompt(rows)),
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=chain[0],
        fallback_models=chain[1:] or None,
        # Do 40 operacji z nowym tekstem i powodem.
        max_tokens=6000,
        thinking={"type": "disabled"},
        # Rekruter czeka z otwartym edytorem; plan dla całego CV trwa dłużej
        # niż propozycja dla jednego zdania.
        timeout=45,
        max_retries=1,
        total_timeout=60,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


async def _log(
    db: AsyncSession, stage: CandidateStage, user_id: int, payload: dict, result: dict
) -> None:
    """Ślad użycia (bez treści CV i bez polecenia). Błąd zapisu nie zabiera planu."""
    try:
        async with db.begin_nested():
            csv_id = await db.scalar(
                select(CandidateStageCV.id).where(
                    CandidateStageCV.candidate_stage_id == stage.id
                )
            )
            if csv_id is None:
                return
            preset = payload.get("preset")
            kinds: dict[str, int] = {}
            for operation in result["operations"]:
                kinds[operation["type"]] = kinds.get(operation["type"], 0) + 1
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv_id,
                    action=ACTIVITY_ACTION,
                    user_id=user_id,
                    # Rodzaj prośby i liczby — bez treści CV i bez słów rekrutera.
                    details={
                        "preset": preset if preset in PRESETS else None,
                        "status": result["status"],
                        "operations": len(result["operations"]),
                        "dropped": len(result["dropped"]),
                        "kinds": kinds,
                        "asks": sum(1 for op in result["operations"] if op.get("ask")),
                        "history": len(_history(payload)),
                        "focus": bool(payload.get("focus")),
                    },
                )
            )
    except Exception:  # noqa: BLE001 — pomiar, nie warunek działania
        logger.warning(
            "[cv_command_ai] nie zapisano wpisu użycia stage=%s",
            stage.id,
            exc_info=True,
        )


async def _sources(db: AsyncSession, stage: CandidateStage) -> str:
    """Oryginalne CV i notatki pary (bez ustaleń handlowych) — do kontroli faktów.

    Nie idą do modelu: fakt, który tam stoi, nie wymaga pytania rekrutera.
    Awaria odczytu = puste źródła, czyli każdy nowy fakt wraca z pytaniem.
    """
    try:
        async with db.begin_nested():
            src = await cv_qc._load_sources(db, stage)
            original = src.original.get("text") or ""
            notes = await cv_qc._notes_text(db, src.candidate.id, CV_HIDDEN_FIELDS)
    except Exception:  # noqa: BLE001 — źródła to podpowiedź, nie warunek
        logger.warning(
            "[cv_command_ai] stage=%s: źródła niedostępne", stage.id, exc_info=True
        )
        return ""
    return f"{original}\n{notes}".strip()


async def propose_plan(
    db: AsyncSession, stage: CandidateStage, *, user_id: int, payload: dict
) -> dict:
    """Plan zmian dla całego CV. Wołający sprawdził dostęp i schemat.

    Nigdy nie rzuca: brak klucza, błąd modelu albo zła odpowiedź to
    ``status: "unavailable"`` — edytor działa dalej bez asystenta.
    """
    if not settings.CV_EDITOR_COMMAND_ENABLED:
        return _unavailable()
    lines = [
        Line(
            id=int(item["id"]),
            kind=str(item["kind"]),
            text=str(item.get("text") or ""),
            section=item.get("section"),
            role=item.get("role"),
        )
        for item in payload.get("lines") or []
    ]
    if not command_text(payload) or not lines:
        return _unavailable(MSG_EMPTY, "empty")
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return _unavailable()
    try:
        job = await db.get(Job, stage.job_id)
        must, nice = dz.job_requirements(job) if job is not None else ([], [])
        requirements = (*must, *nice)
        sources = await _sources(db, stage)
        prompt = build_prompt(payload, lines, requirements)
        system = CV_EDITOR_COMMAND.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem,
            # żeby żądanie nie trzymało połączenia przez cały round-trip.
            await db.commit()
            raw = await run_in_threadpool(_call_model, system, prompt, chain)
        checked = await run_in_threadpool(
            verify_plan, raw, lines, requirements, sources
        )
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "[cv_command_ai] stage=%s failed (%s)", stage.id, type(exc).__name__
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[cv_command_ai] rollback failed")
        return _unavailable()
    if checked["operations"]:
        result = {"status": "ok", "message": None, **checked}
    else:
        message = (
            dropped_message(checked["dropped"]) if checked["dropped"] else MSG_EMPTY
        )
        result = {"status": "empty", "message": message, **checked}
    await _log(db, stage, user_id, payload, result)
    return result


# ── „Tak, dopisz” — fakt z rozmowy z kandydatem (PR 4) ──────────────────────

CONFIRM_TERM_MAX = 120
CONFIRM_TEXT_MAX = 600
CONFIRM_ACTION = "cv_assistant_fact_confirmed"


class ConfirmRefused(ValueError):
    """Potwierdzenia nie zapisujemy (pusto albo kwota) — trasa odpowiada 422."""


async def confirm_fact(
    db: AsyncSession,
    stage: CandidateStage,
    *,
    user_id: int,
    term: str,
    text: str,
) -> None:
    """Fakt, który rekruter potwierdził w asystencie, jako notatka pary.

    Ten sam kształt co „Potwierdzone z kandydatem” z QC (`cv_qc.confirm_with_candidate`):
    notatka z autorem i datą, widoczna w profilu i czytana przez QC jako
    źródło — dzięki temu QC nie zgłasza dopisanego faktu jako „bez źródła”.
    Kwot nie zapisujemy: CV dla klienta ich nie niesie.
    """
    from app.models.note import Note, NoteType  # noqa: PLC0415
    from app.services import note_kinds  # noqa: PLC0415

    literal = " ".join(cv_selection_ai.plain(term or "").split())[:CONFIRM_TERM_MAX]
    said = " ".join(
        cv_selection_ai.plain(cv_selection_ai.clean_markup(text or "")).split()
    )[:CONFIRM_TEXT_MAX]
    if not literal:
        raise ConfirmRefused("empty")
    if has_amount(literal) or has_amount(said):
        raise ConfirmRefused("amount")
    db.add(
        Note(
            content=f"Potwierdzone z kandydatem: {literal}"
            + (f" — {said}" if said else ""),
            note_type=NoteType.general,
            candidate_id=stage.candidate_id,
            job_id=stage.job_id,
            author_id=user_id,
            external_source=note_kinds.QC_CONFIRM_SOURCE,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action=CONFIRM_ACTION,
            user_id=user_id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "term": literal,
            },
        )
    )
    await db.flush()
