"""Pismo na stronie kontraktu — dane z NEXUSA, wzór albo model, sprawdzenie cytatów.

Funkcje nie sprawdzają uprawnień — robi to trasa (bramka pobrania dokumentu
kontraktu, ``api/legal_letters.py``). Niczego nie zapisują i nie wysyłają:
pismo idzie oknem maila NEXUSA albo jako DOCX do Dokumentów kontraktu po
„Zatwierdzam” człowieka. Czyste reguły: ``letters.py``.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.contract import Contract
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services.contract_document_text import index as document_index
from app.services.contract_document_text import service as document_text
from app.services.contract_document_text.structure import (
    document_number,
    ref_of,
    sentences,
)
from app.services.legal import assistant, citations, corpus, deadlines, letters
from app.services.legal.citations import CitationCheck, SourcePassage
from app.services.legal.letters import (
    KIND_CLIENT_LETTER,
    KIND_NOTICE_REPLY,
    KIND_NOTICE_WITHDRAWAL,
    KIND_PENALTY_NOTE,
    KIND_TERMINATION_AGREEMENT,
    KIND_TERMINATION_NOTICE,
    SOURCE_TEMPLATE,
    DeadlineFacts,
    Fact,
    FormWarning,
    LetterKind,
    NoticeRule,
    Recipient,
)
from app.services.legal.pseudonymize import Entity

logger = logging.getLogger(__name__)

PARTNER_NOTICE_MODE = "notice"
PARTNER_PARTY = "consultant"
#: Fragmenty z wyszukiwania w umowie i umowie ramowej klienta dla modelu.
CONTRACT_HITS = 3
CLIENT_HITS = 2
_SEARCH = {
    KIND_NOTICE_REPLY: "zakończenie współpracy zwrot sprzętu poufność usunięcie danych",
    KIND_PENALTY_NOTE: "kara umowna wysokość zapłata",
}


class LetterUnavailable(ValueError):
    """Pisma tego rodzaju nie da się przygotować dla tego kontraktu (422)."""


@dataclass(frozen=True)
class LetterContext:
    contract: Contract
    partner: dict[str, str]
    female: bool
    contract_number: Optional[str]
    signing_date: Optional[date]
    client_name: Optional[str]
    client_legal_name: Optional[str]
    rule: Optional[NoticeRule]
    rule_reason: Optional[str]
    rule_sources: tuple[SourcePassage, ...]
    rule_notes: tuple[str, ...]
    notice_document: Optional[tuple[str, date]]

    @property
    def partner_notice(self) -> bool:
        """Wypowiedzenie złożone przez Partnera zapisane na kontrakcie."""
        return (
            self.contract.agreement_termination_party == PARTNER_PARTY
            and self.contract.agreement_termination_mode == PARTNER_NOTICE_MODE
        )

    @property
    def full_name(self) -> str:
        return self.partner.get("full_name", "")


@dataclass(frozen=True)
class Letter:
    kind: LetterKind
    subject: str
    text: str
    recipient: Recipient
    facts: tuple[Fact, ...]
    steps: tuple[str, ...]
    deadline_note: Optional[str]
    warning: Optional[FormWarning]
    checks: list[CitationCheck]
    issues: list[str]
    lawyer_review: list[str]
    passages: list[SourcePassage]
    notes: list[str] = field(default_factory=list)
    model: Optional[str] = None
    error: Optional[str] = None
    generator_values: dict[str, Any] = field(default_factory=dict)

    @property
    def approval(self) -> letters.ApprovalState:
        return letters.approval_state(
            check_statuses=[c.status for c in self.checks],
            issues=self.issues,
            warning=self.warning,
            has_text=bool(self.text.strip()),
        )


# ── dane z NEXUSA ───────────────────────────────────────────────────────────


def _rule_of(terms: document_text.TerminationTerms) -> NoticeRule:
    sources = list(terms.sources)
    period_source = sources[0].ref if sources else None
    form_source = sources[1].ref if len(sources) > 1 else period_source
    return NoticeRule(
        period_kind=terms.period_kind,
        period_months=terms.period_months,
        period_days=terms.period_days,
        forms=terms.forms,
        under_nullity=terms.under_nullity,
        delivery=terms.delivery,
        period_ref=letters.bare_ref(period_source),
        period_source_ref=period_source,
        form_source_ref=form_source,
    )


async def _generated_row(
    db: AsyncSession, contract: Contract
) -> Optional[B2BGeneratedContract]:
    newest = select(B2BGeneratedContract).order_by(B2BGeneratedContract.id.desc())
    row = await db.scalar(
        newest.where(B2BGeneratedContract.contract_id == contract.id).limit(1)
    )
    if row is None and contract.candidate_id is not None:
        row = await db.scalar(
            newest.where(
                B2BGeneratedContract.candidate_id == contract.candidate_id
            ).limit(1)
        )
    return row


async def _notice_document(
    db: AsyncSession, contract_id: int
) -> Optional[tuple[str, date]]:
    doc = await db.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract_id,
            ContractDocument.doc_type == ContractDocumentType.termination_notice,
        )
        .order_by(ContractDocument.created_at.desc(), ContractDocument.id.desc())
        .limit(1)
    )
    if doc is None:
        return None
    return doc.filename, doc.created_at.date()


async def load_context(db: AsyncSession, contract: Contract) -> LetterContext:
    """Dane osoby, umowy, klienta i reguła wypowiedzenia z PODPISANEJ umowy."""
    from app.services.trainings.agreement import partner_from_contract

    partner = await partner_from_contract(db, contract.id)
    generated = await _generated_row(db, contract)
    detail = await db.scalar(
        select(B2BContractDetail).where(B2BContractDetail.contract_id == contract.id)
    )
    outcome = await document_text.termination_terms(db, contract.id)
    terms = outcome.terms
    number = (
        (generated.contract_number if generated is not None else None)
        or (detail.contract_number if detail is not None else None)
        or None
    )
    signing = (generated.signing_date if generated is not None else None) or (
        detail.signing_date if detail is not None else None
    )
    if number is None and terms is not None and terms.sources:
        # Numer z nagłówka podpisanej umowy („umowa 12/2025 § 8”), gdy rejestr go nie zna.
        label = terms.sources[0].ref.split(" § ")[0]
        tail = label.split(" ", 1)[1] if " " in label else ""
        if label.startswith("umowa ") and "„" not in tail:
            number = tail.strip() or None
    client = await db.get(Client, contract.client_id) if contract.client_id else None
    client_name = (
        (client.display_name or client.name) if client is not None else None
    ) or None
    return LetterContext(
        contract=contract,
        partner=partner,
        female=letters.partner_female(
            partner.get("gender"), partner.get("full_name", "")
        ),
        contract_number=number,
        signing_date=signing,
        client_name=client_name,
        client_legal_name=(getattr(client, "legal_name", None) or client_name)
        if client is not None
        else None,
        rule=_rule_of(terms) if terms is not None else None,
        rule_reason=outcome.reason,
        rule_sources=tuple(terms.sources) if terms is not None else (),
        rule_notes=tuple(terms.notes) if terms is not None else (),
        notice_document=await _notice_document(db, contract.id),
    )


# ── źródła do sprawdzenia cytatów (z bazy, nie od ekranu) ───────────────────


def passages_from_text(
    text: str, label: str, url: Optional[str], filename: Optional[str], kind: str
) -> list[SourcePassage]:
    """Cały dokument jako fragmenty per paragraf i ustęp — źródło weryfikatora."""
    by_ref: dict[str, list[str]] = {}
    for sentence in sentences(text):
        if sentence.section is None:
            continue
        for ref in dict.fromkeys(
            (ref_of(sentence.section, None), ref_of(sentence.section, sentence.point))
        ):
            if ref:
                by_ref.setdefault(ref, []).append(sentence.text)
    return [
        SourcePassage(kind, f"{label} {ref}", " ".join(parts), url, filename)
        for ref, parts in by_ref.items()
    ]


async def contract_passages(db: AsyncSession, contract_id: int) -> list[SourcePassage]:
    """Umowa i aneksy kontraktu z sekcji „Aktualna umowa” jako fragmenty per paragraf."""
    documents = [
        d
        for d in await document_text.read_documents(db, contract_id)
        if d.folder_id is None
        and document_index.has_current_text(d)
        and getattr(d.doc_type, "value", d.doc_type)
        in (ContractDocumentType.contract.value, ContractDocumentType.annex.value)
    ]
    if not documents:
        return []
    chunks = await document_index.load_chunks(db, [d.id for d in documents])
    out: list[SourcePassage] = []
    for document in documents:
        text = "".join(
            c.text
            for c in sorted(
                (c for c in chunks if c.contract_id == document.id),
                key=lambda c: c.index,
            )
        )
        label = document_text._label(document, document_number(text))
        out.extend(
            passages_from_text(
                text,
                label,
                document_text.document_url(document),
                document.filename,
                "contract",
            )
        )
    return out


async def _client_contracts(
    db: AsyncSession, client_id: Optional[int]
) -> list[ClientFrameworkContract]:
    if client_id is None:
        return []
    rows = await db.execute(
        select(ClientFrameworkContract)
        .where(ClientFrameworkContract.client_id == client_id)
        .order_by(ClientFrameworkContract.effective_date.desc().nullslast())
    )
    return list(rows.scalars().all())


def _client_url(fc: ClientFrameworkContract) -> str:
    return f"/clients/{fc.client_id}?tab=contracts"


async def client_passages(
    db: AsyncSession, client_id: Optional[int]
) -> list[SourcePassage]:
    """Umowy ramowe klienta (istniejący indeks) jako fragmenty per paragraf."""
    from app.services import framework_contract_index

    rows = [
        fc
        for fc in await _client_contracts(db, client_id)
        if framework_contract_index.has_current_text(fc)
    ]
    if not rows:
        return []
    chunks = await framework_contract_index.load_chunks(db, [fc.id for fc in rows])
    out: list[SourcePassage] = []
    for fc in rows:
        text = "".join(
            c.text
            for c in sorted(
                (c for c in chunks if c.contract_id == fc.id), key=lambda c: c.index
            )
        )
        out.extend(
            passages_from_text(
                text,
                f"umowa ramowa „{fc.name}”",
                _client_url(fc),
                fc.filename,
                "client",
            )
        )
    return out


async def verification_passages(
    db: AsyncSession, contract: Contract
) -> list[SourcePassage]:
    """Źródła weryfikatora z bazy: umowa Partnera (najpierw) i umowy ramowe klienta."""
    return [
        *await contract_passages(db, contract.id),
        *await client_passages(db, contract.client_id),
    ]


async def verify_letter_text(
    db: AsyncSession,
    contract: Contract,
    text: str,
    extra: Sequence[SourcePassage] = (),
) -> list[CitationCheck]:
    """Cytaty pisma z tekstem źródeł: przepisy z korpusu, umowy z bazy."""
    sources = [*extra, *await verification_passages(db, contract)]
    return await corpus.verify_text(db, text, sources, on_date=business_today())


# ── wyszukiwanie fragmentów dla modelu ──────────────────────────────────────


async def _model_passages(
    db: AsyncSession, ctx: LetterContext, kind: str, user_text: str
) -> list[SourcePassage]:
    from app.services import framework_contract_index
    from app.services.contract_document_text.structure import markers, range_ref

    out: list[SourcePassage] = list(ctx.rule_sources)
    query = _SEARCH.get(kind) or user_text or "współpraca konsultanta"
    try:
        found = await document_text.search_contract_documents(
            db, ctx.contract.id, query[:300]
        )
        out.extend(p.source for p in found.passages[:CONTRACT_HITS])
    except Exception as exc:  # noqa: BLE001 — wyszukiwanie to dodatek do pisma
        logger.warning("[legal-letter] wyszukiwanie w umowie: %s", type(exc).__name__)
    rows = await _client_contracts(db, ctx.contract.client_id)
    if rows and kind in (KIND_NOTICE_REPLY, KIND_PENALTY_NOTE, KIND_CLIENT_LETTER):
        try:
            outcome = await framework_contract_index.search(db, rows, query[:300])
            by_id = {fc.id: fc for fc in rows}
            for passage in outcome.passages[:CLIENT_HITS]:
                fc = by_id[passage.contract_id]
                section = range_ref(markers(passage.text), 0, len(passage.text))
                label = f"umowa ramowa „{fc.name}”"
                out.append(
                    SourcePassage(
                        "client",
                        f"{label} {section}" if section else label,
                        passage.text,
                        _client_url(fc),
                        fc.filename,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[legal-letter] wyszukiwanie w umowie ramowej: %s", type(exc).__name__
            )
    seen: set[tuple[str, str]] = set()
    unique = []
    for passage in out:
        if (passage.ref, passage.text) in seen:
            continue
        seen.add((passage.ref, passage.text))
        unique.append(passage)
    return unique


# ── budowa pisma ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LetterRequest:
    kind: str
    instruction: str = ""
    delivered_on: Optional[date] = None
    termination_date: Optional[date] = None
    original_confirmed: bool = False
    penalty_amount: Optional[float] = None
    payment_days: int = letters.PENALTY_PAYMENT_DAYS


def _partner_address(partner: dict[str, str]) -> str:
    return ", ".join(
        p for p in (partner.get("address"), partner.get("postal_city")) if p
    )


def partner_recipient(ctx: LetterContext) -> Recipient:
    lines = [
        ctx.partner.get("company") or "",
        _partner_address(ctx.partner),
    ]
    return Recipient(
        kind="partner",
        name=ctx.full_name or "Partner",
        lines=tuple(line for line in lines if line),
        email=ctx.partner.get("email") or None,
        candidate_id=ctx.contract.candidate_id,
    )


def client_recipient(ctx: LetterContext) -> Recipient:
    return Recipient(
        kind="client",
        name=ctx.client_legal_name or ctx.client_name or "Klient",
        candidate_id=ctx.contract.candidate_id,
    )


def _contract_phrase(ctx: LetterContext) -> str:
    number = f" nr {ctx.contract_number}" if ctx.contract_number else ""
    signed = f" z dnia {ctx.signing_date:%d.%m.%Y} r." if ctx.signing_date else ""
    return f"umowy o współpracy B2B{number}{signed}"


def subject_for(kind: str, ctx: LetterContext) -> str:
    phrase = _contract_phrase(ctx)
    return {
        KIND_NOTICE_REPLY: f"potwierdzenie wypowiedzenia {phrase}",
        KIND_TERMINATION_NOTICE: f"wypowiedzenie {phrase}",
        KIND_TERMINATION_AGREEMENT: f"porozumienie o rozwiązaniu {phrase}",
        KIND_NOTICE_WITHDRAWAL: f"cofnięcie wypowiedzenia {phrase}",
        KIND_PENALTY_NOTE: f"nota obciążeniowa — kara umowna z {phrase}",
        KIND_CLIENT_LETTER: f"współpraca konsultanta — {phrase}",
    }[kind]


def _delivered_on(ctx: LetterContext, request: LetterRequest) -> Optional[date]:
    if request.delivered_on is not None:
        return request.delivered_on
    if ctx.partner_notice:
        return ctx.contract.agreement_termination_signed_on
    return None


def _deadline_facts(ctx: LetterContext, delivered: Optional[date]) -> DeadlineFacts:
    return letters.deadline_facts(
        ctx.rule,
        delivered,
        recorded_last_day=ctx.contract.agreement_last_day
        if ctx.partner_notice
        else None,
        rule_reason=ctx.rule_reason,
    )


def template_values(
    kind: str,
    ctx: LetterContext,
    *,
    today: date,
    delivered_on: Optional[date],
    end: Optional[date],
) -> dict[str, Any]:
    """Pola wzoru Generatora (klucze ``registry``) z danych NEXUSA i z terminu kodu."""
    partner = ctx.partner
    values: dict[str, Any] = {
        "document_date": today.isoformat(),
        "gender": "f" if ctx.female else "m",
        "partner_name": partner.get("full_name") or None,
        "partner_instrumental": partner.get("name_instrumental") or None,
        "partner_legal_name": partner.get("company") or None,
        "partner_business_address": _partner_address(partner) or None,
        "partner_nip": partner.get("nip") or None,
        "partner_regon": partner.get("regon") or None,
        "contract_number": ctx.contract_number,
        "contract_signing_date": ctx.signing_date.isoformat()
        if ctx.signing_date
        else None,
    }
    if kind == KIND_TERMINATION_NOTICE:
        values["delivery_date"] = (delivered_on or today).isoformat()
        values["termination_date"] = end.isoformat() if end else None
    elif kind == KIND_TERMINATION_AGREEMENT:
        values["termination_date"] = end.isoformat() if end else None
        values["last_service_date"] = end.isoformat() if end else None
    elif kind == KIND_NOTICE_WITHDRAWAL:
        values["notice_delivery_date"] = (
            delivered_on.isoformat() if delivered_on else None
        )
    return {k: v for k, v in values.items() if v not in (None, "")}


def render_template_letter(
    kind: LetterKind,
    ctx: LetterContext,
    values: dict[str, Any],
    *,
    docx: bool = False,
) -> str | bytes:
    """Wzór Generatora wypełniony danymi: tekst (panel, mail) albo DOCX (plik)."""
    from app.services.b2b_documents import registry
    from app.services.b2b_documents.context import (
        BaseContractInfo,
        build_document_context,
    )
    from app.services.b2b_documents.render import (
        render_docx,
        render_html,
        template_key,
    )

    doc_type = registry.get_type(kind.template or "")
    if doc_type is None:
        raise LetterUnavailable(f"Brak wzoru {kind.template!r} w Generatorze.")
    overrides: dict[str, str] = {}
    rule = ctx.rule
    if doc_type.key == "termination_notice":
        # Paragraf i okres z PODPISANEJ umowy, nie z dzisiejszego wzoru; bez
        # reguły zostaje „…”, a pismo jest zablokowane do uzupełnienia.
        overrides["notice_paragraph"] = (rule.period_ref if rule else None) or "…"
        overrides["notice_period_pl"] = (
            letters.period_genitive(rule) if rule else None
        ) or "…"
    context = build_document_context(
        doc_type,
        values,
        language="pl",
        base=BaseContractInfo(
            contract_number=ctx.contract_number,
            signing_date=ctx.signing_date,
            client_name=ctx.client_name,
            client_legal_name=ctx.client_legal_name,
        ),
        refs=None,
        ref_overrides=overrides,
    )
    key = template_key(doc_type.key, "pl", doc_type.template_revision)
    if docx:
        return render_docx(key, context)
    return letters.html_to_text(render_html(key, context))


def _model_entities(
    ctx: LetterContext,
    *,
    delivered: Optional[date],
    end: Optional[date],
    period: Optional[str],
    extra: Sequence[Entity] = (),
    to_client: bool = False,
) -> list[Entity]:
    partner = ctx.partner
    pairs: list[Entity] = [
        Entity("PARTNER", partner.get("full_name", ""), inflect=True),
        Entity("FIRMA_PARTNERA", partner.get("company", "")),
        Entity("NIP", partner.get("nip", "")),
        Entity("ADRES_PARTNERA", _partner_address(partner)),
        Entity("EMAIL_PARTNERA", partner.get("email", "")),
        Entity("TELEFON_PARTNERA", partner.get("phone", "")),
        Entity("KLIENT", ctx.client_legal_name or ctx.client_name or ""),
        Entity("NUMER_UMOWY", ctx.contract_number or ""),
    ]
    if ctx.signing_date:
        pairs.append(Entity("DATA_UMOWY", deadlines.polish_date(ctx.signing_date)))
    if delivered:
        pairs.append(Entity("DATA_ZLOZENIA", deadlines.polish_date(delivered)))
    if end:
        pairs.append(Entity("DATA_ROZWIAZANIA", deadlines.polish_date(end)))
    if period:
        pairs.append(Entity("OKRES_WYPOWIEDZENIA", period))
    pairs.extend(extra)
    pairs.extend(
        letters.CLIENT_COURTESY if to_client else letters.courtesy_entities(ctx.female)
    )
    return [e for e in pairs if e.value.strip()]


async def build_letter(
    db: AsyncSession,
    contract: Contract,
    request: LetterRequest,
    *,
    user_id: Optional[int] = None,
    ctx: Optional[LetterContext] = None,
) -> Letter:
    """Szkic pisma: wzór wypełnia kod, pisma modelu — ``assistant.draft``."""
    kind = letters.KINDS_BY_KEY.get(request.kind)
    if kind is None:
        raise LetterUnavailable(f"Nieznany rodzaj pisma: {request.kind!r}.")
    ctx = ctx or await load_context(db, contract)
    if kind.needs_partner_notice and not ctx.partner_notice:
        raise LetterUnavailable(
            "Na kontrakcie nie ma zapisanego wypowiedzenia złożonego przez Partnera "
            "(„Zapisz rozwiązanie umowy”: tryb wypowiedzenie, strona konsultant)."
        )
    today = business_today()
    delivered = _delivered_on(ctx, request)
    if kind.key == KIND_TERMINATION_NOTICE and delivered is None:
        delivered = today
    facts = _deadline_facts(ctx, delivered)
    end = facts.end
    if kind.key == KIND_TERMINATION_AGREEMENT:
        end = (
            request.termination_date
            or end
            or (ctx.contract.agreement_last_day if ctx.partner_notice else None)
        )
    warning = letters.form_warning(
        kind.key,
        ctx.rule,
        notice_document=ctx.notice_document,
        original_confirmed=request.original_confirmed,
    )
    notes = list(ctx.rule_notes)
    recipient = (
        client_recipient(ctx) if kind.recipient == "client" else partner_recipient(ctx)
    )
    subject = subject_for(kind.key, ctx)
    show_deadline = kind.key in (
        KIND_NOTICE_REPLY,
        KIND_TERMINATION_NOTICE,
        KIND_TERMINATION_AGREEMENT,
    )

    if kind.source == SOURCE_TEMPLATE:
        values = template_values(
            kind.key, ctx, today=today, delivered_on=delivered, end=end
        )
        text = str(render_template_letter(kind, ctx, values))
        issues = letters.placeholder_issues(text)
        checks = await verify_letter_text(db, contract, text)
        return Letter(
            kind=kind,
            subject=subject,
            text=text,
            recipient=recipient,
            facts=facts.facts if show_deadline else (),
            steps=facts.steps if show_deadline else (),
            deadline_note=facts.reason if show_deadline else None,
            warning=warning,
            checks=checks,
            issues=issues,
            lawyer_review=assistant.lawyer_triggers(text),
            passages=list(ctx.rule_sources),
            notes=notes,
            generator_values=values,
        )

    extra: list[Entity] = []
    issues: list[str] = []
    if kind.key == KIND_PENALTY_NOTE:
        if not request.penalty_amount or request.penalty_amount <= 0:
            raise LetterUnavailable("Podaj kwotę kary umownej z umowy.")
        from app.services.b2b_contract_generator.number_words import rate_in_words

        words = rate_in_words(request.penalty_amount, "pl")
        due = deadlines.term_end(
            today, request.payment_days, deadlines.UNIT_DAYS, shift_free_days=True
        )
        extra = [
            Entity("KWOTA_KARY", letters.amount_text(request.penalty_amount, words)),
            Entity("TERMIN_ZAPLATY", deadlines.polish_date(due.end)),
        ]
        facts = DeadlineFacts(
            (
                Fact("Kwota", letters.amount_text(request.penalty_amount, words)),
                Fact("Termin zapłaty", f"{due.end:%d.%m.%Y}"),
            ),
            due.steps,
            due.end,
        )
        show_deadline = True
    if kind.key == KIND_CLIENT_LETTER and len(request.instruction.strip()) < 10:
        raise LetterUnavailable("Napisz w poleceniu, czego dotyczy pismo do klienta.")
    period = letters.period_label(ctx.rule) if ctx.rule else None
    instruction = letters.model_instruction(
        kind.key,
        has_end=end is not None,
        has_period=period is not None,
        user_text=request.instruction,
    )
    passages = await _model_passages(db, ctx, kind.key, request.instruction)
    draft = await assistant.draft(
        db,
        kind=kind.draft_kind or "letter",
        instruction=instruction,
        passages=passages,
        entities=_model_entities(
            ctx,
            delivered=delivered,
            end=end if kind.key == KIND_NOTICE_REPLY else None,
            period=period if kind.key == KIND_NOTICE_REPLY else None,
            extra=extra,
            to_client=kind.recipient == "client",
        ),
        user_id=user_id,
        on_date=today,
    )
    text = ""
    checks: list[CitationCheck] = []
    if draft.text:
        text = letters.compose_letter(
            place="Warszawa",
            on_date=today,
            recipient=recipient,
            subject=subject[:1].upper() + subject[1:],
            body=draft.text,
            signature="B2B.net S.A.",
        )
        checks = await verify_letter_text(db, contract, text, draft.passages)
    issues.extend(draft.issues)
    lawyer = list(draft.lawyer_review)
    if kind.key == KIND_PENALTY_NOTE and "kara umowna" not in lawyer:
        lawyer.insert(0, "kara umowna")
    return Letter(
        kind=kind,
        subject=subject,
        text=text,
        recipient=recipient,
        facts=facts.facts if show_deadline else (),
        steps=facts.steps if show_deadline else (),
        deadline_note=facts.reason if show_deadline else None,
        warning=warning,
        checks=checks,
        issues=issues,
        lawyer_review=lawyer,
        passages=draft.passages,
        notes=notes,
        model=draft.model,
        error=draft.error,
    )


@dataclass(frozen=True)
class TextReview:
    letter_kind: LetterKind
    text: str
    checks: list[CitationCheck]
    warning: Optional[FormWarning]
    issues: list[str]
    approval: letters.ApprovalState
    letter: Optional[Letter] = None


async def review_text(
    db: AsyncSession,
    contract: Contract,
    request: LetterRequest,
    text: str,
) -> TextReview:
    """Sprawdzenie przed „Zatwierdzam” i DOCX — bez modelu.

    Pismo ze wzoru składa się od nowa z danych NEXUSA (tekst od ekranu się nie
    liczy, wzór poprawia się w Generatorze). Pismo modelu to tekst człowieka
    po poprawkach: cytaty sprawdzamy z tekstem źródeł z bazy, pytanie o formę
    musi mieć odpowiedź.
    """
    kind = letters.KINDS_BY_KEY.get(request.kind)
    if kind is None:
        raise LetterUnavailable(f"Nieznany rodzaj pisma: {request.kind!r}.")
    ctx = await load_context(db, contract)
    if kind.source == SOURCE_TEMPLATE:
        letter = await build_letter(db, contract, request, ctx=ctx)
        return TextReview(
            kind,
            letter.text,
            letter.checks,
            letter.warning,
            letter.issues,
            letter.approval,
            letter,
        )
    if kind.needs_partner_notice and not ctx.partner_notice:
        raise LetterUnavailable(
            "Na kontrakcie nie ma zapisanego wypowiedzenia złożonego przez Partnera."
        )
    warning = letters.form_warning(
        kind.key,
        ctx.rule,
        notice_document=ctx.notice_document,
        original_confirmed=request.original_confirmed,
    )
    checks = await verify_letter_text(db, contract, text) if text.strip() else []
    approval = letters.approval_state(
        check_statuses=[c.status for c in checks],
        issues=[],
        warning=warning,
        has_text=bool(text.strip()),
    )
    return TextReview(kind, text, checks, warning, [], approval)


def text_docx(text: str) -> bytes:
    """Pismo modelu jako prosty DOCX: akapit na każdy blok tekstu."""
    from docx import Document

    from app.core.docx_metadata import clear_app_properties, clear_author_metadata

    document = Document()
    for block in [b for b in text.split("\n\n")]:
        lines = block.strip("\n").split("\n")
        paragraph = document.add_paragraph()
        for index, line in enumerate(lines):
            run = paragraph.add_run(line)
            if index < len(lines) - 1:
                run.add_break()
    clear_author_metadata(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return clear_app_properties(buffer.getvalue())


def citation_blocking(checks: Sequence[CitationCheck]) -> bool:
    return citations.blocking(checks)
