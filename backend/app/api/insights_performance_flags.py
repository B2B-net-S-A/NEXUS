"""`/api/insights/performance-flags` — plakietki ostrzeżeń przy osobie.

Odpowiednik czerwonej „Słabe wyniki" i bursztynowej „Procedury" z tabeli
„Performance per osoba" w DynaReporterze, razem z wolnym komentarzem pod nimi.

Dwa różne guardy w jednym routerze i ta różnica jest sednem:

* **GET → `CurrentUser`.** Plakietka jest widoczna zespołowi z definicji —
  o to w niej chodzi. `/insights` widzi każda zalogowana rola (decyzja D7),
  a ostrzeżenie schowane przed częścią zespołu byłoby oceną, o której osoba
  oceniana dowiaduje się od kogoś innego.
* **POST/PATCH → `AdminUser`.** Zapis mówi imiennie „ta osoba pracuje źle".
  To jest decyzja kadrowa i musi mieć jednego, wąskiego autora.

Czego ten moduł świadomie NIE robi:

1. **Nie ma DELETE.** Zdjęcie plakietki to PATCH `is_active=false`, który
   stempluje `cleared_at`/`cleared_by`. Historia oceny zostaje, bo pytanie
   „kto i kiedy to postawił" bywa zadawane pół roku później. Wygaszonej flagi
   nie da się też wskrzesić (409) — wskrzeszenie musiałoby wyczyścić datę
   zdjęcia, czyli skasować dokładnie tę część historii, dla której wiersz żyje.
2. **Nie liczy okresu.** Flaga jest STANEM na dziś, nie miarą w oknie czasu,
   więc nie ma tu `resolve_period` ani cache'u. Cache byłby wręcz defektem:
   admin zdejmuje ostrzeżenie i przez pięć minut widzi je nadal, czyli jego
   własny zapis wygląda na zgubiony.
3. **Nie zna „byłego pracownika".** Ten chip wyprowadza się z `User.is_active`
   i celowo nie jest typem flagi — odejście z firmy to nie ocena jakości pracy,
   a wygaszanie ostrzeżeń nie może nikogo „przywracać" do zespołu.

Stały opis typu („Bardzo słabe wyniki, wymagana nagła poprawa") mieszka
w `FLAG_TYPE_META` i jedzie w każdej odpowiedzi razem z flagą. Świadomie NIE
w bazie i NIE w kodzie frontu: w bazie stworzyłby drugą kopię do migrowania
przy zmianie brzmienia, a we froncie — dwie prawdy, które rozjeżdżają się
cicho, bo obie się renderują.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.user import User
from app.models.user_performance_flag import (
    PerformanceFlagType,
    UserPerformanceFlag,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Brzmienie 1:1 z DynaReportera — plakietka ma czytać się tak samo po obu
# stronach migracji, inaczej ta sama ocena wygląda jak dwie różne.
FLAG_TYPE_META: dict[str, dict[str, str]] = {
    PerformanceFlagType.weak_results.value: {
        "label": "Słabe wyniki",
        "description": "Bardzo słabe wyniki, wymagana nagła poprawa",
        # `severity` steruje WYŁĄCZNIE wyglądem plakietki (czerwona vs
        # bursztynowa). Front nie może wyprowadzać koloru z `flag_type`,
        # bo wtedy dodanie typu wymaga zmiany po obu stronach.
        "severity": "critical",
    },
    PerformanceFlagType.procedures.value: {
        "label": "Procedury",
        "description": "Niestosowanie się do procedur, wymagane przypomnienie procedur",
        "severity": "warning",
    },
}

# Górny limit komentarza. Nie jest kosmetyką: pole renderuje się w wierszu
# tabeli, a wklejona tam notatka ze spotkania rozjechałaby układ każdemu.
MAX_NOTE_LENGTH = 2000


def _clean_note(raw: Optional[str]) -> Optional[str]:
    """Pusty i biały komentarz to BRAK komentarza, nie pusty komentarz.

    Bez tego `""` z formularza zapisuje się jako wartość i front renderuje pod
    plakietką pustą linijkę — wygląda jak ucięty tekst.
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    return trimmed or None


class PerformanceFlagCreate(BaseModel):
    """Nowa plakietka.

    `flag_type` jest ENUMEM, nie stringiem: nieznana wartość ma skończyć się
    czytelnym 422, a nie wierszem, który przejdzie walidację API i odbije się
    dopiero od CHECK-a w bazie jako surowy IntegrityError.
    """

    user_id: int
    flag_type: PerformanceFlagType
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)


