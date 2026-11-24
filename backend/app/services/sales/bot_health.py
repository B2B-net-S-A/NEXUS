"""Evidence from the latest bot attempt, independent of configuration and cadence.

A bot invoked on demand can be idle indefinitely. We therefore describe the
latest attempt and its timestamp rather than declaring it healthy for N days.
Only counters recorded by ingestion count as evidence of a business write.
"""

from __future__ import annotations

from typing import Any, Literal

Outcome = Literal[
    "waiting", "failed", "expired", "saved", "partial", "no_changes", "received"
]

COGNISM_ISSUES = {
    "session_expired": "Sesja Cognism wygasła.",
    "login_failed": "Logowanie do Cognism nie powiodło się.",
    "mfa_required": "Cognism wymaga dodatkowego uwierzytelnienia.",
    "captcha_required": "Cognism wymaga rozwiązania CAPTCHA.",
    "payment_required": "Cognism wymaga opłaty.",
    "panel_unavailable": "Panel Cognism był niedostępny.",
    "time_limit": "Bot zgłosił koniec czasu na sprawdzenie firm.",
    "employer_mismatch": "Dane pracodawcy nie zgadzały się z kartą firmy w NEXUS.",
    "duplicate_result": "Raport zawierał powtórzony wynik firmy.",
}


def _count(report: dict[str, Any], key: str) -> int:
    value = report.get(key)
    return (
        max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0
    )


def _omitted(report: dict[str, Any], *keys: str) -> int:
    dropped = report.get("dropped")
    if not isinstance(dropped, dict):
        return 0
    return sum(
        len(dropped[key])
        if isinstance(dropped.get(key), list)
        else _count(dropped, key)
        for key in keys
    )


def received_outcome(
    kind: str, source: str | None, report: dict[str, Any]
) -> tuple[Outcome, str]:
    """A valid callback can store nothing or leave work awaiting human review.

    Expected exclusions (known contacts, clients, manual fields, duplicate news)
    are not themselves failures. Missing/invalid/ambiguous data is called out.
    Old reports without the relevant counters remain neutral, never green.
    """

    written = incomplete = 0
    if kind in ("signals", "briefing", "winback") and "leads" in report:
        written = sum(_count(report, key) for key in ("leads", "briefings", "hooks"))
        # ``hooks_dropped`` to od 24.11.2026 lista z powodami; starsze raporty: liczba.
        dropped_hooks = report.get("hooks_dropped")
        incomplete = _omitted(report, "unknown_company", "outside_window") + (
            len(dropped_hooks)
            if isinstance(dropped_hooks, list)
            else _count(report, "hooks_dropped")
        )
        incomplete += max(
            0, _count(report, "sent_firms") - _count(report, "checked_firms")
        )
        if "hook_missing" in report:
            incomplete += _count(report, "hook_missing")
        elif isinstance(report.get("researched_company_ids"), list):
            incomplete += max(
                0,
                _count(report, "sent_firms")
                - len(report["researched_company_ids"])
                - _count(report, "hooks"),
            )
        detail = f"Zapisano leadów: {_count(report, 'leads')}, zestawów punktów: {_count(report, 'briefings')}, haczyków: {_count(report, 'hooks')}."
        if _count(report, "briefings_no_news"):
            detail += f" Firm bez nowych informacji: {report['briefings_no_news']}."
        if _count(report, "hook_missing"):
            detail += f" Brak wyniku haczyka dla firm: {report['hook_missing']}."
    elif kind == "enrich" and "applied_fields" in report:
        written = _count(report, "applied_fields")
        incomplete = _count(report, "invalid_fields") + _count(
            report, "unknown_company"
        )
        incomplete += max(
            0, _count(report, "sent_firms") - _count(report, "checked_firms")
        )
        if isinstance(report.get("researched_company_ids"), list):
            incomplete += max(
                0,
                _count(report, "sent_firms") - len(report["researched_company_ids"]),
            )
        detail = f"Wpisano pól: {written}. Zachowano istniejących wartości: {_count(report, 'kept_fields')} (m.in. wpisy ręczne)."
    elif kind == "people" and source == "cognism" and "processed" in report:
        written = _count(report, "people") + _count(report, "contact_changes")
        incomplete = sum(
            _count(report, key)
            for key in ("not_processed", "ambiguous", "unknown_company")
        )
        detail = f"Przetworzono firm: {_count(report, 'processed')}, zapisano osób na mapie: {_count(report, 'people')}, zmian kontaktów: {_count(report, 'contact_changes')}."
        counts = (
            ("not_found", "Nie znaleziono firm"),
            ("no_people", "Firmy bez decydentów"),
            ("ambiguous", "Niejednoznaczne dopasowania"),
            ("not_processed", "Niesprawdzone firmy"),
        )
        details = [detail]
        for key, label in counts:
            if count := _count(report, key):
                details.append(f"{label} ({count}).")
        issues = report.get("firm_issues")
        if isinstance(issues, dict):
            details.extend(
                label
                for code, label in COGNISM_ISSUES.items()
                if code in issues.values()
            )
        detail = " ".join(details)
    elif kind == "people" and source != "cognism" and "added" in report:
        written = _count(report, "added") + _count(report, "contact_changes")
        incomplete = _count(report, "waiting") + _omitted(
            report, "unknown_company", "contacts"
        )
        detail = f"Dodano osób: {_count(report, 'added')}, zmian kontaktów: {_count(report, 'contact_changes')}, wyników czekających na decyzję: {_count(report, 'waiting')}."
    elif kind == "lists" and "added" in report:
        written = _count(report, "added")
        detail = f"Dodano rekordów do kampanii: {written}."
    elif kind == "question" and "results_new" in report:
        written = _count(report, "results_new")
        detail = f"Zapisano odpowiedzi: {written}."
    elif kind == "discovery" and "results_new" in report:
        written = _count(report, "results_new")
        incomplete = _omitted(report, "outside_window")
        detail = f"Zapisano nowych propozycji: {written}."
    else:
        return (
            "received",
            "Raport odebrany; brak liczb potwierdzających zapis w tym starszym raporcie.",
        )
    if incomplete:
        return "partial", f"{detail} Część danych pominięto lub wymaga sprawdzenia."
    if written:
        return "saved", detail
    return "no_changes", f"{detail} Odbiór raportu nie oznacza dodania nowych danych."
