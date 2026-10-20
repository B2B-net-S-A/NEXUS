"""Korekta 0436 „imię bez dopisków” WYKONANA na bazie testowej (D6, 13.10.2026).

Literówka w SQL-u wyszłaby dopiero na produkcji, a faza startu połknęłaby ją
(``|| echo skipped``). Baza testowa jest współdzielona, więc korekta biegnie
z własnym znacznikiem i zawężona do własnych wierszy (``only_ids``); osoby
są wymyślone (repo jest publiczne).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.index_outbox import IndexOutboxEvent
from app.services.candidate_name_marker_repair import (
    apply_name_marker_repair,
    run_candidate_name_marker_repair,
)


def _keys() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"9436_name_markers_{suffix}", f"repair_details_test_{suffix}"


async def _seed() -> dict[str, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        locked = Candidate(
            name="[ACTIVE] Zbigniew",
            lastname=f"Testowy{suffix}",
            external_source="traffit",
            external_id=f"name-marker-{suffix}",
            custom_fields={
                "_nexus_identity": {
                    "name_manual": True,
                    "name_set_at": "2026-08-20T10:00:00+00:00",
                    "name_ownership_reason": "bootstrap_mismatch",
                    "traffit_name": "Zbigniew",
                    "traffit_lastname": f"Testowy{suffix}",
                }
            },
            cv_extracted_data={"traffit_Position": "Developer"},
        )
        blacklisted = Candidate(
            name="Anna",
            lastname=f"Testowa{suffix} (czarna lista)",
            cv_extracted_data=["legacy", "list"],
        )
        manual_status = Candidate(
            name="[BLACKLIST] Piotr",
            lastname=f"Ręczny{suffix}",
            custom_fields={"_nexus_identity": {"status_manual": True}},
        )
        accepted = Candidate(
            name="Marek",
            lastname=f"Nowak{suffix} (zaakceptowany)",
            cv_extracted_data={"traffit_name_marker": "[akcept]"},
        )
        second_surname = Candidate(name="Ewa (Kowalska)", lastname=f"Test{suffix}")
        db.add_all([locked, blacklisted, manual_status, accepted, second_surname])
        await db.commit()
        return {
            "suffix": suffix,
            "locked": locked.id,
            "blacklisted": blacklisted.id,
            "manual_status": manual_status.id,
            "accepted": accepted.id,
            "second_surname": second_surname.id,
        }


def _ids(seed: dict) -> list[int]:
    return [value for key, value in seed.items() if key != "suffix"]


async def _drop(seed: dict, *keys: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(IndexOutboxEvent).where(
                IndexOutboxEvent.entity_type == "candidate",
                IndexOutboxEvent.entity_id.in_(_ids(seed)),
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(_ids(seed))))
        await db.execute(delete(AppSetting).where(AppSetting.key.in_(keys)))
        await db.commit()


async def _outbox_ids(ids: list[int]) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(IndexOutboxEvent.entity_id).where(
                IndexOutboxEvent.entity_type == "candidate",
                IndexOutboxEvent.entity_id.in_(ids),
            )
        )
        return set(rows.all())


async def test_repair_moves_meaning_to_fields_and_strips_names():
    seed = await _seed()
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_candidate_name_marker_repair(
                db, marker=marker, details_key=details_key, only_ids=_ids(seed)
            )
            await db.commit()
        assert summary is not None
        assert summary["changed"] == 4, summary
        assert summary["reindex_recorded"] is True
        assert summary["name_lock_cleared_ids"] == [seed["locked"]]
        assert summary["blacklisted_candidate_ids"] == [seed["blacklisted"]]
        assert summary["blacklist_kept_manual_status_ids"] == [seed["manual_status"]]
        assert summary["actively_looking_candidate_ids"] == [seed["locked"]]

        async with AsyncSessionLocal() as db:
            locked = await db.get(Candidate, seed["locked"])
            assert locked.name == "Zbigniew"
            assert locked.availability_status == AvailabilityStatus.actively_looking
            identity = locked.custom_fields["_nexus_identity"]
            assert "name_manual" not in identity
            assert "name_set_at" not in identity
            assert identity["traffit_name"] == "Zbigniew"
            assert locked.cv_extracted_data["traffit_name_marker"] == "[ACTIVE]"
            assert locked.cv_extracted_data["traffit_Position"] == "Developer"

            blacklisted = await db.get(Candidate, seed["blacklisted"])
            assert blacklisted.lastname == f"Testowa{seed['suffix']}"
            assert blacklisted.status == CandidateStatus.blacklisted
            # Tablica w `cv_extracted_data` zostaje — prowieniencja tylko w obiekcie.
            assert blacklisted.cv_extracted_data == ["legacy", "list"]

            manual = await db.get(Candidate, seed["manual_status"])
            assert manual.name == "Piotr"
            assert manual.status == CandidateStatus.active

            accepted = await db.get(Candidate, seed["accepted"])
            assert accepted.lastname == f"Nowak{seed['suffix']}"
            assert accepted.status == CandidateStatus.active
            assert accepted.availability_status == AvailabilityStatus.unknown
            assert (
                accepted.cv_extracted_data["traffit_name_marker"]
                == "[akcept] (zaakceptowany)"
            )

            untouched = await db.get(Candidate, seed["second_surname"])
            assert untouched.name == "Ewa (Kowalska)"

            receipt = await db.get(AppSetting, marker)
            assert "Zbigniew" not in json.dumps(receipt.value, ensure_ascii=False)
            details = await db.get(AppSetting, details_key)
            assert details.value[str(seed["locked"])]["name"] == "[ACTIVE] Zbigniew"

        assert await _outbox_ids(_ids(seed)) == set(summary["changed_candidate_ids"])

        async with AsyncSessionLocal() as db:
            again = await run_candidate_name_marker_repair(
                db, marker=marker, details_key=details_key, only_ids=_ids(seed)
            )
        assert again is None, "drugi start nie może niczego powtórzyć"
    finally:
        await _drop(seed, marker, details_key)


async def test_migration_run_gets_its_index_queue_at_the_next_start():
    """Migracja (synchroniczna) nie zapisuje kolejki indeksu — robi to faza startu."""
    seed = await _seed()
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await db.run_sync(
                lambda session: apply_name_marker_repair(
                    session.connection(),
                    marker=marker,
                    details_key=details_key,
                    only_ids=_ids(seed),
                )
            )
            await db.commit()
        assert summary["reindex_recorded"] is False
        assert await _outbox_ids(_ids(seed)) == set()

        async with AsyncSessionLocal() as db:
            completed = await run_candidate_name_marker_repair(
                db, marker=marker, details_key=details_key, only_ids=_ids(seed)
            )
            await db.commit()
        assert completed is not None
        assert completed["reindex_recorded"] is True
        assert await _outbox_ids(_ids(seed)) == set(summary["changed_candidate_ids"])

        async with AsyncSessionLocal() as db:
            assert (
                await run_candidate_name_marker_repair(
                    db, marker=marker, details_key=details_key, only_ids=_ids(seed)
                )
                is None
            )
    finally:
        await _drop(seed, marker, details_key)


async def test_prefilter_sql_runs_on_postgres_with_the_python_pattern():
    """Wzorzec wstępnego filtra jest poprawnym wyrażeniem Postgresa."""
    from app.services.candidate_name_marker_repair import PREFILTER_PATTERN

    async with AsyncSessionLocal() as db:
        hits = (
            await db.execute(
                text(
                    "SELECT v FROM unnest(CAST(:values AS text[])) AS v "
                    "WHERE v ~* CAST(:pattern AS text)"
                ),
                {
                    "values": [
                        "[ACTIVE] Jan",
                        "Anna (Kowalska)",
                        "Jan",
                        "ACTIVE Jan",
                        "Nowak / x",
                        "Kowalski zatrudniony",
                        "Łukasz",
                        "{ } Witold",
                        "Skowron \u2601\ufe0f",
                        "?\u200d? Grzegorz",
                        "Żaneta",
                    ],
                    "pattern": PREFILTER_PATTERN,
                },
            )
        ).scalars()
        # Nadzbiór: drugie nazwisko też przechodzi filtr — decyduje Python.
        assert set(hits) == {
            "[ACTIVE] Jan",
            "Anna (Kowalska)",
            "ACTIVE Jan",
            "Nowak / x",
            "Kowalski zatrudniony",
            # 0481: klamry i znaki spoza alfabetów łacińskich (zakres
            # `\u0001-\u024f` musi działać tak samo w Postgresie).
            "{ } Witold",
            "Skowron \u2601\ufe0f",
            "?\u200d? Grzegorz",
        }


async def test_round_0481_fixes_split_fields_first_then_strips_the_rest():
    """Ręczne poprawki 0481 biegną przed regułą; obca osoba pod ID zostaje."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        emoji_name = Candidate(name="\u2601", lastname=f"Szczepan Żuk{suffix} \u2601")
        cut_title = Candidate(name=f"Jakub Kępiński{suffix} (Solution", lastname="Architect)")
        braces = Candidate(name="{ } Witold", lastname=f"Testowy{suffix}")
        ordinary = Candidate(name="Ewa", lastname=f"Zwykła{suffix}")
        db.add_all([emoji_name, cut_title, braces, ordinary])
        await db.commit()
        seed = {
            "suffix": suffix,
            "emoji_name": emoji_name.id,
            "cut_title": cut_title.id,
            "braces": braces.id,
            "ordinary": ordinary.id,
        }
    marker, details_key = _keys()
    manual = {
        seed["emoji_name"]: "split_from_lastname",
        seed["cut_title"]: "split_from_name",
        # Kształt się nie zgadza (zwykłe imię) — nic się nie dzieje.
        seed["ordinary"]: "split_from_lastname",
    }
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_candidate_name_marker_repair(
                db,
                marker=marker,
                details_key=details_key,
                only_ids=_ids(seed),
                manual_fixes=manual,
            )
            await db.commit()
        assert summary["manual_fixed_ids"] == sorted(
            [seed["emoji_name"], seed["cut_title"]]
        )
        assert summary["changed_candidate_ids"] == sorted(
            [seed["emoji_name"], seed["cut_title"], seed["braces"]]
        )
        async with AsyncSessionLocal() as db:
            first = await db.get(Candidate, seed["emoji_name"])
            assert (first.name, first.lastname) == ("Szczepan", f"Żuk{suffix}")
            second = await db.get(Candidate, seed["cut_title"])
            assert (second.name, second.lastname) == ("Jakub", f"Kępiński{suffix}")
            third = await db.get(Candidate, seed["braces"])
            assert third.name == "Witold"
            fourth = await db.get(Candidate, seed["ordinary"])
            assert (fourth.name, fourth.lastname) == ("Ewa", f"Zwykła{suffix}")
            details = (await db.get(AppSetting, details_key)).value
            # Stare wartości sprzed ręcznej poprawki, nie stan po niej.
            assert details[str(seed["emoji_name"])]["name"] == "\u2601"
            assert details[str(seed["cut_title"])]["lastname"] == "Architect)"
        assert await _outbox_ids(_ids(seed)) == set(summary["changed_candidate_ids"])
    finally:
        await _drop(seed, marker, details_key)
