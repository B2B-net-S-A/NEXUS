"""Import mapy technologicznej i rozmów opiekunów z Compassa.

Tabele Compassa: ``tech_interview_cards`` (+ ``tech_interview_card_technologies``,
``tech_interview_card_vendors``, ``tech_interview_card_initiatives``,
``tech_card_sales_status``), słowniki ``technologies``, ``vendors``,
``client_areas``, ``clients``, rejestr ``contractors`` i
``contractor_conversations``.

Połączenie z NEXUSEM (decyzja D7: karta i rozmowa żyją na kontrakcie):

* klient: nazwa klienta Compassa = nazwa (albo nazwa wyświetlana) klienta
  NEXUSA po ``normalize_client_name``, a bez trafienia — po nazwie bez formy
  prawnej (``loose_client_name``, „S.A.”, „sp. z o.o.”); klient scalony →
  klient docelowy; dwa trafienia = brak pewności,
* osoba: kotwica z kolejki „Tożsamość NEXUS” Compassa
  (``contractors.nexus_candidate_id``, a bez niej ``nexus_contract_id`` →
  kandydat kontraktu),
* kontrakt: kandydat + klient + okres (dzień rozmowy w trakcie umowy, umowa
  nie anulowana i nie szkic) — dokładnie jeden, inaczej „conflict”.

Karta bez kotwicy (18.10.2026 — wszystkie: kolejka „Tożsamość NEXUS” jest
pusta) łączy się z kontraktem po kliencie, imieniu i nazwisku konsultanta
(``contractors.full_name``) i dniu rozmowy — decyzja Artura „Import
+ automatyczne parowanie”, reguły w ``app/services/care/card_linking.py``:
dokładnie jeden kontrakt w okresie = połączenie automatyczne, inaczej karta
trafia do klienta z pustym ``contract_id`` (schemat dopuszcza to tylko dla
importu) i czeka na liście „Karty do połączenia” z propozycjami; imię
i nazwisko z Compassa zostaje na karcie (``compass_person_name``). Karta bez
klienta jest pomijana.

Rozmowa bez kotwicy (decyzja Artura z 18.10.2026: „jak karty”) łączy się
z kontraktem tymi samymi regułami — klient z ``client_snapshot`` (pusty =
``contractors.current_client``), imię i nazwisko z ``contractors.full_name``,
dzień rozmowy w okresie umowy. Najpierw wygrywa kontrakt karty tej samej
osoby u tego klienta (karta połączona przez import albo przez DL w „Karty
z Compassa do połączenia”), jeśli dzień rozmowy mieści się w umowie —
dokładnie jeden; potem dokładnie jeden kontrakt po nazwisku. Rozmowa musi
mieć kontrakt, więc niepewna czeka jako „conflict” (raport: same liczby)
i ponowny import po połączeniu karty przez DL ją dociąga. Rytm i opiekun
łączą się nadal wyłącznie po kotwicy.
Technologia spoza słownika ``skills`` (nazwa ani alias) idzie do
``skill_review_queue``, a karta trzyma tekst w ``unrecognized_skills``.
Import nie zgłasza „Do przepięcia” i nie wysyła przypomnień. Punktów planu
sam nie zamyka — rozmowa z importu pokrywa punkty z terminem nie późniejszym
niż jej dzień: plan ich nie zakłada, a otwarte zamyka nocny przebieg opieki
(``care.plan.close_covered``), więc po imporcie kontrakt nie ma zaległości
sprzed ostatniej rozmowy.

Rytm i opiekun (etap 3, 17.10.2026) — z ``contractor_success_settings``
i ``contractors.owner_tcm_id``, tylko przy pewnym kontrakcie (ta sama reguła
co rozmowy z kotwicą: osoba + klient z ``contractors.current_client`` + dzień
eksportu w okresie umowy):

* rytm: monitoring wstrzymany → „wstrzymany”; aktywny w programie wejścia
  (``onboarding_program_ends_on`` nie minął) → co 2 tygodnie do końca
  programu; inaczej ``check_in_cadence_days`` ≤ 14 co 2 tygodnie, ≤ 31 co
  miesiąc, ≤ 93 co kwartał, dalej tylko kamienie. Monitoring nieaktywny →
  rytm domyślny NEXUSA (do raportu). Okres od dnia eksportu z powodem
  „z Compassa”; rytm zmieniony już w NEXUSIE zostaje (``conflict``).
  Plan przelicza nocny przebieg opieki,
* opiekun: konto opiekuna Compassa, które może być opiekunem w NEXUSIE
  (aktywny DL z klientem w portfelu, TCM, admin albo osoba z puli
  opiekunów — ``care_access.owner_problem``), na kontrakcie bez opiekuna;
  inny opiekun wpisany w NEXUSIE zostaje, a osoba z listy wykluczonych puli
  nie przechodzi (``conflict``).
"""

from __future__ import annotations

import calendar as month_calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_care import (
    CONTRACTS_CARE,
    CareCadencePeriod,
    CareConversation,
    ClientArea,
    SkillReviewItem,
    TechCard,
    TechCardSkill,
    TechCardVendor,
    TechVendor,
)
from app.models.hr_ops import HrImportBatch
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import card_linking, owner_pool
from app.services.care import skills as care_skills
from app.services.client_portfolio_import import (
    loose_client_name,
    normalize_client_name,
)
from app.services.contract_care_schema import (
    CARD_STATUSES,
    HIRING_SOURCES,
    NOTE_MAX,
    PERSON_NAME_MAX,
    SALES_STATUSES,
    SHORT_TEXT_MAX,
)

