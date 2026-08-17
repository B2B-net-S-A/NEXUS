"""Help materials API — materiały firmowe w zakładce Pomoc.

Czytelne dla wszystkich zalogowanych; edycja zarezerwowana dla admina —
dokładnie jak ``procedures``. Search po tytule, kategorii, opisie i temacie
szablonu (ILIKE).

Pozycja niesie link do dokumentu w SharePoincie (``url``), treść szablonu
(``template_subject`` + ``template_body``) — np. zaproszenie kalendarzowe, które
nie jest plikiem — albo OBA naraz. Dlatego ``url`` jest opcjonalny, ale wiersz
bez adresu i bez treści szablonu jest odrzucany (422) lustrzanie do CHECK-a
``ck_help_materials_link_or_template`` (``url IS NOT NULL OR template_body IS
NOT NULL``): taka pozycja wyrenderowałaby się w Pomocy bez żadnej akcji, co
czyta się jak awaria, a nie jak pusta treść. To świadomie OR, nie XOR — link
z dołączoną treścią (np. wzór dokumentu + gotowa notatka) jest legalny, a FE
pokazuje wtedy obie akcje.

``slug`` jest NIEZMIENNY po utworzeniu wiersza — patrz ``update_help_material``.

Bezpieczeństwo: ``url`` wpisuje admin, a FE renderuje go jako ``<a href>``.
Walidacja schematu jest ALLOWLISTĄ (tylko http/https), nie blocklistą — dzięki
temu egzotyczne warianty (``vbscript:``, ``data:``, ``blob:``, schematy jeszcze
nieznane) odpadają automatycznie, zamiast wymagać dopisania do listy zakazanych.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.database import get_db
from app.models.help_material import HelpMaterial
from app.models.user import UserRole
from app.api.deps import AdminUser, CurrentUser

router = APIRouter()


# ── URL validation ──────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = ("http://", "https://")
_MAX_URL_LENGTH = 2048
# Znaki sterujące (w tym \n, \r, \t, NUL) — przeglądarki historycznie usuwały je
# z href PRZED interpretacją schematu, więc "java\nscript:" potrafiło się wykonać.
# Odrzucamy je zamiast filtrować.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_url(raw: str) -> str:
    """Przepuszcza wyłącznie absolutne http(s). Wszystko inne → ValueError (422)."""
    if raw is None:
        raise ValueError("Adres URL jest wymagany")

    url = raw.strip()
    if not url:
        raise ValueError("Adres URL jest wymagany")
    if len(url) > _MAX_URL_LENGTH:
        raise ValueError(f"Adres URL jest za długi (max {_MAX_URL_LENGTH} znaków)")
    if _CONTROL_CHARS_RE.search(url):
        raise ValueError("Adres URL zawiera niedozwolone znaki sterujące")

    if not url.lower().startswith(_ALLOWED_SCHEMES):
        raise ValueError(
            "Dozwolone są wyłącznie adresy http:// i https:// "
            "(odrzucono np. javascript:, data:, file:, adresy względne)"
        )

    # Sam prefiks nie wystarcza — "https://" bez hosta to nie jest adres.
    try:
        parsed = urlparse(url)
    except ValueError as exc:  # pragma: no cover - urlparse rzuca sporadycznie
        raise ValueError("Adres URL jest nieprawidłowy") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Adres URL musi zawierać poprawną domenę")

    return url


# ── Pydantic schemas ────────────────────────────────────────────────────────


# Kolumna `sort_order` to INTEGER (int32). Bez tych granic Pydantic przepuszcza
# dowolnie duży int, a odrzuca go dopiero sterownik przy `flush()` — admin
# dostaje wtedy 500 i generyczne „Nie udało się zapisać materiału" zamiast 422
# ze wskazaniem pola.
_INT32_MIN = -2_147_483_648
_INT32_MAX = 2_147_483_647

# Komunikat współdzielony przez walidator schematu (POST) i sprawdzenie stanu
# po scaleniu (PUT) — jeden tekst, żeby admin dostał tę samą diagnozę niezależnie
# od tego, którą ścieżką doszedł do niespójnego wiersza.
_LINK_OR_TEMPLATE_MESSAGE = (
    "Materiał musi mieć adres URL albo treść szablonu — pozycja bez jednego "
    "i drugiego wyświetliłaby się w Pomocy bez żadnej akcji"
)


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """Puste/białe wejście to BRAK wartości, nie pusty string.

    Bez tego ``template_body=""`` przechodziłby CHECK w bazie (kolumna jest
    wtedy NOT NULL) i dawał szablon bez treści — pozycję, która wygląda na
    sprawną, a po kliknięciu nic nie wstawia.
    """
    if value is None:
        return None
    return value.strip() or None


class HelpMaterialCreate(BaseModel):
    category: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    # Opcjonalny, bo szablon treści nie ma adresu. Spójności („link ALBO
    # szablon") pilnuje `_require_link_or_template` niżej.
    url: Optional[str] = None
    description: Optional[str] = None
    template_subject: Optional[str] = Field(default=None, max_length=255)
    template_body: Optional[str] = None
    is_editable_template: bool = False
    sort_order: int = Field(default=0, ge=_INT32_MIN, le=_INT32_MAX)
    is_published: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        normalized = _normalize_optional_text(v)
        if normalized is None:
            return None
        return _validate_url(normalized)

    @field_validator("template_subject", "template_body")
    @classmethod
    def _normalize_template(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_optional_text(v)

    @model_validator(mode="after")
    def _require_link_or_template(self) -> "HelpMaterialCreate":
        if self.url is None and self.template_body is None:
            raise ValueError(_LINK_OR_TEMPLATE_MESSAGE)
        return self


class HelpMaterialUpdate(BaseModel):
    category: Optional[str] = Field(default=None, min_length=1, max_length=255)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    url: Optional[str] = None
    description: Optional[str] = None
    template_subject: Optional[str] = Field(default=None, max_length=255)
    template_body: Optional[str] = None
    is_editable_template: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=_INT32_MIN, le=_INT32_MAX)
    is_published: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        normalized = _normalize_optional_text(v)
        if normalized is None:
            return None
        return _validate_url(normalized)

    @field_validator("template_subject", "template_body")
    @classmethod
    def _normalize_template(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_optional_text(v)

    # Spójności „link ALBO szablon" NIE da się rozstrzygnąć na samym payloadzie:
    # PUT jest częściowy, więc dopiero stan PO scaleniu z wierszem w bazie mówi,
    # czy coś zostało. Sprawdzenie siedzi w `update_help_material`.


class HelpMaterialResponse(BaseModel):
    id: int
    slug: str
    category: str
    title: str
    url: Optional[str]
    description: Optional[str]
    template_subject: Optional[str]
    template_body: Optional[str]
    is_editable_template: bool
    sort_order: int
    is_published: bool
    created_by: Optional[int]
    updated_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ─────────────────────────────────────────────────────────────────


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")

# Litery, których NFKD NIE rozkłada na „baza + znak łączący", bo diakryt jest
# wtopiony w sam kształt glifu (kreska, ligatura). ASCII-fold wyrzuca je wtedy
# BEZ ŚLADU, zamiast sprowadzić do litery bazowej.
#
# Dla polskiego UI kluczowe jest „ł": bez tej mapy „Zupełnie" → „zupenie",
# a „współpracy" → „wspopracy". Pozostałe polskie diakrytyki (ą, ć, ę, ń, ó,
# ś, ź, ż) rozkładają się poprawnie same, więc mapa ich nie dubluje. Resztę
# wpisów trzymamy pod nazwy własne klientów spoza PL (Ø, ß, Æ…).
_TRANSLITERATION = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ð": "d",
        "Ð": "D",
        "ø": "o",
        "Ø": "O",
        "þ": "th",
        "Þ": "Th",
        "ß": "ss",
        "æ": "ae",
        "Æ": "Ae",
        "œ": "oe",
        "Œ": "Oe",
        "ı": "i",
    }
)


# Kolumna `slug` to VARCHAR(255), a Postgres taką wartość ODRZUCA, nie obcina.
# Tytuł mieści się w 255 znakach, ale slug potrafi być DŁUŻSZY od tytułu:
# `_TRANSLITERATION` rozwija 1 znak na 2 (ß→ss, æ→ae, þ→th), a NFKD rozkłada
# ligatury i cyfry rzymskie (ﬄ→ffl, Ⅷ→VIII). Do tego `_ensure_unique_slug`
# dokleja sufiks kolizji. Bez przycięcia obie ścieżki kończą się 500.
_MAX_SLUG_LENGTH = 255


def _trim_slug(slug: str) -> str:
    """Przycina do limitu kolumny, nie zostawiając myślnika na końcu."""
    return slug[:_MAX_SLUG_LENGTH].rstrip("-") or "material"


def _slugify(title: str) -> str:
    """Prosty, deterministyczny slugifier (ASCII, myślniki)."""
    transliterated = title.translate(_TRANSLITERATION)
    normalized = unicodedata.normalize("NFKD", transliterated)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower().strip()
    slug = _SLUG_STRIP_RE.sub("-", lower).strip("-")
    return _trim_slug(slug or "material")


async def _ensure_unique_slug(db: AsyncSession, base: str) -> str:
    """Zwraca slug, dodając sufiks -2, -3, … jeśli już istnieje.

    Wołane WYŁĄCZNIE przy tworzeniu wiersza — slug jest potem niezmienny
    (patrz komentarz przy zmianie tytułu w ``update_help_material``), więc nie
    ma tu wariantu „pomiń własne id".
    """
    candidate = _trim_slug(base)
    suffix = 2
    while True:
        stmt = select(HelpMaterial.id).where(HelpMaterial.slug == candidate)
        existing = await db.scalar(stmt)
        if existing is None:
            return candidate
        # Sufiks musi się ZMIEŚCIĆ w limicie — dlatego skracamy bazę, a nie
        # doklejamy na ślepo (255 + "-2" = 257 → StringDataRightTruncation).
        marker = f"-{suffix}"
        candidate = (
            f"{_trim_slug(base)[: _MAX_SLUG_LENGTH - len(marker)].rstrip('-')}{marker}"
        )
        suffix += 1


def _is_admin(user) -> bool:
    return user.has_role(UserRole.admin)


def _escaped_like_pattern(value: str) -> str:
    """Wzorzec ILIKE, w którym `%` i `_` z wejścia są ZNAKAMI, nie operatorami.

    Bez tego wpisanie `%` dawało wzorzec `%%%` pasujący do każdego wiersza —
    zamiast „Brak materiałów pasujących do wyszukiwania" użytkownik dostawał
    całą bibliotekę i wnioskował, że wyszukiwarka nie działa. Ta sama poprawka
    co w ``clients.py`` i ``b2b_contract_generator.py``.
    """
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Patrz ``procedures.py`` — obie wyszukiwarki żyją na jednym ekranie (Pomoc),
# więc muszą dopasowywać tak samo. Rozjazd semantyki między zakładkami czyta
# się jak awaria jednej z nich.
_MAX_SEARCH_TERMS = 10


def _search_terms(q: str) -> list[str]:
    """Dzieli zapytanie na słowa; każde musi trafić (AND), nie cała fraza.

    „tauron załącznik" ma znaleźć „ZAŁĄCZNIK NR 4 … dla Wykonawcy" w kategorii
    „Onboarding — TAURON" — przy dopasowaniu jednej frazy nie znalazłoby nic,
    bo słowa są w różnych polach.
    """
    return q.split()[:_MAX_SEARCH_TERMS]


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/help-materials", response_model=list[HelpMaterialResponse])
async def list_help_materials(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(
        default=None,
        description="Wyszukaj po tytule, kategorii, opisie i temacie szablonu",
    ),
    published_only: bool = Query(
        default=True,
        description="Domyślnie true; admin może przekazać false aby widzieć szkice",
    ),
) -> list[HelpMaterial]:
    stmt = select(HelpMaterial)

    # Non-admin zawsze widzi tylko opublikowane, niezależnie od query param.
    effective_published_only = published_only or not _is_admin(current_user)
    if effective_published_only:
        stmt = stmt.where(HelpMaterial.is_published.is_(True))

    if q and q.strip():
        for term in _search_terms(q):
            pattern = _escaped_like_pattern(term)
            stmt = stmt.where(
                or_(
                    HelpMaterial.title.ilike(pattern, escape="\\"),
                    HelpMaterial.category.ilike(pattern, escape="\\"),
                    HelpMaterial.description.ilike(pattern, escape="\\"),
                    # Rekruter szuka szablonu po tym, co widzi w Outlooku —
                    # czyli po temacie, nie po naszym tytule pozycji.
                    HelpMaterial.template_subject.ilike(pattern, escape="\\"),
                )
            )

    stmt = stmt.order_by(HelpMaterial.sort_order.asc(), HelpMaterial.title.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/help-materials",
    response_model=HelpMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_help_material(
    data: HelpMaterialCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> HelpMaterial:
    slug = await _ensure_unique_slug(db, _slugify(data.title))
    material = HelpMaterial(
        slug=slug,
        category=data.category.strip(),
        title=data.title.strip(),
        url=data.url,
        description=data.description,
        template_subject=data.template_subject,
        template_body=data.template_body,
        is_editable_template=data.is_editable_template,
        sort_order=data.sort_order,
        is_published=data.is_published,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(material)
    await db.flush()
    await db.refresh(material)
    return material


@router.put("/help-materials/{material_id}", response_model=HelpMaterialResponse)
async def update_help_material(
    material_id: int,
    data: HelpMaterialUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> HelpMaterial:
    material = await db.scalar(
        select(HelpMaterial).where(HelpMaterial.id == material_id)
    )
    if material is None:
        raise HTTPException(status_code=404, detail="Help material not found")

    # PATCH-semantyka częściowa: pominięte pole zostaje bez zmian, jawne null
    # czyści wartość. Rozróżnienie WYŁĄCZNIE przez model_fields_set — wszystkie
    # pola są Optional[...] = None, więc `is not None` skasowałoby url/description
    # przy zmianie samego sort_order.
    fields = data.model_fields_set

    if "title" in fields and data.title is not None:
        # Tytuł zmieniamy, SLUG NIE. Slug jest identyfikatorem wiersza, a nie
        # jego etykietą: nie występuje w żadnej trasie (endpointy biorą
        # `{material_id}`), za to służy za klucz seedowania
        # (`ON CONFLICT (slug)` w entrypoincie) i za punkt zaczepienia dla FE,
        # który po nim odnajduje pozycję-szablon zaproszenia.
        #
        # Przeliczanie sluga z tytułu zrywało oba wiązania naraz: jedna
        # poprawka tytułu w Pomoc → Materiały gasiła przycisk „Zaproszenie
        # prep" na profilu KAŻDEGO kandydata (bez żadnego sygnału dla admina),
        # a przy najbliższym starcie kontenera seed dosiewał bliźniaczy wiersz,
        # bo `ON CONFLICT` przestawał trafiać.
        material.title = data.title.strip()
    if "category" in fields and data.category is not None:
        material.category = data.category.strip()
    # `url` bez strażnika `is not None` — jawne null MUSI czyścić adres, inaczej
    # nie da się zamienić linku w szablon treści. Pominięcie pola nadal nie
    # rusza wartości (rozstrzyga `model_fields_set`), a wiersz bez adresu
    # i bez treści odpada niżej na sprawdzeniu spójności.
    if "url" in fields:
        material.url = data.url
    if "description" in fields:
        material.description = data.description
    if "template_subject" in fields:
        material.template_subject = data.template_subject
    if "template_body" in fields:
        material.template_body = data.template_body
    if "is_editable_template" in fields and data.is_editable_template is not None:
        material.is_editable_template = data.is_editable_template
    if "sort_order" in fields and data.sort_order is not None:
        material.sort_order = data.sort_order
    if "is_published" in fields and data.is_published is not None:
        material.is_published = data.is_published

    # Lustro CHECK-a `ck_help_materials_link_or_template` — sprawdzane PO
    # scaleniu, bo dopiero wtedy widać, czy po edycji cokolwiek zostało.
    # Bez tego admin dostawałby surowy IntegrityError jako 500.
    if material.url is None and material.template_body is None:
        raise HTTPException(status_code=422, detail=_LINK_OR_TEMPLATE_MESSAGE)

    material.updated_by = current_user.id
    await db.flush()
    await db.refresh(material)
    return material


@router.delete(
    "/help-materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_help_material(
    material_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    material = await db.scalar(
        select(HelpMaterial).where(HelpMaterial.id == material_id)
    )
    if material is None:
        raise HTTPException(status_code=404, detail="Help material not found")
    await db.delete(material)
    await db.flush()
