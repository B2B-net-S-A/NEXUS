"""Runda 6 audytu (C2): odczyt PDF-a Nordei (OCR) poza blokadami zapisu.

Upload PDF-a (podmiana pliku, przedłużenie) i zapis zamówień z poczty czytały
formułę faktury Nordei POD blokadą kontraktu/zamówienia albo klienta, a poczta
— osobno dla każdego zamówienia dokumentu (N razy ten sam PDF). Odczyt idzie
teraz raz na dokument, w wątku, przed blokadami; wynik przypisuje się po
przypięciu tych samych bajtów.
"""

from __future__ import annotations

import ast
import inspect
import os
import threading
from types import SimpleNamespace

import pytest

from app.services import nordea_invoice_lines as svc


def _call_lines(func, name: str) -> list[int]:
    tree = ast.parse(inspect.getsource(func))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            called = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", None)
            )
            if called == name:
                lines.append(node.lineno)
    return sorted(lines)


@pytest.mark.parametrize("handler", ["replace_order_po", "create_order_extension"])
def test_upload_reads_the_invoice_formula_before_the_contract_lock(handler):
    from app.api import client_orders

    func = getattr(client_orders, handler)
    reads = _call_lines(func, "read_upload_payload")
    locks = _call_lines(func, "lock_contract_then_orders")
    assert reads and locks
    assert max(reads) < min(locks)
    assert not _call_lines(func, "refresh_on_upload_async")


def test_mail_apply_reads_the_pdf_once_before_the_client_lock():
    from app.services import order_mail_apply

    reads = _call_lines(order_mail_apply.apply_document, "read_upload_payload")
    locks = _call_lines(order_mail_apply.apply_document, "with_for_update")
    assert len(reads) == 1 and locks
    assert reads[0] < min(locks)
    writer = order_mail_apply._write_document
    assert not _call_lines(writer, "refresh_on_upload_async")
    assert not _call_lines(writer, "read_upload_payload")


@pytest.mark.asyncio
async def test_read_upload_payload_parses_a_temp_copy_in_a_worker_thread(
    monkeypatch,
):
    loop_thread = threading.get_ident()
    seen: dict = {}

    def fake_read(path, filename):
        seen["thread"] = threading.get_ident()
        seen["path"] = path
        with open(path, "rb") as handle:
            seen["bytes"] = handle.read()
        return {"source": "pdf", "lines": []}

    monkeypatch.setattr(svc, "is_nordea", lambda client_id: client_id == 7)
    monkeypatch.setattr(svc, "read_pdf_payload", fake_read)

    assert await svc.read_upload_payload(8, b"%PDF-1", "po.pdf") is None
    assert await svc.read_upload_payload(7, None, "po.pdf") is None
    payload = await svc.read_upload_payload(7, b"%PDF-1 data", "po.pdf")

    assert payload == {"source": "pdf", "lines": []}
    assert seen["thread"] != loop_thread
    assert seen["bytes"] == b"%PDF-1 data"
    assert not os.path.exists(seen["path"])


def test_apply_upload_payload_copies_per_order_and_skips_other_clients(monkeypatch):
    monkeypatch.setattr(svc, "is_nordea", lambda client_id: client_id == 7)
    payload = {"source": "pdf", "lines": [{"text": "NIDS: 1"}]}
    first = SimpleNamespace(client_id=7, invoice_lines=None)
    second = SimpleNamespace(client_id=7, invoice_lines=None)
    other = SimpleNamespace(client_id=8, invoice_lines="keep")

    svc.apply_upload_payload(first, payload)
    svc.apply_upload_payload(second, payload)
    svc.apply_upload_payload(other, payload)

    assert first.invoice_lines == payload and second.invoice_lines == payload
    assert first.invoice_lines is not second.invoice_lines
    first.invoice_lines["lines"][0]["text"] = "zmienione"
    assert second.invoice_lines["lines"][0]["text"] == "NIDS: 1"
    assert other.invoice_lines == "keep"

    svc.apply_upload_payload(first, None)
    assert first.invoice_lines is None
