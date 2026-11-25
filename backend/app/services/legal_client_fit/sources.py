"""Źródła porównania: fragmenty umowy ramowej klienta i nasz wzór umowy B2B.

* **Klient** — umowy ramowe (bez wygasłych, rozwiązanych i zastąpionych)
  i ich aneksy z indeksu treści (``framework_contract_index``): dla każdego
  tematu najlepsze fragmenty po słowach i po znaczeniu. Oznaczenie fragmentu
  („Aneks „DORA” (aneks.pdf), § 4 ust. 2”) liczy kod z układu całego
  dokumentu (``contract_document_text.structure``), nie model.
* **Nasz wzór** — ``templates/contract/umowa_b2b_pl.html`` z klauzulami
  klienta (``clause_overrides``, te same operacje co przy generowaniu umowy),
  pocięty na paragrafy („§ 9”) i załączniki („Załącznik nr 2”). Komparycja
  przed § 1 (dane stron) odpada, a pola Jinja zostają jako „…” — do modelu
  nie idą dane osób.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.services import framework_contract_index
from app.services.b2b_contract_generator.clause_overrides import (
    apply_ops_html,
    ops_fingerprint,
    resolve_override,
)
from app.services.contract_document_text.structure import markers, range_ref
from app.services.framework_contract_text import ChunkRef
from app.services.legal_client_fit.topics import TOPICS, Topic

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "templates" / "contract" / "umowa_b2b_pl.html"
)
#: Umowy, które już nie wiążą — ich wymogi nie przechodzą na Partnera.
_INACTIVE = frozenset(
    {
        FrameworkContractStatus.expired,
        FrameworkContractStatus.terminated,
        FrameworkContractStatus.superseded,
    }
)
PASSAGES_PER_TOPIC = 2
CLIENT_CHARS_BUDGET = 36_000
NAME_MAX = 80

SOURCE_FRAMEWORK = "framework_contract"
SOURCE_AMENDMENT = "amendment"


@dataclass(frozen=True)
class ClientPassage:
    """Fragment umowy klienta dla modelu (``key`` = „K3”)."""

    key: str
    source_kind: str
    source_id: int
    document_label: str
    text: str
    #: Przesunięcie fragmentu w całym tekście dokumentu (do oznaczenia §).
    offset: int
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplatePassage:
    """Paragraf albo załącznik naszego wzoru (``key`` = „T5”, ``ref`` = „§ 9”)."""

    key: str
    ref: str
    text: str


@dataclass
class ClientDocuments:
    contracts: list[ClientFrameworkContract]
    amendments: list[ClientContractAmendment]
    #: Pełny tekst dokumentu (sklejone fragmenty) po (rodzaj, id).
    texts: dict[tuple[str, int], str] = field(default_factory=dict)

    @property
    def readable(self) -> list[object]:
        return [
            d
            for d in (*self.contracts, *self.amendments)
            if framework_contract_index.has_current_text(d)
        ]


# ── nasz wzór ───────────────────────────────────────────────────────────────

_JINJA_VALUE = re.compile(r"\{\{.*?\}\}", re.S)
_JINJA_TAG = re.compile(r"\{%.*?%\}", re.S)
_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</p>|<br\s*/?>|</li>|</tr>|</h\d>", re.I)
_SECTION_HEAD = re.compile(r"^§\s*(\d+[A-Za-z]?)\s*\.?$")
_APPENDIX_HEAD = re.compile(r"^za[łl]ącznik\s+nr\s*(\d+)", re.I)


def _plain(fragment: str) -> str:
    text = _BLOCK_END.sub("\n", fragment)
    text = html_lib.unescape(_TAG.sub("", text))
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def client_override(client: Client) -> tuple[Optional[str], list]:
    """Klucz i operacje klauzul klienta — pierwsza nazwa, która trafia we wpis."""
    for name in (client.name, client.legal_name, client.display_name):
        key, ops = resolve_override(name, "pl")
        if key is not None:
            return key, ops
    return None, []


def template_passages(
    html_source: str, ops: Sequence[object] = ()
) -> list[TemplatePassage]:
    """Wzór z klauzulami klienta → paragrafy i załączniki (bez komparycji)."""
    rendered = apply_ops_html(html_source, list(ops)) if ops else html_source
    rendered = _JINJA_TAG.sub("", _JINJA_VALUE.sub("…", rendered))
    heads = list(_H2.finditer(rendered))
    parts: list[tuple[str, str]] = []
    in_appendix = False
    for index, head in enumerate(heads):
        title = _plain(head.group(1))
        body_end = heads[index + 1].start() if index + 1 < len(heads) else len(rendered)
        body = _plain(rendered[head.end() : body_end])
        section = _SECTION_HEAD.match(title)
        appendix = _APPENDIX_HEAD.match(title)
        if appendix:
            in_appendix = True
            ref = f"Załącznik nr {appendix.group(1)}"
            if parts and parts[-1][0] == ref:
                # „Załącznik nr 3 – wzór…” i „ZAŁĄCZNIK NR 3 DO UMOWY…” to jeden załącznik.
                parts[-1] = (ref, f"{parts[-1][1]}\n{title}\n{body}")
            else:
                parts.append((ref, f"{title}\n{body}"))
        elif section and not in_appendix:
            parts.append((f"§ {section.group(1)}", body))
        elif parts and (in_appendix or not section):
            ref, text = parts[-1]
            parts[-1] = (ref, f"{text}\n{title}\n{body}")
    return [
        TemplatePassage(key=f"T{n}", ref=ref, text=text.strip())
        for n, (ref, text) in enumerate(parts, start=1)
        if text.strip()
    ]


def load_template(client: Client) -> tuple[list[TemplatePassage], str, str]:
    """(fragmenty wzoru, etykieta dla ekranu, odcisk treści wzoru)."""
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    key, ops = client_override(client)
    passages = template_passages(source, ops)
    label = (
        f"Wzór umowy B2B (PL) z klauzulami klienta „{key}”"
        if key
        else "Wzór umowy B2B (PL)"
    )
    digest = hashlib.sha256(source.encode("utf-8"))
    digest.update(ops_fingerprint(list(ops)).encode() if ops else b"-")
    return passages, label, digest.hexdigest()


# ── umowa klienta ───────────────────────────────────────────────────────────


async def load_client_documents(db: AsyncSession, client_id: int) -> ClientDocuments:
    contracts = list(
        (
            await db.execute(
                select(ClientFrameworkContract)
                .where(
                    ClientFrameworkContract.client_id == client_id,
                    ClientFrameworkContract.status.notin_(list(_INACTIVE)),
                )
                .order_by(ClientFrameworkContract.id)
            )
        )
        .scalars()
        .all()
    )
    amendments: list[ClientContractAmendment] = []
    if contracts:
        amendments = list(
            (
                await db.execute(
                    select(ClientContractAmendment)
                    .where(
                        ClientContractAmendment.framework_contract_id.in_(
                            [c.id for c in contracts]
                        )
                    )
                    .order_by(ClientContractAmendment.id)
                )
            )
            .scalars()
            .all()
        )
    return ClientDocuments(contracts=contracts, amendments=amendments)


def documents_fingerprint(documents: ClientDocuments, template_digest: str) -> str:
    """Odcisk: które pliki (i ich odczyt) oraz który wzór dały ustalenia."""
    digest = hashlib.sha256(template_digest.encode())
    for kind, rows in (
        (SOURCE_FRAMEWORK, documents.contracts),
        (SOURCE_AMENDMENT, documents.amendments),
    ):
        for row in rows:
            digest.update(
                f"{kind}:{row.id}:{row.file_path}:"
                f"{framework_contract_index.has_current_text(row)}\n".encode()
            )
    return digest.hexdigest()


def _short(name: Optional[str]) -> str:
    name = (name or "").strip() or "bez nazwy"
    return name if len(name) <= NAME_MAX else name[: NAME_MAX - 1] + "…"


def document_label(kind: str, row: object) -> str:
    name = _short(getattr(row, "name", None))
    return f"Aneks „{name}”" if kind == SOURCE_AMENDMENT else f"Umowa ramowa „{name}”"


def _whole_texts(chunks: Sequence[ChunkRef]) -> dict[tuple[str, int], list[ChunkRef]]:
    grouped: dict[tuple[str, int], list[ChunkRef]] = {}
    for chunk in chunks:
        key = (
            (SOURCE_AMENDMENT, chunk.amendment_id)
            if chunk.amendment_id is not None
            else (SOURCE_FRAMEWORK, chunk.contract_id)
        )
        grouped.setdefault(key, []).append(chunk)
    return grouped


async def client_passages(
    db: AsyncSession,
    documents: ClientDocuments,
    topics: Sequence[Topic] = TOPICS,
) -> list[ClientPassage]:
    """Najlepsze fragmenty umowy klienta dla każdego tematu (bez powtórzeń)."""
    readable_contracts = [
        c for c in documents.contracts if framework_contract_index.has_current_text(c)
    ]
    readable_amendments = [
        a for a in documents.amendments if framework_contract_index.has_current_text(a)
    ]
    if not (readable_contracts or readable_amendments):
        return []
    chunks = await framework_contract_index.load_chunks(
        db,
        [c.id for c in readable_contracts],
        [a.id for a in readable_amendments],
    )
    grouped = _whole_texts(chunks)
    for key, rows in grouped.items():
        documents.texts[key] = "".join(
            c.text for c in sorted(rows, key=lambda c: c.index)
        )
    rows_by_key = {
        **{(SOURCE_FRAMEWORK, c.id): c for c in readable_contracts},
        **{(SOURCE_AMENDMENT, a.id): a for a in readable_amendments},
    }

    picked: dict[tuple[str, int, int, int], ClientPassage] = {}
    used = 0
    for topic in topics:
        outcome = await framework_contract_index.search(
            db, readable_contracts, topic.query, readable_amendments
        )
        for passage in outcome.passages[:PASSAGES_PER_TOPIC]:
            source = (
                (SOURCE_AMENDMENT, int(passage.amendment_id))
                if passage.amendment_id is not None
                else (SOURCE_FRAMEWORK, int(passage.contract_id))
            )
            ident = (*source, passage.first_chunk, passage.last_chunk)
            if ident in picked:
                existing = picked[ident]
                picked[ident] = ClientPassage(
                    existing.key,
                    existing.source_kind,
                    existing.source_id,
                    existing.document_label,
                    existing.text,
                    existing.offset,
                    (*existing.topics, topic.key),
                )
                continue
            if used + len(passage.text) > CLIENT_CHARS_BUDGET:
                continue
            ordered = sorted(grouped.get(source, []), key=lambda c: c.index)
            offset = sum(len(c.text) for c in ordered if c.index < passage.first_chunk)
            row = rows_by_key.get(source)
            picked[ident] = ClientPassage(
                key=f"K{len(picked) + 1}",
                source_kind=source[0],
                source_id=source[1],
                document_label=document_label(source[0], row),
                text=passage.text,
                offset=offset,
                topics=(topic.key,),
            )
            used += len(passage.text)
    return list(picked.values())


def client_ref(passage: ClientPassage, quote: str, whole_text: Optional[str]) -> str:
    """„Aneks „DORA”, § 4 ust. 2” — paragraf z układu całego dokumentu."""
    at = passage.text.find(quote[:40]) if quote else -1
    start = passage.offset + max(at, 0)
    end = start + (len(quote) if at >= 0 else len(passage.text))
    section = range_ref(markers(whole_text), start, end) if whole_text else None
    return f"{passage.document_label}, {section}" if section else passage.document_label
