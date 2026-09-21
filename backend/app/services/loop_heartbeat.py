"""MON-04 (audyt 14.09.2026): pętla, która żyje, ale nic nie robi, jest awarią.

``classify_background_tasks`` widzi wyłącznie stan ``asyncio.Task``: zadanie
zawieszone na ``await`` (zablokowane połączenie, zamek, dostawca bez timeoutu)
ma ``done() == False`` i liczy się jako ``running`` bez końca. Synchronizacja
odejść pracowników albo przypomnienia o rozmowach mogły więc stanąć przy
zielonym ``/api/health``.

Każda krytyczna pętla rejestruje się tutaj po przejściu kill-switcha
i wywołuje ``beat.tick()`` na początku każdej iteracji. Pętla, której ostatni
tick jest starszy niż jej ``max_silence_seconds``, trafia na listę ``stalled``.

Stan żyje w pamięci procesu — wystarcza, bo backend to jeden proces uvicorn,
a ``/api/health`` pyta ten sam proces, w którym biegną pętle. Restart zeruje
rejestr razem z pętlami, więc nie ma fałszywego „zawieszenia” po deployu.

Pętla wyłączona flagą NIGDY się nie rejestruje (wraca przed rejestracją),
więc nie może być ``stalled`` — jest ``exited_cleanly`` jak dotąd.

Nowa pętla w ``app.state.background_tasks`` musi być albo zarejestrowana,
albo dopisana do ``EXEMPT`` z powodem — pilnuje tego
``tests/test_loop_heartbeat.py``.
"""

from __future__ import annotations

import time
from typing import Callable

# Pętle celowo bez heartbeatu. Klucz = nazwa w ``app.state.background_tasks``.
EXEMPT: dict[str, str] = {
    "cv_approval": "worker kolejki zatwierdzeń; zawieszenie widać po wieku zadań w kolejce",
    "cv_source_cleanup": "sprzątanie plików z ponowieniami; opóźnienie nie dotyka użytkownika",
    "cv_version_maps": "worker map wersji CV; dodatek, nie ścieżka krytyczna",
    "candidate_search": "worker przeglądów; reaper kończy przeglądy bez postępu po 30 min",
    "candidate_search_retention": "retencja danych; opóźnienie o godziny nieszkodliwe",
    "jarvis_retention": "retencja rozmów Jarvisa; opóźnienie o godziny nieszkodliwe",
    "match_history_ttl": "sprzątanie historii; opóźnienie nieszkodliwe",
    "slack_sla_alerts": "osobna kontrola stopped_webhook_alarms",
    "ai_spend_alerts": "osobna kontrola checks.ai_features",
    "fx_refresh": "świeżość kursów ma własną sondę checks.fx",
    "competition_autofreeze": "zamrożenie rankingów ma własną idempotentną ścieżkę ręczną",
    "cc_centroid_sync": "dobowe przeliczenie centroidów; brak wpływu na bieżącą pracę",
    "kpi_coach_nudger": "powiadomienia motywacyjne; nie ścieżka krytyczna",
    "notification_triggers": "reguły powiadomień; do objęcia po tygodniu obserwacji",
    "notification_volume_monitor": "monitor sam jest sygnałem pomocniczym",
    "linkedin_sync": "integracja opcjonalna, domyślnie wyłączona",
    "m365_cv_parse": "parsowanie CV z poczty; świeżość M365 ma checks.m365",
    "m365_rematch": "dopinanie maili; dodatek do synchronizacji",
    "m365_webhook_renewal": "awaria odnowienia widać jako brak webhooków; polling M365 nadrabia",
    "m365_recording_discovery": "nagrania spotkań; dodatek, nie ścieżka krytyczna",
    "marketplace_sweeper": "sprzątanie Targu; opóźnienie nieszkodliwe",
    "saved_search_alerts": "alerty zapisanych wyszukiwań; nie ścieżka krytyczna",
    "chat_email_fallback": "fallback mailowy czatu; nie ścieżka krytyczna",
    "signature_reconciler": "uzgadnianie podpisów; sweeper podpisów jest objęty",
    "dl_portal_expiry": "dzienny skaner; zastępowany przez objęte dl_alerts",
    "job_deadline_alerts": "dzienny skaner terminów; do objęcia po tygodniu obserwacji",
    "insights_seniority_journal": "dziennik analityczny; opóźnienie nieszkodliwe",
    "cloudtalk_sync": "integracja wyłączona decyzją 28.07",
    "notes_insights_sync": "wzbogacanie notatek; dodatek",
    "weekly_eval": "tygodniowy pomiar jakości; brak wpływu na produkcję",
    "match_digest": "digest dopasowań; nie ścieżka krytyczna",
    "candidate_contact_queue": "kolejka kontaktów ma własny stan last_success_at",
    "candidate_contact_traffit": "ma własny stan last_success_at",
    "priority_work": "ma własny heartbeat worker_heartbeat_at w checks.priority_work",
    "workforce_availability": "ma własną sondę świeżości w checks.workforce_availability",
    "recruitment_allocation": "ma własną sondę świeżości w checks.recruitment_allocation",
    "allocation_matching": "część alokacji; świeżość w checks.recruitment_allocation",
    "runtime_metrics": "sam jest pomiarem (lag pętli, pula) w logach; brak wpisów widać w Loki",
}


class Beat:
    def __init__(
        self, name: str, max_silence_seconds: float, clock: Callable[[], float]
    ):
        self.name = name
        self.max_silence_seconds = max(60.0, float(max_silence_seconds))
        self._clock = clock
        self.last_tick = clock()
        self.ticks = 0

    def tick(self) -> None:
        """Wołane na początku każdej iteracji pętli."""
        self.last_tick = self._clock()
        self.ticks += 1

    def silence(self, now: float) -> float:
        return now - self.last_tick


class Registry:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._beats: dict[str, Beat] = {}

    def register(self, name: str, *, max_silence_seconds: float) -> Beat:
        beat = Beat(name, max_silence_seconds, self._clock)
        self._beats[name] = beat
        return beat

    def stalled(self, running: set[str] | None = None) -> list[str]:
        """Nazwy pętli bez ticku dłużej niż ich próg.

        ``running`` zawęża do zadań, które nadal żyją — pętla, która padła
        wyjątkiem, jest już ``crashed`` i nie powinna być liczona drugi raz.
        """
        now = self._clock()
        return sorted(
            name
            for name, beat in self._beats.items()
            if (running is None or name in running)
            and beat.silence(now) > beat.max_silence_seconds
        )

    def names(self) -> set[str]:
        return set(self._beats)


heartbeats = Registry()


def register(name: str, *, max_silence_seconds: float) -> Beat:
    return heartbeats.register(name, max_silence_seconds=max_silence_seconds)
