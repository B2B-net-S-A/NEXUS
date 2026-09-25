"""Lustro komunikatów bramki „Przekaż do searchu” w froncie.

Okno „Zlecenie” (``OrderSlideOver``) zamienia listę ``blockers`` z
``GET /api/jobs/{id}/readiness`` na wiersze z działaniem (pole budżetu, trzy
przyciski trybu pracy, link do sekcji Championa). Rozpoznaje brak po DOKŁADNYM
zdaniu — więc zdanie zmienione tylko tutaj zamieniłoby wiersz z przyciskiem
w goły tekst, po cichu. Test trzyma oba miejsca razem.
"""

import json
from pathlib import Path

from app.services import job_readiness

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "__fixtures__"
    / "job-readiness-blockers.json"
)

EXPECTED = {
    "title": job_readiness.MSG_TITLE,
    "client": job_readiness.MSG_CLIENT,
    "context": job_readiness.MSG_CONTEXT,
    "questions": job_readiness.MSG_QUESTIONS,
    "must": job_readiness.MSG_MUST,
    "budget": job_readiness.MSG_BUDGET,
    "work_mode": job_readiness.MSG_WORK_MODE,
    "office_days": job_readiness.MSG_OFFICE_DAYS,
    "office_city": job_readiness.MSG_OFFICE_CITY,
    "search": job_readiness.MSG_SEARCH_REQUIREMENTS,
}


def test_frontend_mirror_matches_backend_messages():
    mirror = json.loads(FIXTURE.read_text(encoding="utf-8"))["blockers"]
    assert mirror == EXPECTED


def test_every_backend_message_constant_is_mirrored():
    constants = {
        name
        for name in dir(job_readiness)
        if name.startswith("MSG_") and isinstance(getattr(job_readiness, name), str)
    }
    mirrored = {
        name for name in constants if getattr(job_readiness, name) in EXPECTED.values()
    }
    assert constants == mirrored
