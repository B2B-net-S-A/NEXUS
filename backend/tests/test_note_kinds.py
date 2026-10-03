"""Rodzaj notatki (0412): reguła, filtr dla AI i wyszukiwania, zakryta stawka.

Pomiar 03.10.2026 na produkcji (75 231 notatek): żaden czytelnik nie
odróżniał wpisu automatu od notatki z rozmowy. Testy bez bazy pilnują reguły
``note_kinds.classify`` (wszystkie przykłady są fikcyjne), testy z bazą —
tego, że rodzaj naprawdę steruje listą, bramką must i odczytem faktów.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.api.candidate_access import note_content_hidden
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.note import SYSTEM_NOTE_SOURCE, Note, NoteType
from app.models.note import _set_note_kind_on_insert
from app.models.user import User, UserRole
from app.services import note_kind_schema, note_kinds
from app.services.note_kinds import classify

_BACKEND = Path(__file__).resolve().parents[1]

_CARD = (
    "<p>Imię i nazwisko: Tomasz Wzorcowy</p><p>Stawka: 135</p>"
    "<p>Dostępność: 1 miesiąc</p><p>Tryb pracy: hybrydowo, 2 dni w Łodzi</p>"
    "<p>P1: Opisz doświadczenie z Javą.</p><p>Odpowiedź: Java 21.</p>"
)


# ── bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "Źródło: Pracuj.pl — oferta: Java Developer\nAuto-match score: 67/100",
            note_kinds.AUTOMATCH,
        ),
        (
            "📋 Odpowiedzi z formularza aplikacji — Pracuj.pl, 25.09.2026 "
            "Oferta: Tester Manualny Oczekiwania finansowe netto: 10 000 zł",
            note_kinds.APPLICATION_FORM,
        ),
        (_CARD, note_kinds.CARD),
        (
            "Stawka: 105 PLN. Dostępność: ASAP. Motywacja: chce wrócić do "
            "bankowości. Pytanie 1: integracje? REST i Kafka.",
            note_kinds.CARD,
        ),
        (
            "Pytanie 1: z jaką wersją Angulara pracowałeś? Odpowiedź: 19",
            note_kinds.CARD,
        ),
        ("Wyślijmy za 161 zł/h @Anna Przykładowa", note_kinds.DL_RATE),
        (
            "Pokazujemy za 178zł na: Senior Java Developer (42146) @Jan Testowy",
            note_kinds.DL_RATE,
        ),
        ("150/110", note_kinds.DL_RATE),
        ("110/70 @Anna Przykładowa", note_kinds.DL_RATE),
        ("@Anna Przykładowa 175", note_kinds.DL_RATE),
        (
            "Stawka: 130 zł/h Dostępność: od zaraz Lokalizacja: Kraków",
            note_kinds.SCREENING_FACTS,
        ),
        ("dostępność od 1.08, chce 120zł/h", note_kinds.SCREENING_FACTS),
        ("@Jan Testowy @Anna Przykładowa Przepuszczam", note_kinds.DL_REVIEW),
        (
            "@Anna Przykładowa Brak tasków z Robota. Dopisz proszę, jeżeli to prawda.",
            note_kinds.DL_REVIEW,
        ),
        ("nie odbiera", note_kinds.CONTACT_ATTEMPT),
        ("Nie odbiera&nbsp;", note_kinds.CONTACT_ATTEMPT),
        ("nadal nie odbiera", note_kinds.CONTACT_ATTEMPT),
        ("no", note_kinds.CONTACT_ATTEMPT),
        ("poszedł mail", note_kinds.CONTACT_ATTEMPT),
        (
            "Interview: 14.04.2026 ;14:00 - 15:00 Prep: 14.04.2026; 10.00",
            note_kinds.SCHEDULING,
        ),
        ("@Anna Przykładowa", note_kinds.MENTION),
        ("już @Jan Testowy", note_kinds.MENTION),
        ("$$user_12$$", note_kinds.MENTION),
        ("Nie szuka pracy, ma coś fajnego i stabilnego.", note_kinds.STATUS),
        ("tylko zdalnie", note_kinds.STATUS),
        ("Brak doświadczenia w IT.", note_kinds.REJECTION),
        (
            "Zgodził się na 5 pln podwyżki na godzinę, przygotujemy aneks.",
            note_kinds.CONTRACTOR,
        ),
        (
            "Bardzo konkretny w rozmowie. Ostatnie trzy lata w bankowości, "
            "mikroserwisy na Spring Boot.",
            note_kinds.HUMAN,
        ),
    ],
)
def test_classify_recognises_each_kind(content: str, expected: str):
    assert classify(content, note_type="general") == expected


def test_system_source_and_prep_summary_win_over_content():
    assert (
        classify("Stawka 100, dostępność ASAP", external_source=SYSTEM_NOTE_SOURCE)
        == note_kinds.AUTOMATCH
    )
    assert (
        classify("Podsumowanie prepu", external_source=note_kinds.PREP_SOURCE)
        == note_kinds.PREP_SUMMARY
    )


def test_only_real_mail_threads_are_email():
    thread = (
        "Podpisane dokumenty w załącznikach. Pozdrawiam, Jan. "
        "czw., 28 gru 2023 o 09:41 Anna napisał(a): Dziękuję za dane."
    )
    assert classify(thread, note_type="email") == note_kinds.EMAIL
    assert classify("x" * 1600, note_type="email") == note_kinds.EMAIL
    # Krótka odpowiedź na notatkę, którą import oznaczał jako mail, to nie wątek.
    assert (
        classify("chmurę ma na Azure, ML się nie zajmował", note_type="email")
        == note_kinds.HUMAN
    )


@pytest.mark.parametrize(
    "content",
    [
        # „za 14 dni” to termin, nie stawka.
        "wysłany mail, oddzwoni za 14 dni",
        # Dłuższa notatka z faktami o kandydacie zostaje czytelna dla AI.
        "Wysłana za 85 zł/h. Chce iść w kierunku automatyzacji testów, ma za sobą "
        "trzy lata w projekcie bankowym, zna Selenium i Playwright, okres "
        "wypowiedzenia może skrócić z miesiąca do dwóch tygodni, mieszka w Gdyni.",
    ],
)
def test_client_rate_rule_does_not_swallow_ordinary_notes(content: str):
    assert classify(content, note_type="general") != note_kinds.DL_RATE


@pytest.mark.parametrize(
    "content",
    [
        # Wersja technologii to nie godzina.
        "Rozmowa: zna Pythona 3.11, FastAPI, Postgres",
        "Rozmowa o 12.30: zna Java",
        # „poprawnie” to nie „popraw”.
        "Zna Pythona, poprawnie pisze testy w pytest.",
        "Dobry angielski, mówi poprawnie, zna Kafkę",
        # Rekruter podaje cenę razem z faktami o kandydacie.
        "Wysłałam CV do klienta za 120 zł/h, kandydat zna Java 17, Spring, AWS",
        "nie odbiera, ale wiem, że zna Kotlina",
    ],
)
def test_note_about_the_candidate_is_never_treated_as_noise(content: str):
    assert classify(content, note_type="general") not in note_kinds.AI_EXCLUDED_KINDS


def test_contact_attempt_with_a_number_stays_a_note():
    # „nie odbiera, ale stawkę ma 200” niesie fakt — model ma to przeczytać.
    kind = classify("nie odbiera, ale stawkę ma 200 i tak", note_type="general")
    assert kind not in note_kinds.AI_EXCLUDED_KINDS


def test_every_kind_is_declared_and_fits_the_column():
    assert note_kinds.AI_EXCLUDED_KINDS <= set(note_kinds.ALL_KINDS)
    assert note_kinds.SEARCH_EXCLUDED_KINDS <= note_kinds.AI_EXCLUDED_KINDS
    assert note_kinds.AUTOMAT_KINDS <= note_kinds.SEARCH_EXCLUDED_KINDS
    # Zakryta kwota nie może wyjść samym trafieniem wyszukiwania.
    assert note_kinds.CLIENT_RATE_KINDS <= note_kinds.SEARCH_EXCLUDED_KINDS
    assert note_kinds.CLIENT_RATE_KINDS <= note_kinds.AI_EXCLUDED_KINDS
    assert set(note_kinds.AI_PRIORITY_KINDS).isdisjoint(note_kinds.AI_EXCLUDED_KINDS)
    assert all(len(kind) <= 24 for kind in note_kinds.ALL_KINDS)


def test_sql_filters_keep_unclassified_rows_and_drop_automat():
    ai = note_kinds.ai_readable_sql("n")
    assert "n.kind IS NULL" in ai
    assert "n.external_source IS DISTINCT FROM 'system'" in ai
    for kind in note_kinds.AI_EXCLUDED_KINDS:
        assert f"'{kind}'" in ai
    search = note_kinds.searchable_sql()
    assert "'automatch'" in search and "'application_form'" in search
    # Wyszukiwanie nie chowa maili ani wpisów Delivery Leada.
    assert "'email'" not in search and "'dl_review'" not in search


def test_model_listener_sets_the_kind_before_insert():
    note = Note(content="nie odbiera", note_type=NoteType.general)
    _set_note_kind_on_insert(None, None, note)
    assert note.kind == note_kinds.CONTACT_ATTEMPT


def test_entrypoint_mirrors_the_migration_sql():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for stmt in (*note_kind_schema.COLUMN_DDL, note_kind_schema.REPLY_RETYPE):
        assert stmt in entrypoint, stmt


def test_reply_retype_is_one_off_and_keeps_updated_at():
    sql = note_kind_schema.REPLY_RETYPE
    assert note_kind_schema.REPLY_RETYPE_MARKER in sql
    assert "a.action = 'traffit:Reply'" in sql
    # Odcisk nocnego odczytu faktów stoi na `updated_at` — zmiana typu go nie rusza.
    assert "updated_at" not in sql


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id, email=f"u{user_id}@example.com", role=role, roles=[role.value]
    )


def test_client_rate_note_is_hidden_from_recruiter_but_not_from_its_author():
    recruiter = _user(UserRole.recruiter, 1)
    lead = _user(UserRole.delivery_lead, 2)
    assert note_content_hidden(recruiter, kind=note_kinds.DL_RATE, author_id=2)
    assert not note_content_hidden(lead, kind=note_kinds.DL_RATE, author_id=2)
    assert not note_content_hidden(recruiter, kind=note_kinds.DL_RATE, author_id=1)
    assert not note_content_hidden(recruiter, kind=note_kinds.HUMAN, author_id=2)
    assert not note_content_hidden(recruiter, kind=None, author_id=2)


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"kind-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Kind"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Kind {role.value} {unique}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(name=f"Kind{unique}", lastname="Test", email=f"{unique}@x.com")
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_recruiter_sees_a_placeholder_instead_of_the_client_rate(
    app_client: AsyncClient,
):
    cand_id = await _seed_candidate()
    _, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    lead = await _login(app_client, dl_email, dl_pass)
    created = await app_client.post(
        "/api/notes",
        headers=lead,
        json={"content": "Wyślijmy za 161 zł/h", "candidate_id": cand_id},
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]
    assert created.json()["kind"] == note_kinds.DL_RATE
    # Autor widzi własną notatkę.
    assert created.json()["content"] == "Wyślijmy za 161 zł/h"

    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    recruiter = await _login(app_client, r_email, r_pass)
    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=recruiter
    )
    item = listed.json()["items"][0]
    assert item["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert item["content_rendered"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert item["content_hidden"] is True
    assert "161" not in listed.text

    single = await app_client.get(f"/api/notes/{note_id}", headers=recruiter)
    assert single.json()["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER

    timeline = await app_client.get(
        f"/api/candidates/{cand_id}/timeline", headers=recruiter
    )
    if timeline.status_code == 200:
        assert "161" not in timeline.text

    for_lead = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=lead
    )
    assert for_lead.json()["items"][0]["content"] == "Wyślijmy za 161 zł/h"


@pytest.mark.asyncio
async def test_backfill_classifies_raw_sql_rows_without_touching_updated_at():
    from app.services.note_kind_backfill import classify_notes

    cand_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        note_id = (
            await db.execute(
                text(
                    "INSERT INTO notes (candidate_id, content, note_type, "
                    "created_at, updated_at) VALUES (:c, 'nie odbiera', 'general', "
                    "now() - interval '3 days', now() - interval '3 days') "
                    "RETURNING id"
                ),
                {"c": cand_id},
            )
        ).scalar_one()
        await db.commit()
        before = await db.scalar(select(Note.updated_at).where(Note.id == note_id))
        assert await classify_notes(db, [note_id]) == 1
        await db.commit()
        row = (
            await db.execute(
                select(Note.kind, Note.updated_at).where(Note.id == note_id)
            )
        ).one()
    assert row.kind == note_kinds.CONTACT_ATTEMPT
    assert row.updated_at == before


@pytest.mark.asyncio
async def test_must_evidence_ignores_the_automat_note():
    from app.services.must_text_evidence import _load_notes

    automat = await _seed_candidate()
    human = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Note(
                    content="Źródło: Pracuj.pl — oferta: Kotlin Developer\n"
                    "Auto-match score: 70/100\nMust-have trafione: kotlin",
                    candidate_id=automat,
                    external_source=SYSTEM_NOTE_SOURCE,
                ),
                Note(
                    content="W rozmowie potwierdził trzy lata komercyjnie w Kotlin.",
                    candidate_id=human,
                ),
            ]
        )
        await db.commit()
        has_notes, texts = await _load_notes(db, [automat, human], r"\mkotlin\M")
    assert human in has_notes and automat not in has_notes
    assert human in texts and automat not in texts


@pytest.mark.asyncio
async def test_insights_reader_takes_the_card_first_and_skips_noise():
    from app.services.notes_insights_extractor import NOTES_LIMIT, load_note_rows

    cand_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        db.add(Note(content=_CARD, candidate_id=cand_id))
        await db.flush()
        # Karta jest najstarsza: bez pierwszeństwa wypadłaby poza limit.
        await db.execute(
            text(
                "UPDATE notes SET created_at = now() - interval '400 days' "
                "WHERE candidate_id = :c"
            ),
            {"c": cand_id},
        )
        for index in range(NOTES_LIMIT + 2):
            db.add(
                Note(
                    content=f"Rozmowa numer {index}: opowiadał o projekcie w banku.",
                    candidate_id=cand_id,
                )
            )
        db.add(Note(content="nie odbiera", candidate_id=cand_id))
        db.add(Note(content="Wyślijmy za 161 zł/h", candidate_id=cand_id))
        await db.commit()
        rows = await load_note_rows(db, cand_id)
    contents = [row[3] for row in rows]
    assert len(rows) == NOTES_LIMIT
    assert _CARD in contents
    assert "nie odbiera" not in contents
    assert "Wyślijmy za 161 zł/h" not in contents
