"""Shared readiness rule for manual handoff and automatic allocation."""

from app.models.job import Job
from app.services import champion_view


def job_readiness_blockers(job: Job) -> list[str]:
    """Blockers that prevent handing a recruitment off to search (P0-A).

    The Champion is required: it is the Delivery Lead's ideal-candidate spec and
    the strongest matching signal, so a handoff without it would produce a weak,
    JD-only ranking — exactly the "ranking before the Champion" problem the
    handoff exists to prevent. Requires project context + at least two screening
    questions, plus the basics (title, client) that anchor the search.
    """
    blockers: list[str] = []
    if not (job.title or "").strip():
        blockers.append("Uzupełnij tytuł rekrutacji.")
    if job.client_id is None:
        blockers.append("Przypisz klienta do rekrutacji.")

    cp = job.champion_profile if isinstance(job.champion_profile, dict) else {}
    pc = champion_view.project(cp)
    has_context = bool((pc.get("about") or "").strip()) or bool(
        pc.get("responsibilities")
    )
    if not has_context:
        blockers.append(
            "Uzupełnij kontekst projektu (o projekcie / obowiązki) w Profilu Championa."
        )

    questions = cp.get("screening_questions")
    questions = questions if isinstance(questions, list) else []
    valid_questions = [
        q
        for q in questions
        if isinstance(q, dict) and (q.get("question") or "").strip()
    ]
    if len(valid_questions) < 2:
        blockers.append("Dodaj co najmniej 2 pytania screeningowe w Profilu Championa.")

    return blockers
