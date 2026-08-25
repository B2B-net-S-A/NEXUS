"""Status handlowy wygenerowanej umowy B2B + wyszukiwarka listy.

Dwie rzeczy, których nie da się sprawdzić samą walidacją DTO i dlatego jadą
przez prawdziwą bazę:

1. Zamknięcie umowy **nie usuwa** wiersza i jest niezależne od statusu podpisu
   (podpisaną umowę też się wypowiada — inaczej cała funkcja byłaby martwa dla
   najczęstszego przypadku).
2. ``?q=`` filtruje po stronie serwera, więc znajduje umowy spoza pierwszej
   strony listy — filtrowanie w przeglądarce dawałoby fałszywe „brak wyników".
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.b2b_contract_generator import B2BGeneratedContractUpdate

PATH = "/api/b2b-generator/generated"


async def _admin_user_id(app_client) -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None, "app_client nie zaseedował admina"
    return uid


async def _seed(
    created_by: int,
    *,
    partner_name: str = "Jan Kowalski",
    client_name: str = "Nordea Bank",
    signature_status: str = "unsigned",
) -> tuple[int, str]:
    """Wstaw wiersz i zwróć ``(id, contract_number)``.

    ``seq`` z UUID → brak kolizji z UNIQUE(year, seq) przy powtórnym
    uruchomieniu testu na tej samej bazie."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name=partner_name,
            client_name=client_name,
            language="pl",
            created_by=created_by,
            signature_status=signature_status,
            render_payload={"language": "pl", "client_name": client_name},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id, row.contract_number


# ── DTO: lustro CHECK-a spójności ────────────────────────────────────────────


def test_update_dto_rejects_closed_without_reason_or_date():
    with pytest.raises(ValidationError, match="powód zakończenia umowy"):
        B2BGeneratedContractUpdate(contract_status="closed", closure_date="2026-08-01")
    with pytest.raises(ValidationError, match="Data zakończenia umowy"):
        B2BGeneratedContractUpdate(
            contract_status="closed", closure_reason="project_completed"
        )


def test_update_dto_rejects_suspended_without_reason_or_date():
    """Ten sam komplet reguł co dla „Zakończona", ale komunikat mówi o PROJEKCIE.

    Wspólny tekst kazałby użytkownikowi zgadywać, o którą datę pyta formularz —
    przy zawieszeniu kończy się projekt, umowa trwa dalej."""
    with pytest.raises(ValidationError, match="powód zakończenia projektu"):
        B2BGeneratedContractUpdate(
            contract_status="suspended", closure_date="2026-08-01"
        )
    with pytest.raises(ValidationError, match="Data zakończenia projektu"):
        B2BGeneratedContractUpdate(
            contract_status="suspended", closure_reason="no_client_budget"
        )


def test_update_dto_keeps_legacy_closure_reasons_readable():
    """Katalog sprzed 0226 zniknął z pickera, ale MUSI przejść walidację.

    Produkcja ma wiersze `closed` niosące te wartości; odrzucenie ich tutaj
    wywracałoby odczyt i edycję każdego takiego wpisu."""
    for legacy in ("resignation_before_signing", "termination", "mutual_agreement"):
        dto = B2BGeneratedContractUpdate(
            contract_status="closed",
            closure_reason=legacy,
            closure_date="2026-08-01",
        )
        assert dto.closure_reason == legacy


def test_update_dto_binds_job_id_to_reactivation():
    """`job_id` ma sens wyłącznie przy powrocie na „Aktywna".

    Jawny ``null`` też jest odrzucany: przywrócenie umowy do gry BEZ projektu
    jest dokładnie tym stanem, który opisuje „Zawieszona"."""
    with pytest.raises(ValidationError, match="wyłącznie razem ze statusem"):
        B2BGeneratedContractUpdate(
            contract_status="suspended",
            closure_reason="no_client_budget",
            closure_date="2026-08-01",
            job_id=7,
        )
    with pytest.raises(ValidationError, match="wyłącznie razem ze statusem"):
        B2BGeneratedContractUpdate(client_name="X", job_id=7)
    with pytest.raises(ValidationError, match="Wybierz projekt"):
        B2BGeneratedContractUpdate(contract_status="active", job_id=None)
    assert B2BGeneratedContractUpdate(contract_status="active", job_id=7).job_id == 7


def test_update_dto_requires_free_text_only_for_other():
    with pytest.raises(ValidationError, match="własny powód"):
        B2BGeneratedContractUpdate(
            contract_status="closed",
            closure_reason="other",
            closure_date="2026-08-01",
        )
    with pytest.raises(ValidationError, match="tylko dla powodu"):
        B2BGeneratedContractUpdate(
            contract_status="closed",
            closure_reason="termination",
            closure_reason_other="cokolwiek",
            closure_date="2026-08-01",
        )


