"""Projekt FIX: godziny podwykonawcy akceptuje PM firmy jako koszt. Bez bazy.

Przegląd skrzynek z 23.11.2026 (Pekao PeoPay, PAGW, SGB): klient odbiera
produkt protokołem, a nie godziny. Godziny podwykonawcy są kosztem firmy
i akceptuje je nasz PM. Decyzja Artura z 24.11.2026: kontrakt ma model
rozliczeń ``fixed`` („FIX / produkt”), a akceptacją jest słowo akceptacji
w mailu z domeny firmy. Limit MD na etap to zamówienie MD etapu.
Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.models.contract import EngagementModel
from app.services.client_settlements import mail_text, rules_catalog, timesheet
from tests.test_client_settlements_timesheet import _row, _sheet

ROOT = Path(__file__).resolve().parents[1]
COMPANY = frozenset({"firma.example"})
FIX = mail_text.Senders(client=COMPANY, own=frozenset(), who="PM-a firmy")


def _mail(sender: str, body: str, subject: str = "RE: ts") -> mail_text.Mail:
    return mail_text.Mail(subject=subject, sender=sender, body=body)


PM_REPLY = _mail(
    "Kierownik Projektu <pm@firma.example>",
    "Akceptuje rozliczenie.\n\n"
    "From: Podwykonawca <tester@gmail.com>\n"
    "Sent: Monday, November 23, 2026 3:12 PM\n"
    "Prośba o akcept.\n",
)
TESTER_ONLY = _mail("Podwykonawca <tester@gmail.com>", "Prośba o akcept.", "ts")


def test_model_fix_jest_w_enumie_migracji_i_entrypoincie() -> None:
    assert EngagementModel("fixed") is EngagementModel.fixed
    statement = "ALTER TYPE engagementmodel ADD VALUE IF NOT EXISTS 'fixed'"
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    block = entry[entry.index("_ENUM_STATEMENTS = [") :]
    assert f'"{statement}"' in block[: block.index("\n]")]
    migration = ROOT / "alembic/versions/0767_contract_engagement_fixed.py"
    assert statement in migration.read_text(encoding="utf-8")


def test_akceptacja_pma_firmy_to_dowod_kosztu() -> None:
    assert mail_text.approved([PM_REPLY], FIX) is True
    # Sam podwykonawca prosi o akceptację: nikt z firmy nie zaakceptował.
    assert mail_text.approved([TESTER_ONLY], FIX) is False
    # Nasz mail bez słowa akceptacji też nie wystarcza.
    plain = _mail("Kierownik Projektu <pm@firma.example>", "Przesyłam TS.")
    assert mail_text.approved([plain], FIX) is False


def test_akceptuje_bez_liczby_z_godzinami_z_ts_przy_fix() -> None:
    verdict = mail_text.judge(
        [PM_REPLY],
        month="2026-11",
        hours=Decimal("64"),
        md=None,
        senders=FIX,
        sheet_month="2026-11",
    )
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja bez liczby, godziny z TS"


def test_brak_akceptacji_pma_nazywa_akceptujacego() -> None:
    verdict = mail_text.judge(
        [TESTER_ONLY],
        month="2026-11",
        hours=Decimal("64"),
        md=None,
        senders=FIX,
        sheet_month="2026-11",
    )
    assert not verdict.ok
    parsed = timesheet.parse_rows([_sheet([_row(3, 8)])])
    result = timesheet.evaluate(
        parsed,
        month="2026-11",
        person_name="Jan Testowy",
        has_mail=True,
        rules=rules_catalog.effective({}),
        working_days=20,
        client_mail=False,
        acceptor=FIX.who,
    )
    titles = {c["title"]: c["state"] for g in result.groups for c in g["checks"]}
    assert titles["Brak akceptacji PM-a firmy"] == "warn"
    assert "Brak akceptacji klienta" not in titles
