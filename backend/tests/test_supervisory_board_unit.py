"""Rada (R1) bez bazy: parser odpisu KRS, wiersze z wzmianek, czytnik skanów, dzwonek."""

from __future__ import annotations

from datetime import date

from app.services.board import krs
from app.services.board.notify import entry_message
from app.services.board.reader import clean_fields, parse_reply


def _odpis(*, entries: int = 3, with_audit_2025: bool = False) -> dict:
    wpisy = [
        {
            "numerWpisu": n,
            "dataWpisu": f"0{n}.04.2026" if n < 10 else "22.04.2026",
            "opis": "ZMIANA DANYCH W REJESTRZE",
            "oznaczenieSaduDokonujacegoWpisu": "SYSTEM" if n % 2 else "SĄD REJONOWY",
        }
        for n in range(1, entries + 1)
    ]
    audit = [
        {"pozycja": [{"zaOkresOdDo": "OD 01.01.2024 DO 31.12.2024", "nrWpisuWprow": "2"}]}
    ]
    if with_audit_2025:
        audit.append(
            {"pozycja": [{"zaOkresOdDo": "OD 01.01.2025 DO 31.12.2025", "nrWpisuWprow": "3"}]}
        )
    return {
        "odpis": {
            "naglowekA": {"stanZDnia": "16.11.2026"},
            "naglowekP": {"wpis": wpisy, "stanZDnia": "16.11.2026"},
            "dane": {
                "dzial1": {
                    "danePodmiotu": {
                        "nazwa": [
                            {"nazwa": "STARA NAZWA S.A.", "nrWpisuWykr": "2"},
                            {"nazwa": "NOWA NAZWA SPÓŁKA AKCYJNA"},
                        ]
                    },
                    "kapital": {
                        "wysokoscKapitaluZakladowego": [
                            {"wartosc": "100000,00", "waluta": "PLN", "nrWpisuWykr": "2"},
                            {"wartosc": "1360000,00", "waluta": "PLN"},
                        ],
                        "lacznaLiczbaAkcjiUdzialow": [{"lacznaLiczbaAkcjiUdzialow": "2720000"}],
                    },
                    "umowaStatut": {
                        "informacjaOZawarciuZmianieUmowyStatutu": [
                            {
                                "pozycja": [
                                    {
                                        "zawarcieZmianaUmowyStatutu": "24.11.2025 R., REP.A NR 1/2025",
                                        "nrWpisuWprow": "3",
                                    }
                                ]
                            }
                        ]
                    },
                },
                "dzial2": {
                    "reprezentacja": [
                        {
                            "sklad": [
                                {"funkcjaWOrganie": [{"funkcjaWOrganie": "PREZES ZARZĄDU"}]},
                                {
                                    "funkcjaWOrganie": [
                                        {"funkcjaWOrganie": "CZŁONEK ZARZĄDU", "nrWpisuWykr": "3"}
                                    ],
                                    "nazwisko": [{"nazwisko": {}, "nrWpisuWykr": "3"}],
                                },
                            ]
                        }
                    ],
                    "organNadzoru": [
                        {"sklad": [{"nazwisko": [{"nazwisko": {}}]}, {"nazwisko": [{"nazwisko": {}}]}]}
                    ],
                },
                "dzial3": {
                    "wzmiankiOZlozonychDokumentach": {
                        "wzmiankaOZlozeniuRocznegoSprawozdaniaFinansowego": [
                            {
                                "pozycja": [
                                    {
                                        "dataZlozenia": "17.07.2025",
                                        "zaOkresOdDo": "OD 01.01.2024 DO 31.12.2024",
                                        "nrWpisuWprow": "1",
                                    }
                                ]
                            },
                            {
                                "pozycja": [
                                    {
                                        "dataZlozenia": "22.04.2026",
                                        "zaOkresOdDo": "OD 01.01.2025 DO 31.12.2025",
                                        "nrWpisuWprow": "3",
                                    }
                                ]
                            },
                        ],
                        "wzmiankaOZlozeniuOpiniiBieglegoRewidentaSprawozdaniaZBadania": audit,
                        "wzmiankaOZlozeniuUchwalyPostanowieniaOZatwierdzeniuRocznegoSprawozdaniaFinansowego": [
                            {"pozycja": [{"zaOkresOdDo": "OD 01.01.2025 DO 31.12.2025", "nrWpisuWprow": "3"}]}
                        ],
                    }
                },
            },
        }
    }


def test_parse_takes_active_values_and_counts_current_organs() -> None:
    summary = krs.parse_odpis(_odpis())
    assert summary.name == "NOWA NAZWA SPÓŁKA AKCYJNA"
    assert summary.capital == "1360000,00 PLN"
    assert summary.shares == "2720000"
    assert summary.management_functions == ["PREZES ZARZĄDU"]
    assert summary.supervisory_count == 2
    assert summary.last_entry is not None and summary.last_entry.number == 3
    assert summary.statute_changes[0].act_date == date(2025, 11, 24)


