"""„Przejrzyj wzór”: nowa wersja aktu zmienia przepis cytowany we wzorze (część H).

Plan: ``docs/asystent-prawny-plan.md``, reguła:
``docs/claude/asystent-prawny/przejrzyj-wzor-po-zmianie-przepisu.md``.

Gdy korpus prawa (część A) zapisze nowy tekst aktu (``corpus.changes_since``),
porównujemy oznaczenia zmienione, usunięte i dodane z odwołaniami do przepisów
we wzorach (``citations.extract``):

* szablony z repo: ``app/templates/contract/*.html`` i bieżące rewizje
  ``app/templates/documents/*.html`` z rejestru typów dokumentów,
* klauzule klientów (``b2b_contract_generator.clause_override_content``),
* zatwierdzone, niewycofane wzory własne (część B).

Dla każdej nowej wersji aktu, która dotyka choć jednego cytowanego przepisu,
NEXUS zakłada w Przepisach jedną zmianę (rola ``contracts``) z zadaniami
„Przejrzyj wzór X — zmienił się art. Y”. Do zmiany należy pozycja
``law_radar_items`` z adresem urzędowego tekstu (klasa ``official``, bramka
``verified``, ``analyzed_at`` ustawione — nie idzie do Analityka). Jej odcisk
(``corpus_fingerprint``) jest kluczem bez duplikatów: drugi przebieg dokłada
do otwartej zmiany tylko brakujące zadania, a zamkniętej (zrobione,
„Nie dotyczy”) nie rusza. Bez maili i bez powiadomień.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.law_radar import LawChange, LawChangeEvent, LawChangeTask, LawRadarItem
from app.services.law_radar import schema as radar_schema
from app.services.legal import citations
from app.services.legal.acts import SOURCE_ELI, spec_for

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
#: Ile dni wstecz przegląda pętla (powtórka po awarii; duplikatów pilnuje odcisk).
LOOKBACK = timedelta(days=3)
TASK_PREFIX = "Przejrzyj wzór"
ROLE = "contracts"
GATE_REASON = "legal_corpus"
_LOCK_KEY = "legal_template_review"

#: Umowy z ``templates/contract`` (dokumenty pochodne mają nazwy w rejestrze).
CONTRACT_LABELS: dict[str, str] = {
    "umowa_b2b_pl": "Umowa B2B (PL)",
    "umowa_b2b_en": "Umowa B2B (EN)",
    "umowa_zlecenie_pl": "Umowa zlecenie (PL)",
}


@dataclass(frozen=True)
class TemplateSource:
    key: str
    label: str
    text: str


@dataclass(frozen=True)
class TemplateCitation:
    template_key: str
    label: str
    act_key: str
    ref: str
    key: str


@dataclass(frozen=True)
class ReviewPlan:
    """Nowa wersja aktu i cytaty wzorów, których przepis się zmienił."""

    act_key: str
    act_short: str
    act_title: str
    act_source: str
    version_id: int
    version_ident: str
    valid_from: date
    published_on: Optional[date]
    url: str
    hits: tuple[TemplateCitation, ...] = ()


@dataclass
class ReviewResult:
    versions: int = 0
    changes_created: int = 0
    tasks_added: int = 0
    skipped_closed: int = 0
    plans: list[ReviewPlan] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "versions": self.versions,
            "changes_created": self.changes_created,
            "tasks_added": self.tasks_added,
            "skipped_closed": self.skipped_closed,
        }


# ── tekst wzorów ────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<(style|script)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
#: „art. 22.§ 1 Kodeksu Pracy” (wzór umowy) → „art. 22 § 1”.
_DOT_BEFORE_PAR = re.compile(r"(\d)\.(?=\s*§)")
_SPACES = re.compile(r"\s+")


def plain_text(raw: str) -> str:
    """Tekst z HTML wzoru (bez znaczników i stylów), gotowy dla ``extract``."""
    without_style = _STYLE.sub(" ", raw)
    return normalize(html.unescape(_TAG.sub(" ", without_style)))


def normalize(value: str) -> str:
    return _SPACES.sub(" ", _DOT_BEFORE_PAR.sub(r"\1 ", value)).strip()


def _document_labels() -> dict[str, str]:
    from app.services.b2b_documents.registry import TYPES
    from app.services.b2b_documents.render import template_key

    labels: dict[str, str] = {}
    for doc_type in TYPES.values():
        if doc_type.family == "custom":
            continue
        for language in doc_type.languages:
            key = template_key(doc_type.key, language, doc_type.template_revision)
            suffix = f" ({language.upper()})" if language != "pl" else ""
            labels[key] = f"{doc_type.label}{suffix}"
    return labels


def repo_templates(base: Path = TEMPLATES_DIR) -> list[tuple[str, str, Path]]:
    """``(klucz, nazwa, plik)`` umów z ``contract/`` i bieżących rewizji dokumentów."""
    out = [
        (f"contract/{path.stem}", CONTRACT_LABELS.get(path.stem, path.stem), path)
        for path in sorted((base / "contract").glob("*.html"))
    ]
    labels = _document_labels()
    # Rewizje sprzed obecnej zostają w repo tylko dla wydanych dokumentów.
    out.extend(
        (f"documents/{path.stem}", labels[path.stem], path)
        for path in sorted((base / "documents").glob("*.html"))
        if path.stem in labels
    )
    return out


def repo_template_sources(base: Path = TEMPLATES_DIR) -> list[TemplateSource]:
    return [
        TemplateSource(key, label, plain_text(path.read_text(encoding="utf-8")))
        for key, label, path in repo_templates(base)
    ]


def clause_sources() -> list[TemplateSource]:
    """Klauzule klientów (PL) — jeden wzór na wpis rejestru z treścią."""
    from app.services.b2b_contract_generator.clause_override_content import (
        CLIENT_OVERRIDES,
    )

    out: list[TemplateSource] = []
    for needles, builder in CLIENT_OVERRIDES:
        ops = builder("pl")  # type: ignore[operator]
        texts = [
            block[1]
            for _kind, _anchor, blocks in ops
            for block in blocks
            if isinstance(block, tuple) and len(block) == 2
        ]
        if not texts:
            continue
        out.append(
            TemplateSource(
                f"clauses/{needles[0]}",
                f"Klauzule klienta „{needles[0]}”",
                normalize(" ".join(texts)),
            )
        )
    return out


async def custom_template_sources(db: AsyncSession) -> list[TemplateSource]:
    """Zatwierdzone, niewycofane wzory własne (wersja aktywna)."""
    from app.models.custom_document_template import (
        CustomDocumentTemplate,
        CustomDocumentTemplateVersion,
    )
    from app.services.custom_templates.checks import document_text

    rows = await db.execute(
        select(
            CustomDocumentTemplate.id,
            CustomDocumentTemplateVersion.name,
            CustomDocumentTemplateVersion.docx,
        )
        .join(
            CustomDocumentTemplateVersion,
            CustomDocumentTemplateVersion.id
            == CustomDocumentTemplate.active_version_id,
        )
        .where(
            CustomDocumentTemplate.withdrawn_at.is_(None),
            CustomDocumentTemplateVersion.status == "approved",
        )
        .order_by(CustomDocumentTemplate.id)
    )
    out: list[TemplateSource] = []
    for template_id, name, docx_bytes in rows.all():
        try:
            body = document_text(docx_bytes)
        except Exception:  # noqa: BLE001 — uszkodzony plik nie zatrzymuje reszty
            logger.warning("[legal] wzór własny %s: nie da się odczytać", template_id)
            continue
        out.append(
            TemplateSource(
                f"custom/{template_id}", f"{name} (wzór własny)", normalize(body)
            )
        )
    return out


async def all_sources(db: AsyncSession) -> list[TemplateSource]:
    return [
        *repo_template_sources(),
        *clause_sources(),
        *await custom_template_sources(db),
    ]


# ── cytaty i dopasowanie do zmian ───────────────────────────────────────────


def template_citations(sources: Iterable[TemplateSource]) -> list[TemplateCitation]:
    """Odwołania do przepisów znanych aktów, bez powtórek w jednym wzorze."""
    out: list[TemplateCitation] = []
    for source in sources:
        seen: set[tuple[str, str]] = set()
        for found in citations.extract(normalize(source.text)):
            if found.kind != citations.KIND_LAW or found.act_key is None:
                continue
            ident = (found.act_key, canonical(found.key))
            if ident in seen:
                continue
            seen.add(ident)
            out.append(
                TemplateCitation(
                    source.key, source.label, found.act_key, found.ref, found.key
                )
            )
    return out


def canonical(key: str) -> str:
    """„61 §1” i „61 ust.1” to ta sama jednostka (KC ma §, ustawy ust.)."""
    return key.replace("§", "ust.")


def touched_keys(
    added: Sequence[str], removed: Sequence[str], changed: Sequence[str]
) -> set[str]:
    return {canonical(key) for key in (*added, *removed, *changed)}


def cites_touched(citation_key: str, touched: set[str]) -> bool:
    """Zmieniła się jednostka cytowana albo któraś z jej podjednostek.

    Zmiana artykułu nadrzędnego bez zmiany cytowanego § nie liczy się: tekst
    artykułu obejmuje wszystkie paragrafy, więc zmiana § 2 nie dotyczy
    cytatu z § 1."""
    cited = canonical(citation_key)
    prefix = cited + " "
    return any(key == cited or key.startswith(prefix) for key in touched)


def plan_for_change(
    change: Any, cited: Sequence[TemplateCitation], meta: dict[str, Any]
) -> Optional[ReviewPlan]:
    """``change`` — ``corpus.VersionChange``; ``meta`` — dane wersji i aktu."""
    touched = touched_keys(change.added, change.removed, change.changed)
    if not touched:
        return None
    hits = tuple(
        c
        for c in cited
        if c.act_key == change.act_key and cites_touched(c.key, touched)
    )
    if not hits:
        return None
    spec = spec_for(change.act_key)
    return ReviewPlan(
        act_key=change.act_key,
        act_short=(spec.short_name if spec else meta.get("short_name"))
        or change.act_key,
        act_title=meta.get("title") or (spec.title if spec else change.act_key),
        act_source=meta.get("source") or (spec.source if spec else SOURCE_ELI),
        version_id=change.version_id,
        version_ident=change.version_ident,
        valid_from=change.valid_from,
        published_on=meta.get("published_on"),
        url=meta.get("url") or "",
        hits=hits,
    )


# ── teksty zmiany i zadań ───────────────────────────────────────────────────


def change_title(plan: ReviewPlan) -> str:
    return f"Przejrzyj wzory — nowy tekst {plan.act_short} ({plan.version_ident})"[
        : radar_schema.CHANGE_TITLE_MAX
    ]


def task_text(citation: TemplateCitation, plan: ReviewPlan) -> str:
    tail = f" — zmienił się {citation.ref} {plan.act_short}"
    room = radar_schema.TASK_TEXT_MAX - len(TASK_PREFIX) - len(tail) - 3
    label = (
        citation.label
        if len(citation.label) <= room
        else citation.label[: room - 1] + "…"
    )
    return f"{TASK_PREFIX} „{label}”{tail}"


def task_texts(plan: ReviewPlan) -> list[str]:
    out: list[str] = []
    for citation in plan.hits:
        value = task_text(citation, plan)
        if value.lower() not in {t.lower() for t in out}:
            out.append(value)
    return out


def missing_tasks(existing: Iterable[str], planned: Sequence[str]) -> list[str]:
    """Zadania, których zmiana jeszcze nie ma (bez wielkości liter)."""
    have = {value.strip().lower() for value in existing}
    out: list[str] = []
    for value in planned:
        if value.strip().lower() not in have:
            have.add(value.strip().lower())
            out.append(value)
    return out


def _refs(plan: ReviewPlan) -> str:
    refs: list[str] = []
    for citation in plan.hits:
        if citation.ref not in refs:
            refs.append(citation.ref)
    return ", ".join(refs)


def change_values(plan: ReviewPlan) -> dict[str, Any]:
    refs = _refs(plan)
    templates = len({c.template_key for c in plan.hits})
    return {
        "title": change_title(plan),
        "summary": [
            f"Korpus asystenta prawnego ma nowy tekst: {plan.act_title}"
            f" ({plan.version_ident}, stan od {plan.valid_from.strftime('%d.%m.%Y')}).",
            f"Zmienione przepisy cytowane we wzorach: {refs} {plan.act_short}.",
            f"Wzory do przejrzenia: {templates}. Zadania założył NEXUS, nie bot.",
        ],
        "roles": [ROLE],
        "urgency": "soon",
        "stage": "in_force",
        "effective_on": plan.valid_from,
        "legal_ref": f"{refs} {plan.act_short}"[: radar_schema.LEGAL_REF_MAX],
        "probe_keys": [],
    }


def corpus_fingerprint(version_id: int) -> str:
    return hashlib.sha256(f"legal_corpus:{version_id}".encode()).hexdigest()


_ACT_REF = re.compile(radar_schema.ACT_REF_PATTERN)


def item_values(plan: ReviewPlan, change_id: int, now: datetime) -> dict[str, Any]:
    act_ref = plan.version_ident if _ACT_REF.match(plan.version_ident) else None
    return {
        "fingerprint": corpus_fingerprint(plan.version_id),
        "source": "sejm" if plan.act_source == SOURCE_ELI else "eurlex",
        "klass": "official",
        "gate": "verified",
        "gate_reason": GATE_REASON,
        "title": f"{plan.act_title} — tekst {plan.version_ident}"[
            : radar_schema.ITEM_TITLE_MAX
        ],
        "url": plan.url[: radar_schema.URL_MAX],
        "published": plan.published_on or plan.valid_from,
        "act_ref": act_ref,
        "official": {
            "legal_corpus_version_id": plan.version_id,
            "valid_from": plan.valid_from.isoformat(),
        },
        "change_id": change_id,
        # Pozycja z korpusu nie idzie do Analityka (bierze tylko analyzed_at NULL).
        "analyzed_at": now,
    }


# ── zapis ───────────────────────────────────────────────────────────────────


async def apply(
    db: AsyncSession, plans: Sequence[ReviewPlan], *, now: datetime
) -> ReviewResult:
    """Zmiany i zadania dla planów; commit robi wołający."""
    result = ReviewResult(versions=len(plans), plans=list(plans))
    if not plans:
        return result
    # Pętla i skrypt ręczny naraz nie założą dwóch zmian dla jednej wersji.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _LOCK_KEY}
    )
    for plan in plans:
        planned = task_texts(plan)
        change_id = await db.scalar(
            select(LawRadarItem.change_id).where(
                LawRadarItem.fingerprint == corpus_fingerprint(plan.version_id)
            )
        )
        change = (
            await db.get(LawChange, change_id, with_for_update=True)
            if change_id
            else None
        )
        if change is not None:
            if change.status not in radar_schema.OPEN_STATUSES:
                result.skipped_closed += 1
                continue
            existing = (
                await db.execute(
                    select(LawChangeTask.text).where(
                        LawChangeTask.change_id == change.id
                    )
                )
            ).scalars()
            todo = missing_tasks(existing, planned)
            if todo:
                change.updated_at = now
        else:
            change = LawChange(
                **change_values(plan),
                status="new",
                created_at=now,
                updated_at=now,
            )
            db.add(change)
            await db.flush()
            db.add(
                LawChangeEvent(
                    change_id=change.id,
                    kind="created",
                    note="Nowy tekst aktu w korpusie asystenta prawnego",
                )
            )
            values = item_values(plan, change.id, now)
            stmt = pg_insert(LawRadarItem).values(**values)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[LawRadarItem.fingerprint],
                    set_={"change_id": stmt.excluded.change_id},
                )
            )
            todo = planned
            result.changes_created += 1
        for value in todo:
            task = LawChangeTask(
                change_id=change.id, text=value, role=ROLE, source="user"
            )
            db.add(task)
            await db.flush()
            db.add(
                LawChangeEvent(
                    change_id=change.id, kind="task_added", task_id=task.id, note=value
                )
            )
            result.tasks_added += 1
    return result


async def _version_meta(
    db: AsyncSession, version_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    from app.models.legal_corpus import LegalAct, LegalActVersion

    if not version_ids:
        return {}
    rows = await db.execute(
        select(
            LegalActVersion.id,
            LegalActVersion.url,
            LegalActVersion.published_on,
            LegalAct.title,
            LegalAct.short_name,
            LegalAct.source,
        )
        .join(LegalAct, LegalAct.id == LegalActVersion.act_id)
        .where(LegalActVersion.id.in_(list(version_ids)))
    )
    return {
        vid: {
            "url": url,
            "published_on": published_on,
            "title": title,
            "short_name": short_name,
            "source": source,
        }
        for vid, url, published_on, title, short_name, source in rows.all()
    }


async def build_plans(db: AsyncSession, *, since: datetime) -> list[ReviewPlan]:
    from app.services.legal import corpus

    changes = await corpus.changes_since(db, since)
    if not changes:
        return []
    cited = template_citations(await all_sources(db))
    meta = await _version_meta(db, [c.version_id for c in changes])
    out = []
    for change in changes:
        planned = plan_for_change(change, cited, meta.get(change.version_id, {}))
        if planned is not None:
            out.append(planned)
    return out


async def run(db: AsyncSession, *, since: datetime, now: datetime) -> ReviewResult:
    """Plan i zapis w jednej transakcji (commit robi wołający)."""
    plans = await build_plans(db, since=since)
    return await apply(db, plans, now=now)


async def review_status(db: AsyncSession) -> dict[str, Any]:
    """Do karty „Źródła asystenta prawnego”: otwarte zmiany i ostatnie założenie."""
    rows = (
        await db.execute(
            select(LawChange.status, func.count(), func.max(LawChange.created_at))
            .join(LawRadarItem, LawRadarItem.change_id == LawChange.id)
            .where(LawRadarItem.gate_reason == GATE_REASON)
            .group_by(LawChange.status)
        )
    ).all()
    open_count = sum(
        int(n) for status, n, _ in rows if status in radar_schema.OPEN_STATUSES
    )
    last = max((at for _s, _n, at in rows if at is not None), default=None)
    return {"open": open_count, "last_created_at": last.isoformat() if last else None}
