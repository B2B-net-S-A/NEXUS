"""MD z prośby o akceptację, którą klient zaakceptował w wątku (``accepted_request``).

Bez bazy. Osoby, adresy i liczby fikcyjne. Dwa wzory z próby IX–X 2026:

* konsultant ze skrzynki w domenie klienta prosi kierownika „prośba o akcept TS
  za 10-2026 176h”, kierownik odpisuje „akceptuję”, konsultant przekazuje wątek
  na rozliczenia@ (wzór ERSTE za X);
* nasza koordynatorka prosi „o akceptację czasu za wrzesień dla … - 176h”,
  a kierownik odpisuje „Akceptuję” (wzór BIK).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from email.message import EmailMessage

import pytest

from app.models.consultant_portal import CpDocument
from app.services import storage_service
from app.services.client_settlements import (
    accepted_request,
    mail_text,
    rules_catalog,
    service,
)

EML = mail_text.EML
OCTOBER = "2026-10"
SEPTEMBER = "2026-09"
PERSON = "Jan Testowy"
CONSULTANT = "jan.testowy@klient.example"
MANAGER = "Kierownik Klienta <kierownik@klient.example>"
SENDERS = mail_text.Senders(
    client=frozenset({"klient.example"}),
    own=frozenset({"firma.example"}),
    consultant=frozenset({CONSULTANT}),
)
FOOTER = (
    "Firma Testowa S.A. Dane osobowe przetwarzane zgodnie z Rozporządzeniem (UE) "
    "2016/679 z dnia 27 kwietnia 2016 roku (RODO)."
)


def _eml(subject: str, sender: str, body: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "rozliczenia@firma.example"
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


def _consultant_thread(
    *, reply: str = "akceptuję", request: str = "prośba o akcept TS za 10-2026\n176h"
) -> bytes:
    """Wzór ERSTE: konsultant przekazuje odpowiedź kierownika na swoją prośbę."""

    return _eml(
        "PD: akcept rozliczenia",
        f"Jan Testowy <{CONSULTANT}>",
        "Podsyłam akcept TS, FV w KSeF\nJan Testowy\n"
        "________________________________\n"
        f"Od: {MANAGER}\n"
        "Wysłane: środa, 4 listopada 2026 09:14\n"
        f"Do: Jan Testowy <{CONSULTANT}>\n"
        "Temat: RE: akcept rozliczenia\n"
        f"{reply}\nPozdrawiam,\nKierownik Klienta\n"
        f"From: Jan Testowy <{CONSULTANT}>\n"
        "Sent: Wednesday, November 4, 2026 8:17 AM\n"
        f"To: {MANAGER}\n"
        "Subject: akcept rozliczenia\n"
        f"Hej, {request}\nTS w załączniku\nJan Testowy\n",
    )


def _coordinator_thread(
    *,
    reply: str = "Akceptuję",
    person: str = "Jan Testowy",
    request: str = "Proszę o akceptację czasu za wrzesień dla Jana Testowego - 176h.",
    sender: str = MANAGER,
) -> bytes:
    """Wzór BIK: odpowiedź kierownika na prośbę z rozliczenia@."""

    return _eml(
        f"RE: Akceptacja wrzesień 2026 - {person}",
        sender,
        f"{reply}\nKierownik Klienta\n\n"
        "From: rozliczenia@firma.example <rozliczenia@firma.example>\n"
        "Sent: Monday, October 5, 2026 12:17 PM\n"
        f"To: {MANAGER}\n"
        f"Subject: Akceptacja wrzesień 2026 - {person}\n\n"
        f"Dzień dobry,\n{request}\n\nPozdrawiam,\nKoordynatorka Rozliczeń\n{FOOTER}\n",
    )


def _find(content: bytes, month: str = OCTOBER, *, person: str = PERSON):
    mail = mail_text.read(content, EML)
    assert mail is not None
    return accepted_request.find(mail, month=month, person_name=person, senders=SENDERS)


# ── Czytnik ──────────────────────────────────────────────────────────────────


def test_prosba_konsultanta_zaakceptowana_przez_kierownika():
    found = _find(_consultant_thread())
    assert found is not None
    assert (found.hours, found.md, found.month) == (Decimal("176"), None, OCTOBER)
    assert found.acceptor == "kierownik@klient.example"
    assert found.requester == CONSULTANT
    assert found.quote == "akceptuję"


def test_prosba_koordynatorki_z_osoba_w_temacie_i_stopka_rodo():
    found = _find(_coordinator_thread(), SEPTEMBER)
    assert found is not None
    # „kwietnia 2016” ze stopki nie jest drugim miesiącem prośby.
    assert (found.hours, found.month) == (Decimal("176"), SEPTEMBER)
    assert found.requester == "rozliczenia@firma.example"


def test_liczba_w_samej_akceptacji():
    found = _find(_coordinator_thread(reply="Akceptuję 22 MD za wrzesień."), SEPTEMBER)
    assert found is not None
    assert (found.hours, found.md) == (None, Decimal("22"))


def test_prosba_za_inny_miesiac_daje_jej_miesiac():
    found = _find(_consultant_thread(request="prośba o akcept TS za 09-2026\n176h"))
    assert found is not None and found.month == SEPTEMBER


# ── Ścieżki odmowy ───────────────────────────────────────────────────────────


def test_bez_akceptacji_klienta_nic():
    # Próba IX–X 2026: klient odpisał na przypomnienie prośbą o fakturę w PDF.
    assert (
        _find(
            _coordinator_thread(reply="Prosimy o przesyłanie również faktury w PDF."),
            SEPTEMBER,
        )
        is None
    )


def test_akceptacja_z_naszego_adresu_to_nie_klient():
    content = _coordinator_thread(
        sender="Koordynatorka <rozliczenia@firma.example>", reply="Potwierdzam"
    )
    assert _find(content, SEPTEMBER) is None


def test_odmowa_klienta_nic():
    content = _coordinator_thread(reply="Nie akceptuję, w tym miesiącu był urlop.")
    assert _find(content, SEPTEMBER) is None


def test_konsultant_sam_akceptuje_ze_swojej_skrzynki():
    content = _eml(
        "akcept rozliczenia",
        f"Jan Testowy <{CONSULTANT}>",
        "Akceptuję, za 10-2026 176h.\nJan Testowy\n",
    )
    assert _find(content) is None


def test_dwie_rozne_sumy_w_prosbie():
    content = _consultant_thread(request="prośba o akcept TS za 10-2026\n176h, 168h")
    assert _find(content) is None


def test_godziny_i_md_naraz_to_nie_jedna_suma():
    content = _consultant_thread(request="prośba o akcept za 10-2026: 176h (22 MD)")
    assert _find(content) is None


def test_suma_dla_innej_osoby_w_watku():
    content = _coordinator_thread(
        person="Anna Inna",
        request="Proszę o akceptację czasu za wrzesień dla Anny Innej - 176h.",
    )
    assert _find(content, SEPTEMBER) is None


def test_nowsza_wiadomosc_z_inna_liczba_po_akceptacji():
    content = _eml(
        "RE: RE: Akceptacja wrzesień 2026 - Jan Testowy",
        "Koordynatorka <rozliczenia@firma.example>",
        "Korekta: po poprawce TS jest 168h.\n\n"
        f"From: {MANAGER}\nSent: Tuesday, October 6, 2026 9:00 AM\n"
        "Subject: RE: Akceptacja wrzesień 2026 - Jan Testowy\n\nAkceptuję\n\n"
        "From: rozliczenia@firma.example <rozliczenia@firma.example>\n"
        "Sent: Monday, October 5, 2026 12:17 PM\n"
        "Subject: Akceptacja wrzesień 2026 - Jan Testowy\n\n"
        "Proszę o akceptację czasu za wrzesień dla Jana Testowego - 176h.\n",
    )
    assert _find(content, SEPTEMBER) is None


def test_starsza_prosba_glebiej_w_watku_sie_nie_liczy():
    # Klient odpisał na wiadomość bez liczby; liczba stoi dopiero w starszej.
    content = _eml(
        "RE: Akceptacja wrzesień 2026 - Jan Testowy",
        MANAGER,
        "Akceptuję\n\n"
        "From: rozliczenia@firma.example <rozliczenia@firma.example>\n"
        "Subject: Akceptacja wrzesień 2026 - Jan Testowy\n\nPrzypominam o akceptacji.\n\n"
        "From: rozliczenia@firma.example <rozliczenia@firma.example>\n"
        "Subject: Akceptacja wrzesień 2026 - Jan Testowy\n\n"
        "Proszę o akceptację czasu za wrzesień dla Jana Testowego - 176h.\n",
    )
    assert _find(content, SEPTEMBER) is None


# ── Rozliczenie: MD z prośby i kontrole ──────────────────────────────────────


def _rules(**levels: str) -> dict:
    rules = rules_catalog.effective({})
    for key, level in levels.items():
        rules[key.replace("__", ".")]["level"] = level
    return rules


def _proof(tmp_path, monkeypatch, contents: list[bytes], month: str = OCTOBER, **kw):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True)
    docs = []
    for index, content in enumerate(contents, start=1):
        (folder / f"{index}.eml").write_bytes(content)
        docs.append(
            CpDocument(
                id=index,
                mime=EML,
                kind="report",
                file_path=f"consultant_portal/1/{index}.eml",
                period_guessed=True,
            )
        )
    rules = kw.pop("rules", None) or _rules()
    return asyncio.run(
        service._request_proof(
            docs,
            month=month,
            person_name=PERSON,
            rules=rules,
            senders=kw.pop("senders", SENDERS),
            proof_senders=SENDERS,
            other_md=Decimal("0"),
        )
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def test_md_z_prosby_z_kontrolami(tmp_path, monkeypatch):
    found = _proof(tmp_path, monkeypatch, [_consultant_thread()])
    assert found is not None
    doc, result = found
    assert doc.id == 1
    assert result.md_regular == Decimal("22.000")
    titles = _titles(result)
    assert titles["Miesiąc z dokumentu: październik 2026"] == "ok"
    assert titles["Klient zaakceptował prośbę: 176 h"] == "ok"
    assert not result.blocking


def test_prosba_za_inny_miesiac_bez_md(tmp_path, monkeypatch):
    content = _consultant_thread(request="prośba o akcept TS za 09-2026\n176h")
    assert _proof(tmp_path, monkeypatch, [content]) is None


def test_dwa_maile_miesiaca_z_roznymi_sumami_bez_md(tmp_path, monkeypatch):
    other = _consultant_thread(request="prośba o akcept TS za 10-2026\n168h")
    assert _proof(tmp_path, monkeypatch, [_consultant_thread(), other]) is None


def test_bez_znanych_domen_klienta_bez_md(tmp_path, monkeypatch):
    senders = mail_text.Senders(own=frozenset({"firma.example"}))
    assert (
        _proof(tmp_path, monkeypatch, [_consultant_thread()], senders=senders) is None
    )


@pytest.mark.parametrize(
    ("mimes", "expected"),
    [
        ((EML,), True),
        ((EML, "image/png"), True),
        ((EML, "application/pdf"), False),
        (
            (EML, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            False,
        ),
        (("image/png",), False),
    ],
)
def test_tylko_maile_bez_pliku_godzin(mimes, expected):
    docs = [CpDocument(id=i, mime=m) for i, m in enumerate(mimes)]
    assert service._mails_only(docs) is expected
