"""Archiwum pytań z rozmów u klienta — wybór pytań PO ROLI.

Źródło: ``InterviewQuestion.source == legacy_import`` — pytania, o które klient
pytał kandydatów, zebrane przez rekruterów w Excelu przed NEXUSEM (import:
``scripts/import_legacy_interview_questions.py``, migracja 0383).

Zasady, które łatwo cofnąć:

* **Archiwum nigdy nie jest „najnowszymi N pytaniami klienta”.** U Nordei to
  ~tysiąc pytań z kilkudziesięciu ról; listy typu „ostatnie 15” (prep-kit,
  ocena prepu, Luna na ``/jobs/new``) czytają wyłącznie ``client_debrief``.
  Archiwum dociera do rekrutacji tylko tu — po technologiach roli — albo przez
  przypięcia do podobnych rekrutacji (tiery 1/2 prep-kitu).
* **Ocena prepu go nie czyta.** Pytanie z archiwum wchodzi do oceny dopiero,
  gdy człowiek przypnie je do rekrutacji.
* **Pytanie bez technologii tu nie wchodzi** („opowiedz o sobie” pasuje do
  każdej roli, więc nie mówi nic o tej). Takie pytania docierają wyłącznie
  przez przypięcie do podobnej rekrutacji.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview_question import InterviewQuestion, InterviewQuestionSource

DEFAULT_LIMIT = 10
# Ile kandydatów z SQL-a oglądamy przed rankingiem. Filtr po tagach to
# wstępne sito; ostateczne słowo ma `mentioned_technologies` (tagi + treść).
_POOL = 400


@dataclass(frozen=True)
class ArchiveMatch:
    question: InterviewQuestion
    matched: tuple[str, ...]


async def archive_questions_for_role(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    requirement_names: set[str],
    limit: int = DEFAULT_LIMIT,
) -> list[ArchiveMatch]:
    """Pytania z archiwum tego klienta, które pytają o technologię tej roli.

    Ranking: więcej wspólnych technologii wyżej, potem stała kolejność po id.
    Limit działa PO filtrze — inaczej przy tysiącu pytań klienta zostałaby
    losowa garść, w większości o inne role.
    """
    from app.services.question_suggestions import mentioned_technologies

    names = {n for n in requirement_names if n}
    if client_id is None or not names or limit <= 0:
        return []
    rows = (
        (
            await db.execute(
                select(InterviewQuestion)
                .where(
                    InterviewQuestion.client_id == client_id,
                    InterviewQuestion.source == InterviewQuestionSource.legacy_import,
                    # `@>` jak filtr `skill_tag` w Bazie pytań — jedna technologia
                    # na warunek, bo tagi to lista JSONB.
                    or_(
                        *(
                            InterviewQuestion.skill_tags.contains([n])
                            for n in sorted(names)
                        )
                    ),
                )
                .order_by(InterviewQuestion.id.asc())
                .limit(_POOL)
            )
        )
        .scalars()
        .all()
    )
    matches: list[ArchiveMatch] = []
    for question in rows:
        common = mentioned_technologies(question.text, question.skill_tags) & names
        if common:
            matches.append(ArchiveMatch(question, tuple(sorted(common))))
    matches.sort(key=lambda m: (-len(m.matched), m.question.id))
    return matches[:limit]
