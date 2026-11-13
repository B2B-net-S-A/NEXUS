"""Silnik statusów raportu T4T (plan Nordei N1.3) — przypadki brzegowe z września.

Miesiąc jak wrzesień 2026: przedziały T4T 1–6, 7–13, 14–20, 21–24, 25–30
(ostatni przedział ma 4 dni robocze = 32 h). Godziny i numery fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.client_settlements import time_report_engine as engine
from app.services.client_settlements.time_report_engine import Entry, Period, classify

PERIODS = (
    Period(date(2026, 9, 1), date(2026, 9, 6)),
    Period(date(2026, 9, 7), date(2026, 9, 13)),
    Period(date(2026, 9, 14), date(2026, 9, 20)),
    Period(date(2026, 9, 21), date(2026, 9, 24)),
    Period(date(2026, 9, 25), date(2026, 9, 30)),
)
MONTH_END = date(2026, 9, 30)
NIDS_A, NIDS_B = "2020-000001", "2020-000002"


def _week(index: int, hours: str, status: int = 2, project: str = NIDS_A) -> Entry:
    period = PERIODS[index]
    return Entry(project, period.start, period.end, Decimal(hours), status)


def _full(
    status_by_week: dict[int, int] | None = None, project: str = NIDS_A
) -> list[Entry]:
    """Pełny miesiąc: 40 h w tygodniach 2–3, 32 h w pozostałych (176 h)."""

    hours = ("32", "40", "40", "32", "32")
    statuses = status_by_week or {}
    return [_week(i, h, statuses.get(i, 2), project) for i, h in enumerate(hours)]


def _run(entries: list[Entry], invoice: str | None) -> engine.Outcome:
    outcome = classify(
        entries, Decimal(invoice) if invoice is not None else None, PERIODS, MONTH_END
    )
    assert outcome is not None
    return outcome


def test_zgodne_gdy_zatwierdzone_rowne_fakturze():
    outcome = _run(_full(), "176")
    assert outcome.status == engine.OK
    assert outcome.approved == Decimal("176")
    assert outcome.difference == Decimal("0")
    assert outcome.notes == ()


def test_liczy_sie_tylko_status_2():
    outcome = _run(_full({4: 1}), "176")
    assert outcome.approved == Decimal("144")
    assert outcome.submitted == Decimal("32")
    assert outcome.status == engine.WAITING


def test_status_1_tylko_w_ostatnim_przedziale_to_czekamy():
    outcome = _run(_full({4: 1}), "176")
    assert outcome.status == engine.WAITING
    assert "ostatnim przedziale" in outcome.notes[0]


def test_status_1_we_wczesniejszym_przedziale_to_brak_akceptacji():
    outcome = _run(_full({3: 1}), "176")
    assert outcome.status == engine.NO_APPROVAL
    assert "21–24.09" in outcome.notes[0]


def test_przeniesione_godziny_ze_statusem_1_w_starym_przedziale_sa_zgodne():
    # Konsultant przeniósł 32 h z 21–24 do 25–30 (zatwierdzone), stary wpis wisi w statusie 1.
    entries = _full() + [_week(3, "32", status=1)]
    outcome = _run(entries, "176")
    assert outcome.status == engine.OK
    assert outcome.notes == ("Wisi status 1: 32 h (21–24.09).",)


def test_brak_godzin_w_ostatnim_przedziale_to_czekamy():
    entries = _full()[:4]  # 144 h, nic w 25–30
    outcome = _run(entries, "176")
    assert outcome.status == engine.WAITING
    assert "Brakuje 32 h" in outcome.notes[0]


def test_brak_wiekszy_niz_ostatni_przedzial_to_rozbieznosc():
    entries = _full()[:3]  # 112 h, faktura 176 h: brak 64 h > 32 h z 25–30
    outcome = _run(entries, "176")
    assert outcome.status == engine.DIFFERS
    assert outcome.notes == ("Faktura ma o 64 h więcej niż raport.",)


def test_brak_w_ostatnim_przy_statusie_1_wczesniej_to_rozbieznosc():
    entries = _full({1: 1})[:4]
    outcome = _run(entries, "176")
    assert outcome.status == engine.DIFFERS


def test_faktura_mniejsza_niz_raport_to_rozbieznosc():
    outcome = _run(_full(), "168")
    assert outcome.status == engine.DIFFERS
    assert outcome.difference == Decimal("-8")
    assert outcome.notes == ("Raport ma o 8 h więcej niż faktura.",)


def test_kilka_nids_sumuje_sie_do_jednej_faktury():
    entries = [_week(i, "16", 2, NIDS_A) for i in range(5)] + [
        _week(i, "16", 2, NIDS_B) for i in range(5)
    ]
    outcome = _run(entries, "160")
    assert outcome.status == engine.OK
    assert [p.project_no for p in outcome.projects] == [NIDS_A, NIDS_B]
    assert all(
        sum(w.approved for w in p.weeks) == Decimal("80") for p in outcome.projects
    )


def test_osoba_bez_faktury():
    outcome = _run(_full(), None)
    assert outcome.status == engine.NO_INVOICE
    assert outcome.difference is None


def test_faktura_bez_osoby_w_raporcie():
    outcome = _run([], "176")
    assert outcome.status == engine.NOT_IN_REPORT
    assert outcome.approved == Decimal("0")


def test_ani_raportu_ani_faktury():
    assert classify([], None, PERIODS, MONTH_END) is None


def test_status_0_i_3_nie_licza_sie_do_zadnych_godzin():
    entries = _full() + [_week(4, "8", status=0), _week(4, "8", status=3)]
    outcome = _run(entries, "176")
    assert outcome.status == engine.OK
    assert outcome.submitted == Decimal("0")


def test_tolerancja_grosza_przy_godzinach_z_netto_przez_stawke():
    assert _run(_full(), "176.01").status == engine.OK
    assert _run(_full(), "175").status == engine.DIFFERS


def test_faktura_w_niepelnych_godzinach_to_inna_kwota_nie_rozbieznosc():
    # Polecenie doliczone do godzin: netto ÷ stawka nie daje pełnych godzin (R1, 13.11).
    outcome = _run(_full(), "178.50")
    assert outcome.status == engine.OTHER_AMOUNT
    assert "możliwy dodatek" in outcome.notes[0]


def test_tygodnie_w_kolejnosci_przedzialow_z_pustymi():
    outcome = _run(_full()[:2], "72")
    assert [w.start.day for w in outcome.weeks] == [1, 7, 14, 21, 25]
    assert [w.approved for w in outcome.weeks][2:] == [Decimal("0")] * 3


def test_przedzialy_miesiaca_z_wierszy_raportu():
    entries = _full() + [
        Entry(NIDS_A, date(2026, 8, 31), date(2026, 8, 31), Decimal("8"), 2)
    ]
    found = engine.month_periods(entries, date(2026, 9, 1), date(2026, 9, 30))
    assert found == PERIODS


def test_dni_robocze_bez_weekendow():
    assert engine.weekdays(date(2026, 9, 25), date(2026, 9, 30)) == 4
