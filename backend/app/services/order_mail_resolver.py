"""Dopasowanie osób z wierszy zamówienia do ROSTERA klienta (nie całej bazy).

Ticket: przy wielu konsultantach na jednym zamówieniu system nie bierze
pierwszej pasującej osoby z całej bazy — dopasowuje wyłącznie wśród
konsultantów pracujących u danego klienta. Roster jest SZERSZY niż picker
(``active`` + ``ending``): przedłużenie po przerwie dotyczy osoby, której
kontrakt jest już ``ended`` — to zamówienie go wskrzesza — więc bierzemy też
``draft`` i wszystkie zakończone. Roster służy do NAZWANIA
osoby; czy automat może na niej zapisać, rozstrzyga bramka (status kontraktu).

Dwa rodzaje trafienia, celowo rozróżniane:
* **exact** — równoważne po normalizacji (diakrytyki, kolejność imię/nazwisko,
  myślniki); jedyne, które bramka automatu akceptuje;
* **rescued** — odmiana gramatyczna lub jedna drobna literówka; różnica
  jest sygnałem, że dokument i baza się nie
  zgadzają, więc idzie do kolejki (korpus: „Podwin" w dokumencie CA vs
  „Padwin" na karcie).

Osoba to nie kontrakt: writer potrzebuje KONTRAKTU. Przy dwóch żywych
kontraktach tej samej osoby u klienta ``_contract_for_candidate`` wybiera po
cichu najpóźniejszy — my nie: to niejednoznaczność do kolejki.

Brak w rosterze NIE znaczy „nowa osoba". ``load_people_outside_roster``
sprawdza, czy ktoś o DOKŁADNIE tym imieniu i nazwisku jest już w bazie u
innego klienta, i dokleja to do wyniku (``annotate_known_elsewhere``).
Roster zostaje nietknięty — nie rozszerzamy dopasowania na inne rekordy
klienta, bo podobna nazwa bywa naprawdę innym klientem (rodzina „BNP *").
Ten sygnał służy WYŁĄCZNIE do zatrzymania automatu i pokazania Delivery
Leadowi konkretnej podpowiedzi zamiast domyślnego „Nowy kontraktor": tak
wygląda zarówno pierwsze zlecenie osoby, która pracowała u innego klienta,
jak i dokument przypięty do zdublowanego rekordu klienta. Której z tych
dwóch rzeczy dotyczy — rozstrzyga człowiek, nie heurystyka po nazwie.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.advanced_candidate_search import fold_polish
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    _name_token_variants,
    _names_exactly_equivalent,
    _osa_distance,
)

MATCH_EXACT = "exact"
MATCH_RESCUED = "rescued"
MATCH_AMBIGUOUS = "ambiguous"
MATCH_NONE = "none"

LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class RosterContract:
    contract_id: int
    status: str
    start_date: Optional[date]
    end_date: Optional[date]


@dataclass(frozen=True)
class RosterPerson:
    candidate_id: int
    name: str
    lastname: str
    contracts: tuple[RosterContract, ...]

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.lastname}".strip()


@dataclass(frozen=True)
class ResolvedConsultant:
    row_index: int
    row_name: str
    match_kind: str
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    contract_status: Optional[str] = None
    #: Data końca wybranego kontraktu (ISO) — do komunikatu o zakończonej
    #: współpracy. Tekst, nie ``date``: rekord trafia do JSONB dokumentu.
    contract_end_date: Optional[str] = None
    #: ID kandydatów, które pasowały (>1 = niejednoznaczne).
    candidate_ids: tuple[int, ...] = ()
    #: Kontrakty kandydata u klienta (>1 żywy = niejednoznaczne dla automatu).
    live_contract_ids: tuple[int, ...] = ()
    #: Kandydaci o dokładnie tym imieniu i nazwisku spoza rostera tego klienta.
    #: Niepusta lista przy ``match_kind == "none"`` znaczy „osoba jest w bazie,
    #: tylko nie u tego klienta" — automat wtedy NIE zakłada nowego kontraktora.
    #: Same ID: rekord jest serializowany do JSONB dokumentu.
    known_elsewhere_ids: tuple[int, ...] = ()
    #: Podzbiór ``known_elsewhere_ids`` z TRWAJĄCĄ współpracą u innego klienta.
    #: Rozstrzyga, czy wstrzymanie znaczy „czekamy na podpis umowy" (pusto —
    #: osoba nie pracuje dziś nigdzie), czy „sprawdź, czy to nie zdublowany
    #: rekord klienta" (niepusto — to pytanie do człowieka, nie do zegara).
    known_elsewhere_open_ids: tuple[int, ...] = ()
    reason: str = ""

    @property
    def is_new_without_live_contract(self) -> bool:
        """Nowy kontraktor u tego klienta, bez żywej umowy gdziekolwiek w systemie.

        Dokładnie ten stan znaczy „zamówienie przyszło, zanim podpisano umowę":
        osoby nie ma na rosterze klienta, nigdzie nie ma trwającej współpracy
        i nie ma wątpliwości, o kogo chodzi (imiennicy to decyzja człowieka).
        JEDNO źródło dla planera i dla bramki — obie ścieżki muszą nazywać ten
        sam stan tak samo, inaczej godzinowa ponowna weryfikacja raz czeka
        bezterminowo, a raz eskaluje do Delivery Leada.
        """
        return (
            self.match_kind == MATCH_NONE
            and not self.known_elsewhere_open_ids
            and len(self.known_elsewhere_ids) <= 1
        )

    @property
    def is_unique_person(self) -> bool:
        return (
            self.match_kind in (MATCH_EXACT, MATCH_RESCUED)
            and self.candidate_id is not None
        )

    @property
    def has_single_live_contract(self) -> bool:
        return len(self.live_contract_ids) == 1


async def load_roster(
    db: AsyncSession,
    client_id: int,
) -> list[RosterPerson]:
    """Pełna, aktualna lista osób z kontraktem u tego klienta, bez limitu wieku.

    Status kontraktu ogranicza zapis, nie identyfikację osoby. Zapytanie nie
    używa paginacji ani zapamiętanej listy z chwili importu.
    """
    stmt = (
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Contract.id,
            Contract.status,
            Contract.start_date,
            Contract.end_date,
        )
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(
            Contract.client_id == client_id,
        )
        .order_by(Candidate.id, Contract.start_date.desc().nullslast())
    )
    people: dict[int, dict] = {}
    for cid, name, lastname, contract_id, status, start, end in (
        await db.execute(stmt)
    ).all():
        person = people.setdefault(
            cid, {"name": name or "", "lastname": lastname or "", "contracts": []}
        )
        person["contracts"].append(
            RosterContract(
                contract_id=contract_id,
                status=status.value if hasattr(status, "value") else str(status),
                start_date=start,
                end_date=end,
            )
        )
    return [
        RosterPerson(
            candidate_id=cid,
            name=p["name"],
            lastname=p["lastname"],
            contracts=tuple(p["contracts"]),
        )
        for cid, p in people.items()
    ]


def _pick_contract(
    person: RosterPerson,
) -> tuple[Optional[RosterContract], tuple[int, ...]]:
    """Kontrakt do zapisu: żywy (jeśli dokładnie jeden), potem szkic, potem zakończony."""
    live = [c for c in person.contracts if c.status in ("active", "ending")]
    live_ids = tuple(c.contract_id for c in live)
    if len(live) == 1:
        return live[0], live_ids
    if len(live) > 1:
        return None, live_ids
    drafts = [c for c in person.contracts if c.status == "draft"]
    if drafts:
        return (drafts[0] if len(drafts) == 1 else None), live_ids
    ended = sorted(
        (c for c in person.contracts if c.status == "ended"),
        key=lambda c: c.end_date or date.min,
        reverse=True,
    )
    return (ended[0] if ended else None), live_ids


def _inflected_tokens(token: str) -> set[str]:
    """Ograniczone formy fleksyjne tokenu z bazy, bez obcinania wspólnych rdzeni."""
    forms = {token}
    if len(token) < 3:
        return forms
    if token.endswith(("ski", "cki", "dzki")):
        forms.update(token[:-1] + suffix for suffix in ("iego", "iemu", "im"))
    elif token.endswith(("ska", "cka", "dzka")):
        forms.add(token[:-1] + "iej")
    elif token.endswith("a"):
        forms.update(token[:-1] + suffix for suffix in ("y", "i", "e", "ie"))
    elif token[-1] not in "aeiouy":
        forms.update(token + suffix for suffix in ("a", "owi", "em", "u", "ie"))
        for ending, replacement in (("d", "dzie"), ("t", "cie"), ("r", "rze")):
            if token.endswith(ending):
                forms.add(token[:-1] + replacement)
    return forms


def _roster_name_matches(document_name: str, canonical_name: str) -> bool:
    """Każdy człon musi pasować; odmiana i maks. jedna literówka w całej osobie.

    Kolejność, diakrytyki i myślniki są normalizowane jak dotąd. Nie szukamy
    podobnego nazwiska w całej bazie: wywołujący podaje wyłącznie roster klienta.
    Wszystkie trafienia zachowujemy, żeby nie rozstrzygać kolizji arbitralnie.
    """
    for canonical in _name_token_variants(canonical_name):
        forms = [_inflected_tokens(token) for token in canonical]
        for actual in _name_token_variants(document_name):
            if len(actual) != len(canonical) or len(actual) > 6:
                continue

            @lru_cache(maxsize=None)
            def match(index: int, remaining: tuple[str, ...], typos: int) -> bool:
                if index == len(canonical):
                    return True
                for pos, token in enumerate(remaining):
                    cost = 0 if token in forms[index] else 1
                    if cost and (
                        typos
                        or min(len(canonical[index]), len(token)) < 4
                        or not any(
                            _osa_distance(form, token, max_distance=1) == 1
                            for form in forms[index]
                        )
                    ):
                        continue
                    if match(
                        index + 1, remaining[:pos] + remaining[pos + 1 :], typos + cost
                    ):
                        return True
                return False

            if match(0, actual, 0):
                return True
    return False


def resolve_rows(
    rows: list[ConsultantOrderRow], roster: list[RosterPerson]
) -> list[ResolvedConsultant]:
    out: list[ResolvedConsultant] = []
    for idx, row in enumerate(rows):
        exact = [
            p
            for p in roster
            if _names_exactly_equivalent(row.consultant_name, p.full_name)
        ]
        rescued: list[RosterPerson] = []
        if not exact:
            rescued = [
                p
                for p in roster
                if _roster_name_matches(row.consultant_name, p.full_name)
            ]
        pool, kind = (exact, MATCH_EXACT) if exact else (rescued, MATCH_RESCUED)
        if not pool:
            out.append(
                ResolvedConsultant(
                    row_index=idx,
                    row_name=row.consultant_name,
                    match_kind=MATCH_NONE,
                    reason="Brak takiej osoby wśród konsultantów tego klienta",
                )
            )
            continue
        if len(pool) > 1:
            out.append(
                ResolvedConsultant(
                    row_index=idx,
                    row_name=row.consultant_name,
                    match_kind=MATCH_AMBIGUOUS,
                    candidate_ids=tuple(p.candidate_id for p in pool),
                    reason=(
                        f"Pasuje {len(pool)} osób u tego klienta — wybierz ręcznie: "
                        + "; ".join(
                            f"{p.full_name} (ID {p.candidate_id}; kontrakty: "
                            + ", ".join(str(c.contract_id) for c in p.contracts)
                            + ")"
                            for p in pool
                        )
                    ),
                )
            )
            continue
        person = pool[0]
        contract, live_ids = _pick_contract(person)
        out.append(
            ResolvedConsultant(
                row_index=idx,
                row_name=row.consultant_name,
                match_kind=kind,
                candidate_id=person.candidate_id,
                contract_id=contract.contract_id if contract else None,
                contract_status=contract.status if contract else None,
                contract_end_date=(
                    contract.end_date.isoformat()
                    if contract and contract.end_date
                    else None
                ),
                candidate_ids=(person.candidate_id,),
                live_contract_ids=live_ids,
                reason=(
                    "Dopasowanie dokładne"
                    if kind == MATCH_EXACT
                    else "Dopasowanie z literówką lub odmianą — potwierdź osobę"
                )
                if contract
                else (
                    "Osoba bez kontraktu do zapisu u tego klienta"
                    if not live_ids
                    else f"Osoba ma {len(live_ids)} żywe kontrakty u klienta — wybierz ręcznie"
                ),
            )
        )
    return out


# ── „Ta osoba jest już w bazie, tylko nie u tego klienta" ────────────────────


#: Kontrakty, które w komunikacie liczą się jako TRWAJĄCA współpraca.
_OPEN_ELSEWHERE_STATUSES = ("active", "ending")


@dataclass(frozen=True)
class PersonElsewhere:
    """Osoba o tym samym imieniu i nazwisku, z kontraktem u INNEGO klienta."""

    candidate_id: int
    full_name: str
    contract_id: Optional[int] = None
    contract_status: Optional[str] = None
    client_id: Optional[int] = None
    client_name: str = ""

    @property
    def is_open(self) -> bool:
        return self.contract_status in _OPEN_ELSEWHERE_STATUSES


async def load_people_outside_roster(
    db: AsyncSession,
    *,
    client_id: int,
    names: list[str],
) -> dict[str, tuple[PersonElsewhere, ...]]:
    """Dla każdej nazwy z dokumentu: osoby z bazy spoza rostera tego klienta.

    Dopasowanie jest DOKŁADNE (``_names_exactly_equivalent``) — bez odmiany
    i bez literówek. Ten sygnał wyłącza automat, więc nie może reagować na
    podobieństwo: zatrzymywałby normalne pierwsze zlecenia.

    Prefiltr po nazwisku ze zwiniętymi polskimi znakami po OBU stronach (prod
    nie ma ``unaccent``) — ten sam, którym writer szuka imiennika przed
    założeniem kartoteki, więc kolejka pokazuje dokładnie to, na co writer
    i tak by się natknął.
    """
    # Leniwy import: ``app.api.clients`` importuje serwisy zamówień.
    from app.api.clients import polish_alphabetical_key

    wanted = [n for n in names if n and len(n.split()) >= 2]
    if not wanted:
        return {}
    # Nazwisko bywa pierwszym albo ostatnim wyrazem („KOWALSKI Jan").
    surname_keys = sorted(
        {fold_polish(part) for n in wanted for part in (n.split()[0], n.split()[-1])}
    )
    rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Contract.id,
                Contract.status,
                Contract.client_id,
                Client.name,
            )
            .select_from(Candidate)
            .outerjoin(
                Contract,
                (Contract.candidate_id == Candidate.id)
                & (Contract.client_id != client_id),
            )
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                polish_alphabetical_key(Candidate.lastname).in_(surname_keys),
                Candidate.external_deleted_at.is_(None),
            )
        )
    ).all()

    by_candidate: dict[int, list[PersonElsewhere]] = {}
    full_names: dict[int, str] = {}
    for (
        cand_id,
        name,
        lastname,
        contract_id,
        status,
        contract_client,
        client_name,
    ) in rows:
        full_names[cand_id] = f"{name or ''} {lastname or ''}".strip()
        if contract_id is None:
            by_candidate.setdefault(cand_id, [])
            continue
        by_candidate.setdefault(cand_id, []).append(
            PersonElsewhere(
                candidate_id=cand_id,
                full_name=full_names[cand_id],
                contract_id=contract_id,
                contract_status=(
                    status.value if hasattr(status, "value") else str(status)
                ),
                client_id=contract_client,
                client_name=client_name or "",
            )
        )

    out: dict[str, tuple[PersonElsewhere, ...]] = {}
    for document_name in wanted:
        hits: list[PersonElsewhere] = []
        for cand_id, full_name in full_names.items():
            if not _names_exactly_equivalent(document_name, full_name):
                continue
            engagements = by_candidate.get(cand_id) or []
            if engagements:
                # Trwająca współpraca najpierw — to ona jest podpowiedzią.
                hits.extend(
                    sorted(engagements, key=lambda e: (not e.is_open, e.contract_id))
                )
            else:
                hits.append(PersonElsewhere(candidate_id=cand_id, full_name=full_name))
        if hits:
            out[document_name] = tuple(hits)
    return out


def known_elsewhere_reason(
    document_name: str, hits: tuple[PersonElsewhere, ...]
) -> str:
    """Jedno zdanie do kolejki i do bramki — jedno źródło dla obu ścieżek.

    Zaczyna się od nazwy Z DOKUMENTU: to ona stoi w tabeli osób obok, a pisownia
    w bazie bywa inna (skan bez diakrytyków, odwrócona kolejność imienia
    i nazwiska).
    """

    people = {h.candidate_id: h for h in hits}
    listing = ", ".join(f"„{h.full_name}” (#{h.candidate_id})" for h in people.values())
    if len(people) > 1:
        return (
            f"„{document_name}”: w bazie jest kilka osób o tym imieniu i nazwisku "
            f"({listing}) — wskaż właściwą ręcznie, automat nie zgaduje"
        )
    open_hits = [h for h in hits if h.is_open and h.client_name]
    if open_hits:
        where = "; ".join(
            f"kontrakt #{h.contract_id} u klienta „{h.client_name}”"
            for h in open_hits[:3]
        )
        return (
            f"„{document_name}”: {listing} ma {where}. Sprawdź, czy dokument nie "
            "dotyczy tego samego klienta zapisanego pod drugim rekordem, zanim "
            "założysz nowego kontraktora"
        )
    return (
        f"„{document_name}”: {listing} jest już w bazie, ale bez trwającej "
        "współpracy u innego klienta. Potwierdź, że to ta sama osoba, "
        "i zastosuj ręcznie"
    )


def annotate_known_elsewhere(
    resolved: list[ResolvedConsultant],
    elsewhere: dict[str, tuple[PersonElsewhere, ...]],
) -> list[ResolvedConsultant]:
    """Dokleja podpowiedź do wierszy bez dopasowania w rosterze (czysta funkcja)."""

    out: list[ResolvedConsultant] = []
    for res in resolved:
        hits = elsewhere.get(res.row_name) if res.match_kind == MATCH_NONE else None
        if not hits:
            out.append(res)
            continue
        out.append(
            replace(
                res,
                known_elsewhere_ids=tuple(sorted({h.candidate_id for h in hits})),
                known_elsewhere_open_ids=tuple(
                    sorted({h.candidate_id for h in hits if h.is_open})
                ),
                reason=known_elsewhere_reason(res.row_name, hits),
            )
        )
    return out
