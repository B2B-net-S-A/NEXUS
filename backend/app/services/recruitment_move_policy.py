"""Polityka ruchu karty w rekrutacji — „kto” i „czy wolno” (API v1, 15.10.2026).

Ten sam ruch karty (``pipeline.apply_move``) robią dwaj autorzy: osoba
z Tablicy (``User``, ``POST /api/pipeline/move``) i konto serwisowe z API
integracyjnego v1 (``recruitments:write``). Ciało ruchu jest jedno — bramki
biznesowe (QC CV, „Zweryfikowany”, debrief, eligibility, wersja procesu,
wejście do rekrutacji, etapy-odznaki, powód odrzucenia) liczą się tak samo —
a pytania o uprawnienia i autora idą przez ``RecruitmentMovePolicy``:

* ``UserMovePolicy`` woła DOKŁADNIE te bramki, które handler ``/move`` wołał
  przed wydzieleniem ciała, z tymi samymi argumentami i w tym samym miejscu
  ruchu. Bramkę zespołu i blokadę 12 h czyta przez atrybut
  ``app.api.pipeline`` (podmiana w testach działa jak dotąd). Zachowanie
  ekranu się nie zmienia.
* ``IntegrationMovePolicy`` stosuje decyzję Artura z 15.10.2026: klucz
  przesuwa kartę zwykłymi ruchami między kolumnami w toku, na „Zweryfikowany”
  i do „Zamkniętych” (odrzucenie, rezygnacja — z powodem, bez maila do
  kandydata). Decyzje, które na ekranie należą do człowieka, dostają 403
  ``requires_screen_decision`` (``MoveTarget`` → ``assert_move_allowed``):
  zatrudnienie (także każdy ruch karty, która już stoi w „Zatrudnionych”),
  wysłanie do klienta (przejście karty z kolumn przed
  „CV wysłane” na „CV wysłane” i dalej), kolejka Cpro Nordei (akceptacja
  Delivery Leada i wrzucenie do Cpro) oraz każdy zapis stawki do klienta albo
  stawki kandydata. Bez 12 h blokady (reguła integracji) i w całej firmie —
  konto nie ma zespołu ani portfela.

Konto serwisowe NIGDY nie udaje ``User`` (``write_policy.py``): autorem ruchu
jest ``IntegrationActor`` (``moved_by`` = ``None``, ``details.via`` na
``Activity`` dopisuje stempel sesji klucza), a reguły ekranu, które czytają
osobę przy okazji liczenia faktów (wymagania „Zweryfikowany”, bramka QC
z osobą od Cpro), dostają ``NO_RIGHTS_VIEWER`` — widza bez ról i uprawnień,
któremu każda bramka odmawia. Ruchy, przy których ekran pyta o prawo osoby,
polityka API odrzuca wcześniej; widz jest drugą linią obrony, nie przepustką.

Moduł importuje ``app.api.pipeline`` leniwie (w ciałach metod): trasa
importuje politykę na poziomie modułu — import na górze domykałby cykl.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Optional, Protocol

from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import PipelineStage
from app.models.service_account import ServiceScope
from app.services import pipeline_move_rules
from app.services.board_stage_badges import BOARD_COLUMN_ORDER, is_cpro_stage
from app.services.integration_actor import IntegrationActor, actor_for

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.job import Job
    from app.models.user import User
    from app.schemas.pipeline import StageMove
    from app.services.service_account_auth import ServicePrincipal


REQUIRES_SCREEN_DECISION = "requires_screen_decision"

# Powód odmowy (``details.reason``) → zdanie dla człowieka czytającego log
# automatyzacji. Kody są częścią umowy v1 — nowy powód = nowy klucz.
SCREEN_DECISION_MESSAGES: dict[str, str] = {
    "hire": (
        "Zatrudnienie i zmiany karty zatrudnionej osoby robi człowiek na ekranie "
        "(sposób podpisania umowy, szkic kontraktu i zamówienia) — API ich nie "
        "zapisuje."
    ),
    "client_send": (
        "Wysłanie kandydata do klienta (CV wysłane, stawka do klienta) to "
        "decyzja Delivery Leada na ekranie. API przesuwa kartę przed wysyłką "
        "i po niej, ale nie przez nią."
    ),
    "cpro_queue": (
        "Kolejkę Cpro (akceptacja Delivery Leada i wrzucenie do Cpro) prowadzi "
        "się na ekranie."
    ),
    "client_rate": "Stawkę do klienta wpisuje Delivery Lead na ekranie.",
    "candidate_rate": (
        "Stawkę kandydata zapisuje się na ekranie (okno „Zweryfikowany” albo "
        "profil kandydata)."
    ),
    "delivery_lead_decision": (
        "„Odrzucony przez DL”, wskazanie osoby od Cpro i „Wróć do poprawy” "
        "z polami to decyzje Delivery Leada na ekranie."
    ),
}

NOT_IN_RECRUITMENT_MESSAGE = (
    "Tej osoby nie ma jeszcze w rekrutacji — dodaj ją przez "
    "POST /recruitments/{id}/candidates (wejście do „Nowych” albo "
    "„Screeningu”), a dalej przesuwaj tą trasą."
)


def requires_screen_decision(reason: str) -> HTTPException:
    """403 ``requires_screen_decision`` w kopercie v1 (``details.reason``)."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": REQUIRES_SCREEN_DECISION,
            "message": SCREEN_DECISION_MESSAGES[reason],
            "reason": reason,
        },
    )