def test_update_dto_rejects_explicit_null_status():
    """Jawny ``null`` != pominięcie pola.

    Bez tego null przechodziłby jako „brak zmiany statusu" i lądował w kolumnie
    NOT NULL → IntegrityError (500) zamiast 422."""
    with pytest.raises(ValidationError, match="nie może być pusty"):
        B2BGeneratedContractUpdate(contract_status=None)
    # Pominięcie pola nadal jest legalne (edycja samej nazwy Klienta).
    assert B2BGeneratedContractUpdate(client_name="X").contract_status is None


def test_update_dto_rejects_closure_fields_without_status():
    """Same pola zamknięcia bez statusu zostawiłyby wiersz w sprzeczności."""
    with pytest.raises(ValidationError, match="wyłącznie razem"):
        B2BGeneratedContractUpdate(closure_date="2026-08-01")


# ── API: zamknięcie i powrót do aktywnej ─────────────────────────────────────


async def test_orm_default_status_stays_active_for_directly_seeded_rows(
    app_client, app_auth_headers
):
    """Default kolumny zostaje „active" — to NIE jest status nowej umowy.

    Ten test seeduje wiersz przez ORM, więc mierzy default kolumny, a nie
    zachowanie generowania. Nową umowę oznacza `in_progress`, ustawiane JAWNIE
    w handlerze `/render` (patrz `test_generated_contract_starts_in_progress`).
    Default opisuje wiersz wstawiony BEZ decyzji o statusie: safety-net
    entrypointu, seed, surowy INSERT — zmiana defaultu na `in_progress`
    przepisałaby historię każdego takiego wiersza.
    """
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = next(x for x in resp.json() if x["id"] == rid)
    assert item["contract_status"] == "active"
    assert item["closure_reason"] is None
    assert item["closure_date"] is None
    assert item["can_change_status"] is True


async def test_in_progress_cannot_be_set_by_hand(app_client, app_auth_headers):
    """„W trakcie" to stan, PRZEZ który umowa przechodzi automatycznie.

    Odrzucenie żyje w walidatorze DTO, a nie w zawężonym typie pola, żeby
    komunikat był po polsku i wyjaśniał, skąd ten status się bierze.
    """
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "in_progress"},
    )
    assert resp.status_code == 422, resp.text
    assert "automatycznie" in resp.text

    # Status w bazie nie drgnął.
    listing = await app_client.get(
        PATH, headers=app_auth_headers, params={"limit": 200}
    )
    item = next(x for x in listing.json() if x["id"] == rid)
    assert item["contract_status"] == "active"


def test_dto_rejects_in_progress_with_a_polish_explanation():
    with pytest.raises(ValidationError, match="automatycznie"):
        B2BGeneratedContractUpdate(contract_status="in_progress")


async def test_closing_keeps_the_row_and_records_reason_and_date(
    app_client, app_auth_headers
):
    """Sedno zgłoszenia: „umowa pozostaje w systemie i nie jest usuwana"."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_status"] == "closed"
    assert body["closure_reason"] == "termination"
    assert body["closure_date"] == "2026-08-31"

    listing = await app_client.get(
        PATH, headers=app_auth_headers, params={"limit": 200}
    )
    assert listing.status_code == 200
    assert any(x["id"] == rid for x in listing.json()), "zamknięcie usunęło wiersz"


async def test_explicit_null_status_is_422_not_500(app_client, app_auth_headers):
    """Zepsuty payload ma dawać 422, nie 500 z IntegrityError."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": None},
    )
    assert resp.status_code == 422, resp.text


async def test_closing_other_stores_free_text(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "other",
            "closure_reason_other": "  Zmiana modelu współpracy  ",
            "closure_date": "2026-09-01",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["closure_reason_other"] == "Zmiana modelu współpracy"


async def test_reopening_clears_every_closure_field(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "mutual_agreement",
            "closure_date": "2026-08-31",
        },
    )
    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_status"] == "active"
    assert body["closure_reason"] is None
    assert body["closure_reason_other"] is None
    assert body["closure_date"] is None

    # Wyczyszczone pola muszą PRZEŻYĆ w dzienniku — inaczej powód i data
    # zamknięcia znikają z systemu bezpowrotnie. Ta asercja pilnuje właśnie
    # tego, że czyszczenie wyżej nie jest utratą danych.
    history = await app_client.get(
        f"{PATH}/{rid}/status-history", headers=app_auth_headers
    )
    assert history.status_code == 200, history.text
    events = history.json()
    assert [e["to_status"] for e in events] == ["closed", "active"]
    assert events[0]["reason"] == "mutual_agreement"
    assert events[0]["effective_date"] == "2026-08-31"
    # Zdarzenie powrotu przenosi to, co właśnie zniknęło z wiersza.
    assert events[1]["reason"] == "mutual_agreement"
    assert events[1]["effective_date"] == "2026-08-31"