def test_filing_year_is_the_end_of_the_period_and_missing_audit_is_reported() -> None:
    summary = krs.parse_odpis(_odpis())
    kinds_2025 = {f.kind for f in summary.filings if f.year == 2025}
    assert kinds_2025 == {"financial_statement", "approval"}
    missing = krs.missing_filings(summary)
    assert missing[0] == {"year": 2025, "missing": ["activity_report", "audit_opinion"]}
    assert {m["year"] for m in krs.missing_filings(krs.parse_odpis(_odpis(with_audit_2025=True)))} == {
        2024,
        2025,
    }


def test_seeds_are_stable_keys_with_category_and_organ() -> None:
    seeds = {s.krs_key: s for s in krs.document_seeds(krs.parse_odpis(_odpis()))}
    approval = seeds["approval:2025"]
    assert approval.category == "resolution_general" and approval.organ == "general"
    assert approval.doc_date is None and approval.entry_no == 3
    statement = seeds["financial_statement:2024"]
    assert statement.category == "financial_statement" and statement.doc_date == date(2025, 7, 17)
    assert seeds["statute:3"].category == "statute"
    assert len(seeds) == len(krs.document_seeds(krs.parse_odpis(_odpis())))


def test_sha_ignores_print_time_but_not_content() -> None:
    a = _odpis()
    b = _odpis()
    b["odpis"]["naglowekA"]["stanZDnia"] = "17.11.2026"
    b["odpis"]["naglowekP"]["stanZDnia"] = "17.11.2026"
    assert krs.payload_sha(a) == krs.payload_sha(b)
    assert krs.payload_sha(a) != krs.payload_sha(_odpis(entries=4))


def test_broken_payload_gives_empty_summary_not_error() -> None:
    summary = krs.parse_odpis({"odpis": {"naglowekP": {"wpis": [{"numerWpisu": "x"}]}}})
    assert summary.entries == [] and summary.filings == [] and summary.last_entry is None
    assert krs.parse_pl_date("31.02.2026") is None


def test_reader_keeps_only_known_values_and_rejects_empty_reply() -> None:
    fields = clean_fields(
        {
            "category": "resolution_supervisory",
            "organ": "board",
            "number": " 3/2026 ",
            "doc_date": "2026-03-31T00:00",
            "subject": "przyjęcie budżetu",
            "votes": {"for": "3", "against": 0, "abstain": True},
        }
    )
    assert fields["category"] == "resolution_supervisory"
    assert fields["organ"] is None
    assert fields["number"] == "3/2026"
    assert fields["doc_date"] == "2026-03-31"
    assert fields["votes"] == {"for": 3, "against": 0, "abstain": None}
    assert parse_reply("bez JSON-a").status == "failed"
    assert parse_reply('{"category": "x", "number": null}').status == "failed"
    assert parse_reply('Oto: {"category": "statute"} koniec').status == "read"


def test_bell_names_the_last_entry_and_hides_system_court() -> None:
    entries = krs.parse_odpis(_odpis()).entries
    title, message = entry_message(entries[-1:])
    assert title == "Nowy wpis w KRS spółki (nr 3)"
    assert message == "Wpis nr 3 z 03.04.2026: Zmiana danych w rejestrze."
    title, _ = entry_message(entries)
    assert title == "3 nowe wpisy w KRS spółki (do nr 3)"


def test_cost_months_below_80_percent_of_median_are_incomplete() -> None:
    from app.services.board.summary import MonthRow, complete_cost_months

    rows = [MonthRow(2026, m, 10.0, 9.0) for m in range(1, 10)] + [MonthRow(2026, 10, 12.0, 2.9)]
    complete = complete_cost_months(rows)
    assert (2026, 9) in complete and (2026, 10) not in complete


def test_year_over_year_compares_the_same_months_and_result_only_with_full_costs() -> None:
    from app.services.board.summary import MonthRow, year_over_year

    previous = [MonthRow(2025, m, 10.0, 9.0) for m in range(1, 13)]
    current = [MonthRow(2026, m, 11.0, 10.5) for m in range(1, 10)] + [MonthRow(2026, 10, 12.0, 1.0)]
    out = year_over_year(previous + current, 2026)
    assert out["sales_months"] == 10 and out["result_months"] == 9
    assert out["sales"] == round((9 * 11 + 12) / 1e6, 2)
    assert out["sales_previous"] == round(100 / 1e6, 2)
    assert out["result_pct"] == round(100 * (99 - 94.5) / 99, 1)
    assert out["result_previous_pct"] == 10.0
    assert year_over_year(previous, 2027) == {"sales_months": 0, "result_months": 0}
