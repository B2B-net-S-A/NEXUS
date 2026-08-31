"""Reguły CV per klient — odczyt, edycja i zatwierdzanie.

Dwa wejścia, jedna prawda w bazie:

* profil klienta (``/api/clients/{id}/cv-rule``) — codzienna edycja przy
  kliencie, którego reguła dotyczy;
* przegląd zbiorczy (``/api/settings/cv-rules``) — ekran weryfikacji seeda,
  gdzie widać wszystkie 14 szablonów Championa obok siebie razem ze statusem.

``confirmed_at IS NULL`` znaczy **propozycja, która nie obowiązuje**. Generator
czyta wyłącznie reguły zatwierdzone (``resolve_client_rule``), więc zasiane
dopasowanie po nazwie klienta nie może wejść w życie bez decyzji człowieka.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, TacPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.help_material import HelpMaterial
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


class ChampionTemplateRow(BaseModel):
    """Pozycja ekranu weryfikacji: szablon Championa + stan jego reguły."""

    seed_key: str
    label: str
    template_url: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    filename_pattern: Optional[str] = None
    cv_language: Optional[str] = None
    requires_en_copy: bool = False
    is_active: bool = False
    # "active" | "proposed" | "unassigned"
    state: str


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
    """Zapisz regułę. **Zapis NIE zatwierdza** — świeżo wpisana reguła nadal
    czeka na osobne kliknięcie „Zatwierdź".

    Edycja obowiązującej reguły ZDEJMUJE zatwierdzenie. Inaczej zmiana wzoru
    nazwy pliku wchodziłaby na produkcję bez niczyjej decyzji, a właśnie po to
    ten stan istnieje.
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
    rule.confirmed_at = None
    rule.confirmed_by = None

    await db.commit()
    await db.refresh(rule)
    return _to_read(rule, client_id=cid, client_name=cname)


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


@router.get("/settings/cv-rules", response_model=list[ChampionTemplateRow])
async def list_champion_template_rules(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> list[ChampionTemplateRow]:
    """Ekran weryfikacji: 14 szablonów Championa i stan reguły każdego z nich.

    Pozycja bez wiersza reguły dostaje stan ``unassigned`` — seed nie zasiał jej,
    bo nazwa klienta pasowała do zera albo do wielu rekordów (samych bytów „BNP"
    jest siedem). Ukrycie takiej pozycji sprawiłoby, że brak reguły wyglądałby
    identycznie jak jej nieistnienie i nikt by go nie uzupełnił.
    """
    seed_keys = [key for key, _ in CHAMPION_SEED_KEYS]

    rules = (
        await db.execute(
            select(
                ClientCvRule,
                func.coalesce(
                    func.nullif(func.trim(Client.display_name), ""), Client.name
                ),
            )
            .outerjoin(Client, Client.id == ClientCvRule.client_id)
            .where(ClientCvRule.seed_key.in_(seed_keys))
        )
    ).all()
    by_key = {r.seed_key: (r, cname) for r, cname in rules}

    urls = dict(
        (
            await db.execute(
                select(HelpMaterial.slug, HelpMaterial.url).where(
                    HelpMaterial.slug.in_(seed_keys)
                )
            )
        ).all()
    )

    out: list[ChampionTemplateRow] = []
    for key, label in CHAMPION_SEED_KEYS:
        entry = by_key.get(key)
        if entry is None:
            out.append(
                ChampionTemplateRow(
                    seed_key=key,
                    label=label,
                    template_url=urls.get(key),
                    state="unassigned",
                )
            )
            continue
        rule, client_name = entry
        active = rule.confirmed_at is not None
        out.append(
            ChampionTemplateRow(
                seed_key=key,
                label=label,
                template_url=urls.get(key),
                client_id=rule.client_id,
                client_name=client_name,
                filename_pattern=rule.filename_pattern,
                cv_language=rule.cv_language,
                requires_en_copy=bool(rule.requires_en_copy),
                is_active=active,
                state="active" if active else "proposed",
            )
        )
    return out