async def test_signed_contract_can_still_be_closed(app_client, app_auth_headers):
    """Wypowiedzenie i porozumienie dotyczą umów PODPISANYCH.

    Blokada edycji po podpisaniu chroni treść dokumentu, nie jego bieg —
    gdyby obejmowała status, funkcja byłaby bezużyteczna tam, gdzie jest
    najbardziej potrzebna."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id, signature_status="signed_both")

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_status"] == "closed"

    # Treść dokumentu pozostaje zamrożona.
    blocked = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"client_name": "Inny Klient"},
    )
    assert blocked.status_code == 409


async def _other_legal_user_headers(app_client) -> tuple[int, dict[str, str]]:
    """Załóż innego użytkownika z dostępem do generatora (TAC) i zaloguj go.

    TAC mieści się w `ContractLegalAccess`, więc przechodzi bramkę routera —
    dzięki temu test sprawdza REGUŁĘ WŁASNOŚCI, a nie samą bramkę roli."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"pytest-tac-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Pytest TAC",
            role=UserRole.tac,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id

    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return uid, {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_any_generator_user_can_change_status(app_client, app_auth_headers):
    """Status zmienia KAŻDY, kto widzi wiersz — nie tylko autor wpisu.

    Reguła „autor albo admin" (sprzed 0226) była za wąska dla operacji, o którą
    tu chodzi: kontraktora na nowy projekt kieruje delivery, nie osoba, która
    kiedyś kliknęła „generuj". Przy tamtej regule przycisk „Zmień status" byłby
    niewidoczny dla większości zespołu i zakładka „Umowy bez projektu" nie
    miałaby jak działać. Zawężenie zostaje na `client_name` — patrz test niżej."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)
    _uid, other_headers = await _other_legal_user_headers(app_client)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=other_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "project_completed",
            "closure_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text

    listing = await app_client.get(
        PATH, headers=app_auth_headers, params={"limit": 200}
    )
    item = next(x for x in listing.json() if x["id"] == rid)
    assert item["contract_status"] == "closed"
    assert item["closure_reason"] == "project_completed"


async def test_foreign_user_cannot_edit_client_name(app_client, app_auth_headers):
    """Korekta TREŚCI dokumentu zostaje przy wąskiej bramce (autor albo admin).

    `client_name` synchronizuje `render_payload`, więc zmienia to, co wyjdzie
    z ponownego pobrania DOCX — inna klasa operacji niż status handlowy."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)
    _uid, other_headers = await _other_legal_user_headers(app_client)

    resp = await app_client.patch(
        f"{PATH}/{rid}", headers=other_headers, json={"client_name": "Podmieniony"}
    )
    assert resp.status_code == 403, resp.text

    listing = await app_client.get(
        PATH, headers=app_auth_headers, params={"limit": 200}
    )
    item = next(x for x in listing.json() if x["id"] == rid)
    assert item["client_name"] == "Nordea Bank"


async def test_authorization_precedes_business_rules(app_client, app_auth_headers):
    """403 leci PRZED 409 — kod odpowiedzi nie zdradza stanu podpisu cudzego
    wiersza, zanim ustalimy prawo do jego edycji.

    Pusty payload daje 422, nie 403, i to nie jest regresja: bramka roli
    (`B2BGeneratorAccess`) i client-scope przepuściły już tego użytkownika do
    ODCZYTU tego wiersza, a od 0226 wolno mu też zmienić jego status. „Nie
    przesłano żadnej zmiany" nie ujawnia więc niczego, czego nie widzi na
    liście. Zawężenie dotyczy wyłącznie `client_name` — i tam 403 nadal
    wyprzedza 409."""
    admin_id = await _admin_user_id(app_client)
    signed_id, _ = await _seed(admin_id, signature_status="signed_both")
    _uid, other_headers = await _other_legal_user_headers(app_client)

    empty = await app_client.patch(
        f"{PATH}/{signed_id}", headers=other_headers, json={}
    )
    assert empty.status_code == 422, empty.text

    # Edycja podpisanej: 403, nie 409 (które zdradzałoby stan podpisu).
    signed = await app_client.patch(
        f"{PATH}/{signed_id}", headers=other_headers, json={"client_name": "X"}
    )
    assert signed.status_code == 403, signed.text


async def test_status_filter_narrows_the_listing(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    active_id, _ = await _seed(admin_id)
    closed_id, _ = await _seed(admin_id)
    await app_client.patch(
        f"{PATH}/{closed_id}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "contract_status": "closed"},
    )
    assert resp.status_code == 200, resp.text
    ids = {x["id"] for x in resp.json()}
    assert closed_id in ids
    assert active_id not in ids


# ── API: wyszukiwarka ────────────────────────────────────────────────────────


async def test_search_by_contract_number(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, number = await _seed(admin_id)

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"q": number})
    assert resp.status_code == 200, resp.text
    assert [x["id"] for x in resp.json()] == [rid]


async def test_search_by_partner_full_name_is_case_insensitive(
    app_client, app_auth_headers
):
    admin_id = await _admin_user_id(app_client)
    surname = f"Nowakowski{uuid.uuid4().hex[:8]}"
    rid, _number = await _seed(admin_id, partner_name=f"Anna {surname}")

    resp = await app_client.get(
        PATH, headers=app_auth_headers, params={"q": surname.lower()}
    )
    assert resp.status_code == 200, resp.text
    assert [x["id"] for x in resp.json()] == [rid]


async def test_search_finds_row_by_linked_candidate_name(app_client, app_auth_headers):
    """Umowa jest na firmę Partnera, a szuka się po nazwisku kandydata.

    Bez OUTER JOIN-a na `candidates` ta umowa byłaby nie do znalezienia po
    człowieku, którego dotyczy — a to jest wprost treść zgłoszenia."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
        candidate = Candidate(name="Zofia", lastname=f"Wisniewska{tag}")
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

        seq = 100000 + (uuid.uuid4().int % 800000)
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="ZW Software Sp. z o.o.",  # celowo bez nazwiska
            client_name="Klient",
            language="pl",
            created_by=uid,
            candidate_id=candidate.id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        rid = row.id

    for phrase in (f"Wisniewska{tag}", f"Zofia Wisniewska{tag}"):
        resp = await app_client.get(
            PATH, headers=app_auth_headers, params={"q": phrase}
        )
        assert resp.status_code == 200, resp.text
        assert [x["id"] for x in resp.json()] == [rid], phrase


async def test_search_wildcards_are_escaped_not_executed(app_client, app_auth_headers):
    """`%` wpisany w szukajkę ma szukać znaku `%`, nie zwracać całej listy."""
    admin_id = await _admin_user_id(app_client)
    await _seed(admin_id, partner_name=f"Bez procenta {uuid.uuid4().hex[:8]}")

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"q": "%"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_search_misses_return_empty_not_everything(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    await _seed(admin_id)

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"q": f"nieistniejaca-fraza-{uuid.uuid4().hex}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ── Generowanie: `in_progress` + snapshot danych Partnera ────────────────────


async def _render_docx(app_client, app_auth_headers, **overrides) -> str:
    """Wygeneruj umowę przez PRAWDZIWY `/render` i zwróć jej numer.

    Numer podajemy jawnie (seq z UUID), bo to jedyny sposób odnalezienia
    świeżego wiersza bez ścigania się z innymi testami seedującymi tę tabelę —
    `max(id)` byłby wyścigiem, a `/render` zwraca plik, nie identyfikator.
    """
    seq = 300000 + (uuid.uuid4().int % 500000)
    number = f"{seq}/2026"
    payload = {
        "language": "pl",
        "contract_number": number,
        "partner_name": "Zofia Wiśniewska",
        "client_name": "Nordea Bank",
        "signing_date": "2026-08-01",
        **overrides,
    }
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        headers=app_auth_headers,
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return number


async def _item_by_number(app_client, app_auth_headers, number: str) -> dict:
    resp = await app_client.get(PATH, headers=app_auth_headers, params={"q": number})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1, rows
    return rows[0]


async def test_generated_contract_starts_in_progress(app_client, app_auth_headers):
    """Sedno zmiany: wygenerowanie dokumentu to nie jest „umowa Aktywna".

    Do 0224 rejestr twierdził „Aktywna" o umowie, która dopiero poszła do
    podpisu — bo status brał się z defaultu kolumny.
    """
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)

    assert item["contract_status"] == "in_progress"
    assert item["closure_reason"] is None
    assert item["closure_date"] is None


async def test_generation_snapshots_partner_company_data(app_client, app_auth_headers):
    """Nazwa firmy, NIP i data rozpoczęcia trafiają do KOLUMN, nie tylko do
    `render_payload` — inaczej lista nie może ich pokazać ani po nich filtrować."""
    number = await _render_docx(
        app_client,
        app_auth_headers,
        partner_legal_name="ZW Software Sp. z o.o.",
        partner_nip="123-456-32-18",
        start_date="2026-09-15",
    )
    item = await _item_by_number(app_client, app_auth_headers, number)

    # NIP kanonicznie w cyfrach; surowe formatowanie zostaje w payloadzie.
    assert item["partner_nip"] == "1234563218"
    assert item["start_date"] == "2026-09-15"
    # Spółka → nazwa firmy w pierwszej linii, osoba w drugiej.
    assert item["partner_display_name"] == "ZW Software Sp. z o.o."
    assert item["partner_secondary_line"] == "Zofia Wiśniewska"


async def test_generation_for_sole_trader_hides_the_second_line(
    app_client, app_auth_headers
):
    """JDG: nazwa działalności zawiera już właściciela, więc druga linia byłaby
    duplikacją. Snapshot z rejestru bije heurystykę po nazwie."""
    number = await _render_docx(
        app_client,
        app_auth_headers,
        partner_name="Jan Kowalski",
        partner_legal_name="Kowalski Consulting Sp. z o.o.",
        partner_entity_type="sole_trader",
    )
    item = await _item_by_number(app_client, app_auth_headers, number)

    assert item["partner_display_name"] == "Kowalski Consulting Sp. z o.o."
    assert item["partner_secondary_line"] is None


async def test_unknown_entity_type_degrades_instead_of_blocking_generation(
    app_client, app_auth_headers
):
    """Nieznana wartość podpowiedzi WYŚWIETLANIA nie może zablokować wygenerowania
    umowy — walidator degraduje ją do „brak sygnału", nie do 422."""
    number = await _render_docx(
        app_client,
        app_auth_headers,
        partner_legal_name="Alfa Sp. z o.o.",
        partner_entity_type="jdg",
    )
    item = await _item_by_number(app_client, app_auth_headers, number)
    # Brak sygnału → heurystyka po nazwie → spółka → druga linia jest.
    assert item["partner_secondary_line"] == "Zofia Wiśniewska"


async def test_in_progress_is_filterable(app_client, app_auth_headers):
    """Bez poszerzenia `pattern` w Query najliczniejsza kategoria zwracałaby 422."""
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "contract_status": "in_progress"},
    )
    assert resp.status_code == 200, resp.text
    assert item["id"] in {x["id"] for x in resp.json()}

    active_only = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "contract_status": "active"},
    )
    assert item["id"] not in {x["id"] for x in active_only.json()}