from app.core.scheduling import business_today
from app.services.hr import audit

from .bundle import Bundle
from .common import (
    ImportPlan,
    People,
    changed_fields,
    join_notes,
    load_people,
    local_date,
    parse_date,
    parse_datetime,
    parse_uuid,
    small_int,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, mapped_target, remember

MODULE = "care"
CARDS = "tech_interview_cards"
CONVERSATIONS = "contractor_conversations"

NO_LINK = "kontraktor bez powiązania z NEXUSEM (kolejka „Tożsamość NEXUS”)"
UNSURE_CONTRACT = "kontrakt niepewny — karta przy kliencie, bez kontraktu"
NAME_LINKED = "kontrakt dopasowany po kliencie, imieniu i nazwisku oraz dacie"
NAME_SUGGESTED = "do potwierdzenia przez DL — kilka kontraktów albo poza okresem umowy"
NAME_NOT_FOUND = "bez kontraktu z tym imieniem i nazwiskiem u klienta"
CONVERSATION_UNSURE = "kontrakt rozmowy niepewny"
CONVERSATION_BY_CARD = "kontrakt z karty tej osoby u klienta"
CONVERSATION_WAITS = (
    "rozmowa czeka — kilka kontraktów albo poza okresem umowy; "
    "wróci po połączeniu karty osoby przez DL"
)
CONVERSATION_NO_CLIENT = "klient rozmowy bez odpowiednika w NEXUSIE"
UNKNOWN_SKILL = "technologia spoza słownika — w kolejce do przejrzenia"
RHYTHMS = "contractor_success_settings"
OWNERS = "contractors"
RHYTHM_UNSURE = "kontrakt rytmu niepewny"
RHYTHM_INACTIVE = "monitoring nieaktywny w Compassie — rytm domyślny NEXUSA"
RHYTHM_UNKNOWN = "nieznany stan monitoringu"
RHYTHM_SET_IN_NEXUS = "rytm zmieniony w NEXUSIE — bez nadpisania"
OWNER_UNSURE = "kontrakt opiekuna niepewny"
OWNER_NO_ACCOUNT = "opiekun bez konta w NEXUSIE"
OWNER_NOT_CARE = "opiekun z Compassa nie może być opiekunem tego kontraktu"
OWNER_SET_IN_NEXUS = "opiekun ustawiony w NEXUSIE — bez nadpisania"
OWNER_EXCLUDED = "opiekun z Compassa jest na liście wykluczonych z puli opiekunów"
_SKIPPED_CONTRACT_STATUSES = (ContractStatus.void, ContractStatus.draft)

CATEGORY_LABELS: dict[str, str] = {
    "szkolenia": "Szkolenia",
    "podwyzka": "Podwyżka",
    "follow_up": "Follow-up",
    "zejscie": "Zejście",
    "przedluzenie": "Przedłużenie",
    "informacyjnie": "Informacyjnie",
    "konferencja": "Konferencja",
    "onboarding": "Onboarding",
    "exit": "Exit",
    "delegacja": "Delegacja",
    "internalizacja": "Internalizacja",
    "zmiana_stawki": "Zmiana stawki",
    "inne": "Inne",
}
STATUS_LABELS: dict[str, str] = {
    "w_toku": "w toku",
    "rozwiazane": "rozwiązane",
    "potrzebny_kontakt": "potrzebny kontakt",
    "pilne": "pilne",
}
CARD_FIELDS = (
    "contract_id",
    "client_id",
    "author_user_id",
    "interview_on",
    "status",
    "is_draft",
    "finalized_at",
    "satisfaction",
    "hiring",
    "hiring_source",
    "hiring_roles",
    "project_end_on",
    "project_end_unknown",
    "team_size",
    "team_externals",
    "initiatives",
    "memorable_quote",
    "note",
    "sales_status",
    "sales_deal_title",
    "sales_reason",
    "sales_handled_by",
    "sales_handled_at",
)


@dataclass
class Links:
    """Klienci, kotwice kontraktorów i kontrakty kandydatów (jeden przebieg)."""

    clients_by_key: dict[str, set[int]]
    compass_clients: dict[str, str]
    contractors: dict[str, Mapping[str, Any]]
    clients_by_loose: dict[str, set[int]] = field(default_factory=dict)
    clients_by_words: dict[frozenset[str], set[int]] = field(default_factory=dict)
    by_name: card_linking.ContractIndex = field(
        default_factory=card_linking.ContractIndex
    )
    contract_candidate: dict[int, Optional[int]] = field(default_factory=dict)
    known_candidates: set[int] = field(default_factory=set)
    contracts: dict[int, list[tuple[int, int, Optional[date], Optional[date]]]] = field(
        default_factory=dict
    )
    #: Kontraktor Compassa → kontrakty jego kart w NEXUSIE (klient karty).
    card_contracts: dict[str, list[card_linking.ContractRow]] = field(
        default_factory=dict
    )

    def client_for_name(self, name: Optional[str]) -> Optional[int]:
        matches = self.clients_by_key.get(normalize_client_name(name), set())
        if not matches and loose_client_name(name):
            matches = self.clients_by_loose.get(loose_client_name(name), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def client_for(self, compass_client_id: Any) -> Optional[int]:
        return self.client_for_name(self.compass_clients.get(str(compass_client_id)))

    def card_client_options(self, compass_client_id: Any) -> set[int]:
        """Klienci NEXUSA dla klienta karty: nazwa, nazwa bez formy prawnej,
        a na końcu zbiór słów bez „ex” i „o” („ERSTE / Santander” = „ERSTE (ex
        Santander)”, „Firma” = „Firma sp. z o.o.”). Kilka = duplikat
        z Traffita — rozstrzyga kontrakt osoby."""

        return self.client_options_for_name(
            self.compass_clients.get(str(compass_client_id))
        )

    def client_options_for_name(self, name: Optional[str]) -> set[int]:
        for found in (
            self.clients_by_key.get(normalize_client_name(name)),
            self.clients_by_loose.get(loose_client_name(name)),
            self.clients_by_words.get(_client_words(name)),
        ):
            if found:
                return found
        return set()

    def narrow_clients(
        self, options: set[int], person_name: Optional[str], day: date
    ) -> set[int]:
        """Duplikat klienta (np. dwa „PFRON” z Traffita): wygrywa ten, u którego
        osoba ma pewny kontrakt w dniu rozmowy."""

        if len(options) <= 1:
            return options
        return {
            option
            for option in options
            if self.by_name.match(option, person_name, day).contract_id
        }

    def card_contract_for(
        self, contractor_id: Any, client_id: int, day: date
    ) -> Optional[int]:
        """Kontrakt karty tej osoby u klienta, gdy dzień jest w umowie (jeden)."""

        hits = {
            row.contract_id
            for row in self.card_contracts.get(str(contractor_id), [])
            if row.client_id == client_id and row.covers(day)
        }
        return next(iter(hits)) if len(hits) == 1 else None

    def candidate_for(self, contractor_id: Any) -> Optional[int]:
        row = self.contractors.get(str(contractor_id)) or {}
        candidate = small_int(row.get("nexus_candidate_id"))
        if candidate is not None and candidate in self.known_candidates:
            return candidate
        contract = small_int(row.get("nexus_contract_id"))
        if contract is not None:
            return self.contract_candidate.get(contract)
        return None

    def contract_for(
        self, candidate_id: int, client_id: Optional[int], day: date
    ) -> tuple[Optional[int], Optional[int]]:
        """(kontrakt, klient) — dokładnie jeden kontrakt w okresie, inaczej pusto."""

        hits = [
            (contract_id, contract_client)
            for contract_id, contract_client, start, end in self.contracts.get(
                candidate_id, []
            )
            if (client_id is None or contract_client == client_id)
            and (start is None or start <= day)
            and (end is None or end >= day)
        ]
        return hits[0] if len(hits) == 1 else (None, None)


async def _links(db: AsyncSession, bundle: Bundle) -> Links:
    clients_by_key: dict[str, set[int]] = defaultdict(set)
    clients_by_loose: dict[str, set[int]] = defaultdict(set)
    clients_by_words: dict[frozenset[str], set[int]] = defaultdict(set)
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.name,
                Client.display_name,
                Client.merged_into_client_id,
            )
        )
    ).all()
    merged = {client_id: target for client_id, _, _, target in rows}

    def final(client_id: int) -> int:
        seen: set[int] = set()
        while merged.get(client_id) and client_id not in seen:
            seen.add(client_id)
            client_id = merged[client_id]
        return client_id

    for client_id, name, display, _ in rows:
        for value in (name, display):
            key = normalize_client_name(value)
            if key:
                clients_by_key[key].add(final(client_id))
            loose = loose_client_name(value)
            if loose:
                clients_by_loose[loose].add(final(client_id))
            words = _client_words(value)
            if words:
                clients_by_words[words].add(final(client_id))

    contractors = {str(row.get("id")): row for row in bundle.rows("contractors")}
    contract_ids = {
        small_int(row.get("nexus_contract_id"))
        for row in contractors.values()
        if small_int(row.get("nexus_contract_id")) is not None
    }
    candidate_ids = {
        small_int(row.get("nexus_candidate_id"))
        for row in contractors.values()
        if small_int(row.get("nexus_candidate_id")) is not None
    }
    links = Links(
        clients_by_key=dict(clients_by_key),
        clients_by_loose=dict(clients_by_loose),
        clients_by_words=dict(clients_by_words),
        compass_clients={
            str(row.get("id")): str(row.get("name") or "")
            for row in bundle.rows("clients")
        },
        contractors=contractors,
    )
    if contract_ids:
        links.contract_candidate = dict(
            (
                await db.execute(
                    select(Contract.id, Contract.candidate_id).where(
                        Contract.id.in_(sorted(contract_ids))
                    )
                )
            ).all()
        )
    candidate_ids |= {cid for cid in links.contract_candidate.values() if cid}
    if candidate_ids:
        links.known_candidates = set(
            await db.scalars(
                select(Candidate.id).where(Candidate.id.in_(sorted(candidate_ids)))
            )
        )
        by_candidate: dict[int, list] = defaultdict(list)
        for contract_id, candidate_id, client_id, start, end in (
            await db.execute(
                select(
                    Contract.id,
                    Contract.candidate_id,
                    Contract.client_id,
                    Contract.start_date,
                    Contract.end_date,
                ).where(
                    Contract.candidate_id.in_(sorted(links.known_candidates)),
                    Contract.status.notin_(_SKIPPED_CONTRACT_STATUSES),
                )
            )
        ).all():
            by_candidate[candidate_id].append(
                (contract_id, final(client_id), start, end)
            )
        links.contracts = dict(by_candidate)
    if bundle.rows(CARDS) or bundle.rows(CONVERSATIONS):
        links.by_name = await card_linking.load_index(db)
    if bundle.rows(CONVERSATIONS):
        links.card_contracts = await _card_contracts(db, bundle)
    return links


