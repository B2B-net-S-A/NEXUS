"""NIP kontraktora z faktur KSeF zapisuje się sam: reguła bez bazy.

Decyzja Artura z 25.11.2026 (``contractor_nip``). Osoby, NIP-y i numery są
fikcyjne. Zapis w ``consider`` i przebieg wstecz na bazie sprawdza
``test_contractor_nip_db.py``.
"""

from __future__ import annotations

from typing import Any

from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import contractor_nip as cn
from app.services.client_settlements.rcp_checks import name_tokens

NIP = "9990000011"
OTHER_NIP = "9990000022"
JAN, EWA, NAMESAKE = 101, 102, 103


def _person(candidate_id: int | None, name: str) -> cn.Person:
    return cn.Person(candidate_id, frozenset(name_tokens(name)))


PEOPLE = [
    _person(JAN, "Jan Testowy"),
    _person(EWA, "Ewa Próbna"),
    _person(None, "Ola Zespołowa"),  # konto zespołu
]


def _doc(month: str, name: str | None, source: str = cn.PURCHASE) -> cn.Document:
    return cn.Document(f"{source}-{month}-{name}", source, month, name)


def test_dwa_miesiace_faktur_jednej_osoby_to_dowod() -> None:
    docs = [_doc("2026-09", "JAN TESTOWY IT"), _doc("2026-10", "Testowy Jan Usługi")]
    assert cn.verdict(docs, PEOPLE) == (JAN, cn.PROVEN)


def test_jedna_faktura_albo_jeden_miesiac_nie_wystarcza() -> None:
    assert cn.verdict([_doc("2026-10", "Jan Testowy")], PEOPLE) == (
        JAN,
        cn.SINGLE_MONTH,
    )
    same_month = [_doc("2026-10", "Jan Testowy"), _doc("2026-10", "Jan Testowy IT")]
    assert cn.verdict(same_month, PEOPLE) == (JAN, cn.SINGLE_MONTH)


def test_zakup_i_benefit_zgodne_wystarcza_jedna_faktura_zakupowa() -> None:
    docs = [
        _doc("2026-10", "Jan Testowy"),
        _doc("2026-10", "Firma Usługowa Jan Testowy", cn.BENEFIT),
    ]
    assert cn.verdict(docs, PEOPLE) == (JAN, cn.PROVEN)


def test_same_faktury_benefit_bez_zakupu_nie_wystarczaja() -> None:
    docs = [
        _doc("2026-09", "Jan Testowy", cn.BENEFIT),
        _doc("2026-10", "Jan Testowy", cn.BENEFIT),
    ]
    assert cn.verdict(docs, PEOPLE) == (JAN, cn.BENEFIT_ONLY)


def test_imiennicy_z_kontraktem_albo_z_zespolu_wykluczaja() -> None:
    docs = [_doc("2026-09", "Jan Testowy"), _doc("2026-10", "Jan Testowy")]
    namesakes = [*PEOPLE, _person(NAMESAKE, "Jan Testowy")]
    assert cn.verdict(docs, namesakes) == (None, cn.SEVERAL_PEOPLE)

    staff = [_doc("2026-09", "Ola Zespołowa"), _doc("2026-10", "Ola Zespołowa")]
    assert cn.verdict(staff, PEOPLE) == (None, cn.NOT_CONTRACTOR)
    staff_namesake = [*PEOPLE, _person(NAMESAKE, "Ola Zespołowa")]
    assert cn.verdict(staff, staff_namesake) == (None, cn.SEVERAL_PEOPLE)


def test_dwie_osoby_w_nazwie_sprzedawcy_wykluczaja() -> None:
    docs = [
        _doc("2026-09", "Jan Testowy i Ewa Próbna s.c."),
        _doc("2026-10", "Jan Testowy i Ewa Próbna s.c."),
    ]
    assert cn.verdict(docs, PEOPLE) == (None, cn.SEVERAL_PEOPLE)


def test_fundacja_bez_osoby_w_nazwie_nic_nie_daje() -> None:
    docs = [
        _doc("2026-09", "Fundacja Przykładowy Start"),
        _doc("2026-10", "Fundacja Przykładowy Start"),
        _doc("2026-10", None),
    ]
    assert cn.verdict(docs, PEOPLE) == (None, cn.NO_PERSON)


