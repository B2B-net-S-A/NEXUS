"""Przypomnienie T-15 nie może być gubione przez restart backendu.

Okno było ograniczone z OBU stron (`start_time >= now+14min AND <= now+16min`),
co dawało każdemu wydarzeniu 120-sekundowy przedział kwalifikowalności: tick
w chwili T łapał start S wtedy i tylko wtedy, gdy `T ∈ [S-960s, S-840s]`.
Każda przerwa między tickami dłuższa niż 2 minuty gubiła BEZPOWROTNIE pasmo
startów o szerokości `przerwa − 120s` — a przerwy tej wielkości są rutyną
(Coolify przebudowuje backend przy każdym pushu na main, `entrypoint.sh` robi
alembica i siatkę DDL przed `exec uvicorn`; workflow deployu mówi o 4-6 min
zimnego builda). Po spadnięciu poniżej dolnej granicy `reminder_sent_at`
zostawało NULL na zawsze i rekruter nie dowiadywał się o rozmowie — bez błędu,
bez fallbacku mailowego, bez wpisu w logu.

Duplikatów otwarcie dolnej granicy nie tworzy: at-most-once gwarantuje trwały
stempel `reminder_sent_at` + `SELECT ... FOR UPDATE SKIP LOCKED`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CALENDAR = BACKEND / "app/api/calendar.py"

UTC = timezone.utc


def _loop_source() -> str:
    source = CALENDAR.read_text(encoding="utf-8")
    at = source.index("async def calendar_reminder_loop")
    return source[at : at + 3000]


def test_scan_has_no_lower_bound_at_fourteen_minutes() -> None:
    body = _loop_source()
    assert "minutes=14" not in body, (
        "dolna granica okna nie może wrócić — to ona zamieniała każdy restart "
        "dłuższy niż 2 minuty w bezpowrotnie utracone przypomnienia"
    )
    assert re.search(r"start_time\s*>\s*now", body), (
        "skan musi mieć granicę `> now` (a nie `>= now+14min`), żeby pierwszy "
        "tick po restarcie dogonił wszystko, co przespał"
    )


def test_upper_bound_is_unchanged() -> None:
    body = _loop_source()
    assert "minutes=16" in body, (
        "górna granica zostaje — bez niej pętla obudziłaby przypomnienia dla "
        "wydarzeń oddalonych o tygodnie"
    )


def _eligible(start: datetime, tick: datetime) -> bool:
    """Predykat skanu, wyrażony wprost — arytmetyka jest tu całym sednem."""
    return tick < start <= tick + timedelta(minutes=16)


def test_event_survives_a_six_minute_backend_outage() -> None:
    """Scenariusz z produkcji: rozmowa o 14:00, deploy 13:41-13:47.

    Przy dwustronnym oknie tick o 13:47 pytał o starty między 14:01 a 14:03,
    więc 14:00 przepadało na zawsze. Przy otwartej dolnej granicy pierwszy tick
    po restarcie je łapie.
    """
    start = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    first_tick_after_restart = datetime(2026, 8, 21, 13, 47, tzinfo=UTC)

    # Stary predykat, dla kontrastu — nie łapie.
    old = (
        first_tick_after_restart + timedelta(minutes=14)
        <= start
        <= first_tick_after_restart + timedelta(minutes=16)
    )
    assert old is False

    assert _eligible(start, first_tick_after_restart) is True, (
        "wydarzenie, którego okno przespał restart, musi zostać złapane przez "
        "pierwszy tick po powrocie"
    )


def test_event_already_started_is_not_picked_up() -> None:
    """`> now` chroni przed budzeniem przypomnień o rozmowach, które już trwają."""
    start = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    tick = datetime(2026, 8, 21, 14, 5, tzinfo=UTC)
    assert _eligible(start, tick) is False


def test_cycle_handler_reports_at_error_level() -> None:
    """Sentry ma `event_level=logging.ERROR` — na WARNING trwale padający cykl
    nie wygenerowałby żadnego zdarzenia i przypomnienia po prostu przestałyby
    przychodzić."""
    body = _loop_source()
    assert "logger.exception(" in body
    assert "logger.warning(f\"Calendar reminder loop error" not in body
