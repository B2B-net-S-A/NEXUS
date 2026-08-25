"""Wspólny dawca stron (`candidate_id` + `client_id`) dla testów umów.

Ten helper istniał w czterech kopiach naraz i to nie była kosmetyka: dwie z nich
zostały naprawione, a dwie zostały z pierwotną, wadliwą regułą — więc czerwień
nie znikała, tylko WĘDROWAŁA między shardami CI. Jedna kopia = jedna reguła.

Historia reguły:

1. Pierwotnie helper ŻEROWAŁ na istniejących umowach (`GET /api/contracts` →
   pierwsza z żywym kandydatem), omijając sieroty po migracji 0225
   (``candidate_id IS NULL`` po skasowanym kandydacie → POST 422).
2. Od 2026-08-25 (PR #1259, blokada duplikatu kontraktora) para z istniejącą
   umową jest z definicji BEZUŻYTECZNA jako dawca: ``POST /api/contracts`` dla
   tej samej osoby u tego samego klienta w żywym statusie odpowiada 409
   ``duplicate_contractor``. Helper seeduje więc ŚWIEŻĄ parę wprost w bazie —
   każdy wołający dostaje własną, więc testy nie kolidują ani ze sobą, ani
   z regułą duplikatu, ani z sierotami.

Sygnatura zostaje (``app_client``, ``headers``) dla zgodności z wołającymi —
argumenty nie są już używane, a ``None`` nie jest już nigdy zwracane (gałęzie
skip u wołających pozostają martwym, nieszkodliwym kodem).
"""

import uuid

__all__ = ["pick_parties"]


async def pick_parties(app_client=None, headers=None):
    """Zwróć ``(candidate_id, client_id)`` świeżo zseedowanej pary."""
    del app_client, headers  # zgodność sygnatury — patrz docstring modułu

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Party",
            lastname=f"Donor{unique}",
            email=f"party-{unique}@example.com",
        )
        cli = Client(name=f"Party Client {unique}")
        db.add_all([cand, cli])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(cli)
        return cand.id, cli.id
