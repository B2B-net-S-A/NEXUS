"""Jednorazowe przypisanie zespołu do czterech kategorii (screen Artura, 24.09.2026).

Przepisuje układ ze starego InfraReportera na aktywne konta NEXUSA (konta
z polskimi znakami w nazwisku to nieaktywne duplikaty z importu — tu są
wyłącznie id aktywnych kont; nazwisk w repo nie trzymamy). Oznacza też konta
„Poza przydziałem” wskazane przez Artura.

Na sucho (domyślnie) wypisuje, co by zrobił, i sprawdza każde id: konto musi
istnieć, być aktywne i mieć rolę rekrutera, sourcera albo TAC. Z ``--apply``
zapisuje i zostawia ślad w ``activities`` (jak zapis z panelu).

    python -m scripts.seed_competence_team_2026_09          # na sucho
    python -m scripts.seed_competence_team_2026_09 --apply  # zapis
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

INFRA = "infrastructure_operations"
DEVELOPMENT = "software_development"
QA = "security_quality"
MANAGEMENT = "management_delivery"

# (slug kategorii, priorytet) → id kont. Jedna kategoria z 1. priorytetem na
# osobę — tak jest na screenie i tak wymaga częściowy UNIQUE w bazie.
ASSIGNMENTS: dict[tuple[str, int], tuple[int, ...]] = {
    (INFRA, 1): (155, 85),
    (INFRA, 2): (154, 226),
    (DEVELOPMENT, 1): (151, 140, 91, 227),
    (DEVELOPMENT, 2): (144, 234),
    (QA, 1): (241, 144, 234),
    (QA, 2): (151, 91, 227),
    (MANAGEMENT, 1): (242, 154, 226),
    (MANAGEMENT, 2): (155, 85),
}

# Konta z rolą rekrutera, które nie pracują przy requestach (decyzja Artura).
EXCLUDED: tuple[int, ...] = (153, 240, 243, 236, 238)


def validate_plan() -> list[str]:
    """Błędy planu bez bazy — np. dwie kategorie z 1. priorytetem u jednej osoby."""
    errors = []
    first: dict[int, str] = {}
    for (slug, priority), ids in ASSIGNMENTS.items():
        for user_id in ids:
            if priority == 1:
                if user_id in first:
                    errors.append(
                        f"konto {user_id}: 1. priorytet w {first[user_id]} i {slug}"
                    )
                first[user_id] = slug
    for (slug, priority), ids in ASSIGNMENTS.items():
        if priority == 2:
            for user_id in ids:
                if first.get(user_id) == slug:
                    errors.append(f"konto {user_id}: {slug} jako 1. i 2. priorytet")
    return errors


async def run(apply: bool) -> int:
    import app.models  # noqa: F401 — komplet mapperów
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.competence_category import (
        CompetenceCategory,
        UserCompetenceCategory,
    )
    from app.models.user import User, UserRole

    errors = validate_plan()
    if errors:
        for error in errors:
            print(f"BŁĄD PLANU: {error}")
        return 1
    operator_roles = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)
    async with AsyncSessionLocal() as db:
        categories = dict(
            (
                await db.execute(
                    select(CompetenceCategory.slug, CompetenceCategory.id).where(
                        CompetenceCategory.is_active.is_(True)
                    )
                )
            ).all()
        )
        missing = {slug for slug, _p in ASSIGNMENTS} - set(categories)
        if missing:
            print(f"BRAK KATEGORII (czy migracja 0371 przeszła?): {sorted(missing)}")
            return 1
        all_ids = {i for ids in ASSIGNMENTS.values() for i in ids} | set(EXCLUDED)
        users = {
            u.id: u
            for u in (await db.scalars(select(User).where(User.id.in_(all_ids)))).all()
        }
        problems = []
        for user_id in sorted(all_ids):
            user = users.get(user_id)
            if user is None:
                problems.append(f"konto {user_id}: nie istnieje")
            elif not user.is_active:
                problems.append(f"konto {user_id}: nieaktywne")
            elif user_id not in EXCLUDED and not user.has_any_role(*operator_roles):
                problems.append(f"konto {user_id}: brak roli rekrutera/sourcera/TAC")
        if problems:
            for problem in problems:
                print(f"STOP: {problem}")
            return 1

        planned = 0
        for (slug, priority), ids in sorted(ASSIGNMENTS.items()):
            for user_id in ids:
                planned += 1
                print(
                    f"{'zapis' if apply else 'na sucho'}: konto {user_id} → {slug} ({priority})"
                )
                if not apply:
                    continue
                row = await db.scalar(
                    select(UserCompetenceCategory).where(
                        UserCompetenceCategory.user_id == user_id,
                        UserCompetenceCategory.competence_category_id
                        == categories[slug],
                    )
                )
                if priority == 1:
                    others = (
                        await db.scalars(
                            select(UserCompetenceCategory).where(
                                UserCompetenceCategory.user_id == user_id,
                                UserCompetenceCategory.priority == 1,
                            )
                        )
                    ).all()
                    for other in others:
                        if other is not row:
                            other.priority = 2
                            other.is_primary = False
                    await db.flush()
                if row is None:
                    db.add(
                        UserCompetenceCategory(
                            user_id=user_id,
                            competence_category_id=categories[slug],
                            priority=priority,
                            is_primary=priority == 1,
                        )
                    )
                else:
                    row.priority = priority
                    row.is_primary = priority == 1
                db.add(
                    Activity(
                        entity_type="user",
                        entity_id=user_id,
                        action="competence_category_assigned",
                        details={
                            "competence_category_id": categories[slug],
                            "priority": priority,
                            "source": "seed_competence_team_2026_09",
                        },
                    )
                )
                await db.flush()
        for user_id in EXCLUDED:
            print(
                f"{'zapis' if apply else 'na sucho'}: konto {user_id} → poza przydziałem"
            )
            if apply and not users[user_id].allocation_excluded:
                users[user_id].allocation_excluded = True
                db.add(
                    Activity(
                        entity_type="user",
                        entity_id=user_id,
                        action="allocation_excluded_changed",
                        details={
                            "excluded": True,
                            "source": "seed_competence_team_2026_09",
                        },
                    )
                )
        if apply:
            await db.commit()
        print(
            f"{'Zapisano' if apply else 'Do zapisu'}: {planned} przypisań, "
            f"{len(EXCLUDED)} kont poza przydziałem."
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
