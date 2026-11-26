"""Pomoc bez wzorów Word: formularze onboardingowe na karty klientów (26.11.2026).

Decyzja Artura z 26.11.2026 (wariant B z makiet): rekruterzy pobierali z Pomocy
wzory Word zamiast robić dokumenty w NEXUSIE, a zakładka „Materiały” znika dla
wszystkich poza adminem. Krok robi dwie rzeczy:

- formularze onboardingowe klientów (oświadczenia, zgody, załączniki — dokumenty
  klienta, generatora nie mają) dopisuje do „Dokumentów” na karcie klienta.
  Link, który karta już ma, nie jest dublowany. Każda zmieniona karta dostaje
  nową wersję i wpis w historii (``action="saved"``), jak zapis z formularza;
- przeniesione formularze i wzory, które mają w NEXUSIE swoje miejsce (umowa B2B,
  umowa przedwstępna, Profil Championa, notatka po screeningu), odpublikowuje.
  Wiersze zostają, admin widzi je w Materiałach jako szkic. Zaproszenia na prep
  krok nie rusza: czyta je okno „Zaproś na prep”.

Adresy i nazwy plików krok czyta z wierszy ``help_materials`` (repo jest
publiczne, linki do SharePointa nie trafiają do kodu). Znacznik w
``app_settings`` + advisory lock; paragon niesie tylko id klientów i liczby.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.help_material import HelpMaterial

logger = logging.getLogger(__name__)

REPAIR_MARKER = "help_onboarding_to_client_cards_2026_11_26"
ACTOR_NAME = "NEXUS (formularze onboardingowe z Pomocy)"
# Limit pola w API (`PlaybookPayload.documents`, max_length=50).
DOCUMENTS_LIMIT = 50

NORDEA = 11
BNP_PARIBAS = 12
ERGO = 13
POLKOMTEL = 15
BANK_POCZTOWY = 16
VELOBANK = 37
PFRON = 122
TAURON = 151
BNP_CARDIF = 38335

#: slug wiersza w Materiałach → id klienta (kategorie „Onboarding — <klient>”
#: z seeda 0218 i późniejszego dopisku NORDEA, zgodność z kopią z 26.11).
ONBOARDING_SLUG_TO_CLIENT: dict[str, int] = {
    "nordea-appendix-3-confidentiality": NORDEA,
    "nordea-oswiadczenie-krk-2026": NORDEA,
    "oswiadczenie-o-niekaralnosci-eng-krk-2024-docx": NORDEA,
    "bnp-paribas-oswiadczenie-zdalny-dostep": BNP_PARIBAS,
    "ergo-oswiadczenia-folder": ERGO,
    "ergo-opis-dokumentow-onboarding": ERGO,
    "polkomtel-informacja-przetwarzanie-danych": POLKOMTEL,
    "bank-pocztowy-oswiadczenie-niekaralnosci": BANK_POCZTOWY,
    "bank-pocztowy-oswiadczenie-poufnosci": BANK_POCZTOWY,
    "velobank-dokumenty-etat-umowa-ramowa": VELOBANK,
    "velobank-dokumenty-podwykonawcy-nowy": VELOBANK,
    "velobank-dokumenty-podwykonawcy-instrukcja": VELOBANK,
    "pfron-oswiadczenie-bhp": PFRON,
    "pfron-oswiadczenie-wzor": PFRON,
    "pfron-zalacznik-polityka-oswiadczenie": PFRON,
    "tauron-zalacznik-1-zakres-uslug": TAURON,
    "tauron-draft-umowy": TAURON,
    "tauron-zalacznik-2-raport-miesieczny": TAURON,
    "tauron-zalacznik-3-upowaznienie-dane-osobowe": TAURON,
    "tauron-zalacznik-4-vpn": TAURON,
    "tauron-zalacznik-5a-porozumienie-przesylanie-dokumentow": TAURON,
    "tauron-zalacznik-5b-ksef": TAURON,
    "tauron-zalacznik-6-incydenty-bezpieczenstwa": TAURON,
    "bnp-cardif-zgoda-dane-osobowe": BNP_CARDIF,
}

#: Wzory, które w NEXUSIE mają generator albo formularz.
REPLACED_TEMPLATE_SLUGS: tuple[str, ...] = (
    "szablon-umowy-b2b-2026",
    "umowa-przedwstepna-cez",
    "profil-championa-wzor",
    "notatka-po-screeningu-wzor",
)


def _merged(
    current: Optional[list], additions: list[dict[str, str]]
) -> Optional[list[dict[str, str]]]:
    """Dokumenty karty z dopisanymi formularzami albo ``None``, gdy nic nie dochodzi."""

    existing = [doc for doc in (current or []) if isinstance(doc, dict)]
    urls = {str(doc.get("url", "")).strip() for doc in existing}
    fresh: list[dict[str, str]] = []
    for doc in additions:
        if doc["url"] in urls:
            continue
        urls.add(doc["url"])
        fresh.append(doc)
    room = max(DOCUMENTS_LIMIT - len(existing), 0)
    fresh = fresh[:room]
    if not fresh:
        return None
    return [*existing, *fresh]


async def run_help_onboarding_to_client_cards(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    slug_to_client: Optional[dict[str, int]] = None,
    replaced_slugs: Optional[tuple[str, ...]] = None,
) -> Optional[dict[str, Any]]:
    """Przenieś i odpublikuj; ``None`` = już wykonane. Wołający commituje.

    ``slug_to_client`` i ``replaced_slugs`` podmieniają tylko testy (id klientów
    z produkcji nie istnieją w bazie testowej).
    """
    mapping = ONBOARDING_SLUG_TO_CLIENT if slug_to_client is None else slug_to_client
    replaced = REPLACED_TEMPLATE_SLUGS if replaced_slugs is None else replaced_slugs

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None

    materials = (
        await db.execute(
            select(HelpMaterial)
            .where(HelpMaterial.slug.in_(sorted(mapping)))
            .order_by(HelpMaterial.sort_order, HelpMaterial.id)
        )
    ).scalars()
    by_client: dict[int, list[dict[str, str]]] = {}
    slug_urls: dict[str, tuple[int, str]] = {}
    for material in materials:
        url = (material.url or "").strip()
        if not url.lower().startswith(("https://", "http://")):
            continue
        by_client.setdefault(mapping[material.slug], []).append(
            {"name": material.title, "url": url}
        )
        slug_urls[material.slug] = (mapping[material.slug], url)

    cards = (
        await db.execute(
            select(ClientPlaybook)
            .where(ClientPlaybook.client_id.in_(sorted(by_client)))
            .with_for_update()
        )
    ).scalars()
    found: dict[int, ClientPlaybook] = {card.client_id: card for card in cards}
    results: list[dict[str, Any]] = []
    placed_slugs: set[str] = set()
    for client_id in sorted(by_client):
        card = found.get(client_id)
        if card is None:
            results.append({"client_id": client_id, "skipped": "no_card", "added": 0})
            continue
        merged = _merged(card.documents, by_client[client_id])
        # Z Pomocy schodzi tylko formularz, którego link stoi na karcie (także
        # sprzed kroku); nadmiar ponad limit karty zostaje opublikowany.
        on_card = {
            str(doc.get("url", "")).strip()
            for doc in (merged if merged is not None else card.documents or [])
            if isinstance(doc, dict)
        }
        placed_slugs |= {
            slug
            for slug, (owner, url) in slug_urls.items()
            if owner == client_id and url in on_card
        }
        if merged is None:
            results.append(
                {"client_id": client_id, "skipped": "nothing_to_change", "added": 0}
            )
            continue
        before = list(card.documents or [])
        card.documents = merged
        card.version = int(card.version or 1) + 1
        db.add(
            ClientPlaybookEvent(
                client_id=client_id,
                playbook_version=card.version,
                action="saved",
                changes={"documents": {"from": before, "to": merged}},
                actor_user_id=None,
                actor_name=ACTOR_NAME,
            )
        )
        results.append(
            {
                "client_id": client_id,
                "skipped": None,
                "added": len(merged) - len(before),
            }
        )

    unpublish = sorted(placed_slugs | set(replaced))
    unpublished = 0
    if unpublish:
        outcome = await db.execute(
            update(HelpMaterial)
            .where(
                HelpMaterial.slug.in_(unpublish), HelpMaterial.is_published.is_(True)
            )
            .values(is_published=False, updated_at=datetime.now(timezone.utc))
        )
        unpublished = int(outcome.rowcount or 0)

    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "changed": sum(1 for r in results if r["skipped"] is None),
        "documents_added": sum(r["added"] for r in results),
        "unpublished": unpublished,
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "help onboarding to client cards: cards=%s docs=%s unpublished=%s",
        summary["changed"],
        summary["documents_added"],
        unpublished,
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = [
        f"{r['client_id']}:{r['skipped']}" for r in summary["results"] if r["skipped"]
    ]
    return (
        f"cards={summary['changed']} docs={summary['documents_added']} "
        f"unpublished={summary['unpublished']} skipped={','.join(skipped) or '-'}"
    )
