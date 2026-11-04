"""Pliki z Atlasa → magazyn NEXUSA: przypięcie do szansy/firmy, braki, idempotencja."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany, SalesFile, SalesOpportunity, SalesPipeline
from app.services import storage_service
from app.services.sales.atlas_files import (
    OFFER_BUCKET,
    OFFERS_FOLDER,
    copy_attachments,
)


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


async def _company_with_deal(tag: str) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        pipeline = (
            await db.execute(select(SalesPipeline).where(SalesPipeline.key == "sales"))
        ).scalar_one()
        await db.refresh(pipeline, ["stages"])
        company = SalesCompany(
            name=f"Oferty Atlas {tag}",
            normalized_name=f"oferty atlas {tag}",
            external_ref=f"atlas:companies:c-{tag}",
        )
        db.add(company)
        await db.flush()
        opp = SalesOpportunity(
            company_id=company.id,
            pipeline_id=pipeline.id,
            stage_id=pipeline.stages[0].id,
            title="Z ofertą",
            external_ref=f"atlas:deals:d-{tag}",
        )
        db.add(opp)
        await db.commit()
        return company.id, opp.id


@pytest.mark.asyncio
async def test_atlas_upload_date_and_folder_refresh_without_download(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    tag = uuid.uuid4().hex[:8]
    await _company_with_deal(tag)
    uploaded = datetime(2025, 3, 4, 10, tzinfo=timezone.utc)
    rows = [
        {
            "id": f"f1-{tag}",
            "deal_id": f"d-{tag}",
            "filename": "umowa.pdf",
            "storage_path": "d/umowa.pdf",
            "created_at": uploaded,
        },
        {
            "id": f"f2-{tag}",
            "deal_id": f"d-{tag}",
            "filename": "z-pipedrive.pdf",
            "storage_path": "pipedrive://files/1",
        },
    ]

    async def fetch(bucket: str, path: str):
        return b"tresc"

    async with AsyncSessionLocal() as db:
        report = await copy_attachments(
            db,
            deal_attachments=rows,
            company_attachments=[],
            fetch=fetch,
            users_by_email={},
        )
        await db.commit()
    assert report.as_dict() == {"files_copied": 1, "files_external_reference": 1}
    ref = f"atlas:deal_attachments:f1-{tag}"
    async with AsyncSessionLocal() as db:
        copied = (
            await db.execute(select(SalesFile).where(SalesFile.external_ref == ref))
        ).scalar_one()
        assert copied.created_at == uploaded
        # Plik skopiowany pierwszym biegiem (data przeniesienia, bez folderu).
        copied.created_at = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)
        await db.commit()

    async def no_fetch(bucket: str, path: str):
        raise AssertionError("plik już jest w NEXUSIE")

    rows[0]["folder"] = "Umowy"
    async with AsyncSessionLocal() as db:
        again = await copy_attachments(
            db,
            deal_attachments=rows,
            company_attachments=[],
            fetch=no_fetch,
            users_by_email={},
        )
        await db.commit()
    assert again.as_dict() == {"files_already_copied": 1, "files_external_reference": 1}
    async with AsyncSessionLocal() as db:
        refreshed = (
            await db.execute(select(SalesFile).where(SalesFile.external_ref == ref))
        ).scalar_one()
    assert (refreshed.created_at, refreshed.folder) == (uploaded, "Umowy")


@pytest.mark.asyncio
async def test_latest_offer_version_files_land_in_offers_folder(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    tag = uuid.uuid4().hex[:8]
    company_id, opp_id = await _company_with_deal(tag)
    generated = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    offers = [
        {
            "id": f"o1-{tag}",
            "deal_id": f"d-{tag}",
            "client_company_id": f"c-{tag}",
            "status": "sent",
            "sent_at": datetime(2026, 5, 2, 9),
            "latest_version_id": f"v2-{tag}",
        },
        {
            # Szansy nie ma w NEXUSIE — plik ląduje przy firmie.
            "id": f"o2-{tag}",
            "deal_id": "nie-zaimportowana",
            "client_company_id": f"c-{tag}",
            "status": "draft",
        },
        {"id": f"o3-{tag}", "client_company_id": "obca", "status": "lost"},
        {"id": f"o4-{tag}", "deal_id": f"d-{tag}", "status": "draft"},  # bez wersji
    ]
    versions = [
        {
            "id": f"v1-{tag}",
            "offer_id": f"o1-{tag}",
            "docx_storage_path": f"o1-{tag}/1.0/stara.docx",
        },
        {
            "id": f"v2-{tag}",
            "offer_id": f"o1-{tag}",
            "docx_storage_path": f"o1-{tag}/1.5/propozycja.docx",
            "pdf_storage_path": f"o1-{tag}/1.5/propozycja.pdf",
            "generated_at": generated,
        },
        {
            "id": f"v3-{tag}",
            "offer_id": f"o2-{tag}",
            "pdf_storage_path": f"o2-{tag}/1.0/szkic.pdf",
            "generated_at": generated,
        },
        {
            "id": f"v4-{tag}",
            "offer_id": f"o3-{tag}",
            "pdf_storage_path": f"o3-{tag}/1.0/x.pdf",
        },
    ]
    fetched: list[tuple[str, str]] = []

    async def fetch(bucket: str, path: str):
        fetched.append((bucket, path))
        return b"oferta"

    async with AsyncSessionLocal() as db:
        report = await copy_attachments(
            db,
            deal_attachments=[],
            company_attachments=[],
            offers=offers,
            offer_versions=versions,
            fetch=fetch,
            users_by_email={},
        )
        await db.commit()
    assert report.as_dict() == {
        "offer_files_copied": 3,
        "offer_files_skipped_owner_not_imported": 1,
    }
    assert {bucket for bucket, _ in fetched} == {"offers"}
    assert (OFFER_BUCKET, f"o1-{tag}/1.0/stara.docx") not in fetched

    async with AsyncSessionLocal() as db:
        files = {
            f.external_ref: f
            for f in (
                await db.execute(
                    select(SalesFile).where(
                        SalesFile.external_ref.like(f"atlas:offer_versions:%-{tag}:%")
                    )
                )
            ).scalars()
        }
    pdf = files[f"atlas:offer_versions:v2-{tag}:pdf"]
    assert (pdf.opportunity_id, pdf.folder, pdf.filename, pdf.created_at) == (
        opp_id,
        OFFERS_FOLDER,
        "sent 2026-05-02 propozycja.pdf",
        generated,
    )
    assert files[f"atlas:offer_versions:v2-{tag}:docx"].opportunity_id == opp_id
    draft = files[f"atlas:offer_versions:v3-{tag}:pdf"]
    assert (draft.company_id, draft.filename) == (
        company_id,
        "draft niewysłana szkic.pdf",
    )

    async with AsyncSessionLocal() as db:
        empty = await copy_attachments(
            db,
            deal_attachments=[],
            company_attachments=[],
            offers=[],
            offer_versions=[],
            fetch=fetch,
            users_by_email={},
        )
    assert empty.as_dict() == {}


@pytest.mark.asyncio
async def test_file_of_company_merged_in_nexus_lands_on_merge_target(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        target = SalesCompany(name=f"Docelowa {tag}", normalized_name=f"docelowa {tag}")
        db.add(target)
        await db.flush()
        db.add(
            SalesCompany(
                name=f"Scalona {tag}",
                normalized_name=f"scalona {tag}",
                external_ref=f"atlas:companies:m-{tag}",
                custom_fields={"merged_into": target.id},
            )
        )
        await db.commit()
        target_id = target.id

    async def fetch(bucket: str, path: str):
        return b"tresc"

    async with AsyncSessionLocal() as db:
        await copy_attachments(
            db,
            deal_attachments=[],
            company_attachments=[
                {
                    "id": f"m1-{tag}",
                    "company_id": f"m-{tag}",
                    "filename": "nda.pdf",
                    "storage_path": "c/nda.pdf",
                }
            ],
            fetch=fetch,
            users_by_email={},
        )
        await db.commit()
        copied = (
            await db.execute(
                select(SalesFile).where(
                    SalesFile.external_ref == f"atlas:company_attachments:m1-{tag}"
                )
            )
        ).scalar_one()
    assert copied.company_id == target_id
