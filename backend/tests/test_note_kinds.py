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


# Delivery Lead wymienia rekrutacje po cenie — wpis ma ponad 200 znaków przez
# same tytuły, a o kandydacie nie mówi nic.
_DL_RATE_LIST = (
    "Pokazujemy za 178zł na: Senior Backend Developer do zespołu płatności "
    "(40001) Programista Java w projekcie rozliczeń międzybankowych (40002) "
    "Ekspert integracji systemów kartowych w nowym programie (40003) "
    "@Anna Przykładowa @Jan Testowy"
)
# Ta sama forma, ale z opisem kandydata — zostaje czytelna dla modeli.
_DL_RATE_LIST_WITH_FACTS = (
    "Pokazujemy za 178zł na: Senior Backend Developer do zespołu płatności "
    "(40001) Programista Java w projekcie rozliczeń międzybankowych (40002). "
    "Kandydat pracował pięć lat w bankowości, zna Kafkę i Spring Boot, "
    "komercyjnie prowadził migrację do chmury."
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
        (_DL_RATE_LIST, note_kinds.DL_RATE),
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
    # Formularz zapisany przez scraper (systemowy) zostaje formularzem.
    assert (
        classify(
            "📋 Odpowiedzi z formularza aplikacji — Pracuj.pl, 25.09.2026",
            external_source=SYSTEM_NOTE_SOURCE,
        )
        == note_kinds.APPLICATION_FORM
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
        # Lista rekrutacji z opisem kandydata niesie fakty — nie jest samą ceną.
        _DL_RATE_LIST_WITH_FACTS,
        # Cena obok ustaleń z rozmowy (dostępność, tryb pracy) — notatka niesie
        # fakty, których rekruter i modele nie mogą stracić.
        "Wyślijmy za 160 zł/h. Kandydat dostępny od zaraz, wypowiedzenie 1 miesiąc, "
        "hybryda 2 dni w Warszawie, mieszka w Gdyni, chce 150 netto, rozmowa była "
        "dobra, jest zainteresowany projektem bankowym i chce zmienić branżę, bo "
        "obecna firma nie daje rozwoju.",
        "Rozmowa OK, jest zainteresowany projektem w bankowości, zdalnie, dostępny "
        "od 1.11, okres wypowiedzenia 2 tygodnie, stawka 150 zł/h. Pokażmy za 170 zł "
        "na: Senior Java Developer (40001), Java Developer (40002), Backend "
        "Engineer (40003) oraz Tech Lead (40004).",
        # Bardzo długi wpis zostaje zwykłą notatką, nawet bez słowa o kandydacie.
        _DL_RATE_LIST + " " + "Kolejna rekrutacja w tym samym programie (40004) " * 4,
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


def test_facts_reader_keeps_application_form_answers():
    # Oczekiwania i staż z formularza podał sam kandydat — odczyt faktów je czyta,
    # bramka must nie (formularz niesie tytuł ogłoszenia, nie umiejętności).
    assert note_kinds.APPLICATION_FORM not in note_kinds.FACTS_EXCLUDED_KINDS
    assert note_kinds.APPLICATION_FORM in note_kinds.AI_EXCLUDED_KINDS
    assert note_kinds.AUTOMATCH in note_kinds.FACTS_EXCLUDED_KINDS
    sql = note_kinds.facts_readable_sql()
    assert "kind = 'application_form'" in sql
    assert "'application_form'" not in sql.split(" OR ", 1)[1]


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


def test_every_kind_lands_in_exactly_one_history_tab():
    groups = {kind: note_kinds.group_of(kind) for kind in note_kinds.ALL_KINDS}
    assert set(groups.values()) == set(note_kinds.NOTE_GROUPS)
    assert groups[note_kinds.CONTACT_ATTEMPT] == note_kinds.GROUP_CONTACT
    assert groups[note_kinds.SCHEDULING] == note_kinds.GROUP_CONTACT
    assert groups[note_kinds.DL_RATE] == note_kinds.GROUP_DELIVERY
    assert groups[note_kinds.DL_REVIEW] == note_kinds.GROUP_DELIVERY
    assert groups[note_kinds.EMAIL] == note_kinds.GROUP_EMAIL
    assert groups[note_kinds.AUTOMATCH] == note_kinds.GROUP_AUTOMAT
    assert groups[note_kinds.APPLICATION_FORM] == note_kinds.GROUP_AUTOMAT
    # Karta, fakty ze screeningu i zwykła notatka to rozmowy.
    for kind in (note_kinds.CARD, note_kinds.SCREENING_FACTS, note_kinds.HUMAN):
        assert groups[kind] == note_kinds.GROUP_TALKS


def test_unclassified_note_is_a_talk_and_system_source_is_automat():
    # Nic nie wypada: wiersz bez rodzaju albo z nieznanym rodzajem to rozmowa.
    assert note_kinds.group_of(None) == note_kinds.GROUP_TALKS
    assert note_kinds.group_of("rodzaj-z-przyszlosci") == note_kinds.GROUP_TALKS
    assert (
        note_kinds.group_of(note_kinds.HUMAN, SYSTEM_NOTE_SOURCE)
        == note_kinds.GROUP_AUTOMAT
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


def test_dl_rate_list_examples_sit_between_the_two_limits():
    # Przykłady mają sprawdzać nowy limit, a nie stary: ponad 200, poniżej 400.
    for content in (_DL_RATE_LIST, _DL_RATE_LIST_WITH_FACTS):
        assert 200 < len(note_kinds.plain_text(content)) < 400


@pytest.mark.asyncio
async def test_reclassify_moves_long_price_notes_to_dl_rate_once():
    from app.services.note_kind_backfill import (
        DL_RATE_LISTS_MARKER,
        reclassify_dl_rate_lists,
    )

    cand_id = await _seed_candidate()
    insert = text(
        "INSERT INTO notes (candidate_id, content, note_type, kind, created_at, "
        "updated_at) VALUES (:c, :content, 'general', :kind, "
        "now() - interval '3 days', now() - interval '3 days') RETURNING id"
    )
    async with AsyncSessionLocal() as db:
        # Baza testowa jest wspólna — znacznik mógł zostać po innym biegu.
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :key"),
            {"key": DL_RATE_LISTS_MARKER},
        )
        price_id = (
            await db.execute(
                insert, {"c": cand_id, "content": _DL_RATE_LIST, "kind": "human"}
            )
        ).scalar_one()
        facts_id = (
            await db.execute(
                insert,
                {"c": cand_id, "content": _DL_RATE_LIST_WITH_FACTS, "kind": "human"},
            )
        ).scalar_one()
        await db.commit()
        before = await db.scalar(select(Note.updated_at).where(Note.id == price_id))

        changed = await reclassify_dl_rate_lists(db)
        await db.commit()
        assert changed is not None and changed >= 1

        rows = {
            row.id: row
            for row in (
                await db.execute(
                    select(Note.id, Note.kind, Note.updated_at).where(
                        Note.id.in_([price_id, facts_id])
                    )
                )
            ).all()
        }
        receipt = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": DL_RATE_LISTS_MARKER},
        )
        # Drugi przebieg nic nie robi — znacznik już jest.
        assert await reclassify_dl_rate_lists(db) is None

    assert rows[price_id].kind == note_kinds.DL_RATE
    assert rows[price_id].updated_at == before
    assert rows[facts_id].kind == "human"
    # Paragon wystarcza do odwrócenia i nie niesie treści notatek.
    assert price_id in receipt["previous_kind"]["human"]
    assert facts_id not in receipt["previous_kind"]["human"]
    assert "178" not in str(receipt)


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


@pytest.mark.asyncio
async def test_list_carries_the_history_tab_of_each_note_and_counts_per_tab(
    app_client: AsyncClient,
):
    cand_id = await _seed_candidate()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    for content in (
        "Szuka projektu z Javą 21, nie chce samego utrzymania.",
        "nie odbiera",
        "Stawka 135 zł/h, dostępność 1 miesiąc, tryb pracy hybrydowo.",
    ):
        created = await app_client.post(
            "/api/notes",
            headers=headers,
            json={"content": content, "candidate_id": cand_id},
        )
        assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content="Auto-match 71/100",
                note_type=NoteType.general,
                candidate_id=cand_id,
                external_source=SYSTEM_NOTE_SOURCE,
            )
        )
        await db.commit()

    # `limit` nie zmienia liczników — liczy je baza dla całego zakresu.
    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id, "limit": 1}, headers=headers
    )

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body["items"]) == 1
    assert body["group_counts"] == {
        "talks": 2,
        "contact": 1,
        "delivery": 0,
        "email": 0,
        "automat": 1,
    }
    full = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=headers
    )
    assert sorted(item["group"] for item in full.json()["items"]) == [
        "automat",
        "contact",
        "talks",
        "talks",
    ]


@pytest.mark.asyncio
async def test_no_answer_click_saves_a_contact_attempt_and_other_kinds_are_refused(
    app_client: AsyncClient,
):
    cand_id = await _seed_candidate()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    # Treść, której reguła nie uznałaby za próbę kontaktu — rodzaj podany wprost.
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": "Telefon o 14:10, bez skutku.",
            "candidate_id": cand_id,
            "kind": "contact_attempt",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == note_kinds.CONTACT_ATTEMPT
    assert created.json()["note_type"] == NoteType.general.value

    # Rodzaju zakrywającego treść (stawka do klienta) ani uwagi DL nie da się
    # nadać z przeglądarki.
    for kind in ("dl_rate", "dl_review", "automatch"):
        refused = await app_client.post(
            "/api/notes",
            headers=headers,
            json={"content": "Notatka", "candidate_id": cand_id, "kind": kind},
        )
        assert refused.status_code == 422, kind

    # Odpowiedź w wątku nie przyjmuje rodzaju z żądania.
    reply = await app_client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": "Dopisek do rozmowy, kandydat zna Javę.",
            "parent_note_id": created.json()["id"],
            "kind": "contact_attempt",
        },
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["kind"] != note_kinds.CONTACT_ATTEMPT
