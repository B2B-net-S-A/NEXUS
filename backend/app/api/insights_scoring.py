"""`/api/insights/scoring-config` — zasady gry, jawne i strojone bez deployu.

Dwa różne guardy w jednym routerze, i ta różnica jest sednem:

* **GET → `CurrentUser`.** Punktacja jest REGUŁĄ KONKURSU, nie danymi. Ranking
  jest widoczny dla każdej roli (decyzja D7), a ranking, którego formuły nie
  wolno przeczytać, jest wyrocznią, nie tabelą wyników. To jest realizacja
  punktu planu „napisz na kaflu, co liczy".
* **PATCH → `AdminUser`.** Waga punktowa rozdziela 5000/3000/2000 PLN
  kwartalnie, a progi Ścieżki rozwoju przyznają awanse. Zmiana wagi jest
  decyzją płacową.

Czego ten moduł świadomie NIE robi: nie rusza `competition_winners`. Zamrożone
podium jest write-once, więc zmiana wag obowiązuje od najbliższego
NIEZAMKNIĘTEGO kwartału i nie przelicza historii, za którą poszły pieniądze
(decyzja D3, `docs/insights-dynareporter-migration-plan.md` §Etap 3).

Odpowiedź niesie ostrzeżenie o wstecznym działaniu progów seniority: poziom
jest LICZONY przy odczycie, nie przechowywany, więc obniżenie progu przyznaje
awanse wstecz, a podniesienie je wstecz odbiera (`docs/insights-etap0-specs.md`
§B.2). Konsument musi to pokazać w dialogu zapisu.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.insights_scoring_config import InsightsScoringConfig
from app.models.user import User
from app.services.insights_scoring_config import (
    ScoringConfigError,
    get_scoring_config,
    league_points_formula,
    scoring_fields_payload,
    set_scoring_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

# Ostrzeżenie jedzie w KAŻDEJ odpowiedzi, także GET-owej: dialog zapisu
# renderuje się z danych ekranu, a ostrzeżenie doklejone tylko do PATCH-a
# pokazałoby się po fakcie.
SENIORITY_RETROACTIVE_WARNING = (
    "Poziom Ścieżki rozwoju jest liczony przy odczycie, nie przechowywany. "
    "Obniżenie progu przyznaje awanse WSTECZ, podniesienie — odbiera je wstecz."
)
LEAGUE_NO_RETROACTIVITY_NOTE = (
    "Nowa punktacja obowiązuje od najbliższego niezamkniętego kwartału. "
    "Zamrożone podia (nagrody wypłacone) nie są przeliczane."
)


class ScoringConfigUpdate(BaseModel):
    """Zapis CZĘŚCIOWY: pominięty klucz zostaje bez zmian.

    Wartości są `int` w słowniku, a nie polami modelu, bo lista kluczy żyje
    w `SCORING_FIELDS` — model z dziesięcioma polami byłby drugim miejscem
    do zaktualizowania przy dodaniu progu i pierwszym, o którym ktoś zapomni.
    Nieznany klucz i zły zakres kończą się czytelnym 422, nie cichym
    zignorowaniem: przyjęty i wyrzucony zapis wygląda dla admina jak sukces.
    """

    values: dict[str, int] = Field(
        ...,
        description="Klucze z `SCORING_FIELDS`; wartości całkowite w zakresie pola.",
    )


async def _payload(db: AsyncSession) -> dict:
    config = await get_scoring_config(db)

    # Metadane (kto, kiedy) czytane osobno i FAIL-OPEN: brak tabeli albo
    # nieudany JOIN nie może zabrać samej konfiguracji, bo to ona jest
    # odpowiedzią na pytanie „co się liczy".
    meta: dict[str, dict] = {}
    try:
        rows = (
            await db.execute(
                select(
                    InsightsScoringConfig.key,
                    InsightsScoringConfig.updated_at,
                    User.name.label("updated_by_name"),
                ).join(User, User.id == InsightsScoringConfig.updated_by, isouter=True)
            )
        ).all()
        for row in rows:
            meta[row.key] = {
                "updated_at": (
                    row.updated_at.isoformat() if row.updated_at is not None else None
                ),
                "updated_by_name": row.updated_by_name,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("insights scoring config metadata unavailable: %r", exc)

    return {
        "values": config,
        "fields": scoring_fields_payload(config, meta=meta),
        # Skrót w kształcie, którego front używa na kaflu „System punktowy"
        # — żeby konsument nie musiał znać nazw kluczy konfiguracji.
        "points_formula": league_points_formula(config),
        "notes": {
            "league_no_retroactivity": LEAGUE_NO_RETROACTIVITY_NOTE,
            "seniority_retroactive": SENIORITY_RETROACTIVE_WARNING,
        },
    }


@router.get("")
async def read_scoring_config(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Obowiązująca punktacja + zakresy + kto ją ostatnio zmienił.

    Dostępne dla KAŻDEGO zalogowanego (D7). Nie niesie danych osobowych poza
    imieniem autora ostatniej zmiany — a to jest ta sama informacja co
    „kto ustala reguły", którą i tak widać po roli.
    """
    return await _payload(db)


@router.patch("")
async def update_scoring_config(
    payload: ScoringConfigUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Nadpisz wybrane klucze. Zapis jest atomowy: wszystko albo nic."""
    try:
        await set_scoring_config(db, payload.values, updated_by=current_user.id)
    except ScoringConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    logger.info(
        "insights scoring config updated by user=%s keys=%s",
        current_user.id,
        sorted(payload.values),
    )
    return await _payload(db)
