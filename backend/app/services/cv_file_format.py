"""W jakim pliku klient chce CV: Word, PDF albo oba (decyzja Artura z 25.11.2026).

Pole reguły CV klienta `client_cv_rules.cv_file_format` (migracja 0778).
NULL = bez wymagań: plik idzie za układem CV jak dotąd (klasyczne → Word,
Nowe CV → PDF). Główny przycisk pobrania w karcie „CV do klienta”, edytorze
i wyniku generatora idzie za tym polem.

Format nie zależy od flagi „Nowego CV”: klasyczne CV też ma PDF (z pliku Word
przez LibreOffice). Do etapu 2 Word jest zawsze w układzie klasycznym, więc
„Word” przy „Nowym CV” to ostrzeżenie w interfejsie, nie zmiana pliku.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from app.services.cv_layout_schema import FILE_FORMATS

FileFormat = Literal["docx", "pdf", "both"]


def normalized(value: Any) -> Optional[FileFormat]:
    """Format z bazy albo recepty; nieznana wartość = bez wymagań."""
    return value if value in FILE_FORMATS else None


async def for_client(db, client_id: Optional[int]) -> Optional[FileFormat]:
    """Format z zatwierdzonej reguły klienta; propozycja się nie liczy.

    Czyta kolumnę wprost, jak `cv_layout.default_for_client`: pod zasadami
    centralnymi resolver buduje regułę spoza katalogu w pamięci (bez formatu).
    """
    if not client_id:
        return None
    from sqlalchemy import select

    from app.models.client_cv_rule import ClientCvRule

    return normalized(
        await db.scalar(
            select(ClientCvRule.cv_file_format).where(
                ClientCvRule.client_id == client_id,
                ClientCvRule.confirmed_at.is_not(None),
            )
        )
    )


async def for_stage(db, stage_id: Optional[int]) -> Optional[FileFormat]:
    """Format klienta rekrutacji, do której należy etap (jedno zapytanie)."""
    if not stage_id:
        return None
    from sqlalchemy import select

    from app.models.recruitment_pipeline import CandidateStage
    from app.models.client_cv_rule import ClientCvRule
    from app.models.job import Job

    return normalized(
        await db.scalar(
            select(ClientCvRule.cv_file_format)
            .select_from(CandidateStage)
            .join(Job, Job.id == CandidateStage.job_id)
            .join(ClientCvRule, ClientCvRule.client_id == Job.client_id)
            .where(
                CandidateStage.id == stage_id,
                ClientCvRule.confirmed_at.is_not(None),
            )
        )
    )
