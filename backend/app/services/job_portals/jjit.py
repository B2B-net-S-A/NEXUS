"""JustJoin.IT i RocketJobs — adapter Employer Public API (1EP, 0381).

Jedna klasa dla dwóch portali (``jobBoard``), zarejestrowana w ``ADAPTERS``
dwa razy. Dwie reguły z dokumentacji dostawcy, które kosztują pieniądze:

* ``externalId`` NIE chroni przed duplikatem — ponowienie po timeoucie
  opublikowałoby drugie ogłoszenie i zużyło drugi kredyt. Dlatego
  ``publish`` NAJPIERW szuka opublikowanego ogłoszenia z naszym
  ``externalId`` i dopiero przy pustej liście wysyła ``POST``.
* ``PUT`` podmienia całe ogłoszenie — ``update`` czyta bieżący stan
  (klauzula, kontakt, tagi) i odsyła komplet. Tytułu nie da się zmienić.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

from app.core.database import AsyncSessionLocal
from app.models.job_posting import Portal
from app.services.job_portals import jjit_connection, jjit_payload
from app.services.job_portals.base import (
    PortalAdapter,
    PortalError,
    PortalGone,
    PortalResult,
    PostingContent,
)
from app.services.job_portals.jjit_client import JjitApi

# Publiczny adres ogłoszenia — dokumentacja 1EP go nie podaje, portal zwraca
# tylko `slug`. Szablony do potwierdzenia na pierwszym prawdziwym ogłoszeniu.
_OFFER_URL = {
    "justjoinit": "https://justjoin.it/job-offer/{slug}",
    "rocketjobs": "https://rocketjobs.pl/oferta-pracy/{slug}",
}


class JjitBoardAdapter(PortalAdapter):
    board: ClassVar[str]

    def __init__(self, config=None, *, api: Optional[JjitApi] = None) -> None:
        super().__init__(config)
        self._api = api

    @property
    def api(self) -> JjitApi:
        if self._api is None:
            self._api = JjitApi()
        return self._api

    async def _unit(self) -> str:
        async with AsyncSessionLocal() as db:
            row = await jjit_connection.load(db)
        unit = jjit_connection.unit_for(row, self.board)
        if not unit:
            raise PortalError(
                f"Brak identyfikatora jednostki organizacyjnej {self.label} — "
                "ustaw go w konfiguracji portalu.",
                retryable=False,
            )
        return unit

    def validate_options(self, content: PostingContent) -> list[str]:
        return jjit_payload.validate(
            self.board, content.job, jjit_payload.normalize_options(content.options)
        )

    def _checked_options(self, content: PostingContent) -> dict[str, Any]:
        options = jjit_payload.normalize_options(content.options)
        problems = jjit_payload.validate(self.board, content.job, options)
        if problems:
            raise PortalError(" ".join(problems), retryable=False)
        return options

    async def _skill_ids(self, content: PostingContent) -> dict[str, dict[str, str]]:
        must, nice = jjit_payload.skill_split(self.board, content.job)
        return await self.api.skills(self.board, must + nice)

    def _result(self, ad: dict[str, Any]) -> PortalResult:
        slug = ad.get("slug")
        url = _OFFER_URL[self.board].format(slug=slug) if slug else None
        return PortalResult(external_id=str(ad.get("id") or "") or None, url=url)

    async def publish(self, content: PostingContent) -> PortalResult:
        self.ensure_ready()
        options = self._checked_options(content)
        if not content.external_ref:
            raise PortalError("Brak identyfikatora publikacji.", retryable=False)
        unit = await self._unit()
        existing = await self.api.find_published(unit, content.external_ref)
        if existing:
            return self._result(existing)
        balance = await self.api.balance(unit)
        payment = jjit_payload.pick_payment(
            self.board, balance, now_iso=datetime.now(timezone.utc).isoformat()
        )
        if payment is None:
            raise PortalError(
                f"Brak kodów i aktywnej subskrypcji na {self.label} — ogłoszenie "
                "nie zostało wysłane.",
                retryable=False,
            )
        body = jjit_payload.create_body(
            self.board,
            title=content.title,
            job=content.job,
            options=options,
            apply_url=content.apply_url,
            skill_ids=await self._skill_ids(content),
            payment=payment,
            external_id=content.external_ref,
        )
        return self._result(await self.api.create(unit, body))

    async def update(self, external_id: str, content: PostingContent) -> PortalResult:
        self.ensure_ready()
        options = self._checked_options(content)
        unit = await self._unit()
        current = await self.api.get(unit, external_id)
        body = jjit_payload.update_body(
            self.board,
            current=current,
            job=content.job,
            options=options,
            apply_url=content.apply_url,
            skill_ids=await self._skill_ids(content),
        )
        await self.api.update(unit, external_id, body)
        result = self._result({"id": external_id, "slug": current.get("slug")})
        if current.get("title") and current["title"] != content.title:
            result.extra["title_unchanged"] = True
        return result

    async def unpublish(self, external_id: str) -> None:
        self.ensure_ready()
        unit = await self._unit()
        try:
            await self.api.close(unit, external_id)
        except PortalGone:
            return  # usunięte z portalu poza API — nic do zamknięcia
        except PortalError as exc:
            # 409 = ogłoszenie już zamknięte (dokumentacja) — cel osiągnięty.
            if exc.status == 409:
                return
            raise

    async def status(self, external_id: str) -> dict[str, Any]:
        self.ensure_ready()
        unit = await self._unit()
        ad = await self.api.get(unit, external_id)
        return {"state": str(ad.get("state") or "").casefold() or None}


class JjitAdapter(JjitBoardAdapter):
    portal = Portal.justjoinit
    label = "JustJoin.IT"
    board = "justjoinit"


class RocketJobsAdapter(JjitBoardAdapter):
    portal = Portal.rocketjobs
    label = "RocketJobs"
    board = "rocketjobs"


__all__ = ["JjitAdapter", "JjitBoardAdapter", "RocketJobsAdapter"]
