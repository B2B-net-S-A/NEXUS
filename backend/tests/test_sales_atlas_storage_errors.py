"""Storage failures must abort the import rather than become missing files."""

from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from sqlalchemy import column

from scripts import import_atlas_sales as script


BASE = "https://synthetic-atlas.invalid"
# Load SQLAlchemy's registered ORM types before temporary sys.modules patches;
# restoring that dictionary must not remove partially initialized ORM modules.
importlib.import_module("sqlalchemy.ext.asyncio")


class FakeFile:
    external_ref = column("external_ref")

    def __init__(self, **values):
        self.__dict__.update(values)


class FakeReport:
    def __init__(self):
        self.counts = Counter()

    def add(self, key, amount=1):
        self.counts[key] += amount

    def as_dict(self):
        return dict(self.counts)


def load_copy_service(storage):
    """Load the real copy implementation with offline persistence boundaries."""
    import app.services

    models = ModuleType("app.models.sales")
    models.SalesCompany = type("FakeCompany", (), {})
    models.SalesOpportunity = type("FakeOpportunity", (), {})
    models.SalesFile = FakeFile
    reports = ModuleType("app.services.sales.atlas_import")
    reports.ImportReport = FakeReport
    path = Path(__file__).resolve().parents[1] / "app/services/sales/atlas_files.py"
    spec = importlib.util.spec_from_file_location("atlas_files_offline_test", path)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    with (
        patch.dict(
            sys.modules,
            {
                "app.models.sales": models,
                "app.services.sales.atlas_import": reports,
            },
        ),
        patch.object(app.services, "storage_service", storage, create=True),
    ):
        spec.loader.exec_module(service)
    return service


class AtlasAttachmentFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_exact_bytes_including_empty_file(self):
        for data in (b"synthetic attachment", b""):
            requests = []

            def handler(request):
                requests.append(request)
                return httpx.Response(200, content=data)

            with self.subTest(data=data):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    self.assertEqual(
                        await script._fetch_attachment(
                            client, BASE, "company-attachments", "synthetic/file.txt"
                        ),
                        data,
                    )
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].method, "GET")
                self.assertEqual(
                    str(requests[0].url),
                    BASE + "/storage/v1/object/company-attachments/synthetic/file.txt",
                )

    async def test_only_404_returns_missing(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"error": "synthetic missing"})
            )
        ) as client:
            self.assertIsNone(
                await script._fetch_attachment(
                    client, BASE, "deal-attachments", "missing.txt"
                )
            )

    async def test_auth_rate_limit_and_server_failures_raise_status_error(self):
        for status in (401, 403, 429, 500, 503):
            with self.subTest(status=status):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(
                            status, json={"error": "synthetic provider failure"}
                        )
                    )
                ) as client:
                    with self.assertRaises(httpx.HTTPStatusError) as caught:
                        await script._fetch_attachment(
                            client, BASE, "deal-attachments", "file.txt"
                        )
                self.assertEqual(caught.exception.response.status_code, status)

    async def test_transport_and_timeout_errors_propagate(self):
        for exception in (httpx.ConnectError, httpx.ReadTimeout):

            def handler(request):
                raise exception("synthetic transport failure", request=request)

            with self.subTest(exception=exception.__name__):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    with self.assertRaises(exception):
                        await script._fetch_attachment(
                            client, BASE, "deal-attachments", "file.txt"
                        )


class AtlasAttachmentCopyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = SimpleNamespace(
            save_sales_file=Mock(
                side_effect=lambda owner, owner_id, filename, data: (
                    "synthetic/storage-key",
                    len(data),
                )
            )
        )
        self.service = load_copy_service(self.storage)
        self.service._ids = AsyncMock(
            side_effect=lambda db, model, refs: {ref: 42 for ref in refs}
        )
        self.db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        self.row = {
            "id": "synthetic-attachment",
            "company_id": "synthetic-company",
            "storage_path": "synthetic/file.txt",
            "filename": "synthetic.txt",
            "content_type": "text/plain",
            "uploaded_by_email": "synthetic@example.invalid",
        }

    async def copy(self, fetch, *, dry_run=False):
        return await self.service.copy_attachments(
            self.db,
            deal_attachments=[],
            company_attachments=[self.row],
            fetch=fetch,
            users_by_email={},
            dry_run=dry_run,
        )

    async def test_empty_successful_file_is_saved_and_counted_as_copied(self):
        fetch = AsyncMock(return_value=b"")
        report = await self.copy(fetch)
        self.assertEqual(report.as_dict(), {"files_copied": 1})
        self.storage.save_sales_file.assert_called_once_with(
            "companies", 42, "synthetic.txt", b""
        )
        record = self.db.add.call_args.args[0]
        self.assertEqual(record.size_bytes, 0)
        self.assertEqual(record.company_id, 42)
        self.assertEqual(
            record.external_ref, "atlas:company_attachments:synthetic-attachment"
        )
        self.db.flush.assert_awaited_once()
        self.db.commit.assert_not_awaited()

    async def test_404_is_the_only_missing_counter_and_writes_nothing(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ) as client:

            async def fetch(bucket, path):
                return await script._fetch_attachment(client, BASE, bucket, path)

            report = await self.copy(fetch)
        self.assertEqual(report.as_dict(), {"files_missing_in_storage": 1})
        self.storage.save_sales_file.assert_not_called()
        self.db.add.assert_not_called()
        self.db.flush.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_http_failure_aborts_copy_instead_of_reporting_missing(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(status)
                    )
                ) as client:

                    async def fetch(bucket, path):
                        return await script._fetch_attachment(
                            client, BASE, bucket, path
                        )

                    with self.assertRaises(httpx.HTTPStatusError):
                        await self.copy(fetch)
        self.storage.save_sales_file.assert_not_called()
        self.db.add.assert_not_called()
        self.db.flush.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_transport_failure_aborts_copy_without_persistence(self):
        failure = httpx.ConnectError("synthetic transport failure")
        with self.assertRaises(httpx.ConnectError) as caught:
            await self.copy(AsyncMock(side_effect=failure))
        self.assertIs(caught.exception, failure)
        self.storage.save_sales_file.assert_not_called()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_dry_run_never_downloads_or_saves(self):
        fetch = AsyncMock(side_effect=AssertionError("dry run must not download"))
        report = await self.copy(fetch, dry_run=True)
        self.assertEqual(report.as_dict(), {"files_would_copy": 1})
        fetch.assert_not_awaited()
        self.storage.save_sales_file.assert_not_called()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