@dataclass(frozen=True)
class _NoRightsViewer:
    """Widz bez ról i uprawnień — dla reguł ekranu, które czytają osobę.

    ``has_any_role`` / ``has_role`` odpowiadają „nie”, ``get_all_roles`` jest
    pusty, a ``effective_action_access`` to pusta mapa: ``has_permission``
    czyta ją PRZED domyślnymi uprawnieniami ról, więc każde uprawnienie
    wychodzi ``none`` (obiekt bez tej mapy wracałby do uprawnień roli —
    powód, dla którego konto serwisowe nie udaje ``User``). ``id`` = ``None``:
    porównanie z osobą od Cpro czy autorem blokady nigdy się nie zgadza.
    """

    id: None = None
    name: str = ""
    email: None = None
    role: None = None
    roles: tuple = ()
    effective_action_access: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def has_role(self, _role: object) -> bool:
        return False

    def has_any_role(self, *_roles: object) -> bool:
        return False

    def get_all_roles(self) -> set:
        return set()


NO_RIGHTS_VIEWER = _NoRightsViewer()


@dataclass(frozen=True)
class MoveTarget:
    """Ruch, o który pyta polityka — policzony przed pierwszym zapisem ruchu."""

    data: StageMove
    job: Job
    stage_def: Optional[PipelineStageDef]
    legacy_enum: PipelineStage
    target_column: str
    fresh_pair: bool

    @property
    def is_hire(self) -> bool:
        terminal = getattr(self.stage_def, "terminal_type", None)
        return (
            self.legacy_enum == PipelineStage.hired
            or getattr(terminal, "value", terminal) == "hired"
            or self.target_column == "hired"
        )

    @property
    def is_removal(self) -> bool:
        """Odrzucenie albo rezygnacja (lustro ``is_removal_move`` w ``/move``)."""
        if self.legacy_enum in (PipelineStage.rejected, PipelineStage.withdrawn):
            return True
        stage_def = self.stage_def
        if stage_def is None or not stage_def.is_terminal:
            return False
        terminal = getattr(stage_def.terminal_type, "value", stage_def.terminal_type)
        return terminal in ("rejected", "withdrawn")


class RecruitmentMovePolicy(Protocol):
    """Pytania, które ruch karty zadaje autorowi."""

    @property
    def actor_id(self) -> Optional[int]:
        """``users.id`` autora — ``None`` dla konta serwisowego."""

    @property
    def actor(self) -> Any:
        """Autor dla kodu czytającego ``.id``/``.name`` (notatka, audyt)."""

    @property
    def viewer(self) -> Any:
        """Czyje prawa czytają reguły ekranu (osoba albo ``NO_RIGHTS_VIEWER``)."""

    @property
    def mover(self) -> Optional[User]:
        """Osoba w powiadomieniach o ruchu — ``None`` dla konta serwisowego."""

    @property
    def may_send_rejection_email(self) -> bool:
        """Czy ruch może zaplanować mail odrzucenia (opt-in z okna)."""

    async def ensure_job_access(self, job_id: int) -> None:
        """Zakres rekrutacji (zespół osoby albo scope klucza)."""

    async def assert_move_allowed(self, move: MoveTarget) -> None:
        """Ruchy, których autor nie robi wcale (przed bramkami biznesowymi)."""

    async def assert_can_act(self, *, candidate_id: int, job_id: int) -> None:
        """12 h blokada osoby w „Nowych”/„Screeningu”."""

    def can_terminal_transition(self) -> bool:
        """Ruch terminalny (zatrudnienie, odrzucenie, rezygnacja)."""

    def can_edit_rates(self) -> bool:
        """Ruch na „Zweryfikowany” (może nieść stawkę kandydata)."""


