"""Osoba po zmianie nazwiska: plik z dwoma nazwiskami pasuje do kontraktu (Orlen).

Orlen przysłał podpisany protokół za IX 2026 w pliku „PROTOKÓŁ_ Imię Nowe (Stare)_…”,
a PO i kontrakt mają jedno z nazwisk. ``identity.resolve_named_in_text`` wymaga imienia
i każdego członu nazwiska z kontraktu, więc dodatkowe nazwisko w nazwie pliku nie
przeszkadza. Domena ``pgnig.pl`` (Orlen Upstream) wskazuje klientów Orlenu.
Osoby fikcyjne.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.services.consultant_portal import identity
from app.services.order_policies import known_clients
from tests.care_announcements_seed import tag
from tests.consultant_portal_seed import make_person


async def _named(text: str):
    async with AsyncSessionLocal() as db:
        return await identity.resolve_named_in_text(db, text, today=business_today())


async def test_plik_z_nowym_i_starym_nazwiskiem_pasuje_do_kontraktu() -> None:
    old, new = f"Stara{tag()}", f"Nowa{tag()}"
    person = await make_person(activated=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(name="Kornelia", lastname=old)
        )
        await db.commit()
    for name in (
        f"PROTOKÓŁ_ Kornelia {new} ({old})_WRZESIEŃ 2026.pdf",
        f"PROTOKÓŁ_ Kornelia {old}_WRZESIEŃ 2026-sig.pdf",
    ):
        found = await _named(name)
        assert found is not None and found.id == person.contract_id, name
    # Samo nowe nazwisko nie wskazuje osoby z kontraktem na stare.
    assert await _named(f"PROTOKÓŁ_ Kornelia {new}_PAŹDZIERNIK 2026.pdf") is None


async def test_pgnig_wskazuje_klienta_orlen() -> None:
    nip = known_clients.KNOWN_REGISTRY_IDS["orlen"][0]
    person = await make_person(activated=False)
    async with AsyncSessionLocal() as db:
        clash = await db.scalar(
            select(Client.id).where(Client.nip == nip, Client.id != person.client_id)
        )
        if clash is not None:
            pytest.skip("klient z numerem Orlenu istnieje już w bazie testowej")
        client = await db.get(Client, person.client_id)
        client.nip = nip
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            found = await identity._clients_of_domain(db, "pgnig.pl")
            # Ścieżka czytnika poczty: nazwa pliku wskazuje osobę wśród kontraktów
            # klienta z domeny nadawcy, choć Orlen nie ma kontaktu w pgnig.pl.
            sender = await identity.client_ids_for_sender(db, "Kierownik@PGNiG.pl")
        assert found == frozenset({person.client_id})
        assert person.client_id in sender
    finally:
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, person.client_id)
            client.nip = None
            await db.commit()