async def _card_contracts(
    db: AsyncSession, bundle: Bundle
) -> dict[str, list[card_linking.ContractRow]]:
    """Kontrakty kart z paczki zapisanych już w NEXUSIE, po kontraktorze."""

    contractor_of = {
        card_id: str(row.get("contractor_id"))
        for row in bundle.rows(CARDS)
        if (card_id := parse_uuid(row.get("id"))) is not None
    }
    if not contractor_of:
        return {}
    by_contractor: dict[str, list[card_linking.ContractRow]] = defaultdict(list)
    for compass_card_id, client_id, contract_id, candidate_id, start, end in (
        await db.execute(
            select(
                TechCard.compass_card_id,
                TechCard.client_id,
                Contract.id,
                Contract.candidate_id,
                Contract.start_date,
                Contract.end_date,
            )
            .join(Contract, Contract.id == TechCard.contract_id)
            .where(
                TechCard.compass_card_id.in_(sorted(contractor_of, key=str)),
                Contract.status.notin_(_SKIPPED_CONTRACT_STATUSES),
            )
        )
    ).all():
        by_contractor[contractor_of[compass_card_id]].append(
            card_linking.ContractRow(
                contract_id=contract_id,
                candidate_id=candidate_id,
                client_id=client_id,
                start=start,
                end=end,
            )
        )
    return dict(by_contractor)