class UserMovePolicy:
    """Osoba z Tablicy — delegacja do bramek ``/move`` bez żadnej zmiany."""

    def __init__(self, user: User, db: AsyncSession) -> None:
        self.user = user
        self.db = db

    @property
    def actor_id(self) -> Optional[int]:
        return self.user.id

    @property
    def actor(self) -> Any:
        return self.user

    @property
    def viewer(self) -> Any:
        return self.user

    @property
    def mover(self) -> Optional[User]:
        return self.user

    @property
    def may_send_rejection_email(self) -> bool:
        return True

    async def ensure_job_access(self, job_id: int) -> None:
        from app.api import pipeline as routes

        await routes.ensure_job_membership(self.db, self.user, job_id)

    async def assert_move_allowed(self, move: MoveTarget) -> None:
        # Ekran nie ma osobnej listy odmów — prawa osoby sprawdzają bramki
        # ruchu w swoich miejscach (rola terminalna, wysyłka do klienta…).
        return None

    async def assert_can_act(self, *, candidate_id: int, job_id: int) -> None:
        from app.api import pipeline as routes

        await routes.candidate_claim.assert_can_act(
            self.db,
            process=await routes.candidate_claim.load_process(
                self.db, candidate_id=candidate_id, job_id=job_id
            ),
            user=self.user,
        )

    def can_terminal_transition(self) -> bool:
        from app.api.recruitment_access import user_can_terminal_transition

        return user_can_terminal_transition(self.user)

    def can_edit_rates(self) -> bool:
        from app.api.recruitment_access import user_can_edit_rates

        return user_can_edit_rates(self.user)


