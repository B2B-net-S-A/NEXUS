"""GET /api/admin/client-mixups — raport rozjazdu przypisania klienta.

Po co
-----
Dwa razy niezależnie od siebie zgłoszono ten sam błąd danych: kontrakt i umowa
B2B wskazywały „BNP Paribas Cardif”, a należały do „CARDIF - ASSURANCES RISQUES
DIVERS S.A. ODDZIAŁ W POLSCE”. Dwa przypadki tej samej pomyłki na dwóch różnych
kontach to nie zbieg okoliczności, tylko powtarzalna pułapka: w liście wyboru
klienta stoją obok siebie dwa rekordy o mylnie podobnych nazwach, a wybór
sąsiada nie daje ŻADNEGO widocznego sygnału — dokument generuje się poprawnie,
kontrakt zapisuje się poprawnie, błąd wychodzi miesiące później przy rozliczeniu.

Ten endpoint odpowiada na pytanie, którego nie da się zadać interfejsem:
**gdzie jeszcze mogła zajść ta zamiana?** Nie rozstrzyga i nie poprawia —
ticket wprost żąda listy DO WERYFIKACJI przez zespół produktowy przed
jakąkolwiek masową korektą.

Contract
--------
- **Read-only.** Zero DML: sam SELECT, żadnego przypisania ani kasowania.
  Reguła nie jest kosmetyczna — automatyczne „poprawienie” trafiłoby też
  w przypadki, w których podobna nazwa jest po prostu innym, prawdziwym
  klientem (grupa kapitałowa bywa naszym klientem kilka razy).
- **Bez kwot.** Raport niesie tożsamość powiązania (numer umowy, klient,
  rekrutacja, konsultant), nie stawki — odbiorcą jest zespół produktowy
  weryfikujący przypisania, nie finanse.
- Rodziny klientów wyznacza WSPÓLNY RDZEŃ NAZWY, nie podciąg jednej z nich.
  „BNP” jako podciąg łapie też „BNP Paribas Bank Polska”, który jest odrębnym,
  prawdziwym klientem — a raport, który miesza prawdziwe przypisania
  z podejrzanymi, przestaje być listą do weryfikacji i staje się szumem.
- Dowody, nie werdykty: przy każdym wierszu jedzie NIP obu stron i klient
  REKRUTACJI, z której powstało powiązanie. To one rozstrzygają, a nie
  podobieństwo nazw.

Auth: ``AdminUser`` — raport przekrojowy po całej bazie klientów.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job

router = APIRouter()


# Słowa, które NIE identyfikują firmy — forma prawna i szum administracyjny.
# Bez ich odsiania „SPÓŁKA AKCYJNA” zlepiałaby w jedną rodzinę połowę bazy.
_NOISE_TOKENS = frozenset(
    {
        "sa",
        "spolka",
        "spolki",
        "akcyjna",
        "akcyjnej",
        "zoo",
        "sp",
        "z",
        "o",
        "oo",
        "oddzial",
        "w",
        "polsce",
        "polska",
        "poland",
        "group",
        "grupa",
        "holding",
        "sp_z_oo",
        "s",
        "a",
        "the",
        "and",
        "i",
    }
)

# Rdzeń nazwy musi mieć jakąś masę — dwuznakowy token („BP”, „CA”) trafia
# w przypadkowe firmy i zamienia raport w listę wszystkiego.
_MIN_TOKEN_LEN = 3


# Litery, których NFKD NIE rozkłada — trzeba je przepisać ręcznie. Bez tego
# „SPÓŁKA" składa się do „społka", a `re.split` na klasie [^a-z0-9] tnie ją na
# „spo" + „ka": rdzeniem nazwy zostaje przypadkowy trzyliterowy fragment, który
# łączy w jedną rodzinę firmy niemające ze sobą nic wspólnego. Ta sama tabela
# co w `nordea_order_import._normalize_name_part` i `md_import_parser`.
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})


def _fold(value: str) -> str:
    """Bez diakrytyków, małymi literami — „SPÓŁKA” i „SPOLKA” to to samo słowo.

    Prod nie ma rozszerzenia ``unaccent`` (patrz CLAUDE.md), więc składanie
    robimy w Pythonie, nie w SQL-u.
    """
    translated = (value or "").translate(_TRANSLIT)
    decomposed = unicodedata.normalize("NFKD", translated)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def name_tokens(value: Optional[str]) -> frozenset[str]:
    """Znaczące słowa nazwy klienta — bez form prawnych i bez krótkich skrótów."""
    folded = _fold(value or "")
    raw = re.split(r"[^a-z0-9]+", folded)
    return frozenset(
        token
        for token in raw
        if len(token) >= _MIN_TOKEN_LEN and token not in _NOISE_TOKENS
    )


def shares_identity_token(left: Optional[str], right: Optional[str]) -> bool:
    """Czy dwie nazwy dzielą znaczące słowo — kandydat na tę samą firmę.

    Świadomie NIE ``in`` na całych stringach: podciąg „BNP” łączy „BNP Paribas
    Cardif” z „BNP Paribas Bank Polska”, a to dwa odrębni klienci. Wspólny
    TOKEN („cardif”) jest znacznie węższy i to on odpowiada realnej pomyłce.
    """
    return bool(name_tokens(left) & name_tokens(right))


class MixupClient(BaseModel):
    id: int
    name: str
    display_name: Optional[str] = None
    legal_name: Optional[str] = None
    nip: Optional[str] = None


class MixupContractRow(BaseModel):
    """Kontrakt (moduł Kontrakty) przypisany do jednego z klientów rodziny."""

    kind: str = "contract"
    contract_id: int
    consultant: Optional[str] = None
    status: str
    assigned_client: MixupClient
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    #: Klient REKRUTACJI, z której powstał kontrakt. Rozjazd z ``assigned_client``
    #: to najmocniejszy dowód pomyłki, jaki mamy bez pytania człowieka.
    job_client: Optional[MixupClient] = None
    job_client_mismatch: bool = False


class MixupGeneratedContractRow(BaseModel):
    """Umowa z generatora B2B przypisana do jednego z klientów rodziny."""

    kind: str = "b2b_generated_contract"
    generated_contract_id: int
    contract_number: str
    partner_name: Optional[str] = None
    contract_status: str
    #: Nazwa Klienta WYDRUKOWANA w dokumencie (``client_name``) — bywa inna niż
    #: rekord wskazywany przez ``client_id``, i wtedy dokument jest mocniejszym
    #: świadectwem niż pole strukturalne (precedens: migracja 0242).
    printed_client_name: Optional[str] = None
    assigned_client: Optional[MixupClient] = None
    job_id: Optional[int] = None
    job_client: Optional[MixupClient] = None
    job_client_mismatch: bool = False
    linked_contract_id: Optional[int] = None


class MixupFamily(BaseModel):
    """Grupa klientów o wspólnym rdzeniu nazwy + wszystko, co do nich wisi."""

    token: str
    clients: list[MixupClient]
    contracts: list[MixupContractRow]
    generated_contracts: list[MixupGeneratedContractRow]
    #: Ile wierszy ma rozjazd „klient przypisany ≠ klient rekrutacji”.
    mismatch_count: int


class ClientMixupReport(BaseModel):
    query: Optional[str] = None
    families: list[MixupFamily]
    total_families: int
    total_mismatches: int


def _to_client(client: Optional[Client]) -> Optional[MixupClient]:
    if client is None:
        return None
    return MixupClient(
        id=client.id,
        name=client.name,
        display_name=client.display_name,
        legal_name=client.legal_name,
        nip=client.nip,
    )


def _consultant_name(candidate: Optional[Candidate]) -> Optional[str]:
    if candidate is None:
        return None
    parts = [candidate.name or "", candidate.lastname or ""]
    joined = " ".join(p for p in parts if p).strip()
    return joined or None


@router.get("/client-mixups", response_model=ClientMixupReport)
async def client_mixups(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(
        None,
        description=(
            "Zawęź raport do rodzin zawierających to słowo (np. „cardif”). "
            "Puste = wszystkie rodziny o wspólnym rdzeniu nazwy."
        ),
    ),
) -> ClientMixupReport:
    """Klienci o mylnie podobnych nazwach + ich kontrakty i umowy B2B.

    Wynik jest MATERIAŁEM DO DECYZJI, nie decyzją. ``job_client_mismatch``
    zaznacza wiersze, w których klient przypisany różni się od klienta
    rekrutacji — to najsilniejsza przesłanka pomyłki dostępna maszynowo, ale
    także legalny stan (konsultant przepięty na inny projekt tej samej grupy),
    więc rozstrzyga człowiek.
    """
    clients = list((await db.scalars(select(Client))).all())

    # Rodzina = klienci dzielący znaczący token nazwy. Grupujemy po TOKENIE,
    # bo to on jest nośnikiem pomyłki („cardif” w dwóch różnych rekordach).
    by_token: dict[str, list[Client]] = {}
    for client in clients:
        for token in name_tokens(client.display_name or client.name):
            by_token.setdefault(token, []).append(client)

    needle = _fold(q).strip() if q else None
    families_tokens = {
        token: group
        for token, group in by_token.items()
        # Rodzina zaczyna się przy DWÓCH rekordach — jeden klient o unikalnej
        # nazwie nie ma z czym być pomylony.
        if len(group) > 1 and (needle is None or needle in token)
    }
    if not families_tokens:
        return ClientMixupReport(
            query=q, families=[], total_families=0, total_mismatches=0
        )

    family_client_ids = {c.id for group in families_tokens.values() for c in group}

    contracts = list(
        (
            await db.scalars(
                select(Contract)
                .options(
                    selectinload(Contract.candidate),
                    selectinload(Contract.client),
                )
                .where(Contract.client_id.in_(family_client_ids))
            )
        ).all()
    )
    generated = list(
        (
            await db.scalars(
                select(B2BGeneratedContract).where(
                    B2BGeneratedContract.client_id.in_(family_client_ids)
                )
            )
        ).all()
    )

    # Klient rekrutacji — jednym zapytaniem dla wszystkich job_id naraz.
    # Pętla z ``db.get`` po kilkuset kontraktach to kilkaset round-tripów.
    job_ids = {c.job_id for c in contracts if c.job_id} | {
        g.job_id for g in generated if g.job_id
    }
    job_client_id: dict[int, int] = {}
    job_title: dict[int, str] = {}
    if job_ids:
        rows = await db.execute(
            select(Job.id, Job.client_id, Job.title).where(Job.id.in_(job_ids))
        )
        for jid, cid, title in rows.all():
            job_client_id[jid] = cid
            job_title[jid] = title
    clients_by_id = {c.id: c for c in clients}

    families: list[MixupFamily] = []
    total_mismatches = 0
    for token, group in sorted(families_tokens.items()):
        group_ids = {c.id for c in group}
        rows: list[MixupContractRow] = []
        for contract in contracts:
            if contract.client_id not in group_ids:
                continue
            jc_id = job_client_id.get(contract.job_id) if contract.job_id else None
            mismatch = jc_id is not None and jc_id != contract.client_id
            rows.append(
                MixupContractRow(
                    contract_id=contract.id,
                    consultant=_consultant_name(contract.candidate),
                    status=contract.status.value,
                    assigned_client=_to_client(contract.client)
                    or MixupClient(id=contract.client_id, name="?"),
                    job_id=contract.job_id,
                    job_title=job_title.get(contract.job_id)
                    if contract.job_id
                    else None,
                    job_client=_to_client(clients_by_id.get(jc_id)) if jc_id else None,
                    job_client_mismatch=mismatch,
                )
            )
        gen_rows: list[MixupGeneratedContractRow] = []
        for row in generated:
            if row.client_id not in group_ids:
                continue
            jc_id = job_client_id.get(row.job_id) if row.job_id else None
            mismatch = jc_id is not None and jc_id != row.client_id
            gen_rows.append(
                MixupGeneratedContractRow(
                    generated_contract_id=row.id,
                    contract_number=row.contract_number,
                    partner_name=row.partner_name,
                    contract_status=row.contract_status,
                    printed_client_name=row.client_name,
                    assigned_client=_to_client(clients_by_id.get(row.client_id)),
                    job_id=row.job_id,
                    job_client=_to_client(clients_by_id.get(jc_id)) if jc_id else None,
                    job_client_mismatch=mismatch,
                    linked_contract_id=row.contract_id,
                )
            )
        if not rows and not gen_rows:
            # Rodzina bez ani jednego powiązania nie jest ryzykiem — nie ma
            # czego pomylić, a w raporcie byłaby tylko szumem.
            continue
        mismatches = sum(r.job_client_mismatch for r in rows) + sum(
            r.job_client_mismatch for r in gen_rows
        )
        total_mismatches += mismatches
        families.append(
            MixupFamily(
                token=token,
                clients=[_to_client(c) for c in sorted(group, key=lambda c: c.id)],  # type: ignore[misc]
                contracts=sorted(rows, key=lambda r: r.contract_id),
                generated_contracts=sorted(
                    gen_rows, key=lambda r: r.generated_contract_id
                ),
                mismatch_count=mismatches,
            )
        )

    return ClientMixupReport(
        query=q,
        families=families,
        total_families=len(families),
        total_mismatches=total_mismatches,
    )