async def test_search_finds_a_row_by_company_name_and_by_nip(
    app_client, app_auth_headers
):
    """Kolumna „Partner" pokazuje nazwę firmy, więc wyszukiwarka musi ją znać —
    inaczej użytkownik nie znajduje tego, co widzi na liście. NIP szukany
    z kreskami trafia w kanoniczne cyfry."""
    tag = uuid.uuid4().hex[:10]
    number = await _render_docx(
        app_client,
        app_auth_headers,
        partner_legal_name=f"Wyszukiwalna {tag} Sp. z o.o.",
        partner_nip="987-654-32-10",
    )
    expected = (await _item_by_number(app_client, app_auth_headers, number))["id"]

    by_company = await app_client.get(PATH, headers=app_auth_headers, params={"q": tag})
    assert [x["id"] for x in by_company.json()] == [expected]

    by_nip = await app_client.get(
        PATH, headers=app_auth_headers, params={"q": "987-654-32-10"}
    )
    assert expected in {x["id"] for x in by_nip.json()}


# ── API: filtr zakresu daty rozpoczęcia ──────────────────────────────────────


async def test_start_date_range_filter_is_inclusive_on_both_ends(
    app_client, app_auth_headers
):
    number = await _render_docx(app_client, app_auth_headers, start_date="2026-09-15")
    rid = (await _item_by_number(app_client, app_auth_headers, number))["id"]

    for params in (
        {"start_from": "2026-09-15", "start_to": "2026-09-15"},  # ten sam dzień
        {"start_from": "2026-09-01", "start_to": "2026-09-30"},  # cały miesiąc
        {"start_from": "2026-09-15"},  # tylko dolna granica
        {"start_to": "2026-09-15"},  # tylko górna granica
    ):
        resp = await app_client.get(
            PATH, headers=app_auth_headers, params={"limit": 200, **params}
        )
        assert resp.status_code == 200, resp.text
        assert rid in {x["id"] for x in resp.json()}, params

    outside = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "start_from": "2026-09-16"},
    )
    assert rid not in {x["id"] for x in outside.json()}