#: Słowa bez znaczenia przy porównaniu nazw: „ex” z „(ex Santander)” i „o”
#: z „z o.o.” (``loose_client_name`` zostawia je po kropkach).
_CLIENT_NOISE_WORDS = frozenset({"ex", "o"})


def _client_words(name: Optional[str]) -> frozenset[str]:
    return frozenset(loose_client_name(name).split()) - _CLIENT_NOISE_WORDS


def _month_end(year: Optional[int], month: Optional[int]) -> Optional[date]:
    if year is None or month is None or not (1 <= month <= 12 and 2000 <= year <= 2100):
        return None
    return date(year, month, month_calendar.monthrange(year, month)[1])


def _card_note(row: Mapping[str, Any]) -> Optional[str]:
    labelled = (
        ("Temat", row.get("title")),
        ("Komentarz do zadowolenia", row.get("satisfaction_comment")),
        ("Technologie stare i nowe", row.get("tech_old_new")),
        ("Dostawcy — uwagi", row.get("vendors_note")),
        ("Ubezpieczenie zawodowe", row.get("professional_insurance")),
    )
    lines = [f"{label}: {text(value)}" for label, value in labelled if text(value)]
    return "\n".join(lines) or None


async def _review_mapped(db: AsyncSession) -> dict[str, int]:
    """Nazwy z kolejki, które już zmapowano na umiejętność."""

    rows = await db.execute(
        select(SkillReviewItem.name_key, SkillReviewItem.skill_id).where(
            SkillReviewItem.status.in_(("mapped", "created")),
            SkillReviewItem.skill_id.is_not(None),
        )
    )
    return {key: skill_id for key, skill_id in rows.all()}


