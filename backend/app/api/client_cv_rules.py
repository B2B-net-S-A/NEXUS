"""Reguły CV per klient — odczyt, edycja i zatwierdzanie.

Dwa wejścia, jedna prawda w bazie:

* profil klienta (``/api/clients/{id}/cv-rule``) — codzienna edycja przy
  kliencie, którego reguła dotyczy;
* przegląd zbiorczy (``/api/settings/cv-rules``) — WSZYSTKIE reguły w bazie
  (nie tylko 14 zasianych z szablonów Championa) plus szablony, które nie mają
  jeszcze reguły. Z tego ekranu Delivery Lead / TAC zakłada regułę dla
  dowolnego klienta, edytuje ją, zatwierdza i usuwa — bez wchodzenia w okno
  edycji firmy.

``confirmed_at IS NULL`` znaczy **propozycja, która nie obowiązuje**. Generator
czyta wyłącznie reguły zatwierdzone (``resolve_client_rule``), więc zasiane
dopasowanie po nazwie klienta nie może wejść w życie bez decyzji człowieka.
Własną regułę autor zatwierdza tym samym zapisem (``confirm=true``) — osobny
krok był potrzebny propozycjom z seeda, nie regule, którą ktoś właśnie
świadomie wpisał.

Bramka zapisu to ``TacPlus`` (admin / delivery_lead / tac) i CELOWO nie jest
zawężana do portfela DL: to lustro ``PATCH /api/clients/{id}`` — reguła CV
jest konfiguracją klienta, a Delivery Lead edytuje tu każdego klienta tak samo,
jak edytuje jego kartę. Filtr „moi klienci" jest wygodą interfejsu, nie granicą.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import OperationalUser, TacPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.help_material import HelpMaterial
from app.models.user import User
from app.services.cv_generator_b2b.client_rules import (
    KNOWN_TOKENS,
    build_filename,
    describe_rule,
    snapshot_rule,
)

router = APIRouter(tags=["client-cv-rules"])

# Slugi szablonów „Profil Championa — per klient" z migracji 0219. Ekran
# weryfikacji pokazuje WSZYSTKIE czternaście, także te, dla których seed nie
# stworzył wiersza (nazwa klienta wieloznaczna) — inaczej brakująca reguła
# byłaby nieodróżnialna od nieistniejącej.
CHAMPION_SEED_KEYS: tuple[tuple[str, str], ...] = (
    ("profil-championa-wzor-alior-docx", "ALIOR"),
    ("profil-championa-wzor-bank-pocztowy-docx", "Bank Pocztowy"),
    ("profil-championa-wzor-bik-docx", "BIK"),
    ("profil-championa-wzor-bnp-paribas-docx", "BNP PARIBAS"),
    ("profil-championa-wzor-credit-agricole-docx", "Credit Agricole"),
    ("profil-championa-wzor-energa-docx", "ENERGA"),
    ("profil-championa-wzor-kir-docx", "KIR"),
    ("profil-championa-wzor-nordea-docx", "Nordea"),
    ("profil-championa-wzor-orlen-docx", "ORLEN"),
    ("profil-championa-wzor-pansa-docx", "PANSA"),
    ("profil-championa-wzor-pfron-docx", "PFRON"),
    ("profil-championa-wzor-pko-bp-docx", "PKO BP"),
    ("profil-championa-wzor-santander-docx", "SANTANDER"),
    ("profil-championa-wzor-tauron-docx", "Tauron"),
)


class ClientCvRulePayload(BaseModel):
    """Wejście edycji reguły. Wszystkie pola opcjonalne — pusty wzór znaczy
    „ten klient nie ma własnej nazwy pliku", nie „błąd"."""

    filename_pattern: Optional[str] = Field(default=None, max_length=300)
    spaces_to_underscores: bool = False
    cv_language: Optional[str] = Field(default=None)
    requires_en_copy: bool = False
    requires_rodo_consent_block: bool = False
    notes: Optional[str] = None
    # Zatwierdź tym samym zapisem. Osobne kliknięcie „Zatwierdź" chroniło
    # PROPOZYCJE z seeda (dopasowane po nazwie, więc możliwie błędne). Reguła,
    # którą Delivery Lead właśnie wpisał ręcznie, JEST jego decyzją — kazanie mu
    # klikać drugi raz nie dodaje żadnej weryfikacji, a gubi ludzi: zapisana
    # i niezatwierdzona reguła wygląda w generatorze jak jej brak.
    confirm: bool = False

    @field_validator("cv_language")
    @classmethod
    def _known_language(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        if value not in ("pl", "en"):
            raise ValueError("Język CV może być tylko „pl” albo „en”.")
        return value

    @field_validator("filename_pattern")
    @classmethod
    def _known_tokens(cls, value: Optional[str]) -> Optional[str]:
        """Odrzuć nieznany token ZANIM trafi do nazwy pliku.

        Bez tej walidacji literówka („{STANOWISKA}") przeszłaby przez zapis
        i wyszła dopiero na dokumencie wysłanym klientowi — jako dosłowny
        nawias klamrowy w nazwie pliku.
        """
        if not value or not value.strip():
            return None
        unknown = [
            tok
            for tok in re.findall(r"\{[A-Za-z_]+\}", value)
            if tok not in KNOWN_TOKENS
        ]
        if unknown:
            raise ValueError(
                "Nieznane pola we wzorze: "
                + ", ".join(sorted(set(unknown)))
                + ". Dozwolone: "
                + ", ".join(KNOWN_TOKENS)
                + "."
            )
        return value.strip()


class ClientCvRuleRead(BaseModel):
    client_id: int
    client_name: Optional[str] = None
    filename_pattern: Optional[str] = None
    spaces_to_underscores: bool = False
    cv_language: Optional[str] = None
    requires_en_copy: bool = False
    requires_rodo_consent_block: bool = False
    notes: Optional[str] = None
    seed_key: Optional[str] = None
    confirmed_at: Optional[str] = None
    confirmed_by_name: Optional[str] = None
    # Czy reguła OBOWIĄZUJE. Front nie może tego wyliczać z `confirmed_at` sam,
    # bo to jedyne miejsce, w którym „propozycja" i „reguła" się rozchodzą.
    is_active: bool = False
    # Opis polityki do banera w generatorze. Pusty string = klient wybrany, ale
    # bez zatwierdzonych reguł; `null` = brak wiersza w ogóle.
    client_policy: Optional[str] = None
    # Podgląd nazwy pliku na przykładowych danych — rekruter widzi skutek wzoru
    # zanim cokolwiek wygeneruje.
    filename_preview: Optional[str] = None


class ClientCvRuleListItem(ClientCvRuleRead):
    """Wiersz przeglądu zbiorczego: reguła + szablon Championa, z którego
    została zasiana (pusty dla reguł założonych ręcznie)."""

    template_label: Optional[str] = None
    template_url: Optional[str] = None
    updated_at: Optional[str] = None


class UnassignedChampionTemplate(BaseModel):
    """Szablon Championa BEZ wiersza reguły — seed nie zasiał go, bo nazwa
    klienta pasowała do zera albo do wielu rekordów."""

    seed_key: str
    label: str
    template_url: Optional[str] = None


class CvRulesOverview(BaseModel):
    rules: list[ClientCvRuleListItem]
    unassigned_templates: list[UnassignedChampionTemplate]


_PREVIEW_POSITION = "Analityk Biznesowy"
_PREVIEW_NAME = "Jan Kowalski"
_PREVIEW_PROJECT = "4521"


def _preview(rule: Optional[ClientCvRule]) -> Optional[str]:
    result = build_filename(
        snapshot_rule(rule),
        position=_PREVIEW_POSITION,
        candidate_name=_PREVIEW_NAME,
        project=_PREVIEW_PROJECT,
    )
    return result.filename if result else None


def _to_read(
    rule: Optional[ClientCvRule],
    *,
    client_id: int,
    client_name: Optional[str],
    confirmed_by_name: Optional[str] = None,
) -> ClientCvRuleRead:
    if rule is None:
        return ClientCvRuleRead(
            client_id=client_id, client_name=client_name, client_policy=None
        )
    active = rule.confirmed_at is not None
    return ClientCvRuleRead(
        client_id=client_id,
        client_name=client_name,
        filename_pattern=rule.filename_pattern,
        spaces_to_underscores=bool(rule.spaces_to_underscores),
        cv_language=rule.cv_language,
        requires_en_copy=bool(rule.requires_en_copy),
        requires_rodo_consent_block=bool(rule.requires_rodo_consent_block),
        notes=rule.notes,
        seed_key=rule.seed_key,
        confirmed_at=rule.confirmed_at.isoformat() if rule.confirmed_at else None,
        confirmed_by_name=confirmed_by_name,
        is_active=active,
        # Niezatwierdzona reguła NIE opisuje polityki — generator jej nie zna,
        # więc twierdzenie „zastosowano" byłoby nieprawdą.
        client_policy=describe_rule(snapshot_rule(rule)) if active else "",
        filename_preview=_preview(rule) if active else None,
    )


async def _client_or_404(db: AsyncSession, client_id: int) -> tuple[int, str]:
    row = (
        await db.execute(
            select(
                Client.id,
                func.coalesce(
                    func.nullif(func.trim(Client.display_name), ""), Client.name
                ),
            ).where(Client.id == client_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Klient nie został znaleziony.")
    return row[0], row[1]


@router.get("/clients/{client_id}/cv-rule", response_model=ClientCvRuleRead)
async def get_client_cv_rule(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Reguła CV klienta — także niezatwierdzona.

    Bramka jest lustrem `GET /api/clients/{id}` (`OperationalUser`), bo to
    konfiguracja klienta, a nie dana kandydata. Nie zawęża to nikomu dostępu
    do banera w generatorze: `CANDIDATE_DOCUMENT_ROLES` (bramka obu ścieżek
    generacji) to DOKŁADNIE ten sam zestaw siedmiu ról operacyjnych.

    Samo uwierzytelnienie nie wystarcza — `notes` niosą standardy handlowe
    klienta (SLA, off-limit, adresy biur), a `test_route_authz_contract`
    świadomie nie wpuszcza nowych tras bez bramki zasobu.
    """
    cid, cname = await _client_or_404(db, client_id)
    rule = (
        await db.execute(select(ClientCvRule).where(ClientCvRule.client_id == cid))
    ).scalar_one_or_none()
    return _to_read(rule, client_id=cid, client_name=cname)


@router.put("/clients/{client_id}/cv-rule", response_model=ClientCvRuleRead)
async def upsert_client_cv_rule(
    client_id: int,
    payload: ClientCvRulePayload,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Zapisz regułę.

    Domyślnie zapis **NIE zatwierdza** — reguła zostaje propozycją, dopóki ktoś
    jej nie zatwierdzi. Edycja obowiązującej reguły ZDEJMUJE zatwierdzenie:
    inaczej zmiana wzoru nazwy pliku wchodziłaby na produkcję bez niczyjej
    decyzji, a właśnie po to ten stan istnieje.

    ``confirm=true`` zatwierdza tym samym zapisem — decyzja jest w tym samym
    kliknięciu, więc osobny krok nie wnosiłby nic poza drugim kliknięciem.
    """
    cid, cname = await _client_or_404(db, client_id)
    rule = (
        await db.execute(select(ClientCvRule).where(ClientCvRule.client_id == cid))
    ).scalar_one_or_none()
    if rule is None:
        rule = ClientCvRule(client_id=cid)
        db.add(rule)

    rule.filename_pattern = payload.filename_pattern
    rule.spaces_to_underscores = payload.spaces_to_underscores
    rule.cv_language = payload.cv_language
    rule.requires_en_copy = payload.requires_en_copy
    rule.requires_rodo_consent_block = payload.requires_rodo_consent_block
    rule.notes = payload.notes
    if payload.confirm:
        rule.confirmed_at = datetime.now(timezone.utc)
        rule.confirmed_by = current_user.id
    else:
        rule.confirmed_at = None
        rule.confirmed_by = None

    await db.commit()
    await db.refresh(rule)
    return _to_read(
        rule,
        client_id=cid,
        client_name=cname,
        confirmed_by_name=current_user.name if payload.confirm else None,
    )


@router.post("/clients/{client_id}/cv-rule/confirm", response_model=ClientCvRuleRead)
async def confirm_client_cv_rule(
    client_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Zatwierdź regułę — od tej chwili generator ją stosuje."""
    cid, cname = await _client_or_404(db, client_id)
    rule = (
        await db.execute(select(ClientCvRule).where(ClientCvRule.client_id == cid))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=404,
            detail="Ten klient nie ma jeszcze reguł CV — najpierw je zapisz.",
        )
    rule.confirmed_at = datetime.now(timezone.utc)
    rule.confirmed_by = current_user.id
    await db.commit()
    await db.refresh(rule)
    return _to_read(
        rule, client_id=cid, client_name=cname, confirmed_by_name=current_user.name
    )


@router.delete("/clients/{client_id}/cv-rule", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_cv_rule(
    client_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Usuń regułę — klient wraca do globalnej nazwy pliku i wolnego wyboru
    języka."""
    cid, _ = await _client_or_404(db, client_id)
    rule = (
        await db.execute(select(ClientCvRule).where(ClientCvRule.client_id == cid))
    ).scalar_one_or_none()
    if rule is not None:
        await db.delete(rule)
        await db.commit()


_CLIENT_DISPLAY_NAME = func.coalesce(
    func.nullif(func.trim(Client.display_name), ""), Client.name
)


@router.get("/settings/cv-rules", response_model=CvRulesOverview)
async def cv_rules_overview(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CvRulesOverview:
    """Przegląd zbiorczy: KAŻDA reguła w bazie + szablony Championa bez reguły.

    Do 09.2026 ten endpoint zwracał wyłącznie 14 zasianych szablonów, więc
    reguła założona ręcznie dla piętnastego klienta była na tym ekranie
    NIEWIDOCZNA — a ekran nie miał żadnej akcji, tylko odsyłał do okna edycji
    firmy. Teraz lista jest pełna, a szablony bez wiersza idą osobno: ukrycie
    ich sprawiłoby, że brak reguły wyglądałby identycznie jak jej nieistnienie
    i nikt by go nie uzupełnił.

    Odczyt jest nieoskopowany także dla Delivery Leada (lustro
    ``GET /api/clients/{id}/cv-rule``) — zawężenie do portfela robi interfejs,
    jako filtr, który da się wyłączyć.
    """
    seed_labels = dict(CHAMPION_SEED_KEYS)
    seed_keys = list(seed_labels)

    confirmed_by_user = aliased(User)
    rows = (
        await db.execute(
            select(ClientCvRule, _CLIENT_DISPLAY_NAME, confirmed_by_user.name)
            .join(Client, Client.id == ClientCvRule.client_id)
            .outerjoin(
                confirmed_by_user, confirmed_by_user.id == ClientCvRule.confirmed_by
            )
            .order_by(func.lower(_CLIENT_DISPLAY_NAME), ClientCvRule.id)
        )
    ).all()

    urls = dict(
        (
            await db.execute(
                select(HelpMaterial.slug, HelpMaterial.url).where(
                    HelpMaterial.slug.in_(seed_keys)
                )
            )
        ).all()
    )

    rules: list[ClientCvRuleListItem] = []
    seen_seed_keys: set[str] = set()
    for rule, client_name, confirmed_by_name in rows:
        base = _to_read(
            rule,
            client_id=rule.client_id,
            client_name=client_name,
            confirmed_by_name=confirmed_by_name,
        )
        if rule.seed_key:
            seen_seed_keys.add(rule.seed_key)
        rules.append(
            ClientCvRuleListItem(
                **base.model_dump(),
                template_label=seed_labels.get(rule.seed_key or ""),
                template_url=urls.get(rule.seed_key) if rule.seed_key else None,
                updated_at=rule.updated_at.isoformat() if rule.updated_at else None,
            )
        )

    unassigned = [
        UnassignedChampionTemplate(
            seed_key=key, label=label, template_url=urls.get(key)
        )
        for key, label in CHAMPION_SEED_KEYS
        if key not in seen_seed_keys
    ]
    return CvRulesOverview(rules=rules, unassigned_templates=unassigned)