async def test_rows_without_start_date_fall_outside_every_range(
    app_client, app_auth_headers
):
    """Nieznana data rozpoczęcia nie mieści się w żadnym przedziale — wiersze
    historyczne (bez payloadu) wypadają z filtra, i to jest poprawne."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "start_from": "1900-01-01", "start_to": "2999-12-31"},
    )
    assert resp.status_code == 200, resp.text
    assert rid not in {x["id"] for x in resp.json()}


async def test_reversed_start_date_range_is_an_error_not_an_empty_list(
    app_client, app_auth_headers
):
    """Pusta lista czytałaby się jako „nie ma takich umów", a cicha zamiana
    granic sprawiłaby, że filtr działa inaczej, niż napisano w URL-u."""
    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"start_from": "2026-09-30", "start_to": "2026-09-01"},
    )
    assert resp.status_code == 422, resp.text


async def test_date_filter_combines_with_search_and_status(
    app_client, app_auth_headers
):
    """Trzy filtry muszą działać koniunkcyjnie — każdy dokłada własne WHERE."""
    tag = uuid.uuid4().hex[:10]
    number = await _render_docx(
        app_client,
        app_auth_headers,
        partner_legal_name=f"Koniunkcja {tag}",
        start_date="2026-10-05",
    )
    rid = (await _item_by_number(app_client, app_auth_headers, number))["id"]

    hit = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={
            "q": tag,
            "contract_status": "in_progress",
            "start_from": "2026-10-01",
            "start_to": "2026-10-31",
        },
    )
    assert [x["id"] for x in hit.json()] == [rid]

    # Ten sam wiersz, ale zakres dat obok — koniunkcja musi go odrzucić.
    miss = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={
            "q": tag,
            "contract_status": "in_progress",
            "start_from": "2026-11-01",
        },
    )
    assert miss.json() == []


# ── Cykl życia: Aktywna → Zawieszona → Aktywna (z projektem) → Zakończona ────


async def _seed_linked_contract(client_name: str = "Nordea Bank") -> tuple[int, int]:
    """Kontraktor + kontrakt w module Kontrakty. Zwraca ``(contract_id, client_id)``.

    Zawieszona umowa wraca do gry dopiero, gdy ma się gdzie zapisać notatka
    o poprzednim projekcie — bez tego wiersza ścieżka kończy się 409."""
    from datetime import date as _date

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Zawieszony",
            lastname=f"K-{uuid.uuid4().hex[:6]}",
            email=f"zaw-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=client_name)
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_date(2026, 1, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id, client.id


async def _seed_job(client_id: int, title: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = Job(title=title, client_id=client_id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_second_project(contract_id: int, client_name: str) -> tuple[int, int]:
    """Drugi projekt TEJ SAMEJ osoby u innego klienta: ``(contract_id, client_id)``.

    Projekt to OSOBNY wiersz ``Contract``, więc reaktywacja na nowy projekt ma
    dokąd przepiąć link — bez tego wiersza sprawdzalibyśmy tylko, że nic się
    nie stało."""
    from datetime import date as _date

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        candidate_id = await db.scalar(
            select(Contract.candidate_id).where(Contract.id == contract_id)
        )
        client = Client(name=client_name)
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contract = Contract(
            candidate_id=candidate_id,
            client_id=client.id,
            # Szkic, bo Flow B zakłada kontraktora bez `contract_type`/
            # `work_mode` — tak wygląda nowy projekt w chwili reaktywacji.
            status=ContractStatus.draft,
            start_date=_date(2026, 8, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id, client.id


async def _link(generated_id: int, *, contract_id: int | None) -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == generated_id)
            .values(contract_id=contract_id)
        )
        await db.commit()


async def _suspend(app_client, headers, rid: int, *, date: str = "2026-08-01"):
    return await app_client.patch(
        f"{PATH}/{rid}",
        headers=headers,
        json={
            "contract_status": "suspended",
            "closure_reason": "no_client_budget",
            "closure_date": date,
        },
    )


async def test_suspend_requires_active_source_status(app_client, app_auth_headers):
    """`in_progress → suspended` to ślepy zaułek, więc jest zablokowany.

    Powrót na „Aktywna" wymaga powiązanego kontraktu, a ten powstaje dopiero
    przy potwierdzeniu podpisu — umowa przed podpisem utknęłaby w zakładce
    „Umowy bez projektu" z jedynym wyjściem przez zamknięcie."""
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    await _link(rid, contract_id=None)

    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == rid)
            .values(contract_status="in_progress")
        )
        await db.commit()

    resp = await _suspend(app_client, app_auth_headers, rid)
    assert resp.status_code == 422, resp.text
    assert "tylko umowę aktywną" in resp.json()["detail"]