class PerformanceFlagUpdate(BaseModel):
    """Zapis CZĘŚCIOWY — pominięte pole zostaje bez zmian.

    Rozróżnienie po `model_fields_set`, nie po `None`: oba pola są opcjonalne,
    więc bez tego wygaszenie plakietki kasowałoby przy okazji jej komentarz.
    """

    is_active: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)


def _flag_payload(
    flag: UserPerformanceFlag,
    *,
    created_by_name: Optional[str],
    cleared_by_name: Optional[str],
) -> dict:
    meta = FLAG_TYPE_META.get(flag.flag_type, {})
    return {
        "id": flag.id,
        "user_id": flag.user_id,
        "flag_type": flag.flag_type,
        # Etykieta i opis jadą Z FLAGĄ, nie osobnym słownikiem do sklejenia
        # po stronie klienta — konsument nie ma jak pomylić typu z opisem.
        "label": meta.get("label", flag.flag_type),
        "description": meta.get("description", ""),
        "severity": meta.get("severity", "warning"),
        "note": flag.note,
        "is_active": flag.is_active,
        "created_at": flag.created_at.isoformat() if flag.created_at else None,
        "created_by_id": flag.created_by,
        # Podpis jedzie do UI razem z oceną. Anonimowa negatywna ocena
        # widoczna zespołowi jest nie do obrony; `null` tutaj znaczy „konto
        # autora zostało usunięte", a nie „nie wiadomo kto".
        "created_by_name": created_by_name,
        "cleared_at": flag.cleared_at.isoformat() if flag.cleared_at else None,
        "cleared_by_id": flag.cleared_by,
        "cleared_by_name": cleared_by_name,
    }


def _types_payload() -> list[dict]:
    return [{"value": value, **meta} for value, meta in sorted(FLAG_TYPE_META.items())]


async def _load_flags(db: AsyncSession, *, active_only: bool, user_id: int | None):
    """Flagi razem z imionami autora i osoby wygaszającej (dwa aliasy `users`)."""
    creator = aliased(User)
    clearer = aliased(User)
    stmt = (
        select(
            UserPerformanceFlag,
            creator.name.label("created_by_name"),
            clearer.name.label("cleared_by_name"),
        )
        .join(creator, creator.id == UserPerformanceFlag.created_by, isouter=True)
        .join(clearer, clearer.id == UserPerformanceFlag.cleared_by, isouter=True)
    )
    if active_only:
        stmt = stmt.where(UserPerformanceFlag.is_active.is_(True))
    if user_id is not None:
        stmt = stmt.where(UserPerformanceFlag.user_id == user_id)
    # Stała kolejność: bez niej dwie plakietki tej samej osoby potrafią zamienić
    # się miejscami między odczytami i wygląda to jak zmiana danych.
    stmt = stmt.order_by(
        UserPerformanceFlag.user_id,
        UserPerformanceFlag.created_at.desc(),
        UserPerformanceFlag.id.desc(),
    )
    return (await db.execute(stmt)).all()


async def _single_flag_payload(db: AsyncSession, flag_id: int) -> dict:
    """Odczytaj JEDNĄ flagę w tym samym kształcie co lista.

    Odpowiedź zapisu musi mieć kształt odczytu, inaczej front po zapisie
    trzyma obiekt o innych polach niż ten z listy i renderuje go inaczej.
    """
    creator = aliased(User)
    clearer = aliased(User)
    row = (
        await db.execute(
            select(
                UserPerformanceFlag,
                creator.name.label("created_by_name"),
                clearer.name.label("cleared_by_name"),
            )
            .join(creator, creator.id == UserPerformanceFlag.created_by, isouter=True)
            .join(clearer, clearer.id == UserPerformanceFlag.cleared_by, isouter=True)
            .where(UserPerformanceFlag.id == flag_id)
        )
    ).one()
    return _flag_payload(
        row[0],
        created_by_name=row.created_by_name,
        cleared_by_name=row.cleared_by_name,
    )


