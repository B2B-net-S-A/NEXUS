"""Szkic wiadomości na LinkedInie pod rekrutację (F38, wtyczka 28.10.2026).

Model pisze szkic z profilu otwartego na LinkedInie i z rekrutacji; rekruter
czyta, poprawia i wysyła sam — wtyczka niczego nie wysyła. Model jest
podpowiedzią: gdy nie odpowie, wtyczka dostaje szablon złożony z rekrutacji
(``ai = False``) i ścieżka działa dalej.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.job import Job
from app.models.user import User
from app.schemas.linkedin_extension import ProfileRead
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.linkedin_extension_lookup import split_full_name
from app.services.llm_prompts import LINKEDIN_MESSAGE_DRAFT
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.linkedin_message_draft

KIND_LABELS: dict[str, str] = {
    "inmail": "InMail w LinkedIn Recruiterze",
    "invitation": "notatka do zaproszenia do sieci",
    "linkedin_message": "wiadomość na LinkedInie",
}
# Zaproszenie z notatką LinkedIn przycina do 300 znaków; InMail i wiadomość
# czyta się na telefonie, więc krótko.
LIMITS: dict[str, int] = {"invitation": 300, "inmail": 700, "linkedin_message": 600}


async def _job_facts(db: AsyncSession, job_id: int) -> Optional[dict]:
    row = (
        await db.execute(
            select(
                Job.title,
                func.coalesce(Client.display_name, Client.name),
                Job.must_skills,
                Job.location,
                Job.remote_policy,
            )
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id == job_id)
        )
    ).first()
    if row is None:
        return None
    title, client_name, must, location, remote = row
    skills: list[str] = []
    for item in must or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            skills.append(name.strip())
    return {
        "title": title,
        "client": client_name,
        "skills": skills[:6],
        "location": location,
        "remote": getattr(remote, "value", remote),
    }


def _job_block(job: dict) -> str:
    lines = [f"Rola: {job['title']}"]
    if job.get("client"):
        lines.append(f"Klient: {job['client']}")
    if job.get("skills"):
        lines.append("Najważniejsze technologie: " + ", ".join(job["skills"]))
    if job.get("location"):
        lines.append(f"Miejsce: {job['location']}")
    if job.get("remote"):
        lines.append(f"Tryb pracy: {job['remote']}")
    return fence("client_recruitment", "\n".join(lines))


def _profile_block(profile: ProfileRead) -> str:
    lines = []
    if profile.headline:
        lines.append(f"Nagłówek: {profile.headline}")
    if profile.current_title or profile.current_company:
        lines.append(
            "Teraz: " + " w ".join(p for p in (profile.current_title, profile.current_company) if p)
        )
    for entry in profile.experience[:4]:
        line = " · ".join(p for p in (entry.title, entry.company) if p)
        if line:
            lines.append(f"Wcześniej: {line}")
    if profile.skills:
        lines.append("Umiejętności: " + ", ".join(profile.skills[:15]))
    return fence("candidate_profile", "\n".join(lines) or "(pusty profil)")


def _signature(user: User) -> str:
    first = (user.name or "").split()[0] if user.name else "Rekruter"
    return f"{first}, B2B Network"


def fallback_text(profile: ProfileRead, job: dict, user: User, kind: str) -> str:
    first, _ = split_full_name(profile.full_name)
    role = job["title"]
    client = f" w {job['client']}" if job.get("client") else ""
    tech = f" ({', '.join(job['skills'][:3])})" if job.get("skills") else ""
    text = (
        f"Cześć {first or ''},\n"
        f"szukam osoby na stanowisko {role}{client}{tech}. "
        "Twój profil wygląda na dobre dopasowanie.\n\n"
        "Masz 15 minut w tym tygodniu na krótką rozmowę?\n\n"
        f"{_signature(user)}"
    )
    return _trim(text, LIMITS[kind])


def _trim(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    return cut[: cut.rfind(" ")].rstrip(" ,.;") + "…" if " " in cut else cut + "…"


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=700,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def draft_message(
    db: AsyncSession, *, user: User, job_id: int, kind: str, profile: ProfileRead
) -> Optional[tuple[str, bool]]:
    """``(tekst, czy_z_AI)``; ``None`` = nie ma takiej rekrutacji."""
    job = await _job_facts(db, job_id)
    if job is None:
        return None
    limit = LIMITS[kind]
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return fallback_text(profile, job, user, kind), False
    first, _ = split_full_name(profile.full_name)
    # Imię stoi poza ogrodzeniem danych — tylko litery i łącznik.
    first = re.sub(r"[^\w\-]", "", first)[:40]
    prompt = LINKEDIN_MESSAGE_DRAFT.render(
        kind_label=KIND_LABELS[kind],
        limit=limit,
        first_name=first or "",
        signature=_signature(user),
        profile=_profile_block(profile),
        job=_job_block(job),
    )
    try:
        async with ai_feature(db, FEATURE, user_id=user.id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, LINKEDIN_MESSAGE_DRAFT.system_prompt or "", prompt, chain
            )
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning("[linkedin_message_draft] failed (%s)", type(exc).__name__)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[linkedin_message_draft] rollback failed")
        return fallback_text(profile, job, user, kind), False
    text = (raw or "").strip().strip("`").strip()
    if not text:
        return fallback_text(profile, job, user, kind), False
    return _trim(text, limit), True
