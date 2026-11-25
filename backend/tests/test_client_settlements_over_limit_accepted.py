"""MD ponad dni robocze i faktura KSeF w wątku Time Sheet. Dane fikcyjne.

Próba rozliczeń IX–X 2026 na kopii produkcji: MD zgodne z fakturą Finansów, a
rozliczenie czekało na człowieka.

* Osoba z 182 h przy 22 dniach roboczych (22,75 MD). Klient podpisał arkusz
  zbiorczy z tą liczbą, a ``fields.md_month_limit`` dawał „22,75 MD przy 22 dniach
  roboczych”. Akceptacja klienta tej liczby (podpis klienta albo mail z domeny
  klienta z liczbą równą dowodowi) zdejmuje uwagę. Mniejsza liczba, podpis samej
  osoby, inna domena i MD u innych klientów zostawiają ją.
* Konsultant wysłał fakturę z KSeF w wątku „TS …” („Wystawione”), więc plik miał
  rodzaj „raport”. Był najnowszy, ``_pick_report`` brał go za RCP i rozliczenie
  stało na „Nie rozpoznano szablonu RCP”, choć podpisany RCP leżał obok.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.client_settlements import mail_text, rcp_checks, service
from app.services.client_settlements.timesheet_pko import month_limit
from tests.test_client_settlements_pko_velo import _plain_pdf

MONTH = "2026-10"
LIMIT = "fields.md_month_limit"
CLIENT = frozenset({"klient.example"})
OURS = frozenset({"firma.example"})
SENDERS = mail_text.Senders(client=CLIENT, own=OURS)


def _rules(level: str = "warn") -> dict:
    return {LIMIT: {"level": level, "params": {}}}


def _proof(md: str = "22.75", *, level: str = "warn", other: Decimal = Decimal("0")):
    proof = rcp_checks.ProofResult(md_regular=Decimal(md), md_extra=None)
    group = rcp_checks._Group(proof, _rules(level), "Pola i sumy")
    month_limit(group, Decimal(md), 22, other)
    group.close()
    return proof


def _signed(md: str = "22.75", *, by_client: bool = True) -> SimpleNamespace:
    marker = {
        "kind": "sheet",
        "document_id": 1,
        "signer": "Kierownik Testowy",
        "signed_at": "2026-11-10T12:00:00+01:00",
        "complete": True,
        "md": md,
        "by_client": by_client,
    }
    return SimpleNamespace(checks=[{"signed": marker}])


def _limit_check(proof: rcp_checks.ProofResult) -> dict:
    return next(
        c
        for g in proof.groups
        for c in g["checks"]
        if "dniach roboczych" in c["title"]
    )


def test_podpis_klienta_z_ta_liczba_zdejmuje_uwage() -> None:
    proof = _proof()
    assert proof.warn and _limit_check(proof)["state"] == "warn"  # tak było

    after = service._over_limit_accepted(proof, _signed(), Decimal("0"))

    check = _limit_check(after)
    assert check["state"] == "ok"
    assert check["title"] == "22,75 MD przy 22 dniach roboczych, zaakceptowane przez klienta"
    assert check["detail"] == "Podpis klienta obejmuje 22,75 MD."
    assert "rule" not in check
    assert not after.warn and not after.blocking


def test_mail_klienta_z_ta_liczba_zdejmuje_uwage() -> None:
    proof = _proof()
    proof.client_count = "Mail klienta z tą liczbą (Akceptacja: 182 h za październik 2026)."

    after = service._over_limit_accepted(proof, SimpleNamespace(checks=[]), Decimal("0"))

    assert _limit_check(after)["state"] == "ok"
    assert not after.warn


def test_bez_akceptacji_uwaga_zostaje() -> None:
    after = service._over_limit_accepted(
        _proof(), SimpleNamespace(checks=[]), Decimal("0")
    )

    assert _limit_check(after)["state"] == "warn"
    assert _limit_check(after)["rule"] == LIMIT
    assert after.warn


def test_akceptacja_mniejszej_liczby_nie_obejmuje_md() -> None:
    after = service._over_limit_accepted(_proof(), _signed("22"), Decimal("0"))

    assert _limit_check(after)["state"] == "warn"
    assert after.warn


def test_arkusz_od_samej_osoby_nie_zdejmuje_uwagi() -> None:
    after = service._over_limit_accepted(
        _proof(), _signed(by_client=False), Decimal("0")
    )

    assert _limit_check(after)["state"] == "warn"
    assert after.warn


def test_md_u_innych_klientow_zostaja_do_wyjasnienia_z_osoba() -> None:
    # 12 MD tu i 12 MD u innego klienta przy 22 dniach: podpis klienta obejmuje
    # tylko jego część, a sprawa idzie do wyjaśnienia z osobą (decyzja Artura).
    proof = _proof("12", other=Decimal("12"))
    after = service._over_limit_accepted(proof, _signed("12"), Decimal("12"))

    assert _limit_check(after)["state"] == "warn"
    assert after.warn


def test_inne_uwagi_zostaja() -> None:
    proof = _proof()
    other = rcp_checks._Group(proof, _rules(), "Arkusz zbiorczy")
    other.warn("W arkuszu 22,75 MD, w Time Sheet 22,5 MD")
    other.close()

    after = service._over_limit_accepted(proof, _signed(), Decimal("0"))

    assert _limit_check(after)["state"] == "ok"
    assert after.warn


def test_poziom_blokuje_tez_zdjety_akceptacja_klienta() -> None:
    proof = _proof(level="block")
    assert proof.blocking  # tak było

    after = service._over_limit_accepted(proof, _signed(), Decimal("0"))

    assert not after.blocking and not after.warn


def _mail(sender: str, body: str) -> mail_text.Mail:
    return mail_text.Mail(subject="Time Sheet październik 2026", sender=sender, body=body)


def _judge(mail: mail_text.Mail, **kw) -> mail_text.Verdict:
    args = {"month": MONTH, "hours": Decimal("182"), "md": None, "senders": SENDERS}
    args.update(kw)
    return mail_text.judge([mail], **args)


def test_mail_z_domeny_klienta_z_liczba_obejmuje_liczbe() -> None:
    verdict = _judge(
        _mail("Kierownik <kierownik@klient.example>", "Akceptuję 182 h za październik 2026.")
    )

    assert verdict.ok and verdict.counted


def test_mail_z_innej_domeny_nie_jest_akceptacja_liczby() -> None:
    verdict = _judge(
        _mail("Kierownik <kierownik@inna.example>", "Akceptuję 182 h za październik 2026.")
    )

    assert not verdict.ok and not verdict.counted


def test_akceptuje_bez_liczby_nie_obejmuje_liczby() -> None:
    verdict = _judge(
        _mail("Kierownik <kierownik@klient.example>", "Akceptuję."), sheet_month=MONTH
    )

    assert verdict.ok and not verdict.counted


def test_akceptacja_innej_liczby_nie_przechodzi() -> None:
    verdict = _judge(
        _mail("Kierownik <kierownik@klient.example>", "Akceptuję 176 h za październik 2026.")
    )

    assert not verdict.ok and not verdict.counted


@pytest.fixture
def _storage(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    return tmp_path


def _doc(storage, name: str, content: bytes) -> SimpleNamespace:
    from app.services.consultant_portal.documents import SUBDIR

    (storage / SUBDIR).mkdir(exist_ok=True)
    (storage / SUBDIR / name).write_bytes(content)
    return SimpleNamespace(mime="application/pdf", file_path=f"{SUBDIR}/{name}")


def test_faktura_ksef_w_watku_time_sheet_to_nie_rcp(_storage) -> None:
    invoice = _doc(
        _storage,
        "faktura.pdf",
        _plain_pdf(
            [
                "Krajowy System e-Faktur",
                "Numer Faktury: 7/2026",
                "Numer KSeF: 1234567890-20261002-ABCDEF000000-12",
                "Uslugi informatyczne 10 000,00",
            ]
        ),
    )
    rcp = _doc(
        _storage,
        "rcp.pdf",
        _plain_pdf(["Rozliczenie czasu pracy", "Faktura dotyczy uslug za 2026-10"]),
    )

    assert service._not_report(invoice)
    assert not service._not_report(rcp)