@router.get("")
async def list_active_flags(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Wszystkie AKTYWNE plakietki, pogrupowane po osobie.

    Bez filtra po użytkowniku i bez paginacji — świadomie. Aktywnych ostrzeżeń
    jest z natury garść (w DynaReporterze cztery na siedemnaście osób), a tabela
    „Performance per osoba" potrzebuje ich wszystkich naraz. Filtr per wiersz
    zamieniłby jeden odczyt w N zapytań i wprowadziłby stan, w którym część
    wierszy ma plakietki, a część jeszcze się ładuje.

    Dostępne dla KAŻDEGO zalogowanego (D7) — patrz docstring modułu.
    """
    rows = await _load_flags(db, active_only=True, user_id=None)

    flags_by_user: dict[str, list[dict]] = {}
    for row in rows:
        flag = row[0]
        # Klucz jako STRING: JSON i tak nie ma kluczy liczbowych, więc
        # int-owy klucz w Pythonie i tak wyszedłby po drugiej stronie jako
        # tekst — lepiej, żeby kontrakt mówił to wprost.
        flags_by_user.setdefault(str(flag.user_id), []).append(
            _flag_payload(
                flag,
                created_by_name=row.created_by_name,
                cleared_by_name=row.cleared_by_name,
            )
        )

    return {
        "flags_by_user": flags_by_user,
        "types": _types_payload(),
        "total_active": len(rows),
    }


@router.get("/history/{user_id}")
async def read_flag_history(
    user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Pełna historia plakietek jednej osoby — także wygaszonych.

    Świadomie WĘŻSZE niż odczyt aktywnych: bieżące ostrzeżenie jest sygnałem
    do poprawy i ma być widoczne, ale zdjęta ocena sprzed roku nie ma powodu
    wisieć przed całym zespołem — a właśnie dlatego trzymamy ją w bazie, żeby
    dało się do niej wrócić przy rozmowie rocznej albo sporze.
    """
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Użytkownik nie istnieje"
        )

    rows = await _load_flags(db, active_only=False, user_id=user_id)
    return {
        "user_id": user_id,
        "user_name": target.name,
        # Chip „były pracownik" — wyprowadzany, nie przechowywany.
        "is_former_employee": not target.is_active,
        "flags": [
            _flag_payload(
                row[0],
                created_by_name=row.created_by_name,
                cleared_by_name=row.cleared_by_name,
            )
            for row in rows
        ],
        "types": _types_payload(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_flag(
    payload: PerformanceFlagCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Postaw plakietkę. Autor stemplowany zawsze — anonimowo się nie da."""
    target = await db.get(User, payload.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Użytkownik nie istnieje"
        )
    # Świadomie NIE blokujemy osób nieaktywnych: DynaReporter pokazuje
    # plakietki także przy byłych pracownikach, a ocena postawiona tuż przed
    # odejściem jest dokładnie tą, którą trzeba móc odtworzyć.

    existing = (
        await db.execute(
            select(UserPerformanceFlag.id).where(
                UserPerformanceFlag.user_id == payload.user_id,
                UserPerformanceFlag.flag_type == payload.flag_type.value,
                UserPerformanceFlag.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Sprawdzamy jawnie, żeby zwrócić zdanie po polsku ze wskazaniem
        # istniejącego wiersza — częściowy indeks unikalny i tak by to złapał,
        # ale jako surowy IntegrityError bez żadnej podpowiedzi.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ta osoba ma już aktywne ostrzeżenie tego typu (id={existing}). "
                "Zmień jego komentarz albo je wygaś."
            ),
        )

    flag = UserPerformanceFlag(
        user_id=payload.user_id,
        flag_type=payload.flag_type.value,
        note=_clean_note(payload.note),
        is_active=True,
        created_by=current_user.id,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)

    logger.info(
        "performance flag raised: user=%s type=%s by=%s",
        payload.user_id,
        payload.flag_type.value,
        current_user.id,
    )
    return await _single_flag_payload(db, flag.id)


@router.patch("/{flag_id}")
async def update_flag(
    flag_id: int,
    payload: PerformanceFlagUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Popraw komentarz albo WYGAŚ plakietkę. Skasować jej nie można."""
    flag = await db.get(UserPerformanceFlag, flag_id)
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ostrzeżenie nie istnieje"
        )

    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pusty zapis — podaj `note` albo `is_active`.",
        )

    if payload.is_active is True and not flag.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wygaszonego ostrzeżenia nie przywracamy — wyczyściłoby to datę "
                "i autora zdjęcia, czyli historię, dla której ten wiersz istnieje. "
                "Postaw nowe ostrzeżenie."
            ),
        )

    # Komentarz PRZED wygaszeniem: jedno żądanie potrafi nieść oba pola, a po
    # zmianie kolejności zapis „popraw komentarz i zdejmij" odbiłby się od
    # własnego guardu na wygaszonej fladze.
    if "note" in fields:
        if not flag.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nie zmieniamy treści wygaszonej oceny — to zapis historyczny.",
            )
        flag.note = _clean_note(payload.note)

    if payload.is_active is False and flag.is_active:
        flag.is_active = False
        flag.cleared_at = datetime.now(timezone.utc)
        flag.cleared_by = current_user.id
        logger.info(
            "performance flag cleared: id=%s user=%s by=%s",
            flag.id,
            flag.user_id,
            current_user.id,
        )

    await db.commit()
    return await _single_flag_payload(db, flag.id)
