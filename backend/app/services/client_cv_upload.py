"""Gotowe CV do klienta wgrane kafelkiem w rekrutacji (15.10.2026, D1–D3).

Zgłoszenie rekrutera: plik „B2B_…docx” wgrany w panelu osoby lądował jako
oryginał kandydata i główne CV profilu (AI czytało z niego profil), a CV do
klienta trzeba było jeszcze podmienić paskiem „Ta osoba ma już gotowe CV”.
Pomiar na produkcji 13–15.10.2026: 15 z 37 wgrań w panelu to gotowe CV do
klienta, a 16 z 17 importów pliku z profilu dotyczyło pliku, który ta sama
osoba wgrała najwyżej 30 minut wcześniej.

Reguły, które łatwo cofnąć:

* CV do klienta poznajemy po nazwie pliku (D1): „B2B” jako osobne słowo albo
  stały początek wzoru nazwy klienta rekrutacji („ZOB-…”, „ORLEN_…”,
  „Bank_Pocztowy_…”). Samo „B2B” pomijało czterech klientów. Tylko Word —
  PDF-a nie da się wczytać do edytora.
* Nieprzejrzane auto-CV podmieniamy bez pytania; CV, które ktoś poprawiał,
  wybrał albo zatwierdził — dopiero po potwierdzeniu (D2).
* Plik z nagłówkiem innej osoby nie zostaje CV do klienta. Bramka tożsamości
  oryginału tego pliku nie zobaczy, a 15.10.2026 ten sam plik trafił do panelu
  innej osoby.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument

# Lustro `isClientCvFilename` z `frontend/src/lib/candidate-files.ts`.
CLIENT_CV_NAME = re.compile(r"(^|[_\s-])b2b([_\s.-]|$)", re.IGNORECASE)
UPLOAD_ACTION = "branded_cv_uploaded_in_recruitment"
UNDO_ACTION = "branded_cv_upload_undone"

_SEPARATORS = re.compile(r"[\s._-]+")
# Krótszy stały początek wzoru („CV_”) łapałby zwykłe CV kandydatów.
_MIN_PREFIX = 3
_NAME_SEPARATORS = (" – ", " — ", " - ")
_NAME_SPLIT = re.compile(r"[\s_.\-–—,;()]+")
_H1 = re.compile(r"<h1[\s>/]", re.IGNORECASE)


def _fold(value: str) -> str:
    return _SEPARATORS.sub("_", value.strip().lower())


def pattern_prefix(filename_pattern: Optional[str]) -> str:
    """Stały początek wzoru nazwy klienta („ZOB-{PROJEKT}_…” → „zob”)."""
    literal = (filename_pattern or "").split("{", 1)[0]
    folded = _fold(literal).strip("_")
    return folded if len(folded) >= _MIN_PREFIX else ""


def looks_like_client_cv(filename: str, client_pattern: Optional[str] = None) -> bool:
    """Plik Word nazwany jak CV do klienta: „…B2B…” albo wzór klienta rekrutacji."""
    name = (filename or "").strip()
    if not name.lower().endswith(".docx"):
        return False
    if CLIENT_CV_NAME.search(name):
        return True
    prefix = pattern_prefix(client_pattern)
    return bool(prefix) and _fold(name).startswith(prefix + "_")


def cv_header(html: str) -> Optional[str]:
    """Tekst pierwszego nagłówka ``<h1>`` CV wczytanego z pliku Word."""
    from app.services.cv_qc import EditableCv

    if not html:
        return None
    doc = EditableCv.parse(html)
    for index, (start, _end) in enumerate(doc.spans):
        if start is not None and _H1.match(doc.tokens[start]["raw"]):
            return doc.blocks[index].text.strip() or None
    return None


def _name_tokens(value: Optional[str]) -> set[str]:
    from app.services.candidate_identity_quarantine import normalize_person_name_part

    tokens = (
        normalize_person_name_part(part) for part in _NAME_SPLIT.split(value or "")
    )
    return {token for token in tokens if len(token) >= 2}


def other_person_name(
    *,
    header: Optional[str],
    filename: str,
    first_name: Optional[str],
    last_name: Optional[str],
) -> Optional[str]:
    """Imię i nazwisko z nagłówka CV, gdy to na pewno ktoś inny; inaczej ``None``.

    Odmawiamy tylko przy pewności: nagłówek „stanowisko – imię nazwisko” niesie
    co najmniej dwa słowa po łączniku, a nazwiska osoby nie ma ani w całym
    nagłówku, ani w nazwie pliku. CV blind (sam tytuł) i nagłówek bez łącznika
    przechodzą. Nazwisko porównujemy po słowach, bez wielkości liter
    i polskich znaków, więc „Nowak-Kowalska” pasuje do „Anna Nowak”.
    """
    header = (header or "").strip()
    cut = max(
        (header.rfind(sep) + len(sep) for sep in _NAME_SEPARATORS if sep in header),
        default=-1,
    )
    observed = header[cut:].strip() if cut >= 0 else ""
    if len(_name_tokens(observed)) < 2:
        return None
    surname = _name_tokens(last_name)
    if not surname:
        return None
    stem = os.path.splitext(filename or "")[0]
    if surname & (_name_tokens(header) | _name_tokens(stem)):
        return None
    return observed


async def client_filename_pattern(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[str]:
    """Wzór nazwy CV klienta rekrutacji; ``None``, gdy go nie znamy.

    Najpierw zatwierdzona reguła klienta (jak przy nazwie kopii,
    `detached_copy_settings`), a bez niej katalog polityk — czysta funkcja.
    Rozpoznanie pliku to tylko porównanie nazwy, więc katalog wystarcza także
    przy wyłączonych politykach centralnych.
    """
    from fastapi import HTTPException

    from app.services.cv_generator_b2b import central_policies
    from app.services.cv_generator_b2b.client_rules import (
        resolve_client_rule,
        snapshot_rule,
    )

    if not client_id:
        return None
    try:
        rule = snapshot_rule(await resolve_client_rule(db, client_id))
    except HTTPException:
        rule = None
    if rule is not None and rule.filename_pattern:
        return rule.filename_pattern
    return central_policies.policy_for(client_id).get("filename_pattern")


async def is_untouched_auto_cv(db: AsyncSession, csv: CandidateStageCV) -> bool:
    """Szkic od automatu, którego od podpięcia nikt nie zmienił (D2).

    Każda zmiana treści podbija ``edit_revision``, więc wpis podpięcia przez
    automat z tą samą rewizją znaczy „nikt nie ruszał”. Dołączona zgoda RODO
    rewizji nie podbija, a import pliku by ją zgubił — wtedy pytamy.
    """
    from app.services.cv_auto_generate import ATTACH_ACTION

    if (
        csv.branded_status != "draft"
        or not csv.generated_document_id
        or csv.branded_consent_content is not None
    ):
        return False
    origin = await db.scalar(
        select(CvGeneratedDocument.origin).where(
            CvGeneratedDocument.id == csv.generated_document_id
        )
    )
    if origin != "auto":
        return False
    attached = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv.id,
            Activity.action == ATTACH_ACTION,
            Activity.details["edit_revision"].astext == str(csv.edit_revision or 0),
        )
        .limit(1)
    )
    return attached is not None


async def last_upload_if_current(
    db: AsyncSession, csv: CandidateStageCV, sha256: str
) -> Optional[dict]:
    """Szczegóły wgrania tego pliku jako CV do klienta, gdy nikt potem nic nie zmienił.

    „Cofnij” po wgraniu wysyła ten sam plik jako CV kandydata. Przywracamy
    poprzednie CV do klienta tylko wtedy, gdy obecne to dokładnie ten plik
    w nietkniętej wersji — inaczej cofnięcie skasowałoby czyjąś pracę.
    """
    row = await db.scalar(
        select(Activity.details)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv.id,
            Activity.action == UPLOAD_ACTION,
            Activity.details["edit_revision"].astext == str(csv.edit_revision or 0),
            Activity.details["upload_sha256"].astext == sha256,
        )
        .order_by(Activity.id.desc())
        .limit(1)
    )
    return dict(row) if row else None