class IntegrationMovePolicy:
    """Konto serwisowe API v1 — decyzje ze scope'u i z reguł 15.10.2026.

    Każda metoda sprawdza scope ``recruitments:write``, nawet gdy trasa zrobiła
    to zależnością — polityka nie zakłada, skąd ją wywołano.
    """

    def __init__(self, principal: ServicePrincipal, db: AsyncSession) -> None:
        self.principal = principal
        self.db = db
        self._actor = actor_for(principal)

    @property
    def actor_id(self) -> Optional[int]:
        return None

    @property
    def actor(self) -> IntegrationActor:
        return self._actor

    @property
    def viewer(self) -> Any:
        return NO_RIGHTS_VIEWER

    @property
    def mover(self) -> Optional[User]:
        return None

    @property
    def may_send_rejection_email(self) -> bool:
        # Mail odrzucenia wychodzi ze skrzynki osoby, która odrzuca (runda 9,
        # R9-N11-1) — konto serwisowe skrzynki nie ma.
        return False

    def _require_scope(self) -> None:
        scope = ServiceScope.recruitments_write
        if scope.value not in self.principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_scope",
                    "message": "Ruch karty wymaga scope'u recruitments:write.",
                    "required": [scope.value],
                    "missing": [scope.value],
                },
            )

    async def ensure_job_access(self, job_id: int) -> None:
        # Cała firma: rekrutacje widzi i obsługuje każdy (23.09.2026), a konto
        # serwisowe nie ma zespołu. Istnienie rekrutacji sprawdził ruch.
        self._require_scope()

    async def assert_move_allowed(self, move: MoveTarget) -> None:
        self._require_scope()
        if move.fresh_pair:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "not_in_recruitment",
                    "message": NOT_IN_RECRUITMENT_MESSAGE,
                },
            )
        self._refuse_screen_fields(move.data)
        if move.is_hire:
            raise requires_screen_decision("hire")
        # Kolumna karty jak przy bramkach ekranu: para w „Zamkniętych” liczy
        # się kolumną sprzed zamknięcia (``gate_stage_row``).
        row, current_column = await pipeline_move_rules.gate_stage_row(
            self.db, candidate_id=move.data.candidate_id, job_id=move.job.id
        )
        if current_column == "hired":
            # Karta zatrudnionej osoby — cofnięcie albo zamknięcie zatrudnienia
            # rusza umowę i zamówienie, więc decyduje człowiek.
            raise requires_screen_decision("hire")
        if move.is_removal:
            # Odrzucenie i rezygnacja z każdej kolumny w toku — także z kolejki
            # Cpro i od klienta. Osobę zawsze da się zamknąć (lustro eligibility).
            return
        await self._refuse_cpro_and_client_send(
            move, row=row, current_column=current_column
        )

    def _refuse_screen_fields(self, data: StageMove) -> None:
        """Pola ruchu, które na ekranie wpisuje człowiek (trasa v1 ich nie
        przekazuje — polityka nie zakłada, skąd ją wywołano)."""
        if (
            data.client_rate_value is not None
            or data.client_rate_unit is not None
            or data.client_rate_currency is not None
        ):
            raise requires_screen_decision("client_rate")
        if data.expected_rate_value is not None or data.expected_rate_is_minimum:
            raise requires_screen_decision("candidate_rate")
        if data.hired_signed_via is not None or data.hired_current_engagement:
            raise requires_screen_decision("hire")
        if (
            data.task_assignee_id is not None
            or data.fix_fields
            or data.ended_by == pipeline_move_rules.ENDED_BY_DELIVERY_LEAD
        ):
            raise requires_screen_decision("delivery_lead_decision")

    async def _refuse_cpro_and_client_send(
        self, move: MoveTarget, *, row: Any, current_column: str
    ) -> None:
        job = move.job
        candidate_id = move.data.candidate_id
        stage_name = move.stage_def.name if move.stage_def is not None else None
        if is_cpro_stage(stage_name):
            raise requires_screen_decision("cpro_queue")
        if row is not None and row.stage_def_id is not None:
            current_name = await self.db.scalar(
                select(PipelineStageDef.name).where(
                    PipelineStageDef.id == row.stage_def_id
                )
            )
            if is_cpro_stage(current_name):
                # Karta w kolejce Cpro (albo zamknięta z niej): „✓ Wrzucone”
                # i zwrot do przeglądu to ruchy osoby od Cpro i DL-a.
                raise requires_screen_decision("cpro_queue")
        order = BOARD_COLUMN_ORDER
        crosses_to_client = (
            move.target_column in order
            and order.index(move.target_column) >= order.index("cv_sent")
            and (
                current_column not in order
                or order.index(current_column) < order.index("cv_sent")
            )
        )
        if crosses_to_client:
            raise requires_screen_decision("client_send")
        # Ta sama reguła co ekran (stawka i uprawnienie wysyłki) — na wypadek
        # etapu, którego kolumna nie mówi „CV wysłane”, a kod tak.
        if pipeline_move_rules.requires_dl_client_rate(
            move.legacy_enum, job.client_id, stage_name=stage_name
        ) and await pipeline_move_rules.arrives_from_before_client_send(
            self.db, candidate_id=candidate_id, job_id=job.id
        ):
            raise requires_screen_decision("client_send")

    async def assert_can_act(self, *, candidate_id: int, job_id: int) -> None:
        # 12 h blokada należy się wyłącznie człowiekowi (decyzja 23.09.2026);
        # integracja ani jej nie zakłada, ani jej nie podlega.
        self._require_scope()

    def can_terminal_transition(self) -> bool:
        # Zatrudnienie odrzuca ``assert_move_allowed``; zostają odrzucenie
        # i rezygnacja, które klucz zapisuje.
        return True

    def can_edit_rates(self) -> bool:
        # Ruch na „Zweryfikowany” bez stawki w żądaniu (stawkę z ruchu
        # odrzuca ``assert_move_allowed``) — przenosi tylko stawkę pary.
        return True


__all__ = [
    "IntegrationMovePolicy",
    "MoveTarget",
    "NO_RIGHTS_VIEWER",
    "NOT_IN_RECRUITMENT_MESSAGE",
    "REQUIRES_SCREEN_DECISION",
    "RecruitmentMovePolicy",
    "SCREEN_DECISION_MESSAGES",
    "UserMovePolicy",
    "requires_screen_decision",
]
