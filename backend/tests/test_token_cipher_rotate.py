"""Rotacja klucza szyfrowania danych: ``app.cli.token_cipher_rotate`` (25.11.2026).

Klucze są losowe i zna je tylko ten plik. Skrypt zmienia wyłącznie wartości
czytelne poprzednim kluczem, więc wiersze innych testów (klucz z CI) liczą się
jako nieczytelne i zostają nietknięte. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from app.cli import token_cipher_rotate as rotate
from app.core.database import AsyncSessionLocal, Base
from app.core.encryption import TokenCipher, TokenCipherNotConfigured
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_payroll_lists import (
    PayrollList,
    PayrollListLine,
    PayrollParameterVersion,
    PayrollPersonData,
)
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.invite_link import CandidateInviteLink
from app.models.m365 import M365Connection
from app.services.hr.billing_details import ACCOUNT_FINGERPRINT_PURPOSE
from app.services.hr.payroll_lists.pesel import FINGERPRINT_PURPOSE as PESEL_PURPOSE
from tests.hr import payments_fixtures as fx

# ── Rejestr kolumn ───────────────────────────────────────────────────────────


def _model_columns(suffixes: tuple[str, ...]) -> set[str]:
    import app.models  # noqa: F401 — rejestruje wszystkie modele w metadanych

    return {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith(suffixes)
    }


def test_every_encrypted_column_is_rotated() -> None:
    """Nowa kolumna szyfrowana kluczem tokenów (``*_ct``, ``*_encrypted``)
    bez wpisu w ``FERNET_COLUMNS`` po rotacji przestałaby się czytać."""

    registered = {
        f"{spec.table}.{name}"
        for spec in rotate.FERNET_COLUMNS
        for name in spec.columns
    }
    assert _model_columns(("_ct", "_encrypted")) == registered


def test_every_fingerprint_column_is_recomputed() -> None:
    registered = {f"{table}.{column}" for table, column in rotate.HMAC_COLUMNS}
    assert _model_columns(("_hmac",)) == registered


# ── Przebieg na bazie ────────────────────────────────────────────────────────


def _key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _pesel(serial: int) -> str:
    base = f"850607{serial:04d}"
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    check = (10 - sum(int(d) * w for d, w in zip(base, weights)) % 10) % 10
    return f"{base}{check}"


def _fp(cipher: TokenCipher, purpose: bytes, value: str) -> str:
    return cipher.fingerprints(purpose, value)[0]


class Seeded:
    """Id wierszy tego testu i ich jawne wartości (do sprawdzenia po rotacji)."""

    def __init__(self) -> None:
        self.user_ids: list[int] = []
        self.connection_id = 0
        self.unreadable_connection_id = 0
        self.unreadable_ct = ""
        self.invite_token = ""
        self.billing_id = 0
        self.person_id = 0
        self.period_id = 0
        self.settlement_id = 0
        self.payment_id = 0
        self.changed_payment_id = 0
        self.changed_payment_hmac = ""
        self.version_id = 0
        self.list_id = 0
        self.line_id = 0


ACCOUNT = fx.account("99990011", "4242")
REPLACED = fx.account("99990012", "4242")
PESEL = _pesel(1234)


async def _seed(old: TokenCipher, unknown: TokenCipher) -> Seeded:
    s = Seeded()
    year = random.randint(2080, 2089)
    marker = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        owner = await fx.make_user(db, "recruiter")
        other = await fx.make_user(db, "recruiter")
        s.user_ids = [owner.id, other.id]
        connection = M365Connection(
            user_id=owner.id,
            tenant_id="rotacja-test",
            mailbox_upn=f"rotacja-{marker}@example.com",
            access_token_ct=old.encrypt("access-token"),
            refresh_token_ct=old.encrypt("refresh-token"),
            expires_at=now,
        )
        s.unreadable_ct = unknown.encrypt("never-readable")
        broken = M365Connection(
            user_id=other.id,
            tenant_id="rotacja-test",
            mailbox_upn=f"rotacja-{marker}-b@example.com",
            access_token_ct=s.unreadable_ct,
            refresh_token_ct=s.unreadable_ct,
            expires_at=now,
        )
        s.invite_token = f"rotacja-{uuid.uuid4().hex}"
        invite = CandidateInviteLink(
            token=s.invite_token,
            created_by=owner.id,
            kind="recruiter",
            slug=f"rotacja-{marker}",
            token_ct=old.encrypt("invite-secret"),
        )
        billing = EmployeeBillingDetails(
            user_id=owner.id,
            payment_terms_days=14,
            account_encrypted=old.encrypt(ACCOUNT),
            account_last4=ACCOUNT[-4:],
            account_source="manual",
        )
        person = PayrollPersonData(
            user_id=owner.id,
            data_encrypted=old.encrypt(
                json.dumps({"pesel": PESEL, "bank_account": ACCOUNT}, sort_keys=True)
            ),
            pesel_hmac=_fp(old, PESEL_PURPOSE, PESEL),
            pesel_last4=PESEL[-4:],
            account_hmac=_fp(old, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT),
            account_last4=ACCOUNT[-4:],
            missing=[],
        )
        db.add_all([connection, broken, invite, billing, person])
        period = await fx.closed_period(db, year, 7)
        settlement = await fx.settlement(
            db, period, owner, employment_type="b2b", expected="100.00"
        )
        payment = PayrollPayment(
            kind="transfer_batch",
            settlement_id=settlement.id,
            match_status="matched",
            amount=Decimal("100.00"),
            currency="PLN",
            booked_on=date(year, 8, 10),
            title="Wynagrodzenie testowe",
            counterparty_last4=ACCOUNT[-4:],
            counterparty_hmac=_fp(old, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT),
            batch_key=uuid.uuid4().hex,
            batch_format="elixir",
        )
        # Rachunek zmienił się po paczce: skrót nie pasuje do bieżącego rachunku.
        s.changed_payment_hmac = _fp(old, ACCOUNT_FINGERPRINT_PURPOSE, REPLACED)
        changed = PayrollPayment(
            kind="transfer_batch",
            settlement_id=settlement.id,
            match_status="matched",
            amount=Decimal("100.00"),
            currency="PLN",
            booked_on=date(year, 8, 10),
            title="Wynagrodzenie testowe",
            counterparty_last4=REPLACED[-4:],
            counterparty_hmac=s.changed_payment_hmac,
            batch_key=uuid.uuid4().hex,
            batch_format="elixir",
        )
        version = PayrollParameterVersion(
            effective_from=date(year, 1, 1),
            params={},
            status="confirmed",
            source="manual",
            confirmed_at=now,
        )
        db.add_all([payment, changed, version])
        await db.flush()
        payroll_list = PayrollList(
            period_id=period.id,
            year=year,
            month=7,
            number=f"LP/rotacja/{marker}",
            pay_date=date(year, 8, 10),
            parameter_version_id=version.id,
        )
        db.add(payroll_list)
        await db.flush()
        line = PayrollListLine(
            list_id=payroll_list.id,
            user_id=owner.id,
            person_name="Osoba Testowa",
            kind="uop",
            source="payroll_line",
            payee_last4=ACCOUNT[-4:],
            payee_hmac=_fp(old, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT),
        )
        db.add(line)
        await db.commit()
        s.connection_id = connection.id
        s.unreadable_connection_id = broken.id
        s.billing_id = billing.id
        s.person_id = person.id
        s.period_id = period.id
        s.settlement_id = settlement.id
        s.payment_id = payment.id
        s.changed_payment_id = changed.id
        s.version_id = version.id
        s.list_id = payroll_list.id
        s.line_id = line.id
    return s


async def _cleanup(s: Seeded) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PayrollListLine).where(PayrollListLine.id == s.line_id))
        await db.execute(delete(PayrollList).where(PayrollList.id == s.list_id))
        await db.execute(
            delete(PayrollParameterVersion).where(
                PayrollParameterVersion.id == s.version_id
            )
        )
        await db.execute(
            delete(PayrollPayment).where(
                PayrollPayment.settlement_id == s.settlement_id
            )
        )
        await db.execute(
            delete(PayrollSettlement).where(PayrollSettlement.id == s.settlement_id)
        )
        await db.execute(delete(PayrollPeriod).where(PayrollPeriod.id == s.period_id))
        await db.execute(
            delete(PayrollPersonData).where(PayrollPersonData.user_id.in_(s.user_ids))
        )
        await db.execute(
            delete(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id.in_(s.user_ids)
            )
        )
        await db.execute(
            delete(CandidateInviteLink).where(
                CandidateInviteLink.token == s.invite_token
            )
        )
        await db.execute(
            delete(M365Connection).where(M365Connection.user_id.in_(s.user_ids))
        )
        await db.commit()


def _rotated(report: dict, column: str) -> int:
    return report["columns"][column].get("rotated", 0)


@pytest.mark.asyncio
async def test_rotation_reencrypts_everything_and_recomputes_fingerprints() -> None:
    old_key, new_key = _key(), _key()
    old = TokenCipher(old_key)
    rotating = TokenCipher(new_key, [old_key])
    new_only = TokenCipher(new_key)
    s = await _seed(old, TokenCipher(_key()))
    try:
        dry = await rotate.run(AsyncSessionLocal, rotating, apply=False)
        assert dry["previous_only"] == 9, dry
        assert dry["ready_to_drop_previous"] is False
        assert all("rotated" not in counts for counts in dry["columns"].values())

        report = await rotate.run(AsyncSessionLocal, rotating, apply=True)

        for column in (
            "m365_connections.access_token_ct",
            "m365_connections.refresh_token_ct",
            "candidate_invite_links.token_ct",
            "employee_billing_details.account_encrypted",
            "payroll_person_data.data_encrypted",
            "payroll_person_data.pesel_hmac",
            "payroll_person_data.account_hmac",
            "payroll_list_lines.payee_hmac",
        ):
            assert _rotated(report, column) == 1, (column, report["columns"][column])
        assert _rotated(report, "payroll_payments.counterparty_hmac") == 1
        assert report["previous_only"] == 0
        assert report["conflicts"] == 0
        assert report["ready_to_drop_previous"] is True
        json.dumps(report)  # same liczby — da się wypisać bez obiektów i wartości

        async with AsyncSessionLocal() as db:
            connection = await db.get(M365Connection, s.connection_id)
            assert new_only.decrypt(connection.access_token_ct) == "access-token"
            assert new_only.decrypt(connection.refresh_token_ct) == "refresh-token"
            with pytest.raises(TokenCipherNotConfigured):
                old.decrypt(connection.access_token_ct)
            broken = await db.get(M365Connection, s.unreadable_connection_id)
            assert broken.access_token_ct == s.unreadable_ct
            invite = await db.get(CandidateInviteLink, s.invite_token)
            assert new_only.decrypt(invite.token_ct) == "invite-secret"
            billing = await db.get(EmployeeBillingDetails, s.billing_id)
            assert new_only.decrypt(billing.account_encrypted) == ACCOUNT
            person = await db.get(PayrollPersonData, s.person_id)
            data = json.loads(new_only.decrypt(person.data_encrypted))
            assert data == {"bank_account": ACCOUNT, "pesel": PESEL}
            assert person.pesel_hmac == _fp(new_only, PESEL_PURPOSE, PESEL)
            assert person.account_hmac == _fp(
                new_only, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT
            )
            payment = await db.get(PayrollPayment, s.payment_id)
            assert payment.counterparty_hmac == _fp(
                new_only, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT
            )
            changed = await db.get(PayrollPayment, s.changed_payment_id)
            assert changed.counterparty_hmac == s.changed_payment_hmac
            line = await db.get(PayrollListLine, s.line_id)
            assert line.payee_hmac == _fp(
                new_only, ACCOUNT_FINGERPRINT_PURPOSE, ACCOUNT
            )

        again = await rotate.run(AsyncSessionLocal, rotating, apply=True)
        assert all("rotated" not in counts for counts in again["columns"].values())
        assert again["ready_to_drop_previous"] is True
    finally:
        await _cleanup(s)


@pytest.mark.asyncio
async def test_pesel_conflict_is_counted_and_blocks_dropping_the_old_key() -> None:
    """Ten sam PESEL u dwóch osób, jeden skrót już bieżącym kluczem: przeliczenie
    drugiego łamie unikalność — liczba w raporcie zamiast wyjątku, a poprzedni
    klucz zostaje (bez niego skrót przestałby pasować)."""

    old_key, new_key = _key(), _key()
    old = TokenCipher(old_key)
    rotating = TokenCipher(new_key, [old_key])
    number = _pesel(4321)
    user_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        first = await fx.make_user(db, "recruiter")
        second = await fx.make_user(db, "recruiter")
        user_ids = [first.id, second.id]
        for user, cipher in ((first, rotating), (second, old)):
            db.add(
                PayrollPersonData(
                    user_id=user.id,
                    data_encrypted=cipher.encrypt(json.dumps({"pesel": number})),
                    pesel_hmac=_fp(cipher, PESEL_PURPOSE, number),
                    pesel_last4=number[-4:],
                    missing=[],
                )
            )
        await db.commit()
    try:
        report = await rotate.run(AsyncSessionLocal, rotating, apply=True)

        assert report["columns"]["payroll_person_data.pesel_hmac"]["conflict"] == 1
        assert report["conflicts"] == 1
        assert report["previous_only"] == 1
        assert report["ready_to_drop_previous"] is False
        async with AsyncSessionLocal() as db:
            rows = {
                row.user_id: row
                for row in await db.scalars(
                    select(PayrollPersonData).where(
                        PayrollPersonData.user_id.in_(user_ids)
                    )
                )
            }
        # Treść przeszyfrowana, skrót drugiej osoby został przy poprzednim kluczu.
        assert rotating.key_index(rows[second.id].data_encrypted) == 0
        assert rows[second.id].pesel_hmac == _fp(old, PESEL_PURPOSE, number)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollPersonData).where(PayrollPersonData.user_id.in_(user_ids))
            )
            await db.commit()


@pytest.mark.asyncio
async def test_without_previous_key_nothing_is_ready_to_drop() -> None:
    """Brak poprzedniego klucza = nic do przeszyfrowania, ale też nie wolno
    ogłosić gotowości: stare wiersze byłyby po prostu nieczytelne."""

    report = await rotate.run(AsyncSessionLocal, TokenCipher(_key()), apply=False)
    assert report["previous_keys"] == 0
    assert report["previous_only"] == 0
    assert report["ready_to_drop_previous"] is False