async def test_suspended_row_leaves_active_tab(app_client, app_auth_headers):
    """Wiersz zawieszony znika z zakładki „Umowy aktywne i w trakcie podpisu"
    i pojawia się w „Umowy bez projektu" — filtr wielu statusów to rozstrzyga."""
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)

    assert (await _suspend(app_client, app_auth_headers, rid)).status_code == 200

    active_tab = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params=[("contract_status", "active"), ("contract_status", "in_progress")],
    )
    assert rid not in [x["id"] for x in active_tab.json()]

    no_project_tab = await app_client.get(
        PATH, headers=app_auth_headers, params={"contract_status": "suspended"}
    )
    item = next(x for x in no_project_tab.json() if x["id"] == rid)
    assert item["contract_status"] == "suspended"
    assert item["closure_reason"] == "no_client_budget"
    assert item["closure_date"] == "2026-08-01"


async def test_reactivation_without_linked_contract_is_409(
    app_client, app_auth_headers
):
    """Brak kontraktora = notatka nie ma gdzie trafić → 409, nie cicha strata.

    Świadomie 409, nie 422: to nie jest błąd w przesłanych danych, tylko stan
    świata, który trzeba najpierw zmienić gdzie indziej."""
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    assert (await _suspend(app_client, app_auth_headers, rid)).status_code == 200

    _contract_id, client_id = await _seed_linked_contract()
    job_id = await _seed_job(client_id, "Nowy projekt")

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )
    assert resp.status_code == 409, resp.text
    assert "podpisaną obustronnie" in resp.json()["detail"]


