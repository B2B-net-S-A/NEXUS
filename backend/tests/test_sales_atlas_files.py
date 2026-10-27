"""Pliki z Atlasa → magazyn NEXUSA: przypięcie do szansy/firmy, braki, idempotencja."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany, SalesFile, SalesOpportunity, SalesPipeline
from app.services import storage_service
from app.services.sales.atlas_files import copy_attachments


@pytest.mark.asyncio
async def test_files_land_on_their_opportunity_and_company_once(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        pipeline = (
            await db.execute(select(SalesPipeline).where(SalesPipeline.key == "sales"))
        ).scalar_one()
        await db.refresh(pipeline, ["stages"])
        company = SalesCompany(
            name=f"Pliki Atlas {tag}",
            normalized_name=f"pliki atlas {tag}",
            external_ref=f"atlas:companies:c-{tag}",
        )
        db.add(company)
        await db.flush()
        opp = SalesOpportunity(
            company_id=company.id,
            pipeline_id=pipeline.id,
            stage_id=pipeline.stages[0].id,
            title="Z Atlasa",
            external_ref=f"atlas:deals:d-{tag}",
        )
        db.add(opp)
        await db.commit()
        company_id, opp_id = company.id, opp.id

    deal_rows = [
        {
            "id": f"f1-{tag}",
            "deal_id": f"d-{tag}",
            "filename": "oferta.pdf",
            "storage_path": "d/1_oferta.pdf",
            "folder": "Oferty",
        },
        {
            "id": f"f2-{tag}",
            "deal_id": f"d-{tag}",
            "filename": "zniknal.pdf",
            "storage_path": "d/2_zniknal.pdf",
        },
        {
            "id": f"f3-{tag}",
            "deal_id": "nie-zaimportowana",
            "filename": "x.pdf",
            "storage_path": "d/3_x.pdf",
        },
    ]
    company_rows = [
        {
            "id": f"f4-{tag}",
            "company_id": f"c-{tag}",
            "filename": "nda.docx",
            "storage_path": "c/4_nda.docx",
        }
    ]
    fetched: list[tuple[str, str]] = []

    async def fetch(bucket: str, path: str):
        fetched.append((bucket, path))
        return None if "zniknal" in path else b"tresc"

    async with AsyncSessionLocal() as db:
        report = await copy_attachments(
            db,
            deal_attachments=deal_rows,
            company_attachments=company_rows,
            fetch=fetch,
            users_by_email={},
        )
        await db.commit()
    counts = report.as_dict()
    assert counts == {
        "files_copied": 2,
        "files_missing_in_storage": 1,
        "files_skipped_owner_not_imported": 1,
    }
    assert ("company-attachments", "c/4_nda.docx") in fetched

    async with AsyncSessionLocal() as db:
        files = {
            f.external_ref: f
            for f in (
                await db.execute(
                    select(SalesFile).where(
                        SalesFile.external_ref.like(f"atlas:%-{tag}")
                    )
                )
            ).scalars()
        }
    assert files[f"atlas:deal_attachments:f1-{tag}"].opportunity_id == opp_id
    assert files[f"atlas:deal_attachments:f1-{tag}"].folder == "Oferty"
    assert files[f"atlas:company_attachments:f4-{tag}"].company_id == company_id
    assert (
        storage_service.read_sales_file(
            files[f"atlas:company_attachments:f4-{tag}"].storage_key
        )
        == b"tresc"
    )

    async with AsyncSessionLocal() as db:
        again = await copy_attachments(
            db,
            deal_attachments=deal_rows,
            company_attachments=company_rows,
            fetch=fetch,
            users_by_email={},
        )
    assert again.as_dict()["files_already_copied"] == 2


@pytest.mark.asyncio
async def test_dry_run_neither_downloads_nor_writes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompany(
                name=f"Sucho {tag}",
                normalized_name=f"sucho {tag}",
                external_ref=f"atlas:companies:s-{tag}",
            )
        )
        await db.commit()

    async def fetch(bucket: str, path: str):
        raise AssertionError("na sucho nic nie pobieramy")

    async with AsyncSessionLocal() as db:
        report = await copy_attachments(
            db,
            deal_attachments=[],
            company_attachments=[
                {
                    "id": f"x-{tag}",
                    "company_id": f"s-{tag}",
                    "filename": "a.pdf",
                    "storage_path": "c/a.pdf",
                }
            ],
            fetch=fetch,
            users_by_email={},
            dry_run=True,
        )
    assert report.as_dict() == {"files_would_copy": 1}
    assert not list(tmp_path.rglob("*.pdf"))
