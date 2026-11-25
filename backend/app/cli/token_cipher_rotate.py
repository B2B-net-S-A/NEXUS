"""Przeszyfrowanie danych nowym kluczem po rotacji ``M365_TOKEN_ENCRYPTION_KEY``.

Uruchomienie (w kontenerze backendu, po wdrożeniu z nowym kluczem w
``M365_TOKEN_ENCRYPTION_KEY`` i starym w ``M365_TOKEN_ENCRYPTION_KEY_PREVIOUS``)::

    python -m app.cli.token_cipher_rotate            # na sucho: same liczby
    python -m app.cli.token_cipher_rotate --apply    # przeszyfrowanie porcjami

Co robi:

* każda kolumna z ``FERNET_COLUMNS``: wartość czytelna tylko poprzednim kluczem
  dostaje ten sam tekst zaszyfrowany bieżącym (``TokenCipher.rotate``). Zapis
  jest warunkowy (``UPDATE … WHERE kolumna = stara wartość``): wiersz, który
  aplikacja zmieniła w międzyczasie (np. odświeżony token skrzynki M365), jest
  już zaszyfrowany bieżącym kluczem i zostaje bez zmian;
* skróty HMAC z ``HMAC_COLUMNS``: dane płacowe osoby liczą je od nowa
  z odszyfrowanej treści; paczka przelewów i pozycja listy płac pamiętają skrót
  rachunku z dnia paczki — skrót poprzednim kluczem, który pasuje do bieżącego
  rachunku osoby, dostaje skrót bieżącym. Skrót, który nie pasuje do bieżącego
  rachunku (rachunek zmienił się po paczce), zostaje (``other``): pobranie
  pliku i tak zgłosi zmianę rachunku;
* wartość, której nie czyta żaden klucz, zostaje (``unreadable``);
* porcje po ``--batch-size`` wierszy, każda w osobnej transakcji; drugi bieg
  nic nie zmienia.

Wynik to JSON z samymi liczbami: bez id, treści i wartości (logi i paragony
nie mogą ich mieć). ``ready_to_drop_previous`` = jest poprzedni klucz i nic nie
jest czytelne tylko nim (ani szyfrogram, ani skrót) — dopiero wtedy wolno
wyczyścić ``M365_TOKEN_ENCRYPTION_KEY_PREVIOUS``. Kod wyjścia ``--apply``:
0 przy ``ready_to_drop_previous``, 1 w przeciwnym razie.

Procedura: ``docs/claude/podstawy/rotacja-klucza-szyfrowania-tokenow.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import TokenCipher, TokenCipherNotConfigured
from app.services.hr.billing_details import ACCOUNT_FINGERPRINT_PURPOSE
from app.services.hr.payroll_lists.pesel import (
    FINGERPRINT_PURPOSE as PESEL_FINGERPRINT_PURPOSE,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200

SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class FernetColumns:
    table: str
    pk: str
    columns: tuple[str, ...]


#: Każda kolumna szyfrowana ``get_token_cipher()``. Nowa kolumna = wpis tutaj
#: (pilnuje ``tests/test_token_cipher_rotate.py`` po nazwach ``*_ct``,
#: ``*_encrypted`` w modelach).
FERNET_COLUMNS: tuple[FernetColumns, ...] = (
    FernetColumns("m365_connections", "id", ("access_token_ct", "refresh_token_ct")),
    FernetColumns("candidate_invite_links", "token", ("token_ct",)),
    FernetColumns("employee_billing_details", "id", ("account_encrypted",)),
    FernetColumns("payroll_person_data", "id", ("data_encrypted",)),
    FernetColumns("integration_webhooks", "id", ("secret_ct",)),
    FernetColumns(
        "job_board_connections", "id", ("access_token_ct", "refresh_token_ct")
    ),
)

#: Każda kolumna ze skrótem HMAC z kluczem wyprowadzonym z tego sekretu
#: (pilnuje ten sam test po nazwach ``*_hmac``).
HMAC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("payroll_person_data", "pesel_hmac"),
    ("payroll_person_data", "account_hmac"),
    ("payroll_list_lines", "payee_hmac"),
    ("payroll_payments", "counterparty_hmac"),
)


def _table(name: str, *columns: str) -> sa.TableClause:
    return sa.table(name, *(sa.column(column) for column in columns))


_PERSON = _table(
    "payroll_person_data",
    "id",
    "user_id",
    "candidate_id",
    "candidate_ref",
    "data_encrypted",
    "pesel_hmac",
    "account_hmac",
)
_BILLING = _table("employee_billing_details", "user_id", "account_encrypted")
_LINES = _table(
    "payroll_list_lines", "id", "user_id", "candidate_id", "candidate_ref", "payee_hmac"
)
_PAYMENTS = _table("payroll_payments", "id", "settlement_id", "counterparty_hmac")
_SETTLEMENTS = _table("payroll_settlements", "id", "user_id")


def _decrypt(cipher: TokenCipher, ciphertext: Optional[str]) -> Optional[str]:
    if not ciphertext:
        return None
    try:
        return cipher.decrypt(ciphertext)
    except (TokenCipherNotConfigured, ValueError):
        return None


def _person_data(cipher: TokenCipher, ciphertext: Optional[str]) -> Optional[dict]:
    raw = _decrypt(cipher, ciphertext)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _classify(stored: Optional[str], expected: tuple[str, ...]) -> str:
    """``current`` / ``previous`` (do przeliczenia) / ``other`` / ``empty``."""

    if not stored:
        return "empty"
    if expected and stored == expected[0]:
        return "current"
    if stored in expected[1:]:
        return "previous"
    return "other"


async def _batches(
    factory: SessionFactory,
    query: sa.Select,
    pk: sa.ColumnElement,
    batch_size: int,
):
    """Porcje wierszy po kluczu głównym; każda porcja we własnej sesji."""

    last: Any = None
    while True:
        page = query.order_by(pk).limit(batch_size)
        if last is not None:
            page = page.where(pk > last)
        async with factory() as db:
            rows = (await db.execute(page)).all()
            if not rows:
                return
            yield db, rows
        last = rows[-1][0]


async def _rotate_ciphertexts(
    factory: SessionFactory,
    cipher: TokenCipher,
    spec: FernetColumns,
    *,
    apply: bool,
    batch_size: int,
    stats: dict[str, Counter],
) -> None:
    table = _table(spec.table, spec.pk, *spec.columns)
    pk = table.c[spec.pk]
    query = sa.select(pk, *(table.c[name] for name in spec.columns))
    async for db, rows in _batches(factory, query, pk, batch_size):
        for row in rows:
            changes: dict[str, tuple[str, str]] = {}
            for name, value in zip(spec.columns, row[1:]):
                counter = stats[f"{spec.table}.{name}"]
                index = cipher.key_index(value) if value else None
                if not value:
                    counter["empty"] += 1
                elif index is None:
                    counter["unreadable"] += 1
                elif index == 0:
                    counter["current"] += 1
                else:
                    counter["previous"] += 1
                    if apply:
                        changes[name] = (value, cipher.rotate(value))
            if not changes:
                continue
            statement = sa.update(table).where(pk == row[0])
            for name, (old, _new) in changes.items():
                statement = statement.where(table.c[name] == old)
            result = await db.execute(
                statement.values({name: new for name, (_old, new) in changes.items()})
            )
            outcome = "rotated" if result.rowcount == 1 else "changed_meanwhile"
            for name in changes:
                stats[f"{spec.table}.{name}"][outcome] += 1
        if apply:
            await db.commit()


async def _set_fingerprint(
    db: AsyncSession,
    table: sa.TableClause,
    row_id: Any,
    column: str,
    old: str,
    new: str,
    counter: Counter,
) -> None:
    """Zapis warunkowy jednego skrótu; konflikt unikalności (PESEL) = liczba."""

    try:
        async with db.begin_nested():
            result = await db.execute(
                sa.update(table)
                .where(table.c.id == row_id, table.c[column] == old)
                .values({column: new})
            )
    except IntegrityError:
        counter["conflict"] += 1
        return
    counter["rotated" if result.rowcount == 1 else "changed_meanwhile"] += 1


async def _rotate_person_fingerprints(
    factory: SessionFactory,
    cipher: TokenCipher,
    *,
    apply: bool,
    batch_size: int,
    stats: dict[str, Counter],
) -> None:
    query = sa.select(
        _PERSON.c.id,
        _PERSON.c.data_encrypted,
        _PERSON.c.pesel_hmac,
        _PERSON.c.account_hmac,
    )
    async for db, rows in _batches(factory, query, _PERSON.c.id, batch_size):
        for row_id, ciphertext, pesel_hmac, account_hmac in rows:
            data = _person_data(cipher, ciphertext)
            for column, stored, purpose, field in (
                ("pesel_hmac", pesel_hmac, PESEL_FINGERPRINT_PURPOSE, "pesel"),
                (
                    "account_hmac",
                    account_hmac,
                    ACCOUNT_FINGERPRINT_PURPOSE,
                    "bank_account",
                ),
            ):
                counter = stats[f"payroll_person_data.{column}"]
                if data is None:
                    counter["empty" if not stored else "unreadable"] += 1
                    continue
                value = data.get(field)
                expected = cipher.fingerprints(purpose, str(value)) if value else ()
                state = _classify(stored, expected)
                counter[state] += 1
                if state == "previous" and apply:
                    await _set_fingerprint(
                        db, _PERSON, row_id, column, stored, expected[0], counter
                    )
        if apply:
            await db.commit()


async def _billing_accounts(
    db: AsyncSession, cipher: TokenCipher, user_ids: set[int]
) -> dict[int, Optional[str]]:
    if not user_ids:
        return {}
    rows = await db.execute(
        sa.select(_BILLING.c.user_id, _BILLING.c.account_encrypted).where(
            _BILLING.c.user_id.in_(user_ids)
        )
    )
    return {user_id: _decrypt(cipher, ciphertext) for user_id, ciphertext in rows}


async def _person_accounts(
    db: AsyncSession, cipher: TokenCipher, candidate_ids: set[int], refs: set[str]
) -> tuple[dict[int, Optional[str]], dict[str, Optional[str]]]:
    by_candidate: dict[int, Optional[str]] = {}
    by_ref: dict[str, Optional[str]] = {}
    if not candidate_ids and not refs:
        return by_candidate, by_ref
    condition = sa.false()
    if candidate_ids:
        condition = condition | _PERSON.c.candidate_id.in_(candidate_ids)
    if refs:
        condition = condition | _PERSON.c.candidate_ref.in_(refs)
    rows = await db.execute(
        sa.select(
            _PERSON.c.candidate_id, _PERSON.c.candidate_ref, _PERSON.c.data_encrypted
        ).where(condition)
    )
    for candidate_id, ref, ciphertext in rows:
        data = _person_data(cipher, ciphertext) or {}
        account = data.get("bank_account") or None
        if candidate_id is not None:
            by_candidate[candidate_id] = account
        if ref is not None:
            by_ref[ref] = account
    return by_candidate, by_ref


async def _rotate_line_fingerprints(
    factory: SessionFactory,
    cipher: TokenCipher,
    *,
    apply: bool,
    batch_size: int,
    stats: dict[str, Counter],
) -> None:
    """Pozycje listy płac: rachunek jak przy pliku przelewów
    (``payroll_lists.transfers._accounts``) — konto albo dane płacowe osoby."""

    counter = stats["payroll_list_lines.payee_hmac"]
    query = sa.select(
        _LINES.c.id,
        _LINES.c.user_id,
        _LINES.c.candidate_id,
        _LINES.c.candidate_ref,
        _LINES.c.payee_hmac,
    ).where(_LINES.c.payee_hmac.is_not(None))
    async for db, rows in _batches(factory, query, _LINES.c.id, batch_size):
        users = await _billing_accounts(
            db, cipher, {row.user_id for row in rows if row.user_id is not None}
        )
        by_candidate, by_ref = await _person_accounts(
            db,
            cipher,
            {
                row.candidate_id
                for row in rows
                if row.user_id is None and row.candidate_id
            },
            {
                row.candidate_ref
                for row in rows
                if row.user_id is None
                and row.candidate_id is None
                and row.candidate_ref
            },
        )
        for row in rows:
            if row.user_id is not None:
                account = users.get(row.user_id)
            elif row.candidate_id is not None:
                account = by_candidate.get(row.candidate_id)
            else:
                account = by_ref.get(row.candidate_ref)
            expected = (
                cipher.fingerprints(ACCOUNT_FINGERPRINT_PURPOSE, account)
                if account
                else ()
            )
            state = _classify(row.payee_hmac, expected)
            counter[state] += 1
            if state == "previous" and apply:
                await _set_fingerprint(
                    db,
                    _LINES,
                    row.id,
                    "payee_hmac",
                    row.payee_hmac,
                    expected[0],
                    counter,
                )
        if apply:
            await db.commit()


async def _rotate_payment_fingerprints(
    factory: SessionFactory,
    cipher: TokenCipher,
    *,
    apply: bool,
    batch_size: int,
    stats: dict[str, Counter],
) -> None:
    """Paczka przelewów: rachunek osoby z rozliczenia (``bank.batches._same_account``)."""

    counter = stats["payroll_payments.counterparty_hmac"]
    query = (
        sa.select(_PAYMENTS.c.id, _SETTLEMENTS.c.user_id, _PAYMENTS.c.counterparty_hmac)
        .select_from(
            _PAYMENTS.outerjoin(
                _SETTLEMENTS, _SETTLEMENTS.c.id == _PAYMENTS.c.settlement_id
            )
        )
        .where(_PAYMENTS.c.counterparty_hmac.is_not(None))
    )
    async for db, rows in _batches(factory, query, _PAYMENTS.c.id, batch_size):
        accounts = await _billing_accounts(
            db, cipher, {user_id for _id, user_id, _fp in rows if user_id is not None}
        )
        for payment_id, user_id, stored in rows:
            account = accounts.get(user_id) if user_id is not None else None
            expected = (
                cipher.fingerprints(ACCOUNT_FINGERPRINT_PURPOSE, account)
                if account
                else ()
            )
            state = _classify(stored, expected)
            counter[state] += 1
            if state == "previous" and apply:
                await _set_fingerprint(
                    db,
                    _PAYMENTS,
                    payment_id,
                    "counterparty_hmac",
                    stored,
                    expected[0],
                    counter,
                )
        if apply:
            await db.commit()


async def survey(
    factory: SessionFactory,
    cipher: TokenCipher,
    *,
    apply: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, dict[str, int]]:
    """Jeden przebieg po wszystkich kolumnach; z ``apply`` także zapis."""

    stats: dict[str, Counter] = {
        f"{spec.table}.{name}": Counter()
        for spec in FERNET_COLUMNS
        for name in spec.columns
    }
    stats.update({f"{table}.{column}": Counter() for table, column in HMAC_COLUMNS})
    # Najpierw szyfrogramy: skróty danych osoby liczą się z treści, którą czyta
    # już bieżący klucz.
    for spec in FERNET_COLUMNS:
        await _rotate_ciphertexts(
            factory, cipher, spec, apply=apply, batch_size=batch_size, stats=stats
        )
    for step in (
        _rotate_person_fingerprints,
        _rotate_line_fingerprints,
        _rotate_payment_fingerprints,
    ):
        await step(factory, cipher, apply=apply, batch_size=batch_size, stats=stats)
    return {name: dict(sorted(counter.items())) for name, counter in stats.items()}


def _total(columns: dict[str, dict[str, int]], state: str) -> int:
    return sum(counts.get(state, 0) for counts in columns.values())


async def run(
    factory: SessionFactory,
    cipher: TokenCipher,
    *,
    apply: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    columns = await survey(factory, cipher, apply=apply, batch_size=batch_size)
    report: dict[str, Any] = {"apply": apply, "columns": columns}
    final = columns
    if apply:
        # Stan po zapisie liczony od nowa, nie z liczników zapisu.
        final = await survey(factory, cipher, apply=False, batch_size=batch_size)
        report["after"] = final
    previous_only = _total(final, "previous")
    report.update(
        {
            "previous_keys": cipher.previous_count,
            "previous_only": previous_only,
            "unreadable": _total(final, "unreadable"),
            # Konflikt powstaje tylko przy zapisie, więc z przebiegu zapisu.
            "conflicts": _total(columns, "conflict"),
            "ready_to_drop_previous": cipher.previous_count > 0 and previous_only == 0,
        }
    )
    return report


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="przeszyfruj (bez tego: same liczby)"
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size musi być dodatnie")

    from app.core.database import AsyncSessionLocal
    from app.core.encryption import get_token_cipher

    try:
        cipher = get_token_cipher()
    except TokenCipherNotConfigured as exc:
        # Komunikat mówi tylko, która zmienna jest zła — nigdy wartość.
        print(f"Klucze szyfrowania nie są poprawne: {exc}", file=sys.stderr)
        return 2
    report = await run(
        AsyncSessionLocal, cipher, apply=args.apply, batch_size=args.batch_size
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.apply and not report["ready_to_drop_previous"]:
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
