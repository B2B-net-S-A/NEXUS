"""Orlen i Centrum e-Zdrowia po przeglądzie skrzynek Finansów (23.11.2026). Bez bazy.

* Orlen Upstream pisze z ``pgnig.pl``: domena należy do Orlenu w rejestrze domen.
* ``cl.protocol_amount``: kwota do faktury równa kwocie netto z protokołu klienta;
  finanse Orlenu odesłały fakturę za X, która różniła się od protokołu.
* ``cl.copyright_statement``: miesięczne oświadczenie o przeniesieniu autorskich
  praw majątkowych (CeZ), z okresem miesiąca i podpisem po jego końcu.
Osoby, kwoty i dokumenty fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal as D

from app.services.client_settlements import copyright_statement, rules_catalog
from app.services.client_settlements.declared import Declared, evaluate
from app.services.client_settlements.engine import Inputs, OrderState, compute
from app.services.order_policies import known_clients

FIRST, LAST = date(2026, 10, 1), date(2026, 10, 31)


def test_pgnig_to_domena_orlenu():
    assert known_clients.KNOWN_SENDER_DOMAINS["pgnig.pl"] == "orlen"
    assert known_clients.KNOWN_SENDER_DOMAINS["orlen.pl"] == "orlen"
    assert known_clients.KNOWN_REGISTRY_IDS["orlen"]


# ── Kwota z protokołu ────────────────────────────────────────────────────────


def _rules(level: str) -> dict:
    return rules_catalog.effective(
        {"cl.protocol_amount": {"level": level, "params": {}}}
    )


def _result(level: str, amount: str, rate: str = "1000"):
    rules = _rules(level)
    proof = evaluate(
        Declared(
            source="Protokół Orlen",
            consultant="Anna Nowak",
            month="2026-10",
            hours=D("120"),
            amount=D(amount),
        ),
        month="2026-10",
        person_name="Anna Nowak",
        rules=rules,
        working_days=22,
    )
    order = OrderState(
        order_id=1,
        number="PO_1",
        md_total=D("100"),
        md_available=D("100"),
        rate_cost=D("800"),
        rate_revenue=D(rate),
    )
    return compute(
        Inputs(
            md_regular=proof.md_regular,
            md_extra=None,
            rules=rules,
            order=order,
            has_report=True,
            proof=proof,
        )
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.checks for c in g["checks"]}


def test_kwota_do_faktury_inna_niz_w_protokole_to_uwaga():
    # 120 h = 15 MD × 1000 zł = 15 000 zł do faktury, protokół mówi 15 400 zł.
    result = _result("warn", "15400")
    assert result.amount_revenue == D("15000.00")
    assert _titles(result)["Kwota do faktury inna niż w protokole klienta"] == "warn"
    assert result.status == "warnings"


def test_kwota_jak_w_protokole_przechodzi():
    result = _result("warn", "15000")
    assert _titles(result)["Do faktury 15000 zł jak w protokole"] == "ok"
    assert result.status == "ok"


def test_regula_wylaczona_nic_nie_porownuje():
    result = _result("off", "15400")
    assert "Kwota do faktury inna niż w protokole klienta" not in _titles(result)
    assert result.status == "ok"


# ── Oświadczenie o prawach autorskich (CeZ) ──────────────────────────────────


STATEMENT = """OŚWIADCZENIE
o przeniesieniu autorskich praw majątkowych
do umowy wykonawczej nr CeZ/1/2026 z dnia 12.03.2026
Oświadczam, że z chwilą odbioru przenoszę na Zamawiającego autorskie prawa
majątkowe do utworów wytworzonych w okresie od 01.10.2026 do 31.10.2026.
Warszawa, dnia 03.11.2026
"""


def _judge(text: str, signed_at=()) -> list[str]:
    return [
        f.title
        for f in copyright_statement.judge(
            copyright_statement.parse(text), first=FIRST, last=LAST, signed_at=signed_at
        )
    ]


def test_rozpoznanie_po_nazwie_albo_tresci():
    assert copyright_statement.is_statement(
        "Oswiadczenie_prawa_autorskie_10_2026.pdf", ""
    )
    assert copyright_statement.is_statement("skan.pdf", STATEMENT)
    assert not copyright_statement.is_statement(
        "Oświadczenie o rozwiązaniu umowy.pdf", "Rozwiązuję umowę z dniem 31.10.2026."
    )
    assert not copyright_statement.is_statement("Protokół odbioru X.pdf", "Protokół")


def test_poprawne_oswiadczenie():
    assert _judge(STATEMENT) == ["Oświadczenie o prawach autorskich za miesiąc"]


def test_podpis_przed_koncem_miesiaca():
    text = STATEMENT.replace("dnia 03.11.2026", "dnia 30.10.2026")
    assert _judge(text) == ["Oświadczenie podpisane przed końcem miesiąca"]
    # Podpis elektroniczny wygrywa z datą w treści.
    early = [datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)]
    assert _judge(STATEMENT, early) == ["Oświadczenie podpisane przed końcem miesiąca"]


def test_zly_okres_i_naglowek_wzor():
    text = "Wzór\n" + STATEMENT.replace(
        "od 01.10.2026 do 31.10.2026", "od 01.09.2026 do 30.09.2026"
    )
    assert _judge(text) == [
        "Oświadczenie za inny okres",
        "Oświadczenie z nagłówkiem „Wzór”",
    ]


def test_regula_w_katalogu_wylaczona_domyslnie():
    rules = rules_catalog.effective({})
    assert rules["cl.copyright_statement"]["level"] == "off"
    assert rules["cl.protocol_amount"]["level"] == "off"


async def test_regula_cez_w_przeliczeniu_czyta_plik_osoby(tmp_path, monkeypatch):
    """``service._copyright_checks``: oświadczenie w DOCX wśród plików miesiąca,
    a bez niego uwaga „Brak oświadczenia”."""

    import io

    import docx

    from app.models.consultant_portal import CpDocument
    from app.services.client_settlements import service
    from app.services.client_settlements.declared import DOCX

    document = docx.Document()
    for line in STATEMENT.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    (tmp_path / "o.docx").write_bytes(buffer.getvalue())
    monkeypatch.setattr(
        service.portal_documents, "path_for", lambda relative: tmp_path / relative
    )
    rules = rules_catalog.effective(
        {"cl.copyright_statement": {"level": "warn", "params": {}}}
    )
    statement = CpDocument(file_path="o.docx", file_name="skan.docx", mime=DOCX)

    proof = await service._copyright_checks(None, [statement], "2026-10", rules)
    assert proof is not None and not proof.warn
    assert proof.groups[0]["checks"][0]["title"] == (
        "Oświadczenie o prawach autorskich za miesiąc"
    )

    missing = await service._copyright_checks(None, [], "2026-10", rules)
    assert missing is not None and missing.warn
    assert missing.groups[0]["checks"][0]["title"] == (
        "Brak oświadczenia o prawach autorskich"
    )
    off = rules_catalog.effective({})
    assert await service._copyright_checks(None, [], "2026-10", off) is None