def test_inkubator_z_jedna_faktura_z_nazwiskiem_nie_jest_nip_em_osoby() -> None:
    """NIP wspólny: osoba w nazwie jednej faktury nie przejmuje NIP-u fundacji."""

    docs = [
        _doc("2026-08", "Fundacja Przykładowy Start"),
        _doc("2026-09", "Fundacja Przykładowy Start Jan Testowy"),
        _doc("2026-10", "Fundacja Przykładowy Start Jan Testowy"),
    ]
    assert cn.verdict(docs, PEOPLE) == (None, cn.UNNAMED)


def test_benefit_z_inna_osoba_niz_zakupy_wyklucza() -> None:
    docs = [
        _doc("2026-09", "Jan Testowy"),
        _doc("2026-10", "Jan Testowy"),
        _doc("2026-10", "Ewa Próbna", cn.BENEFIT),
    ]
    assert cn.verdict(docs, PEOPLE) == (None, cn.SEVERAL_PEOPLE)


def _registry(**values: Any) -> cn.Registry:
    registry = cn.Registry(people=PEOPLE, candidate_of={501: JAN, 502: EWA})
    for candidate_id, nip in values.get("owned", ()):
        registry.note(candidate_id, nip)
    return registry


def test_warunki_osoby_i_nip_u() -> None:
    current = {JAN, EWA}

    def check(registry: cn.Registry, **kw: Any) -> str:
        return cn.check(
            registry,
            NIP,
            JAN,
            current=kw.get("current", current),
            rejected=kw.get("rejected", set()),
        )

    assert check(_registry()) == cn.PROVEN
    # NIP innego kandydata, osoby z Płac albo umowy bez osoby.
    assert check(_registry(owned=[(EWA, NIP)])) == cn.TAKEN
    assert check(_registry(owned=[(None, NIP)])) == cn.TAKEN
    # Ten sam NIP w partner_nip umowy tej osoby nie przeszkadza.
    assert check(_registry(owned=[(JAN, NIP)])) == cn.PROVEN
    assert check(_registry(owned=[(JAN, OTHER_NIP)])) == cn.HAS_NIP
    assert check(_registry(), rejected={(NIP, 501)}) == cn.REJECTED
    assert check(_registry(), rejected={(NIP, 502), (OTHER_NIP, 501)}) == cn.PROVEN
    assert check(_registry(), current={EWA}) == cn.NOT_CONTRACTOR


def test_indeks_przebiegu_po_zapisie_wiaze_kolejne_faktury_nip_u() -> None:
    tokens = frozenset(name_tokens("Jan Testowy"))
    index = ci.ContractorIndex(
        without_nip=[
            ci.Contractor(501, JAN, tokens, None),
            ci.Contractor(503, JAN, tokens, None),
            ci.Contractor(502, EWA, frozenset(name_tokens("Ewa Próbna")), None),
        ]
    )
    cn._rebind(index, JAN, NIP)
    assert [p.contract_id for p in index.by_nip[NIP]] == [501, 503]
    assert {p.nip for p in index.by_nip[NIP]} == {NIP}
    assert [p.contract_id for p in index.without_nip] == [502]


def test_liczniki_planu() -> None:
    plan = cn.Plan(
        confirm={JAN: NIP},
        decisions={
            NIP: (JAN, cn.PROVEN),
            OTHER_NIP: (None, cn.NO_PERSON),
            "9990000033": (EWA, cn.SINGLE_MONTH),
        },
    )
    assert plan.counts() == {
        "nips": 3,
        "candidates": 1,
        "with_benefit": 0,
        "no_person": 1,
        "proven": 1,
        "single_month": 1,
    }


async def test_awaria_przebiegu_wstecz_nie_zatrzymuje_pobierania_z_ksef(
    monkeypatch,
) -> None:
    from app.services.hr.ksef import sync
    from app.tasks import hr_loops

    calls: list[str] = []

    async def broken(db: Any, **_: Any) -> None:
        calls.append("backfill")
        raise RuntimeError("fikcyjna awaria")

    async def fetched(db: Any) -> dict[str, Any]:
        calls.append("run_once")
        return {"status": "ok", "saved": 1}

    class Session:
        async def rollback(self) -> None:
            calls.append("rollback")

    monkeypatch.setattr(cn, "backfill_once", broken)
    monkeypatch.setattr(sync, "run_once", fetched)
    assert await hr_loops.ksef_fetch_job(Session()) == {"status": "ok", "saved": 1}
    assert calls == ["backfill", "rollback", "run_once"]
