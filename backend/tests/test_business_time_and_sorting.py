"""Granice dni/miesięcy w kalendarzu firmy + porządek alfabetyczny polskich nazw.

Dwie klasy cichych regresów, obie kosztujące pieniądze lub wiarygodność:

1. **Czas.** Kontener chodzi w UTC (`backend/Dockerfile` nie ustawia `TZ`), więc
   ``date.today()`` przez pierwsze 1–2 godziny polskiej doby zwraca WCZORAJ,
   a naiwna data porównana z kolumną ``timestamptz`` kompiluje się do
   ``$1::DATE`` i granica wypada o północy UTC sesji Postgresa. Liczba
   pozostaje poprawna — opisuje tylko inny dzień, więc nic nie krzyczy.

2. **Sortowanie.** Prod i CI stoją na ``postgres:16-alpine`` (musl), a musl nie
   implementuje żadnej kolacji — ``ORDER BY`` na tekście degraduje się do
   porządku bajtowego, w którym Ł/Ś/Ż są WIĘKSZE od Z. Zmierzone na tym samym
   tagu obrazu: ``SELECT 'Łukasz' < 'Zbigniew'`` zwraca ``f``, a katalog i tak
   raportuje ``datcollate = en_US.utf8``, więc odczyt ``pg_database`` daje złą
   odpowiedź. Testy niżej pinują WYNIK naszych helperów, a nie zachowanie
   libc — dzięki temu przechodzą też na obrazie z glibc i nie zamieniają się
   w pułapkę dla kogoś, kto kiedyś ten obraz podmieni.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import String, column, select, values

from app.api import clients as clients_api
from app.core.database import AsyncSessionLocal
from app.services import competitions
from app.services import dashboard_metrics
from app.tasks import contract_alerts


def _utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# ── 1. Okresy konkursowe liczone po kalendarzu warszawskim ──────────────────


def test_month_bounds_follow_warsaw_not_utc_midnight():
    """Sierpień to [31.07 22:00Z, 31.08 22:00Z), bo latem Warszawa to UTC+2.

    Przy granicy UTC ruch `hired` zapisany 1.09 o 00:40 w Warszawie
    (= 31.08 22:40Z) wpadał do SIERPNIA — i tak trafiał na zamrażane,
    nieodwracalne podium z nagrodą 1500 PLN.
    """
    start, end = competitions.month_bounds(2026, 8)
    assert (start, end) == (_utc(2026, 7, 31, 22), _utc(2026, 8, 31, 22))
    assert _utc(2026, 8, 31, 22, 40) >= end  # wrześniowe zdarzenie poza sierpniem


def test_month_bounds_handle_winter_offset_and_year_roll():
    """Zimą offset to +1, więc styczeń zaczyna się 31.12 o 23:00Z."""
    assert competitions.month_bounds(2026, 1) == (
        _utc(2025, 12, 31, 23),
        _utc(2026, 1, 31, 23),
    )
    assert competitions.month_bounds(2026, 12) == (
        _utc(2026, 11, 30, 23),
        _utc(2026, 12, 31, 23),
    )


def test_quarter_bounds_follow_warsaw_too():
    """Progi kwartalne (5000/3000/2000 PLN) jadą na tej samej granicy co miesięczne."""
    assert competitions.quarter_bounds(2026, 3) == (
        _utc(2026, 6, 30, 22),
        _utc(2026, 9, 30, 22),
    )
    assert competitions.quarter_bounds(2026, 1) == (
        _utc(2025, 12, 31, 23),
        _utc(2026, 3, 31, 22),
    )


def test_business_days_count_includes_last_calendar_day_of_month():
    """Ostatni dzień miesiąca NIE może wypaść z licznika dni roboczych.

    Regres byłby o jeden dzień w dół: `month_bounds` zwraca teraz granicę
    warszawską w UTC (1.09 lokalnie = 31.08 22:00Z), więc wyprowadzanie
    ostatniego dnia przez „koniec minus doba" dałoby 30., a nie 31. sierpnia.
    Próg „4 weryfikacje / dzień roboczy" liczyłby wtedy za mało i wykluczał
    z nagrody kogoś, kto trafiał w target każdego realnego dnia.
    """
    # 31.08.2026 to poniedziałek i nie jest polskim świętem ustawowym.
    assert date(2026, 8, 31).weekday() == 0
    full_month = competitions.business_days_elapsed_in_month(
        2026, 8, today=date(2026, 9, 15)
    )
    without_last_day = competitions.business_days_elapsed_in_month(
        2026, 8, today=date(2026, 8, 30)
    )
    assert full_month == without_last_day + 1


# ── 2. Remisy w konkursach rozstrzygane bez porządku bajtowego ──────────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


async def test_monthly_race_tie_break_is_id_not_name(monkeypatch):
    """Remis o 1500 PLN nie może zależeć od pisowni nazwy.

    Tie-break po tekście pod musl to porównanie bajtowe — „Łukasz" przegrywa
    z „Zbigniewem" ZAWSZE, a pierwszy wiersz tego rankingu to `qualified_leader`,
    czyli nazwisko przypisane do nagrody, potem zamrażane niezmiennie.
    """
    monkeypatch.setattr(
        competitions, "business_days_elapsed_in_month", lambda _y, _m: 10
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=_Rows([])))
    await competitions.monthly_most_recommendations(db, "2026-08")
    sql = str(db.execute.await_args.args[0])
    assert "t.name asc" not in sql.lower()
    assert sql.lower().count("t.recommendations desc, t.id asc") == 2
    assert "ORDER BY recommendations DESC, id ASC" in sql


async def test_stage_ranking_and_hall_of_fame_tie_break_is_id_not_name():
    db = SimpleNamespace(execute=AsyncMock(return_value=_Rows([])))
    await competitions._rank_recruiters_by_stage(
        db, stage=competitions.PipelineStage.hired, start=_utc(2026, 8, 1), end=_utc(2026, 9, 1)
    )
    stage_sql = str(db.execute.await_args.args[0])
    assert "ORDER BY count(*) DESC, u.id ASC" in stage_sql
    assert "u.name ASC" not in stage_sql

    db = SimpleNamespace(execute=AsyncMock(return_value=_Rows([])))
    await competitions.hall_of_fame(db)
    hof_sql = str(db.execute.await_args.args[0])
    assert "ORDER BY count(*) DESC, u.id ASC" in hof_sql
    assert "u.name ASC" not in hof_sql


# ── 3. Alerty kontraktowe i KPI liczą dzień firmy, nie dzień UTC ────────────


class _CapturingDb:
    """Sesja-atrapa: zapamiętuje instrukcje i udaje puste wyniki."""

    def __init__(self):
        self.statements = []

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return _Rows([])


def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


async def test_contract_threshold_window_uses_business_today(monkeypatch):
    """Okno alertu liczy się od dnia warszawskiego, nie od daty UTC kontenera."""
    monkeypatch.setattr(contract_alerts, "business_today", lambda: date(2026, 9, 1))
    db = _CapturingDb()
    await contract_alerts._contracts_at_threshold(db, 30)
    sql = _sql(db.statements[0])
    assert "2026-10-01" in sql  # target = business_today + 30
    assert "2026-09-30" in sql  # window_start = target - 1


async def test_status_promotion_uses_business_today(monkeypatch):
    """Kontrakt kończący się DZIŚ przechodzi na `ended` w polskim dniu, nie w UTC."""

    class _Rowcount(_Rows):
        rowcount = 0

    class _Db(_CapturingDb):
        async def execute(self, statement, *args, **kwargs):
            self.statements.append(statement)
            return _Rowcount([])

    monkeypatch.setattr(contract_alerts, "business_today", lambda: date(2026, 9, 1))
    db = _Db()
    await contract_alerts._promote_statuses(db)
    ending_sql, ended_sql = (_sql(s) for s in db.statements)
    assert "2026-10-01" in ending_sql  # cutoff = dziś + 30 dni
    assert "2026-09-01" in ended_sql


async def test_hired_this_month_binds_warsaw_month_as_timestamps(monkeypatch):
    """`moved_at` to `timestamptz` — granicą musi być chwila, nie naiwna data.

    Naiwna data kompiluje się do `$1::DATE` i rozwiązuje o północy UTC sesji,
    więc zatrudnienie z 31.08 23:00Z (1.09 o 01:00 w Warszawie) wypadało
    z sierpnia po jednej stronie granicy i z września po drugiej — znikało
    z KPI na stałe. Samo `ENV TZ` tego nie naprawia.
    """
    monkeypatch.setattr(
        dashboard_metrics, "business_today", lambda: date(2026, 9, 15)
    )

    class _Scalar(_Rows):
        def scalar(self):
            return 0

    class _Db(_CapturingDb):
        async def execute(self, statement, *args, **kwargs):
            self.statements.append(statement)
            return _Scalar([])

    db = _Db()
    await dashboard_metrics.compute_kpi_snapshot(db)
    hired = [s for s in db.statements if "candidate_stages" in _sql(s)]
    assert hired, "brak zapytania o hired_this_month"
    sql = _sql(hired[-1])
    assert "2026-08-31 22:00:00" in sql
    assert "2026-09-30 22:00:00" in sql


# ── 4. Alfabet: polskie nazwy przed Z, nie za Z ─────────────────────────────


_POLISH_NAMES = [
    "Zurich",
    "Łukasiewicz S.A.",
    "alfa sp. z o.o.",
    "Śnieżka",
    "Żabka",
    "Alior Bank",
    "Ćwikła",
    "Bank Pocztowy",
]


@pytest.mark.asyncio
async def test_client_catalogue_sorts_polish_names_before_z():
    """Katalog klientów musi układać Ł/Ś/Ż wewnątrz alfabetu, nie za Zurichem.

    Wcześniejsze `lower()` naprawiało wyłącznie połowę dotyczącą wielkości
    liter, więc każdy klient o polskim inicjale lądował na ostatniej stronie.
    """
    v = values(column("name", String), name="t").data([(n,) for n in _POLISH_NAMES])
    stmt = select(v.c.name).order_by(
        clients_api.polish_alphabetical_key(v.c.name).asc()
    )
    async with AsyncSessionLocal() as db:
        ordered = [row[0] for row in (await db.execute(stmt)).all()]
    assert ordered == [
        "alfa sp. z o.o.",
        "Alior Bank",
        "Bank Pocztowy",
        "Ćwikła",
        "Łukasiewicz S.A.",
        "Śnieżka",
        "Żabka",
        "Zurich",
    ]


def test_consultant_picker_and_client_catalogue_agree_on_the_alphabet():
    """Dwie powierzchnie tej samej aplikacji nie mogą mieć różnych alfabetów.

    Picker konsultantów sortuje w Pythonie (`normalize_person_name_part`),
    katalog klientów w SQL (`translate` + `lower`). Fold musi być ten sam.
    """
    from app.services.candidate_identity_quarantine import normalize_person_name_part

    for raw, folded in (
        ("Łukasz", "lukasz"),
        ("Świderski", "swiderski"),
        ("Żabka", "zabka"),
        ("Ćwikła", "cwikla"),
        ("Gródek", "grodek"),
        ("Węgiel", "wegiel"),
        ("Toruń", "torun"),
        ("Źródło", "zrodlo"),
    ):
        assert normalize_person_name_part(raw) == folded
        sql_folded = raw.translate(
            str.maketrans(clients_api._PL_DIACRITICS, clients_api._PL_ASCII_FOLD)
        ).lower()
        assert sql_folded == folded
