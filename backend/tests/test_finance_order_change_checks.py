"""Finanse: odhaczenia „Zrobione" w Zmianach w zamówieniach i pobrania PDF-ów (0354).

Baza testowa jest wspólna i nie jest czyszczona — każdy test pracuje na
własnym kliencie i dalekim miesiącu, a asercje filtrują po swoim kliencie.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.services.finance_order_pdfs import (
    OrderPdfEntry,
    ascii_slug,
    build_zip,
    client_zip_name,
    month_zip_name,
    zip_member_name,
)
from tests.test_finance_order_changes import _far_day, _login, _month, _seed
from tests.test_finance_order_pdfs import _far_month
from tests.test_finance_order_pdfs import _seed as _seed_pdfs

pytestmark = pytest.mark.asyncio


# ── Nazwy w archiwum (bez bazy) ─────────────────────────────────────────────


def _entry(**overrides) -> OrderPdfEntry:
    values = dict(
        kind="order",
        id=1,
        client_id=7,
        client_name="Nordea Bank Abp",
        original_name="x.pdf",
        file_path="client_orders/1/x.pdf",
        content_type="application/pdf",
        consultant_name="Axel Gocan",
        consultant_lastname="Gocan",
        start=date(2026, 10, 1),
        end=date(2026, 12, 31),
        entry_type="extension",
        status="active",
        order_number="286139",
        uploaded_at=None,
    )
    values.update(overrides)
    return OrderPdfEntry(**values)


def test_zip_member_name_follows_the_schema_without_polish_letters_or_spaces():
    assert zip_member_name(_entry()) == (
        "Nordea_Bank_Abp_286139_Gocan_Przedluzenie_01.10.2026-31.12.2026.pdf"
    )
    name = zip_member_name(
        _entry(
            client_name="Biuro Informacji Kredytowej S.A.",
            order_number="OIT/0189/2026",
            consultant_lastname="Łęcka-Żółć",
            entry_type="new",
            end=None,
        )
    )
    assert name == (
        "Biuro_Informacji_Kredytowej_S.A_OIT-0189-2026_Lecka-Zolc_Nowe_"
        "01.10.2026-bezterminowo.pdf"
    )
    assert " " not in name and name.isascii()


def test_missing_parts_get_placeholders_instead_of_disappearing():
    name = zip_member_name(
        _entry(order_number=None, consultant_lastname=None, entry_type="amendment")
    )
    assert name == (
        "Nordea_Bank_Abp_bez-numeru_bez-nazwiska_Aneks_01.10.2026-31.12.2026.pdf"
    )


def test_zip_names():
    assert client_zip_name("Nordea Bank Abp", 2026, 9) == "Nordea_Bank_Abp_2026-09.zip"
    assert month_zip_name(2026, 9) == "Zamowienia_2026-09.zip"
    assert ascii_slug("Bank Pocztowy S.A.") == "Bank_Pocztowy_S.A"


def test_zip_lists_missing_files_and_keeps_duplicate_names(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    content = build_zip(
        [
            (_entry(id=1), str(pdf)),
            (_entry(id=2), str(pdf)),
            (_entry(id=3, consultant_lastname="Brak"), None),
        ],
        client_folders=True,
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = sorted(archive.namelist())
        missing = archive.read("BRAKUJACE_PLIKI.txt").decode()
    folder = "Nordea_Bank_Abp/"
    assert names == [
        "BRAKUJACE_PLIKI.txt",
        f"{folder}Nordea_Bank_Abp_286139_Gocan_Przedluzenie_01.10.2026-31.12.2026.pdf",
        f"{folder}Nordea_Bank_Abp_286139_Gocan_Przedluzenie_01.10.2026-31.12.2026_2.pdf",
    ]
    assert "_Brak_" in missing


# ── Odhaczenia ──────────────────────────────────────────────────────────────


async def _check(app_client, headers, day: date, key: str, done: bool):
    return await app_client.post(
        "/api/finance/order-changes/checks",
        json={"year": day.year, "month": day.month, "item_key": key, "done": done},
        headers=headers,
    )


async def _check_rows(key: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.order_change_check import OrderChangeCheck

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(OrderChangeCheck)
            .where(OrderChangeCheck.item_key == key)
        )


async def test_entry_is_checked_undone_and_both_stay_in_the_history(
    app_client: AsyncClient, app_auth_headers: dict
):
    day = _far_day(2061, 2064).replace(day=3)
    ids = await _seed(start=day, end=day + timedelta(days=80))
    body = await _month(app_client, app_auth_headers, day)
    assert body["can_check"] is True
    [entry] = [e for e in body["entries"] if e["client_id"] == ids["client_id"]]
    key = entry["item_key"]
    assert key == f"entry:{ids['order_id']}:live:{day.isoformat()}"
    assert entry["done"] is None
    assert entry["order_start"] == day.isoformat()
    assert entry["order_end"] == (day + timedelta(days=80)).isoformat()
    assert entry["entered_at"]
    assert entry["pdf"] is None  # zamówienie bez PDF-u

    checked = await _check(app_client, app_auth_headers, day, key, True)
    assert checked.status_code == 200, checked.text
    assert checked.json()["done"]["by_name"]

    # Po odświeżeniu stan jest ten sam (zapis, nie stan przeglądarki).
    again = await _month(app_client, app_auth_headers, day)
    [entry] = [e for e in again["entries"] if e["item_key"] == key]
    assert entry["done"]["by_name"] == checked.json()["done"]["by_name"]

    # Ten sam stan drugi raz nie dopisuje wpisu.
    assert (
        await _check(app_client, app_auth_headers, day, key, True)
    ).status_code == 200
    assert await _check_rows(key) == 1

    undone = await _check(app_client, app_auth_headers, day, key, False)
    assert undone.status_code == 200 and undone.json()["done"] is None
    assert await _check_rows(key) == 2

    history = await app_client.get(
        "/api/finance/order-changes/history",
        params={"order_id": ids["order_id"]},
        headers=app_auth_headers,
    )
    assert history.status_code == 200, history.text
    kinds = [item["kind"] for item in history.json()["items"]]
    assert kinds[:2] == ["unchecked", "checked"]
    assert all(item["by_name"] for item in history.json()["items"][:2])


async def test_changed_again_gives_a_new_todo_and_keeps_the_old_check(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    first = _far_day(2065, 2068).replace(day=1)
    ids = await _seed(start=first - timedelta(days=90), end=first + timedelta(days=9))
    body = await _month(app_client, app_auth_headers, first)
    [ending] = [e for e in body["ending_orders"] if e["order_id"] == ids["order_id"]]
    old_key = ending["item_key"]
    resp = await _check(app_client, app_auth_headers, first, old_key, True)
    assert resp.status_code == 200, resp.text

    # Zamówienie zmienia się ponownie — nowa data końca w tym samym miesiącu.
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.end_date = first + timedelta(days=19)
        await db.commit()

    after = await _month(app_client, app_auth_headers, first)
    [ending] = [e for e in after["ending_orders"] if e["order_id"] == ids["order_id"]]
    assert ending["item_key"] != old_key
    assert ending["done"] is None  # nowa pozycja „Do zrobienia"
    [previous] = [s for s in after["superseded"] if s["item_key"] == old_key]
    assert previous["tab"] == "ending"
    assert previous["order_id"] == ids["order_id"]
    assert previous["summary"].startswith("Koniec zamówienia")


async def test_stale_key_is_refused_without_a_write(
    app_client: AsyncClient, app_auth_headers: dict
):
    day = _far_day(2069, 2070)
    key = "entry:999999999"
    resp = await _check(app_client, app_auth_headers, day, key, True)
    assert resp.status_code == 409
    assert await _check_rows(key) == 0


async def test_only_admin_and_finance_can_check(app_client: AsyncClient):
    day = _far_day(2071, 2072).replace(day=4)
    ids = await _seed(start=day, end=day + timedelta(days=30))
    key = f"entry:{ids['order_id']}:live:{day.isoformat()}"

    finance = await _login(app_client, "finance")
    body = await _month(app_client, finance, day)
    assert body["can_check"] is True
    assert (await _check(app_client, finance, day, key, True)).status_code == 200

    recruiter = await _login(app_client, "recruiter")
    assert (await _check(app_client, recruiter, day, key, False)).status_code == 403
    assert await _check_rows(key) == 1


async def test_summary_counts_todo_changes_of_the_current_month(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.scheduling import business_today

    day = _far_day(2073, 2074)
    ids = await _seed(start=day, end=day + timedelta(days=90))
    # Zmiana stawki trafia do Zmian BIEŻĄCEGO miesiąca (miesiąc wprowadzenia).
    patch = await app_client.patch(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}",
        json={"rate_client": "1500"},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text

    today = business_today()
    before = await app_client.get(
        "/api/finance/order-changes/summary", headers=app_auth_headers
    )
    assert before.status_code == 200, before.text
    summary = before.json()
    assert summary["todo"] == summary["tabs"]["changes"]["todo"]

    body = await _month(app_client, app_auth_headers, today)
    [change] = [
        c
        for c in body["changes"]
        if c["order_id"] == ids["order_id"] and c["kind"] == "rate_revenue"
    ]
    assert change["item_key"].startswith("chg:ev:")
    assert change["entered_by"]  # autor zmiany, nie „automatycznie"
    assert change["entered_automatically"] is False
    resp = await _check(app_client, app_auth_headers, today, change["item_key"], True)
    assert resp.status_code == 200, resp.text

    after = (
        await app_client.get(
            "/api/finance/order-changes/summary", headers=app_auth_headers
        )
    ).json()
    assert after["tabs"]["changes"]["todo"] == summary["tabs"]["changes"]["todo"] - 1


# ── Pobrania PDF-ów ─────────────────────────────────────────────────────────


async def _files(app_client, headers, month: date, client_id: int) -> dict:
    resp = await app_client.get(
        "/api/finance/order-pdfs",
        params={"year": month.year, "month": month.month},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    [client] = [c for c in resp.json()["clients"] if c["client_id"] == client_id]
    return {(f["kind"], f["id"]): f for f in client["files"]}


async def test_download_status_is_per_person_and_preview_does_not_count(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    ids = await _seed_pdfs(month)
    key = ("order", ids["periodic"])
    assert (await _files(app_client, app_auth_headers, month, ids["client_id"]))[key][
        "downloaded_at"
    ] is None

    preview = await app_client.get(
        f"/api/finance/order-pdfs/order/{ids['periodic']}/file?preview=true",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200
    files = await _files(app_client, app_auth_headers, month, ids["client_id"])
    assert files[key]["downloaded_at"] is None

    download = await app_client.get(
        f"/api/finance/order-pdfs/order/{ids['periodic']}/file",
        headers=app_auth_headers,
    )
    assert download.status_code == 200
    files = await _files(app_client, app_auth_headers, month, ids["client_id"])
    assert files[key]["downloaded_at"] is not None

    # U innej osoby plik jest nadal „Nowy".
    finance = await _login(app_client, "finance")
    other = await _files(app_client, finance, month, ids["client_id"])
    assert other[key]["downloaded_at"] is None


async def test_client_and_month_zip_hold_every_file_under_the_schema_names(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    ids = await _seed_pdfs(month)
    params = {"year": month.year, "month": month.month}

    client_zip = await app_client.get(
        "/api/finance/order-pdfs/zip",
        params={**params, "client_id": ids["client_id"]},
        headers=app_auth_headers,
    )
    assert client_zip.status_code == 200, client_zip.text
    assert (
        f"_{month.year}-{month.month:02d}.zip"
        in client_zip.headers["content-disposition"]
    )
    with zipfile.ZipFile(io.BytesIO(client_zip.content)) as archive:
        names = archive.namelist()
    assert len(names) == 5
    sfx = ids["suffix"]
    assert any(f"_Alfa{sfx}_Przedluzenie_" in name for name in names)
    assert all(name.isascii() and " " not in name for name in names)

    # Po ZIP-ie wszystkie pliki klienta są „Pobrane przez Ciebie".
    files = await _files(app_client, app_auth_headers, month, ids["client_id"])
    assert all(f["downloaded_at"] for f in files.values())

    month_zip = await app_client.get(
        "/api/finance/order-pdfs/zip", params=params, headers=app_auth_headers
    )
    assert month_zip.status_code == 200, month_zip.text
    assert "Zamowienia_" in month_zip.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(month_zip.content)) as archive:
        folders = {name.split("/")[0] for name in archive.namelist()}
    assert ascii_slug(f"FinPdf {sfx}") in folders


async def test_selected_files_zip_marks_only_those_files(
    app_client: AsyncClient,
):
    month = _far_month()
    ids = await _seed_pdfs(month)
    headers = await _login(app_client, "finance")
    resp = await app_client.get(
        "/api/finance/order-pdfs/zip",
        params={
            "year": month.year,
            "month": month.month,
            "client_id": ids["client_id"],
            "files": f"order:{ids['periodic']},group:{ids['solo']}",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        assert len(archive.namelist()) == 2
    files = await _files(app_client, headers, month, ids["client_id"])
    downloaded = {key for key, f in files.items() if f["downloaded_at"]}
    assert downloaded == {("order", ids["periodic"]), ("group", ids["solo"])}

    bad = await app_client.get(
        "/api/finance/order-pdfs/zip",
        params={"year": month.year, "month": month.month, "files": "evil:1"},
        headers=headers,
    )
    assert bad.status_code == 422


async def test_file_with_a_todo_change_is_flagged_until_it_is_checked(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    ids = await _seed_pdfs(month)
    key = ("order", ids["periodic"])
    files = await _files(app_client, app_auth_headers, month, ids["client_id"])
    assert files[key]["pending_change"] is True

    body = await _month(app_client, app_auth_headers, month)
    for tab in ("changes", "entries", "exits", "ending_orders", "gaps"):
        for item in body[tab]:
            if item["order_id"] == ids["periodic"]:
                resp = await _check(
                    app_client, app_auth_headers, month, item["item_key"], True
                )
                assert resp.status_code == 200, resp.text

    files = await _files(app_client, app_auth_headers, month, ids["client_id"])
    assert files[key]["pending_change"] is False


async def test_filled_draft_comes_back_as_todo_after_it_was_checked(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Dziennik zmian celowo pomija szkice — uzupełnienie stawek i aktywacja
    szkicu nie daje wpisu. Pozycja Wejść odhaczona na pustym szkicu musi więc
    wrócić jako „Do zrobienia", bo Finanse jeszcze nie widziały kwot."""

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    day = _far_day(2075, 2077).replace(day=5)
    ids = await _seed(
        start=day, end=day + timedelta(days=60), status=ClientOrderStatus.draft
    )
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.rate_client = None
        order.rate_candidate = None
        await db.commit()

    body = await _month(app_client, app_auth_headers, day)
    [entry] = [e for e in body["entries"] if e["order_id"] == ids["order_id"]]
    resp = await _check(app_client, app_auth_headers, day, entry["item_key"], True)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.rate_client = 1400
        order.rate_candidate = 1000
        order.status = ClientOrderStatus.active
        await db.commit()

    after = await _month(app_client, app_auth_headers, day)
    [entry_after] = [e for e in after["entries"] if e["order_id"] == ids["order_id"]]
    assert entry_after["item_key"] != entry["item_key"]
    assert entry_after["done"] is None
