"""Scalenie zdublowanych kart firm i domeny (``scripts/sales_company_merge.py``).

Baza testowa jest wspólna dla przebiegu, więc skrypt widzi tu tylko karty tego modułu,
a liczniki do ``--expect-*`` testy biorą z biegu na sucho, tak jak operator. Wszystkie
firmy, osoby i domeny są zmyślone.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesCompany,
    SalesCompanyAlias,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services.company_names import normalize_company_name
from app.services.sales.company_aliases import JOINED, REJECTED
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from scripts import sales_company_merge as merge
from tests.test_sales_companies_api import _user
from tests.test_sales_last_touch import CREATED, _activity, _opportunity, _touch

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

#: Karty tego modułu; skrypt widzi tylko je, bo inne testy też zakładają firmy i lejek.
_own: set[int] = set()


@pytest.fixture(autouse=True)
def only_own_cards(monkeypatch):
    original = merge._cards_query
    _own.clear()
    monkeypatch.setattr(
        merge,
        "_cards_query",
        lambda: original().where(SalesCompany.id.in_(set(_own))),
    )


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _card(name: str, *, mails: tuple[str, ...] = (), **fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.flush()
        for index, mail in enumerate(mails):
            db.add(
                SalesContact(
                    company_id=company.id, full_name=f"Osoba {index}", email=mail
                )
            )
        await db.commit()
        _own.add(company.id)
        return company.id


async def _company(company_id: int) -> SalesCompany:
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesCompany, company_id)
        assert row is not None
        return row


async def _alias(company_id: int, alias: str, status: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyAlias(
                company_id=company_id,
                alias=alias,
                normalized_alias=normalize_company_name(alias),
                status=status,
            )
        )
        await db.commit()


async def _aliases(company_id: int) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(SalesCompanyAlias.alias, SalesCompanyAlias.status).where(
                SalesCompanyAlias.company_id == company_id
            )
        )
        return dict(rows.all())


async def _contact_companies(*company_ids: int) -> Counter[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(SalesContact.company_id).where(
                SalesContact.company_id.in_(company_ids)
            )
        )
        return Counter(rows.all())


async def _dry(**options: Any) -> merge.Report:
    return await merge.run(merge.Options(**options), now=NOW)


async def _apply(**options: Any) -> merge.Report:
    """Bieg na sucho, potem ``--apply`` z jego licznikami, jak w instrukcji skryptu."""

    planned = await _dry(**options)
    admin = await _user(role="admin")
    return await merge.run(
        merge.Options(
            apply=True,
            actor_id=admin.id,
            expect_merge=planned.to_merge,
            expect_domains=planned.domains_to_set,
            **options,
        ),
        now=NOW,
    )


def _listed(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cli_default_is_a_dry_run_and_decisions_are_ids() -> None:
    options, lock = merge._parse(["--decide", "7:8,9", "--company-ids", "1,2"])

    assert options.apply is False
    assert options.decide == ((7, (8, 9)),)
    assert options.company_ids == (1, 2)
    assert lock is None


def test_lock_lets_the_minute_cron_run_the_script_only_once(monkeypatch) -> None:
    """Zadanie Coolify odpala komendę co minutę; pracuje tylko pierwsze odpalenie."""

    calls = []

    async def fake_run(options):
        calls.append(options)
        return merge.Report()

    monkeypatch.setattr(merge, "run", fake_run)
    lock = Path(f"/tmp/nexus-sales-company-merge-{uuid.uuid4().int % 10**12}")
    try:
        assert merge.main(["--lock", str(lock)]) == merge.EXIT_OK
        assert merge.main(["--lock", str(lock)]) == merge.EXIT_ALREADY_RAN
    finally:
        lock.rmdir()

    assert len(calls) == 1
    with pytest.raises(SystemExit):
        merge._parse(["--lock", "/tmp/cokolwiek"])


def test_target_is_the_client_card_then_the_account_then_the_most_contacts() -> None:
    def card(company_id: int, client_id: Optional[int] = None) -> merge.Card:
        return merge.Card(
            company_id, "Zmyślona", None, "zmyslona", None, client_id, None, None, None
        )

    plain, busy, account, client = card(1), card(2), card(3), card(4, client_id=77)
    stats = {
        1: merge.Stats(contacts=5),
        2: merge.Stats(contacts=40, activities=9),
        3: merge.Stats(contacts=0, factory_opportunities=1),
        4: merge.Stats(contacts=1),
    }

    assert merge._pick_target([plain, busy, account, client], stats) is client
    assert merge._pick_target([plain, busy, account], stats) is account
    assert merge._pick_target([plain, busy], stats) is busy
    # Remis rozstrzyga starsza karta, żeby wynik nie zależał od kolejności wierszy.
    assert merge._pick_target([card(9), card(8)], {8: stats[1], 9: stats[1]}).id == 8


async def test_dry_run_writes_nothing_and_keeps_names_out_of_the_report(
    tmp_path,
) -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}", mails=(f"a@zmyslona{tag}.example",))
    source = await _card(f"ZMYŚLONA {tag} Sp. z o.o.")
    await _opportunity(target, pipeline_key=IT_FACTORIES_PIPELINE_KEY)
    listing = tmp_path / "lista.json"

    report = await _dry(list_out=str(listing))

    assert report.mode == "dry-run"
    assert report.groups == {"pewna": 1}
    assert (report.to_merge, report.merged) == (1, 0)
    assert (report.domains_to_set, report.domains_set) == (1, 0)
    assert tag not in json.dumps(asdict(report))
    group = _listed(listing)["groups"][0]
    assert group["target_id"] == target
    assert {card["name"] for card in group["cards"]} == {
        f"Zmyślona {tag}",
        f"ZMYŚLONA {tag} Sp. z o.o.",
    }
    assert group["domain"]["proposed"] == f"zmyslona{tag}.example"
    for company_id in (target, source):
        row = await _company(company_id)
        assert (row.archived_at, row.domain) == (None, None)


async def test_dry_run_transaction_refuses_writes(monkeypatch) -> None:
    """Sucho to nie umowa w kodzie: sama baza odrzuca zapis w tej transakcji."""

    async def write_anyway(db, options, names, moment):
        await db.execute(
            update(SalesCompany).values(domain="x.example").where(SalesCompany.id == 0)
        )

    monkeypatch.setattr(merge, "_build_plan", write_anyway)
    with pytest.raises(Exception, match="read-only"):
        await _dry()


async def test_list_with_company_names_cannot_land_in_the_repository() -> None:
    inside = Path(__file__).resolve().parent / "lista-firm.json"

    with pytest.raises(merge.Refused, match="poza repozytorium"):
        await _dry(list_out=str(inside))

    assert not inside.exists()


async def test_apply_merges_an_unambiguous_group_into_the_account_card() -> None:
    tag = _tag()
    account = await _card(f"Zmyślona {tag}")
    bigger = await _card(
        f"ZMYŚLONA {tag} S.A.",
        mails=(f"a@zmyslona{tag}.example", f"b@zmyslona{tag}.example"),
    )
    await _opportunity(account, pipeline_key=IT_FACTORIES_PIPELINE_KEY)
    moved, _ = await _opportunity(bigger, status="won")

    report = await _apply()

    assert (report.merged, report.domains_set) == (1, 1)
    assert report.moving == {
        "contacts": 2,
        "opportunities": 1,
        "activities": 0,
        "files": 0,
    }
    source = await _company(bigger)
    assert source.archived_at == NOW
    assert source.custom_fields["merged_into"] == account
    assert (await _company(account)).domain == f"zmyslona{tag}.example"
    assert await _contact_companies(account, bigger) == {account: 2}
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesOpportunity, moved)).company_id == account
        events = (
            await db.scalars(
                select(SalesOpportunityEvent).where(
                    SalesOpportunityEvent.opportunity_id == moved
                )
            )
        ).all()
    assert [(e.kind, e.old_value, e.new_value) for e in events] == [
        ("company_merged", str(bigger), str(account))
    ]
    assert events[0].user_id is not None


async def test_second_run_changes_nothing() -> None:
    tag = _tag()
    account = await _card(f"Zmyślona {tag}", mails=(f"a@zmyslona{tag}.example",))
    source = await _card(f"Zmyślona {tag} sp. z o.o.")
    await _opportunity(account, pipeline_key=IT_FACTORIES_PIPELINE_KEY)

    first = await _apply()
    after_first = (await _company(account)).updated_at
    planned = await _dry()
    second = await _apply()

    assert (first.merged, first.domains_set) == (1, 1)
    assert (planned.to_merge, planned.domains_to_set) == (0, 0)
    assert planned.domains == {"jest": 1}
    assert (second.merged, second.domains_set) == (0, 0)
    assert (await _company(account)).updated_at == after_first
    assert (await _company(source)).custom_fields["merged_into"] == account


@pytest.mark.parametrize(
    "expect",
    [
        {},
        {"expect_merge": 1},
        {"expect_merge": 7, "expect_domains": 1},
        {"expect_merge": 1, "expect_domains": 7},
    ],
)
async def test_apply_without_the_accepted_counts_is_refused(expect) -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}", mails=(f"a@zmyslona{tag}.example",))
    source = await _card(f"Zmyślona {tag} S.A.")
    admin = await _user(role="admin")

    with pytest.raises(merge.Refused):
        await merge.run(
            merge.Options(
                company_ids=(target,), apply=True, actor_id=admin.id, **expect
            ),
            now=NOW,
        )

    assert (await _company(source)).archived_at is None
    assert (await _company(target)).domain is None


async def test_apply_needs_an_active_admin_as_the_actor() -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}")
    source = await _card(f"Zmyślona {tag} S.A.")
    seller = await _user("sales_edit")

    for actor_id in (None, seller.id):
        with pytest.raises(merge.Refused, match="administratora"):
            await merge.run(
                merge.Options(
                    company_ids=(target,),
                    apply=True,
                    actor_id=actor_id,
                    expect_merge=1,
                    expect_domains=0,
                ),
                now=NOW,
            )

    assert (await _company(source)).archived_at is None


async def test_ambiguous_groups_are_listed_for_a_decision_and_never_merged(
    tmp_path,
) -> None:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        clients = [Client(name=f"Klient Zmyślony {tag} {n}") for n in (1, 2)]
        db.add_all(clients)
        await db.commit()
        client_ids = [client.id for client in clients]
    two_nips = [
        await _card(f"Dwa Nipy {tag}", nip="1111111111"),
        await _card(f"Dwa Nipy {tag} S.A.", nip="222-222-22-22"),
    ]
    two_clients = [
        await _card(f"Dwóch Klientów {tag}", client_id=client_ids[0]),
        await _card(f"Dwóch Klientów {tag} S.A.", client_id=client_ids[1]),
    ]
    parent = await _card(f"Matka Córka {tag}")
    child = await _card(f"Matka Córka {tag} sp. z o.o.", parent_company_id=parent)
    shared_nip = [
        await _card(f"Pierwszy Bank {tag}", nip="3333333333"),
        await _card(f"Zupełnie Inna {tag}", nip="3333333333"),
    ]
    two_mails = [
        await _card(f"Dwie Poczty {tag}", mails=(f"a@jedna{tag}.example",)),
        await _card(f"Dwie Poczty {tag} S.A.", mails=(f"a@druga{tag}.example",)),
    ]
    seeds = (two_nips[0], two_clients[0], parent, shared_nip[0], two_mails[0])
    listing = tmp_path / "lista.json"

    report = await _apply(company_ids=seeds, list_out=str(listing))

    assert report.groups == {"do_decyzji": 5}
    assert report.to_decide_reasons == {
        "rozne_nipy": 1,
        "dwoch_klientow": 1,
        "matka_i_corka": 1,
        "wspolny_nip_rozne_nazwy": 1,
        "rozne_domeny_poczty": 1,
    }
    assert (report.to_merge, report.merged) == (0, 0)
    assert {g["status"] for g in _listed(listing)["groups"]} == {"do_decyzji"}
    for company_id in (*two_nips, *two_clients, parent, child, *shared_nip, *two_mails):
        assert (await _company(company_id)).archived_at is None


async def test_same_brand_cards_are_only_listed_until_artur_decides(tmp_path) -> None:
    tag = _tag()
    account = await _card(f"Zmyślona {tag}")
    variant = await _card(
        f"Zmyślona {tag} Bank Polska S. A", mails=(f"a@zmyslona{tag}.example",)
    )
    other = await _card(f"Zmyślona {tag} Leasing")
    await _opportunity(account, pipeline_key=IT_FACTORIES_PIPELINE_KEY)
    listing = tmp_path / "lista.json"

    planned = await _dry(list_out=str(listing))

    assert planned.groups == {"pojedyncza": 1}
    assert (planned.similar_cards, planned.similar_name_variants) == (2, 1)
    assert planned.to_merge == 0
    group = _listed(listing)["groups"][0]
    assert {card["id"]: card["role"] for card in group["similar"]} == {
        variant: "wariant",
        other: "inna_spolka",
    }
    assert group["decide_variants"] == f"{account}:{variant}"

    report = await _apply(decide=((account, (variant,)),))

    assert report.groups == {"decyzja": 1}
    assert report.to_merge_by_origin == {"decyzja": 1}
    assert (report.merged, report.names_joined, report.domains_set) == (1, 1, 1)
    assert (await _company(variant)).custom_fields["merged_into"] == account
    assert (await _company(other)).archived_at is None
    # „Kogo znamy” dopasowuje osoby po nazwie, więc nazwa wchłoniętej karty zostaje.
    assert await _aliases(account) == {f"Zmyślona {tag} Bank Polska S. A": JOINED}
    assert (await _company(account)).domain == f"zmyslona{tag}.example"


async def test_malformed_decisions_are_refused() -> None:
    tag = _tag()
    first, second, third = [await _card(f"Zmyślona {tag} {n}") for n in "abc"]
    archived = await _card(f"Zmyślona {tag} d", archived_at=CREATED)

    for decide in (
        ((first, ()),),
        ((first, (first,)),),
        ((first, (archived,)),),
        ((first, (second,)), (third, (second,))),
    ):
        with pytest.raises(merge.Refused, match="--decide"):
            await _dry(decide=decide)


async def test_decision_cannot_join_cards_of_two_clients() -> None:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        clients = [Client(name=f"Klient Zmyślony {tag} {n}") for n in (1, 2)]
        db.add_all(clients)
        await db.commit()
        client_ids = [client.id for client in clients]
    target = await _card(f"Zmyślona {tag}", client_id=client_ids[0])
    source = await _card(f"Zmyślona {tag} Polska", client_id=client_ids[1])

    report = await _apply(decide=((target, (source,)),))

    assert report.blocked_reasons == {"dwoch_klientow": 1}
    assert (report.to_merge, report.merged) == (0, 0)
    assert (await _company(source)).client_id == client_ids[1]
    assert (await _company(source)).archived_at is None


async def test_group_is_not_merged_when_an_open_opportunity_touch_would_move(
    tmp_path,
) -> None:
    tag = _tag()
    quiet = await _card(f"Zmyślona {tag}")
    worked = await _card(f"Zmyślona {tag} S.A.")
    opportunity_id, _ = await _opportunity(quiet)
    recent = NOW - timedelta(days=3)
    await _activity("note", company_id=worked, created_at=recent)
    before = await _touch(opportunity_id, NOW)
    listing = tmp_path / "lista.json"

    report = await _apply(company_ids=(quiet,), list_out=str(listing))

    assert before == CREATED
    assert report.groups == {"zablokowana": 1}
    assert report.blocked_reasons == {"dotyk": 1}
    assert (report.to_merge, report.merged) == (0, 0)
    assert _listed(listing)["groups"][0]["blocked"] == ["dotyk"]
    assert await _touch(opportunity_id, NOW) == before
    for company_id in (quiet, worked):
        assert (await _company(company_id)).archived_at is None


async def test_activity_older_than_the_touch_does_not_block_and_touch_stays() -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}", mails=("a@zmyslona.example",))
    source = await _card(f"Zmyślona {tag} S.A.")
    opportunity_id, _ = await _opportunity(target, created_at=NOW - timedelta(days=30))
    await _activity("note", company_id=source, created_at=CREATED)
    closed, _ = await _opportunity(source, status="lost")
    before = await _touch(opportunity_id, NOW)

    report = await _apply(company_ids=(target,))

    assert report.merged == 1
    assert await _touch(opportunity_id, NOW) == before
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesOpportunity, closed)).company_id == target


async def test_result_other_than_the_plan_rolls_everything_back(monkeypatch) -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}")
    source = await _card(f"Zmyślona {tag} S.A.")
    opportunity_id, _ = await _opportunity(target)
    planned = await _dry(company_ids=(target,))
    admin = await _user(role="admin")
    original = merge.merge_companies

    async def merge_and_touch(db, **kwargs):
        await original(db, **kwargs)
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.id == opportunity_id)
            .values(last_activity_at=NOW - timedelta(days=1))
        )

    monkeypatch.setattr(merge, "merge_companies", merge_and_touch)
    with pytest.raises(merge.ResultDiffers):
        await merge.run(
            merge.Options(
                company_ids=(target,),
                apply=True,
                actor_id=admin.id,
                expect_merge=planned.to_merge,
                expect_domains=planned.domains_to_set,
            ),
            now=NOW,
        )

    assert planned.to_merge == 1
    assert (await _company(source)).archived_at is None
    assert await _touch(opportunity_id, NOW) == CREATED


async def test_group_is_not_merged_when_a_joined_name_would_be_lost() -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}")
    source = await _card(f"Zmyślona {tag} S.A.")
    await _alias(target, f"Dawna Nazwa {tag}", REJECTED)
    await _alias(source, f"Dawna Nazwa {tag}", JOINED)

    report = await _apply(company_ids=(target,))

    assert report.blocked_reasons == {"dolaczona_nazwa": 1}
    assert (report.to_merge, report.merged) == (0, 0)
    assert (await _company(source)).archived_at is None
    assert await _aliases(source) == {f"Dawna Nazwa {tag}": JOINED}


async def test_joined_names_of_the_source_follow_the_merge() -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}")
    source = await _card(f"Zmyślona {tag} S.A.")
    await _alias(source, f"Dawna Nazwa {tag}", JOINED)
    await _alias(source, f"Obca Nazwa {tag}", REJECTED)

    report = await _apply(company_ids=(target,))

    assert (report.merged, report.names_joined) == (1, 0)
    assert await _aliases(target) == {
        f"Dawna Nazwa {tag}": JOINED,
        f"Obca Nazwa {tag}": REJECTED,
    }


async def test_plan_counts_the_names_the_merge_joins_source_by_source() -> None:
    tag = _tag()
    target = await _card(f"Zmyślona {tag}")
    first = await _card(f"Zmyślona {tag} Group")
    # Nazwa prawna drugiej karty to nazwa pierwszej, a pierwsza jest już dołączona.
    second = await _card(
        f"Zmyślona {tag} Polska", legal_name=f"Zmyślona {tag} Group Sp. z o.o."
    )

    report = await _apply(decide=((target, (first, second)),))

    assert (report.merged, report.names_to_join, report.names_joined) == (2, 2, 2)
    assert await _aliases(target) == {
        f"Zmyślona {tag} Group": JOINED,
        f"Zmyślona {tag} Polska": JOINED,
    }


async def test_domain_shared_by_two_companies_is_a_conflict_until_accepted(
    tmp_path,
) -> None:
    tag = _tag()
    shared = f"grupa{tag}.example"
    first = await _card(f"Pierwsza {tag}", mails=(f"a@{shared}", f"b@{shared}"))
    second = await _card(f"Druga {tag}", mails=(f"c@{shared}", f"d@{shared}"))
    holder = await _card(f"Trzecia {tag}", domain=f"https://www.zajeta{tag}.example/pl")
    fourth = await _card(
        f"Czwarta {tag}",
        mails=(f"a@zajeta{tag}.example", f"b@zajeta{tag}.example"),
    )
    seeds = (first, second, holder, fourth)
    listing = tmp_path / "lista.json"

    planned = await _dry(company_ids=seeds, list_out=str(listing))

    assert planned.domains == {"konflikt": 3, "jest": 1}
    assert planned.domains_to_set == 0
    by_target = {g["target_id"]: g["domain"] for g in _listed(listing)["groups"]}
    assert by_target[first]["shared_with"] == [second]
    assert by_target[fourth]["shared_with"] == [holder]

    report = await _apply(company_ids=seeds, accept_domain=(first,))

    assert report.domains_set == 1
    assert (await _company(first)).domain == shared
    assert (await _company(second)).domain is None
    assert (await _company(fourth)).domain is None
    assert (await _company(holder)).domain == f"https://www.zajeta{tag}.example/pl"


async def test_domain_comes_from_company_mail_then_from_the_website() -> None:
    tag = _tag()
    majority = await _card(
        f"Większość {tag}",
        mails=(
            f"a@wiekszosc{tag}.example",
            f"B@Wiekszosc{tag}.example ",
            f"c@inna{tag}.example",
            "prywatny@gmail.com",
            "bez-malpy",
        ),
        website_url=f"https://www.strona{tag}.example/kontakt",
    )
    website = await _card(
        f"Strona {tag}",
        mails=("ktos@wp.pl",),
        website_url=f"http://www.strona-b{tag}.example/",
    )
    lone_matching = await _card(f"Samotna {tag}", mails=(f"a@samotna{tag}.example",))
    lone_foreign = await _card(f"Obca {tag}", mails=("a@doradca-zewnetrzny.example",))
    tie = await _card(
        f"Remis {tag}", mails=(f"a@remis{tag}.example", f"a@remis-b{tag}.example")
    )
    kept = await _card(
        f"Wpisana {tag}",
        mails=(f"a@nowa{tag}.example", f"b@nowa{tag}.example"),
        domain=f"wpisana{tag}.example",
    )
    empty = await _card(f"Pusta {tag}")
    seeds = (majority, website, lone_matching, lone_foreign, tie, kept, empty)

    report = await _apply(company_ids=seeds)

    assert report.domains == {"do_zapisu": 3, "slaba": 2, "jest": 1, "brak": 1}
    assert report.domains_set == 3
    assert (await _company(majority)).domain == f"wiekszosc{tag}.example"
    assert (await _company(website)).domain == f"strona-b{tag}.example"
    assert (await _company(lone_matching)).domain == f"samotna{tag}.example"
    assert (await _company(kept)).domain == f"wpisana{tag}.example"
    for company_id in (lone_foreign, tie, empty):
        assert (await _company(company_id)).domain is None


async def test_names_file_adds_companies_and_counts_names_without_a_card(
    tmp_path,
) -> None:
    tag = _tag()
    listed = await _card(f"Z Listy {tag} Sp. z o.o.")
    duplicate = await _card(f"Z LISTY {tag}")
    relative = await _card(f"Bez Karty {tag} Polska")
    names = tmp_path / "lista-firm.txt"
    names.write_text(
        f"# lista z researchu\nZ listy {tag}\n\nBez Karty {tag}\nZ listy {tag}\n",
        encoding="utf-8",
    )
    listing = tmp_path / "lista.json"

    report = await _dry(names_file=str(names), list_out=str(listing))

    assert (report.seeds_names, report.names_without_card) == (1, 1)
    assert report.groups == {"pewna": 1}
    assert report.to_merge == 1
    data = _listed(listing)
    assert {card["id"] for card in data["groups"][0]["cards"]} == {listed, duplicate}
    assert data["groups"][0]["seeds"] == ["lista"]
    missing = data["names_without_card"]
    assert [entry["name"] for entry in missing] == [f"Bez Karty {tag}"]
    assert [(c["id"], c["role"]) for c in missing[0]["similar"]] == [
        (relative, "wariant")
    ]


async def test_unknown_or_archived_card_id_is_refused() -> None:
    archived = await _card(f"Zmyślona {_tag()}", archived_at=CREATED)

    with pytest.raises(merge.Refused, match="--company-ids"):
        await _dry(company_ids=(archived,))