async def test_reactivation_assigns_project_and_writes_note(
    app_client, app_auth_headers
):
    """Powrót do gry: nowy projekt + klient na wierszu, notatka w Kontraktach.

    Notatka jest jedynym miejscem, w którym data i powód zakończenia
    poprzedniego projektu docierają do człowieka pracującego w module
    Kontrakty — na samej umowie pola te MUSZĄ zostać wyczyszczone."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    contract_id, client_id = await _seed_linked_contract("Klient docelowy")
    await _link(rid, contract_id=contract_id)
    job_id = await _seed_job(client_id, "Projekt po przerwie")

    assert (await _suspend(app_client, app_auth_headers, rid)).status_code == 200

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_status"] == "active"
    assert body["job_id"] == job_id
    assert body["client_id"] == client_id
    assert body["client_name"] == "Klient docelowy"
    # Pola zamknięcia wyczyszczone — wymusza to CHECK spójności.
    assert body["closure_reason"] is None
    assert body["closure_date"] is None

    async with AsyncSessionLocal() as db:
        notes = list(
            (await db.execute(select(Note).where(Note.contract_id == contract_id)))
            .scalars()
            .all()
        )
    assert len(notes) == 1
    assert notes[0].content == (
        "Poprzedni projekt zakończony: 2026-08-01, powód: Brak budżetu u klienta"
    )


async def test_reactivation_repoints_contract_to_the_new_project(
    app_client, app_auth_headers
):
    """Reaktywacja przepina `contract_id` na kontrakt NOWEGO projektu.

    Do 2026-08-25 zmieniały się tylko `job_id`/`client_id`/`client_name`, a link
    do Kontraktów zostawał na poprzednim projekcie — produkcyjna umowa
    „Bank Pocztowy S.A." wskazywała kontrakt Energi. Skutek szedł w obie
    strony: stary projekt był nieusuwalny (chroniony cudzym podpisem), a nowy
    nie był chroniony wcale.

    Notatka o poprzednim projekcie MUSI przy tym zostać na STARYM kontrakcie —
    to tam prowadzona jest historia, której dotyczy."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.note import Note

    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    old_contract_id, _old_client_id = await _seed_linked_contract("Energa")
    await _link(rid, contract_id=old_contract_id)
    new_contract_id, new_client_id = await _seed_second_project(
        old_contract_id, "Bank Pocztowy S.A."
    )
    job_id = await _seed_job(new_client_id, "Body-leasing w banku")

    assert (await _suspend(app_client, app_auth_headers, rid)).status_code == 200

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        linked = await db.scalar(
            select(B2BGeneratedContract.contract_id).where(
                B2BGeneratedContract.id == rid
            )
        )
        note_contract_ids = list(
            (
                await db.scalars(
                    select(Note.contract_id).where(
                        Note.contract_id.in_([old_contract_id, new_contract_id])
                    )
                )
            ).all()
        )
    assert linked == new_contract_id
    assert note_contract_ids == [old_contract_id]


async def test_reactivation_keeps_link_when_new_project_has_no_contract(
    app_client, app_auth_headers
):
    """Brak kontraktu nowego projektu = link bez zmian, nie nowy kontrakt.

    `ensure_b2b_employment_draft` zakłada kontrakt z pominięciem
    `_assert_no_duplicate_contract`, więc „domyślenie" wiersza przy reaktywacji
    mogłoby po cichu zrobić drugiego kontraktora u tego samego klienta."""
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract

    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    old_contract_id, _old_client_id = await _seed_linked_contract("Energa")
    await _link(rid, contract_id=old_contract_id)
    # Klient docelowy nie ma kontraktu tej osoby — tylko rekrutację.
    _other_contract_id, other_client_id = await _seed_linked_contract(
        "Klient bez umowy"
    )
    job_id = await _seed_job(other_client_id, "Projekt bez kontraktora")

    assert (await _suspend(app_client, app_auth_headers, rid)).status_code == 200

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        linked = await db.scalar(
            select(B2BGeneratedContract.contract_id).where(
                B2BGeneratedContract.id == rid
            )
        )
        candidate_id = await db.scalar(
            select(Contract.candidate_id).where(Contract.id == old_contract_id)
        )
        contracts_of_person = await db.scalar(
            select(func.count())
            .select_from(Contract)
            .where(Contract.candidate_id == candidate_id)
        )
    assert linked == old_contract_id
    assert contracts_of_person == 1


