"""Plan kont z Symfonii FK (K1): eksport „Model księgowy” (XML) → ``finance_accounts``.

Księgowa wczytuje plan kont jednym plikiem zamiast zakładać ok. 930 kont
ręcznie. Plik to ``DokumentXML`` z Symfonii („Model księgowy”); czytamy z niego
tylko elementy ``plankont`` i ``znacznik`` (znaczniki MF z JPK_KR_PD).

* **Numer konta** = ``syntet`` dopełnione zerami do trzech cyfr + kolejne
  ``wartN`` aż do pary ``typN``/``wartN`` = 0/0 (``syntet=10, wart1=3`` →
  ``010-3``). Węzeł, którego segment ``wartN`` jest zerem przy ``typN`` ≠ 0
  („Kontrahenci”, „Pracownicy”), nie jest kontem: to słownik analityki pod
  kontem z segmentów przed zerem (``200-2`` + zero → słownik kontrahentów na
  ``200-2``), więc analityki ``200-2-NNN`` nie zakładamy po jednej.
* **Typ konta**: ``typ`` 1 = bilansowe, 2 = wynikowe, 0 = pozabilansowe. Dla
  bilansowych Symfonia nie podaje strony, więc aktywne/pasywne/aktywno-pasywne
  wynika z zespołu (0, 1, 3, 6 → aktywne; 8 → pasywne; 2 → aktywno-pasywne) —
  księgowa poprawia pojedyncze konta w Planie kont.
* **Pozycja sprawozdania**: ``znacznik`` → ``KOD`` albo ``KOD_Wn/KOD_Ma``
  (``clean_report_line``); znacznik z numerem konta spoza pliku (np.
  ``200-2-x``) pomijamy.
* **Nie nadpisujemy**: konto, które już jest w planie, zostaje z nazwą,
  rodzajem i wyłączeniem, jakie ma; uzupełniamy mu tylko puste pola (konto
  nadrzędne, typ, pozycja sprawozdania, a słownik — gdy konto nie jest
  w regule dekretu i nie ma zapisów). Niczego nie kasujemy ani nie wyłączamy.
  Nowe konto pod kontem z aktywnej reguły dekretu E2 pomijamy (konto
  z analityką pod spodem przestaje być księgowalne).
* **Bezpieczeństwo pliku**: bez rozwijania encji i bez sieci; plik z DOCTYPE
  odrzucamy, a rozmiar ograniczamy (``MAX_BYTES``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from lxml import etree
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_posting import FinanceAccount
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.finance_ledger.posting import clean_account
from app.services.finance_posting_schema import ACCOUNT_NAME_MAX
from app.services.ledger import chart, engine, markers
from app.services.ledger_schema import ACCOUNT_DICTIONARIES

MAX_BYTES = 10 * 1024 * 1024
MAX_SEGMENTS = 5
PREVIEW_ROWS = 60
PROBLEMS_SHOWN = 30

ROOT_TAG = "DokumentXML"
#: Zespoły kont bilansowych → typ (Symfonia nie podaje strony konta).
BALANCE_TYPE_BY_CLASS = {
    "0": "active",
    "1": "active",
    "3": "active",
    "6": "active",
    "8": "passive",
    "2": "mixed",
}
#: ``typ`` konta w Symfonii: 1 bilansowe, 2 wynikowe, 0 pozabilansowe.
SYMFONIA_RESULT = "2"
SYMFONIA_OFF_BALANCE = "0"
#: Nazwy węzłów słownikowych Symfonii → słownik NEXUSA. Pracownicy (234)
#: nie mają osobnego słownika — idą pod kontrahentów, pozycje bez powiązania.
DICTIONARY_BY_NAME = {"kontrahenci": "counterparty", "pracownicy": "counterparty"}
_NOT_XML = "".join(chr(c) for c in range(32) if c not in (9, 10, 13))


@dataclass
class ChartAccount:
    number: str
    name: str
    account_type: Optional[str]
    dictionary: Optional[str] = None
    report_line: Optional[str] = None


@dataclass
class ParsedChart:
    accounts: dict[str, ChartAccount] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    dictionaries: int = 0
    markers_applied: int = 0
    markers_ignored: int = 0
    notes: list[str] = field(default_factory=list)


def _number(element: Any) -> tuple[Optional[str], bool]:
    """Numer konta z atrybutów ``syntet``/``typN``/``wartN``; ``True`` = węzeł słownika."""

    try:
        parts = [f"{int(element.get('syntet')):03d}"]
        dictionary = False
        for index in range(1, MAX_SEGMENTS + 1):
            kind = int(element.get(f"typ{index}") or 0)
            value = int(element.get(f"wart{index}") or 0)
            if kind == 0 and value == 0:
                break
            if value == 0:
                dictionary = True
                break
            parts.append(str(value))
    except (TypeError, ValueError):
        return None, False
    return "-".join(parts), dictionary


def _account_type(symfonia_type: str, number: str) -> Optional[str]:
    if symfonia_type == SYMFONIA_RESULT:
        return "result"
    if symfonia_type == SYMFONIA_OFF_BALANCE:
        return "off_balance"
    return BALANCE_TYPE_BY_CLASS.get(number[:1])


def _text(value: Optional[str]) -> str:
    return " ".join((value or "").translate({ord(c): " " for c in _NOT_XML}).split())


def _read(content: bytes) -> Any:
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik jest za duży (najwyżej 10 MB).")
    head = content[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ImportFileError("Plik XML z definicją DOCTYPE jest odrzucany.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise ImportFileError(
            "To nie jest poprawny plik XML z Symfonii („Model księgowy”)."
        ) from exc
    if root.tag != ROOT_TAG:
        raise ImportFileError(
            "To nie jest eksport „Model księgowy” z Symfonii FK (brak elementu "
            f"{ROOT_TAG})."
        )
    return root


def parse(content: bytes) -> ParsedChart:
    """Konta, słowniki i znaczniki z pliku — bez bazy."""

    root = _read(content)
    parsed = ParsedChart()
    dictionary_of: dict[str, str] = {}
    dropped_dictionaries: list[str] = []
    for element in root.iter("plankont"):
        number, is_dictionary = _number(element)
        label = _text(element.get("nazwa"))
        if number is None:
            parsed.problems.append("Konto bez numeru w pliku — pominięte.")
            continue
        if is_dictionary:
            parent = number
            kind = DICTIONARY_BY_NAME.get(label.lower())
            if kind is None:
                dropped_dictionaries.append(f"{number} „{label}”")
                continue
            dictionary_of[parent] = kind
            if label.lower() == "pracownicy":
                parsed.notes.append(
                    f"Konto {parent}: słownik „Pracownicy” zapisany jako słownik "
                    "kontrahentów — pozycje bez powiązania z kontrahentem."
                )
            continue
        try:
            clean = clean_account(number, f"Konto {number}")
        except LedgerError as exc:
            parsed.problems.append(exc.message)
            continue
        if not label:
            parsed.problems.append(f"Konto {clean} nie ma nazwy — pominięte.")
            continue
        if clean in parsed.accounts:
            parsed.problems.append(f"Konto {clean} występuje w pliku dwa razy.")
            continue
        parsed.accounts[clean] = ChartAccount(
            number=clean,
            name=label[:ACCOUNT_NAME_MAX],
            account_type=_account_type(element.get("typ") or "", clean),
        )
    if dropped_dictionaries:
        parsed.problems.append(
            "Słowniki analityki bez odpowiednika w NEXUSIE (pominięte): "
            + ", ".join(dropped_dictionaries[:10])
        )
    for parent, kind in dictionary_of.items():
        account = parsed.accounts.get(parent)
        if account is None or kind not in ACCOUNT_DICTIONARIES:
            parsed.problems.append(
                f"Słownik pod kontem {parent}, którego nie ma w pliku — pominięty."
            )
            continue
        account.dictionary = kind
        parsed.dictionaries += 1
    refused: list[tuple[str, str]] = []
    for element in root.iter("znacznik"):
        number = _text(element.get("konto"))
        account = parsed.accounts.get(number)
        first = _text(element.get("znacznikJpk1"))
        second = _text(element.get("znacznikJpk2"))
        if account is None or not first:
            parsed.markers_ignored += 1
            continue
        try:
            account.report_line = markers.clean_report_line(
                f"{first}/{second}" if second else first
            )
        except LedgerError as exc:
            refused.append((number, exc.message))
            continue
        parsed.markers_applied += 1
    if refused:
        shown = ", ".join(number for number, _ in refused[:8])
        more = f" i jeszcze {len(refused) - 8}" if len(refused) > 8 else ""
        parsed.problems.append(
            f"Pozycji sprawozdania nie zapisano na {len(refused)} kontach "
            f"({shown}{more}): para znaczników Wn/Ma konta wynikowego albo za "
            "długa — ustaw ją w Planie kont, gdy księgowa potwierdzi."
        )
    if not parsed.accounts:
        raise ImportFileError("W pliku nie ma żadnego konta (elementów „plankont”).")
    return parsed


def _ancestors(number: str) -> list[str]:
    parts = number.split("-")
    return ["-".join(parts[:cut]) for cut in range(len(parts) - 1, 0, -1)]


async def apply(
    db: AsyncSession, parsed: ParsedChart, *, save: bool, actor_id: int
) -> dict[str, Any]:
    """Dokłada brakujące konta; ``save=False`` tylko liczy (bez zapisu)."""

    existing = {
        row.number: row for row in (await db.scalars(select(FinanceAccount))).all()
    }
    in_rules = await chart._rule_usage(db)  # noqa: SLF001 — ten sam plan kont
    in_lines = await chart._line_usage(db, include_payroll=True)  # noqa: SLF001
    known = set(existing) | set(parsed.accounts)
    problems = list(parsed.problems)
    created: list[ChartAccount] = []
    new_rows: list[FinanceAccount] = []
    filled = 0
    blocked_total = 0
    kept_names = 0
    kept_dictionary: list[str] = []
    for number in sorted(parsed.accounts, key=lambda item: item.split("-")):
        item = parsed.accounts[number]
        parent = next((cand for cand in _ancestors(number) if cand in known), None)
        row = existing.get(number)
        if row is not None:
            changed = False
            if row.name != item.name:
                kept_names += 1
            if row.parent_number is None and parent is not None:
                row.parent_number, changed = parent, True
            if row.account_type is None and item.account_type:
                row.account_type, changed = item.account_type, True
            if row.report_line is None and item.report_line:
                row.report_line, changed = item.report_line, True
            if row.dictionary is None and item.dictionary:
                if in_rules.get(number) or in_lines.get(number):
                    kept_dictionary.append(number)
                else:
                    row.dictionary, changed = item.dictionary, True
            if changed:
                row.updated_by = actor_id
                filled += 1
            continue
        blocked = next(
            (
                cand
                for cand in _ancestors(number)
                if cand in existing and in_rules.get(cand)
            ),
            None,
        )
        if blocked is not None:
            blocked_total += 1
            problems.append(
                f"Konto {number} pominięte: konto {blocked} jest w aktywnej regule "
                "dekretu faktur i po dodaniu analityki nie dałoby się na nie księgować."
            )
            continue
        created.append(item)
        new_rows.append(
            FinanceAccount(
                number=number,
                name=item.name,
                kind="other",
                active=True,
                parent_number=parent,
                account_type=item.account_type,
                dictionary=item.dictionary,
                report_line=item.report_line,
                updated_by=actor_id,
            )
        )
    if kept_dictionary:
        problems.append(
            "Słownik analityki z Symfonii nie został ustawiony na kontach, które są "
            "w regule dekretu albo mają zapisy: "
            + ", ".join(kept_dictionary[:10])
            + " — ustaw go ręcznie w Planie kont."
        )
    notes = list(parsed.notes)
    if kept_names:
        notes.append(
            f"Nazwy {kept_names} istniejących kont różnią się od Symfonii — zostały "
            "bez zmian."
        )
    if save:
        db.add_all(new_rows)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise LedgerError(
                "Plan kont zmienił się w czasie importu — wczytaj plik ponownie.",
                status=409,
            ) from exc
    return {
        "saved": save,
        "accounts_in_file": len(parsed.accounts),
        "created": len(created),
        "existing": len(parsed.accounts) - len(created) - blocked_total,
        "blocked": blocked_total,
        "filled": filled,
        "dictionaries": parsed.dictionaries,
        "markers": parsed.markers_applied,
        "markers_ignored": parsed.markers_ignored,
        "problems": problems[:PROBLEMS_SHOWN],
        "problems_total": len(problems),
        "notes": notes,
        "preview": [
            {
                "number": item.number,
                "name": item.name,
                "account_type": item.account_type,
                "account_type_label": engine.ACCOUNT_TYPE_LABELS.get(
                    item.account_type or "", None
                ),
                "dictionary": item.dictionary,
                "report_line": item.report_line,
            }
            for item in created[:PREVIEW_ROWS]
        ],
    }