async def _plan_cards(
    db: AsyncSession, bundle: Bundle, people: People, links: Links, result: ImportPlan
) -> None:
    dictionary = await care_skills.load_dictionary(db)
    reviewed = await _review_mapped(db)
    technologies = {str(row.get("id")): row for row in bundle.rows("technologies")}
    vendors = {str(row.get("id")): row for row in bundle.rows("vendors")}
    areas = {str(row.get("id")): row for row in bundle.rows("client_areas")}
    card_techs: dict[str, list[str]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_technologies"):
        card_techs[str(row.get("card_id"))].append(str(row.get("technology_id")))
    card_vendors: dict[str, list[str]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_vendors"):
        card_vendors[str(row.get("card_id"))].append(str(row.get("vendor_id")))
    initiatives: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_initiatives"):
        name = text(row.get("name"), 200)
        if name:
            initiatives[str(row.get("card_id"))].append(
                {
                    "name": name,
                    "kind": str(row.get("kind") or "inne"),
                    "priority": str(row.get("priority") or "normalny"),
                }
            )
    sales = {
        str(row.get("card_id")): row for row in bundle.rows("tech_card_sales_status")
    }
    pairings: Counter[str] = Counter()
    no_client = 0

    for row in bundle.rows(CARDS):
        sid = source_id(CARDS, row)
        card_key = str(row.get("id"))
        compass_card_id = parse_uuid(row.get("id"))
        interview_on = parse_date(row.get("interview_date"))
        if compass_card_id is None or interview_on is None:
            result.rows.append(RowPlan(sid, "skip", "karta bez id albo daty rozmowy"))
            continue
        contractor = links.contractors.get(str(row.get("contractor_id"))) or {}
        person_name = text(contractor.get("full_name"), PERSON_NAME_MAX)
        options = links.narrow_clients(
            links.card_client_options(row.get("client_id")), person_name, interview_on
        )
        if len(options) != 1:
            no_client += 1
            result.rows.append(
                RowPlan(sid, "skip", "klient karty bez odpowiednika w NEXUSIE")
            )
            continue
        client_id = next(iter(options))
        notes: list[str] = []
        candidate_id = links.candidate_for(row.get("contractor_id"))
        contract_id = None
        if candidate_id is not None:
            contract_id, _ = links.contract_for(candidate_id, client_id, interview_on)
            if contract_id is None:
                notes.append(UNSURE_CONTRACT)
            pairing = "anchor" if contract_id is not None else "anchor_unsure"
        else:
            match = links.by_name.match(client_id, person_name, interview_on)
            contract_id = match.contract_id
            pairing = match.state
            notes.append(
                {
                    "auto": NAME_LINKED,
                    "suggested": NAME_SUGGESTED,
                    "none": NAME_NOT_FOUND,
                }[match.state]
            )
        pairings[pairing] += 1

        skill_ids: set[int] = set()
        unrecognized: dict[str, str] = {}
        for tech_id in card_techs[card_key]:
            tech = technologies.get(tech_id) or {}
            name = text(tech.get("name"))
            if not name:
                continue
            candidates = [name, *[str(alias) for alias in tech.get("aliases") or []]]
            found = next(
                (
                    dictionary.resolve(value)
                    for value in candidates
                    if dictionary.resolve(value) is not None
                ),
                None,
            )
            if found is None:
                found = reviewed.get(care_skills.name_key(name))
            if found is not None:
                skill_ids.add(found)
            else:
                unrecognized[care_skills.name_key(name)] = name
        if unrecognized:
            notes.append(UNKNOWN_SKILL)

        is_draft = bool(row.get("is_draft", True))
        status = row.get("status") if row.get("status") in CARD_STATUSES else None
        if not is_draft and status is None:
            is_draft = True
            notes.append("karta gotowa bez statusu — zapisana jako szkic")
        hiring = row.get("hiring") if isinstance(row.get("hiring"), bool) else None
        project_end_unknown = bool(row.get("project_end_unknown"))
        externals = small_int(row.get("team_externals"))
        satisfaction = small_int(row.get("satisfaction"))
        sale = sales.get(card_key, {})
        sales_status = (
            sale.get("status") if sale.get("status") in SALES_STATUSES else None
        )
        area = areas.get(str(row.get("client_area_id"))) or {}
        values = {
            "contract_id": contract_id,
            "client_id": client_id,
            "compass_person_name": person_name,
            "author_user_id": people.account(row.get("tcm_id"))
            or people.account(row.get("created_by")),
            "interview_on": interview_on,
            "status": status,
            "is_draft": is_draft,
            "finalized_at": None
            if is_draft
            else parse_datetime(row.get("finalized_at")),
            "satisfaction": satisfaction if satisfaction in range(1, 6) else None,
            "hiring": hiring,
            "hiring_source": row.get("hiring_source")
            if hiring is True and row.get("hiring_source") in HIRING_SOURCES
            else None,
            "hiring_roles": [
                role.strip()[:120]
                for role in (row.get("hiring_roles") or [])
                if isinstance(role, str) and role.strip()
            ]
            if hiring is True
            else [],
            "project_end_on": None
            if project_end_unknown
            else _month_end(
                small_int(row.get("project_end_year")),
                small_int(row.get("project_end_month")),
            ),
            "project_end_unknown": project_end_unknown,
            "team_size": text(row.get("team_size"), 80),
            "team_externals": externals
            if externals is not None and 0 <= externals <= 10000
            else None,
            "initiatives": initiatives[card_key],
            "memorable_quote": text(row.get("memorable_quote"), SHORT_TEXT_MAX),
            "note": _card_note(row),
            "sales_status": sales_status,
            "sales_deal_title": text(sale.get("atlas_deal_title"), SHORT_TEXT_MAX)
            if sales_status
            else None,
            "sales_reason": text(sale.get("reason")) if sales_status else None,
            "sales_handled_by": text(sale.get("handled_by_name"), 200)
            if sales_status
            else None,
            "sales_handled_at": parse_datetime(sale.get("handled_at"))
            if sales_status
            else None,
        }
        payload = {
            "compass_card_id": compass_card_id,
            "values": values,
            "skill_ids": sorted(skill_ids),
            "unrecognized": [unrecognized[key] for key in sorted(unrecognized)],
            "vendors": sorted(
                {
                    text((vendors.get(vendor_id) or {}).get("name"), 120) or ""
                    for vendor_id in card_vendors[card_key]
                }
                - {""}
            ),
            "area": text(area.get("name"), 120),
            "created_at": parse_datetime(row.get("created_at")),
        }
        reason = join_notes(notes)
        existing = await db.scalar(
            select(TechCard).where(TechCard.compass_card_id == compass_card_id)
        )
        if existing is None:
            action = "conflict" if contract_id is None or unrecognized else "create"
            payload["write"] = True
            result.rows.append(RowPlan(sid, action, reason, payload))
            continue
        payload["card_id"] = existing.id
        if existing.contract_id is not None and contract_id is None:
            # Kontrakt dopięty w NEXUSIE zostaje (import go nie odpina).
            values["contract_id"] = existing.contract_id
        changed = changed_fields(existing, values)
        same_relations = await _same_relations(db, existing, payload)
        if not changed and same_relations:
            result.rows.append(RowPlan(sid, "unchanged", reason, payload))
        elif set(changed) <= {"contract_id", "compass_person_name"} and same_relations:
            # Kontrakt znaleziony po poprzednim imporcie (kotwica w Compassie,
            # nowy kontrakt w NEXUSIE) albo karta sprzed kolumny z nazwiskiem.
            payload["write"] = True
            result.rows.append(RowPlan(sid, "update", reason, payload))
        else:
            result.rows.append(
                RowPlan(
                    sid,
                    "conflict",
                    "karta zmieniona w NEXUSIE albo w Compassie — bez nadpisania",
                    payload,
                )
            )
    # Same liczby (bez nazwisk): ile kart połączył import, ile czeka na DL.
    result.extra["cards"] = {
        "linked_by_anchor": pairings["anchor"],
        "linked_by_name": pairings["auto"],
        "to_confirm_with_suggestions": pairings["suggested"],
        "to_confirm_without_match": pairings["none"] + pairings["anchor_unsure"],
        "without_client": no_client,
    }


async def _same_relations(
    db: AsyncSession, card: TechCard, payload: Mapping[str, Any]
) -> bool:
    skills = sorted(
        await db.scalars(
            select(TechCardSkill.skill_id).where(TechCardSkill.card_id == card.id)
        )
    )
    vendor_keys = sorted(
        await db.scalars(
            select(TechVendor.name_key)
            .join(TechCardVendor, TechCardVendor.vendor_id == TechVendor.id)
            .where(TechCardVendor.card_id == card.id)
        )
    )
    area_key = None
    if card.client_area_id is not None:
        area_key = await db.scalar(
            select(ClientArea.name_key).where(ClientArea.id == card.client_area_id)
        )
    wanted_area = care_skills.name_key(payload["area"]) if payload["area"] else None
    return (
        skills == payload["skill_ids"]
        and vendor_keys == sorted(care_skills.name_key(v) for v in payload["vendors"])
        and area_key == wanted_area
        and sorted(card.unrecognized_skills or [])
        == sorted(care_skills.name_key(v) for v in payload["unrecognized"])
    )


def _conversation_contract(
    links: Links, row: Mapping[str, Any], day: date
) -> tuple[Optional[int], str, list[str]]:
    """(kontrakt, sposób połączenia, powody) rozmowy — kotwica, karta, nazwisko."""

    contractor_id = row.get("contractor_id")
    candidate_id = links.candidate_for(contractor_id)
    if candidate_id is not None:
        client_id = links.client_for_name(row.get("client_snapshot"))
        contract_id, _ = links.contract_for(candidate_id, client_id, day)
        if contract_id is None:
            return None, "anchor_unsure", [CONVERSATION_UNSURE]
        return contract_id, "anchor", []
    contractor = links.contractors.get(str(contractor_id)) or {}
    person_name = text(contractor.get("full_name"), PERSON_NAME_MAX)
    client_name = text(row.get("client_snapshot")) or text(
        contractor.get("current_client")
    )
    options = links.narrow_clients(
        links.client_options_for_name(client_name), person_name, day
    )
    if len(options) != 1:
        return None, "no_client", [CONVERSATION_NO_CLIENT]
    client_id = next(iter(options))
    contract_id = links.card_contract_for(contractor_id, client_id, day)
    if contract_id is not None:
        return contract_id, "card", [CONVERSATION_BY_CARD]
    match = links.by_name.match(client_id, person_name, day)
    if match.contract_id is not None:
        return match.contract_id, "auto", [NAME_LINKED]
    if match.suggestions:
        return None, "suggested", [CONVERSATION_WAITS]
    return None, "none", [NAME_NOT_FOUND]


async def _plan_conversations(
    db: AsyncSession, bundle: Bundle, people: People, links: Links, result: ImportPlan
) -> None:
    pairings: Counter[str] = Counter()
    for row in bundle.rows(CONVERSATIONS):
        sid = source_id(CONVERSATIONS, row)
        occurred_on = parse_date(row.get("conversation_date"))
        if parse_uuid(row.get("id")) is None or occurred_on is None:
            result.rows.append(RowPlan(sid, "skip", "rozmowa bez id albo daty"))
            continue
        contract_id, pairing, notes = _conversation_contract(links, row, occurred_on)
        pairings[pairing] += 1
        if contract_id is None:
            action = "skip" if pairing == "no_client" else "conflict"
            result.rows.append(RowPlan(sid, action, join_notes(notes)))
            continue
        follow_up = parse_date(row.get("follow_up_date"))
        if follow_up is not None and follow_up < occurred_on:
            follow_up = None
            notes.append("termin kontaktu przed datą rozmowy — pominięty")
        header = " · ".join(
            value
            for value in (
                CATEGORY_LABELS.get(str(row.get("category"))),
                STATUS_LABELS.get(str(row.get("status"))),
            )
            if value
        )
        body = text(row.get("note"))
        note = "\n\n".join(part for part in (header, body) if part)[:NOTE_MAX] or None
        values = {
            "contract_id": contract_id,
            "author_user_id": people.account(row.get("tcm_id"))
            or people.account(row.get("created_by")),
            "occurred_on": occurred_on,
            "channel": "phone",
            "note": note,
            "follow_up_on": follow_up,
        }
        compass_source_id = str(row.get("id"))
        payload = {
            "compass_source_id": compass_source_id,
            "values": values,
            "created_at": parse_datetime(row.get("created_at")),
        }
        existing = await db.scalar(
            select(CareConversation).where(
                CareConversation.compass_source_id == compass_source_id
            )
        )
        reason = join_notes(notes)
        if existing is None:
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        payload["conversation_id"] = existing.id
        action = "update" if changed_fields(existing, values) else "unchanged"
        result.rows.append(RowPlan(sid, action, reason, payload))
    # Same liczby (bez nazwisk): ile rozmów trafiło na oś, ile czeka.
    result.extra["conversations"] = {
        "linked_by_anchor": pairings["anchor"],
        "linked_by_card": pairings["card"],
        "linked_by_name": pairings["auto"],
        "waiting_with_suggestions": pairings["suggested"],
        "waiting_without_match": pairings["none"] + pairings["anchor_unsure"],
        "without_client": pairings["no_client"],
    }


def rhythm_level(
    status: Any,
    days: Any,
    program_ends_on: Optional[date],
    program_done: bool,
    day: date,
) -> Optional[tuple[str, Optional[date]]]:
    """(poziom, do kiedy) z ustawień opieki Compassa; ``None`` = bez okresu."""

    if status == "paused":
        return "paused", None
    if status != "active":
        return None
    if program_ends_on is not None and not program_done and program_ends_on > day:
        return "biweekly", program_ends_on
    cadence = small_int(days)
    if cadence is None:
        return None
    if cadence <= 14:
        return "biweekly", None
    if cadence <= 31:
        return "monthly", None
    if cadence <= 93:
        return "quarterly", None
    return "milestones", None


def _sure_contract(
    links: Links, contractor_id: Any, day: date
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(kandydat, kontrakt, klient) kontraktora w dniu eksportu."""

    candidate_id = links.candidate_for(contractor_id)
    if candidate_id is None:
        return None, None, None
    row = links.contractors.get(str(contractor_id)) or {}
    contract_id, client_id = links.contract_for(
        candidate_id, links.client_for_name(row.get("current_client")), day
    )
    return candidate_id, contract_id, client_id


async def _plan_rhythms(
    db: AsyncSession, bundle: Bundle, links: Links, result: ImportPlan, day: date
) -> None:
    for row in bundle.rows(RHYTHMS):
        sid = f"{RHYTHMS}:{row.get('contractor_id')}"
        candidate_id, contract_id, _ = _sure_contract(
            links, row.get("contractor_id"), day
        )
        if candidate_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_LINK))
            continue
        if contract_id is None:
            result.rows.append(RowPlan(sid, "conflict", RHYTHM_UNSURE))
            continue
        status = row.get("monitoring_status")
        if status == "inactive":
            result.rows.append(RowPlan(sid, "skip", RHYTHM_INACTIVE))
            continue
        mapped = rhythm_level(
            status,
            row.get("check_in_cadence_days"),
            parse_date(row.get("onboarding_program_ends_on")),
            row.get("onboarding_program_completed_at") not in (None, ""),
            day,
        )
        if mapped is None:
            result.rows.append(RowPlan(sid, "skip", RHYTHM_UNKNOWN))
            continue
        level, until_on = mapped
        days = small_int(row.get("check_in_cadence_days"))
        values = {
            "level": level,
            "until_on": until_on,
            "note": "Z Compassa: wstrzymany."
            if level == "paused"
            else f"Z Compassa: kontakt co {days} dni."
            if days
            else "Z Compassa.",
        }
        payload = {"contract_id": contract_id, "values": values, "starts_on": day}
        previous = await mapped_target(db, MODULE, sid)
        existing = (
            await db.get(CareCadencePeriod, int(previous.target_id))
            if previous is not None
            else None
        )
        manual = await db.scalar(
            select(CareCadencePeriod.id).where(
                CareCadencePeriod.contract_id == contract_id,
                CareCadencePeriod.reason != "imported",
            )
        )
        if manual is not None:
            result.rows.append(RowPlan(sid, "conflict", RHYTHM_SET_IN_NEXUS))
            continue
        if existing is None:
            result.rows.append(RowPlan(sid, "create", "", payload))
            continue
        payload["period_id"] = existing.id
        action = "update" if changed_fields(existing, values) else "unchanged"
        result.rows.append(RowPlan(sid, action, "", payload))


async def _plan_owners(
    db: AsyncSession,
    bundle: Bundle,
    people: People,
    links: Links,
    result: ImportPlan,
    day: date,
) -> None:
    owners = [row for row in bundle.rows(OWNERS) if row.get("owner_tcm_id")]
    contract_ids: dict[str, Optional[int]] = {}
    for row in owners:
        _, contract_id, _ = _sure_contract(links, row.get("id"), day)
        contract_ids[str(row.get("id"))] = contract_id
    known = await care_access.contracts_by_id(
        db, [cid for cid in contract_ids.values() if cid is not None]
    )
    excluded = await owner_pool.excluded_ids(db)
    for row in owners:
        sid = source_id(OWNERS, row)
        if links.candidate_for(row.get("id")) is None:
            result.rows.append(RowPlan(sid, "skip", NO_LINK))
            continue
        contract = known.get(contract_ids[str(row.get("id"))] or -1)
        if contract is None:
            result.rows.append(RowPlan(sid, "conflict", OWNER_UNSURE))
            continue
        account_id = people.account(row.get("owner_tcm_id"))
        if account_id is None:
            result.rows.append(RowPlan(sid, "conflict", OWNER_NO_ACCOUNT))
            continue
        account = await db.get(User, account_id)
        if account is not None and account.id in excluded:
            result.rows.append(RowPlan(sid, "conflict", OWNER_EXCLUDED))
            continue
        if await care_access.owner_problem(
            db, account, client_ids=[contract.client_id]
        ):
            result.rows.append(RowPlan(sid, "conflict", OWNER_NOT_CARE))
            continue
        payload = {"contract_id": contract.id, "owner_id": account_id}
        if contract.explicit_owner_id == account_id:
            result.rows.append(RowPlan(sid, "unchanged", "", payload))
        elif contract.explicit_owner_id is not None:
            result.rows.append(RowPlan(sid, "conflict", OWNER_SET_IN_NEXUS))
        else:
            result.rows.append(RowPlan(sid, "create", "", payload))


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    links = await _links(db, bundle)
    # Dzień eksportu: na nim sprawdzamy okres umowy i od niego liczy się rytm.
    day = local_date(bundle.exported_at) or business_today()
    await _plan_cards(db, bundle, people, links, result)
    await _plan_conversations(db, bundle, people, links, result)
    await _plan_rhythms(db, bundle, links, result, day)
    await _plan_owners(db, bundle, people, links, result, day)
    return result


async def _upsert_by_key(
    db: AsyncSession, model, values: dict[str, Any], keys: list[str]
) -> int:
    statement = (
        insert(model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=keys)
        .returning(model.id)
    )
    created = (await db.execute(statement)).scalar_one_or_none()
    if created is not None:
        return created
    query = select(model.id)
    for key in keys:
        query = query.where(getattr(model, key) == values[key])
    return (await db.scalars(query)).one()


async def _write_card(db: AsyncSession, row: RowPlan) -> TechCard:
    payload = row.payload
    values = payload["values"]
    if "card_id" in payload:
        card = await db.get(TechCard, payload["card_id"])
        for key, value in values.items():
            setattr(card, key, value)
    else:
        card = TechCard(compass_card_id=payload["compass_card_id"], **values)
        if payload["created_at"] is not None:
            card.created_at = payload["created_at"]
        db.add(card)
    card.client_area_id = (
        await _upsert_by_key(
            db,
            ClientArea,
            {
                "client_id": values["client_id"],
                "name": payload["area"],
                "name_key": care_skills.name_key(payload["area"]),
            },
            ["client_id", "name_key"],
        )
        if payload["area"]
        else None
    )
    await db.flush()
    resolved = await care_skills.resolve_card_names(
        db,
        payload["unrecognized"],
        previous_unrecognized=card.unrecognized_skills or [],
        actor_id=None,
    )
    card.unrecognized_skills = resolved.unrecognized
    skill_ids = set(payload["skill_ids"]) | resolved.skill_ids
    await db.execute(delete(TechCardSkill).where(TechCardSkill.card_id == card.id))
    if skill_ids:
        await db.execute(
            insert(TechCardSkill).values(
                [{"card_id": card.id, "skill_id": sid} for sid in sorted(skill_ids)]
            )
        )
    vendor_ids = [
        await _upsert_by_key(
            db,
            TechVendor,
            {"name": name, "name_key": care_skills.name_key(name)},
            ["name_key"],
        )
        for name in payload["vendors"]
    ]
    await db.execute(delete(TechCardVendor).where(TechCardVendor.card_id == card.id))
    if vendor_ids:
        await db.execute(
            insert(TechCardVendor).values(
                [
                    {"card_id": card.id, "vendor_id": vid}
                    for vid in sorted(set(vendor_ids))
                ]
            )
        )
    await db.flush()
    return card


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {
        "cards_written": 0,
        "cards_without_contract": 0,
        "conversations_written": 0,
        "rhythms_written": 0,
        "owners_written": 0,
    }
    for row in module_plan.rows:
        table = row.source_id.split(":", 1)[0]
        if table == CARDS and row.payload.get("write"):
            card = await _write_card(db, row)
            written["cards_written"] += 1
            if card.contract_id is None:
                written["cards_without_contract"] += 1
            target_table, target_id = "tech_cards", card.id
        elif table == CONVERSATIONS and row.action in ("create", "update"):
            payload = row.payload
            if "conversation_id" in payload:
                conversation = await db.get(
                    CareConversation, payload["conversation_id"]
                )
                for key, value in payload["values"].items():
                    setattr(conversation, key, value)
            else:
                conversation = CareConversation(
                    compass_source_id=payload["compass_source_id"], **payload["values"]
                )
                if payload["created_at"] is not None:
                    conversation.created_at = payload["created_at"]
                db.add(conversation)
            await db.flush()
            written["conversations_written"] += 1
            target_table, target_id = "care_conversations", conversation.id
        elif table == RHYTHMS and row.action in ("create", "update"):
            payload = row.payload
            if "period_id" in payload:
                period = await db.get(CareCadencePeriod, payload["period_id"])
                for key, value in payload["values"].items():
                    setattr(period, key, value)
            else:
                period = CareCadencePeriod(
                    contract_id=payload["contract_id"],
                    starts_on=payload["starts_on"],
                    reason="imported",
                    created_by=actor_user_id,
                    **payload["values"],
                )
                db.add(period)
            await db.flush()
            written["rhythms_written"] += 1
            target_table, target_id = "care_cadence_periods", period.id
        elif table == OWNERS and row.action == "create":
            payload = row.payload
            await db.execute(
                CONTRACTS_CARE.update()
                .where(
                    CONTRACTS_CARE.c.id == payload["contract_id"],
                    CONTRACTS_CARE.c.care_owner_user_id.is_(None),
                )
                .values(care_owner_user_id=payload["owner_id"])
            )
            audit.record(
                db,
                actor_user_id=actor_user_id,
                subject_user_id=payload["owner_id"],
                entity_type="contract",
                entity_id=payload["contract_id"],
                action="care.owner_set",
                details={
                    "previous": None,
                    "owner": payload["owner_id"],
                    "reason": None,
                    "source": "compass_import",
                },
            )
            written["owners_written"] += 1
            target_table, target_id = "contracts", payload["contract_id"]
        else:
            continue
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table=target_table,
            target_id=target_id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