async def test_reactivation_does_not_rewrite_signed_document(
    app_client, app_auth_headers
):
    """Przypisanie nowego projektu NIE dotyka `render_payload`.

    Korekta literówki w nazwie Klienta synchronizuje payload, bo poprawia to, co
    MIAŁO być w dokumencie. Tutaj zmienia się fakt handlowy, a podpisany DOCX
    jest zapisem tego, co strony podpisały."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id, client_name="Pierwotny Klient")
    contract_id, client_id = await _seed_linked_contract("Zupełnie Inny Klient")
    await _link(rid, contract_id=contract_id)
    job_id = await _seed_job(client_id, "Projekt u innego klienta")

    await _suspend(app_client, app_auth_headers, rid)
    await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )

    async with AsyncSessionLocal() as db:
        payload = await db.scalar(
            select(B2BGeneratedContract.render_payload).where(
                B2BGeneratedContract.id == rid
            )
        )
    assert payload["client_name"] == "Pierwotny Klient"


async def test_status_history_survives_the_clearing(app_client, app_auth_headers):
    """Dziennik pamięta to, co znika z wiersza przy powrocie na „Aktywna"."""
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    contract_id, client_id = await _seed_linked_contract()
    await _link(rid, contract_id=contract_id)
    job_id = await _seed_job(client_id, "Projekt z historii")

    await _suspend(app_client, app_auth_headers, rid, date="2026-07-15")
    await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active", "job_id": job_id},
    )

    resp = await app_client.get(
        f"{PATH}/{rid}/status-history", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        ("active", "suspended"),
        ("suspended", "active"),
    ]
    # Zawieszenie zapisuje datę NOWEGO zdarzenia…
    assert events[0]["effective_date"] == "2026-07-15"
    assert events[0]["reason"] == "no_client_budget"
    # …a powrót — datę zakończenia POPRZEDNIEGO projektu, bo to ona znika.
    assert events[1]["effective_date"] == "2026-07-15"
    assert events[1]["job_id"] == job_id
    assert events[1]["job_title"] == "Projekt z historii"


async def test_closure_reason_filter_narrows_the_listing(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    budget_id, _ = await _seed(admin_id)
    health_id, _ = await _seed(admin_id)
    await app_client.patch(
        f"{PATH}/{budget_id}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "no_client_budget",
            "closure_date": "2026-08-01",
        },
    )
    await app_client.patch(
        f"{PATH}/{health_id}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "contractor_health_reasons",
            "closure_date": "2026-08-02",
        },
    )

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"contract_status": "closed", "closure_reason": "no_client_budget"},
    )
    ids = [x["id"] for x in resp.json()]
    assert budget_id in ids
    assert health_id not in ids


async def test_unknown_filter_values_are_422_not_ignored(app_client, app_auth_headers):
    """Ciche zignorowanie filtra zwróciłoby PEŁNĄ listę umów pod nagłówkiem
    zakładki, która obiecuje wąski podzbiór — to gorsze niż błąd."""
    bad_status = await app_client.get(
        PATH, headers=app_auth_headers, params={"contract_status": "zombie"}
    )
    assert bad_status.status_code == 422, bad_status.text
    assert "zombie" in bad_status.json()["detail"]

    bad_reason = await app_client.get(
        PATH, headers=app_auth_headers, params={"closure_reason": "bo tak"}
    )
    assert bad_reason.status_code == 422, bad_reason.text


async def test_reopening_a_closed_contract_does_not_require_a_project(
    app_client, app_auth_headers
):
    """ŚWIADOMA ASYMETRIA względem powrotu z zawieszenia.

    `suspended → active` to zdarzenie biznesowe (kontraktor wraca do pracy), więc
    musi powiedzieć, do czyjego projektu. `closed → active` to KOREKTA POMYŁKI —
    ktoś zamknął nie tę umowę. Wymuszanie projektu blokowałoby cofnięcie błędnego
    kliknięcia i kazałoby wpisać projekt, którego może nie być.

    Ta ścieżka nie ma dziś powierzchni w UI (zakładka „Zakończone umowy" jest
    read-only), ale API ją dopuszcza i ten test przypina ją jako decyzję, a nie
    przeoczenie. Ślad zostaje w dzienniku."""
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id)
    await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "project_completed",
            "closure_date": "2026-08-31",
        },
    )

    resp = await app_client.patch(
        f"{PATH}/{rid}", headers=app_auth_headers, json={"contract_status": "active"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_status"] == "active"
    assert resp.json()["closure_reason"] is None

    history = await app_client.get(
        f"{PATH}/{rid}/status-history", headers=app_auth_headers
    )
    # `_seed` wstawia wiersz BEZ statusu, więc obowiązuje default kolumny
    # (`active`) — `in_progress` ustawia wyłącznie handler `/render`.
    assert [(e["from_status"], e["to_status"]) for e in history.json()] == [
        ("active", "closed"),
        ("closed", "active"),
    ]
    # Bez projektu nie ma czego przypisać — wiersz zostaje bez rekrutacji.
    assert history.json()[-1]["job_id"] is None
