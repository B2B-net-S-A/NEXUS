#!/usr/bin/env python3
"""Odczyt wykonań zadania scalania kart firm z Coolify: do logu idą same liczby.

Wejście (stdin): odpowiedź API Coolify z wykonaniami jednorazowego zadania.
Wyjście: zwalidowany raport z licznikami albo jedna linia ``::error::`` o treści
ustalonej tutaj. Surowa treść wykonania nie jest drukowana nigdy, bo repo i logi
Actions są publiczne, a obok raportu w wykonaniu mogą stać logi aplikacji.

Komenda zadania kończy się ``; echo <SENTINEL>``, więc Coolify nie widzi kodu
wyjścia ``scripts/sales_company_merge.py``. Filtr odtwarza go z treści i kończy
się tym samym kodem: 0 raport, 1 błąd, 2 odmowa, 3 wynik zapisu inny niż plan,
4 blokada. Kod 10 znaczy „wyniku jeszcze nie ma” i workflow czeka dalej.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, NamedTuple

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_RESULT_DIFFERS = 3
EXIT_ALREADY_RAN = 4
EXIT_PENDING = 10

MODES = {"dry-run", "apply"}
# Pola ``Report`` ze skryptu. Lista jest zamknięta: nowe pole trzeba tu dopisać
# świadomie, a zgodność pilnuje test kontraktu.
COUNTERS = {
    "seeds_pipeline",
    "seeds_names",
    "seeds_ids",
    "names_without_card",
    "similar_cards",
    "similar_name_variants",
    "to_merge",
    "names_to_join",
    "outlook_duplicates",
    "domains_to_set",
    "merged",
    "names_joined",
    "domains_set",
}
BREAKDOWNS = {
    "groups",
    "to_decide_reasons",
    "blocked_reasons",
    "to_merge_by_origin",
    "moving",
    "domains",
}
# Licznik zapisu → licznik planu. Na sucho zapis to zero, po ``apply`` równa się
# planowi (inaczej skrypt kończy się kodem 3 i raportu nie drukuje).
WRITTEN = {
    "merged": "to_merge",
    "names_joined": "names_to_join",
    "domains_set": "domains_to_set",
}
# Odmowy skryptu mają stałą treść i liczby. Filtr przepuszcza tylko te, które zna
# (ciągi cyfr zamienione na N), bo sam zestaw znaków nie odróżni komunikatu od
# nazwy firmy ani domeny.
KNOWN_REFUSALS = frozenset(
    {
        "--expect-merge N, a jest N",
        "--expect-domains N, a jest N",
        "--apply wymaga --expect-merge i --expect-domains z biegu na sucho",
        "--actor-id: potrzebne aktywne konto administratora",
        "--decide: podaj DOCELOWA:ŹRÓDŁO[,ŹRÓDŁO], każdą kartę raz",
        "--decide: karta nie istnieje albo jest w archiwum",
        "--decide: karta występuje w dwóch decyzjach",
        "--company-ids: karta nie istnieje albo jest w archiwum",
        "karta z planu zniknęła albo trafiła do archiwum",
    }
)

_KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
_LOCK_LINE = re.compile(
    r"^lock /tmp/nexus-sales-company-merge-\d+ exists — already ran$", re.M
)
_REFUSED = re.compile(r"^Odmowa, nic nie zapisano: (.*)$", re.M)
_RESULT_DIFFERS = re.compile(
    r"^Odmowa, transakcja wycofana: wynik zapisu różni się od planu$", re.M
)
_ERROR = re.compile(r"^Błąd: (.*)$", re.M)
_ERROR_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")

_CHECK_FIRST = "Przed kolejnym apply uruchom bieg na sucho i porównaj liczniki."


class ReportValidationError(ValueError):
    """Wykonanie nie zawiera raportu o oczekiwanym kształcie."""


class Outcome(NamedTuple):
    code: int
    text: str


PENDING = Outcome(EXIT_PENDING, "")


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def validate_report(report: Any, mode: str) -> dict[str, Any]:
    """Zwraca raport tylko wtedy, gdy każdy klucz i każda wartość są sprawdzone."""
    if not isinstance(report, dict) or set(report) != {"mode"} | COUNTERS | BREAKDOWNS:
        raise ReportValidationError
    if mode not in MODES or report["mode"] != mode:
        raise ReportValidationError
    if not all(_count(report[name]) for name in COUNTERS):
        raise ReportValidationError
    for name in BREAKDOWNS:
        part = report[name]
        if not isinstance(part, dict) or not all(
            isinstance(key, str) and _KEY.fullmatch(key) and _count(value)
            for key, value in part.items()
        ):
            raise ReportValidationError
    for written, planned in WRITTEN.items():
        if report[written] != (report[planned] if mode == "apply" else 0):
            raise ReportValidationError
    return report


def _last_report(text: str) -> Any:
    decoder = json.JSONDecoder()
    found = None
    for match in re.finditer(r"\{", text):
        try:
            candidate, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "mode" in candidate:
            found = candidate
    return found


def read_execution(text: str, mode: str) -> Outcome:
    """Wynik jednego wykonania, które naprawdę pracowało (bez linii blokady)."""
    if _RESULT_DIFFERS.search(text):
        return Outcome(
            EXIT_RESULT_DIFFERS,
            "::error::Kod 3: wynik zapisu różnił się od planu, transakcja wycofana, "
            "nic nie zapisano. " + _CHECK_FIRST,
        )
    refused = _REFUSED.findall(text)
    if refused:
        reason = refused[-1].strip()
        if re.sub(r"\d+", "N", reason) not in KNOWN_REFUSALS:
            reason = "treści odmowy filtr nie zna, więc jej nie drukuje"
        return Outcome(
            EXIT_REFUSED, f"::error::Kod 2: odmowa, nic nie zapisano: {reason}"
        )
    failed = _ERROR.findall(text)
    if failed:
        name = failed[-1].strip()
        if not _ERROR_TYPE.fullmatch(name):
            name = "typ poza dozwolonym kształtem"
        return Outcome(
            EXIT_ERROR,
            f"::error::Kod 1: błąd skryptu ({name}); ślad w <lock>/error.log "
            "w kontenerze. " + _CHECK_FIRST,
        )
    try:
        report = validate_report(_last_report(text), mode)
    except ReportValidationError:
        return Outcome(
            EXIT_ERROR,
            "::error::Wykonanie nie zawiera poprawnego raportu z licznikami, więc "
            "stan zapisu jest nieznany. " + _CHECK_FIRST,
        )
    return Outcome(EXIT_OK, json.dumps(report, ensure_ascii=False, indent=2))


def classify(executions: Any, mode: str, sentinel: str) -> Outcome:
    if mode not in MODES or not sentinel:
        return Outcome(
            EXIT_ERROR, "::error::Filtr raportu: nieznany tryb albo brak znacznika."
        )
    if not isinstance(executions, list):
        return PENDING
    finished = []
    for execution in executions:
        message = execution.get("message") if isinstance(execution, dict) else None
        if isinstance(message, str) and sentinel in message:
            finished.append(message.replace("\r\n", "\n").split(sentinel, 1)[0])
    worked = [text for text in finished if not _LOCK_LINE.search(text)]
    if worked:
        outcomes = {read_execution(text, mode) for text in worked}
        if len(outcomes) > 1:
            return Outcome(
                EXIT_ERROR,
                "::error::Kilka wykonań pracowało i dało różne wyniki, więc stan "
                "zapisu jest nieznany. " + _CHECK_FIRST,
            )
        return outcomes.pop()
    # Same linie blokady i żadnego wykonania w toku: katalog blokady istniał,
    # zanim to zadanie powstało, czyli ten bieg workflow już raz pracował.
    if finished and len(finished) == len(executions):
        return Outcome(
            EXIT_ALREADY_RAN,
            "::error::Kod 4: blokada. Ten bieg workflow już raz uruchomił skrypt, "
            "a „Re-run” nie powtarza pracy: wynik jest w poprzedniej próbie, "
            "kolejny bieg wymaga nowego uruchomienia workflow.",
        )
    return PENDING


def main() -> int:
    try:
        try:
            executions = json.loads(sys.stdin.read())
        except ValueError:
            executions = None
        outcome = classify(
            executions, os.environ.get("MODE", ""), os.environ.get("SENTINEL", "")
        )
    except Exception as exc:  # noqa: BLE001 — treść wykonania zostaje prywatna
        print(f"::error::Filtr raportu: {type(exc).__name__}")
        return EXIT_ERROR
    if outcome.text:
        print(outcome.text)
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
