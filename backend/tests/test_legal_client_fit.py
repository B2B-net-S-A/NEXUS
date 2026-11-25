"""Zgodność umów B2B z umową ramową klienta (asystent prawny G) — bez bazy.

Klauzule i umowy w tym pliku są fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.api import client_framework_contracts as fc_api
from app.api import legal_client_fit as api
from app.models.ai_feature import AIFeatureKey
from app.models.user import UserRole
from app.services.legal_client_fit import engine, service, sources, task_provider
from app.services.legal_client_fit.sources import ClientPassage, TemplatePassage
from tests.test_permissions_contracts_rules import _holder, _user

CLIENT_TEXT = (
    "§ 4\n1. Wykonawca zapewni, że jego personel, w tym personel podwykonawców, "
    "odbędzie coroczne szkolenie z bezpieczeństwa ICT wskazane przez Zamawiającego.\n"
    "2. Wykonawca zgłosi Zamawiającemu każdy incydent w ciągu 4 godzin od jego "
    "wykrycia.\n"
)
CLIENT = [
    ClientPassage(
        key="K1",
        source_kind="amendment",
        source_id=7,
        document_label="Aneks „Przykładowy aneks DORA”",
        text=CLIENT_TEXT,
        offset=0,
        topics=("ict_training", "incident_reporting"),
    )
]
OURS = [
    TemplatePassage(
        key="T1",
        ref="§ 8",
        text="Tajemnica\nPartner zachowa w poufności wszelkie informacje Klienta.",
    ),
    TemplatePassage(
        key="T2",
        ref="§ 9",
        text="Świadczenie Usług\nPartner niezwłocznie informuje B2BNET o zdarzeniach "
        "zakłócających świadczenie Usług.",
    ),
]
WHOLE = {("amendment", 7): CLIENT_TEXT}


def _reply(*findings: dict) -> str:
    return "Oto wynik:\n" + json.dumps({"findings": list(findings)}, ensure_ascii=False)


def _parse(reply: str, mapping: dict | None = None):
    return engine.parse_reply(
        reply, client=CLIENT, ours=OURS, mapping=mapping or {}, whole_texts=WHOLE
    )


GAP = {
    "topic": "ict_training",
    "state": "gap",
    "summary": "Klient wymaga szkoleń ICT, nasz wzór ich nie przewiduje.",
    "client": {
        "source": "K1",
        "quote": "odbędzie coroczne szkolenie z bezpieczeństwa ICT wskazane przez "
        "Zamawiającego",
    },
    "ours": None,
    "annex_text": "Partner zobowiązuje się do udziału w corocznym szkoleniu "
    "z bezpieczeństwa ICT wskazanym przez Klienta.",
}


# ── silnik: cytaty sprawdza kod ─────────────────────────────────────────────


def test_gap_with_verified_client_quote_is_kept_with_code_ref() -> None:
    findings, dropped = _parse(_reply(GAP))
    assert dropped == []
    [finding] = findings
    assert finding.state == "gap"
    assert finding.our_quote is None and finding.our_ref is None
    # Paragraf i ustęp liczy kod z układu dokumentu, nie model.
    assert finding.client_ref == "Aneks „Przykładowy aneks DORA”, § 4 ust. 1"
    assert finding.next_step and "aneksie" in finding.next_step
    assert finding.annex_text.startswith("Partner zobowiązuje się")


def test_finding_without_verified_client_quote_is_dropped() -> None:
    invented = {**GAP, "client": {"source": "K1", "quote": "szkolenie co pół roku"}}
    wrong_source = {**GAP, "client": {"source": "K9", "quote": GAP["client"]["quote"]}}
    findings, dropped = _parse(_reply(invented))
    assert findings == [] and dropped[0].topic == "ict_training"
    findings, dropped = _parse(_reply(wrong_source))
    assert findings == [] and len(dropped) == 1


def test_ok_or_decide_without_our_verified_quote_is_dropped() -> None:
    ok_without_ours = {**GAP, "state": "ok"}
    ok_with_invented = {
        **GAP,
        "state": "ok",
        "ours": {"source": "T1", "quote": "Partner odbywa szkolenia ICT"},
    }
    for item in (ok_without_ours, ok_with_invented):
        findings, dropped = _parse(_reply(item))
        assert findings == [], item
        assert len(dropped) == 1


def test_decide_with_both_quotes_verified() -> None:
    decide = {
        "topic": "incident_reporting",
        "state": "decide",
        "summary": "Klient: 4 godziny, my: niezwłocznie.",
        "client": {
            "source": "K1",
            "quote": "Wykonawca zgłosi Zamawiającemu każdy incydent w ciągu 4 godzin",
        },
        "ours": {
            "source": "T2",
            "quote": "Partner niezwłocznie informuje B2BNET o zdarzeniach",
        },
        "annex_text": "Partner zgłasza B2BNET każdy incydent w ciągu 4 godzin od "
        "jego wykrycia.",
    }
    [finding], dropped = _parse(_reply(decide))
    assert dropped == []
    assert finding.our_ref == "§ 9"
    assert finding.client_ref.endswith("§ 4 ust. 2")
    assert finding.annex_text and "4 godzin" in finding.annex_text


def test_annex_text_with_number_not_in_client_quote_is_withheld() -> None:
    item = {**GAP, "annex_text": "Partner odbywa szkolenie co 6 miesięcy."}
    [finding], _dropped = _parse(_reply(item))
    assert finding.annex_text is None


def test_unknown_topic_duplicate_topic_and_invented_marker() -> None:
    other = {**GAP, "topic": "kawa_w_biurze"}
    invented_marker = {**GAP, "annex_text": "Partner [OSOBA_9] odbywa szkolenie."}
    findings, dropped = _parse(_reply(GAP, GAP, other))
    assert [f.topic for f in findings] == ["ict_training"]
    assert len(dropped) == 2
    [finding], _ = _parse(_reply(invented_marker))
    assert finding.annex_text is None


def test_quote_with_inner_quotation_marks_is_checked_not_waved_through() -> None:
    text = "Wykonawca zapewni, że „Personel” odbędzie szkolenie."
    assert engine.quote_verified("zapewni, że „Personel” odbędzie", text, "client")
    assert not engine.quote_verified("zapewni, że „Kadra” odbędzie", text, "client")
    assert not engine.quote_verified("", text, "client")


def test_reply_that_is_not_json_is_a_failure_not_an_empty_result() -> None:
    findings, _ = _parse("Nie potrafię odpowiedzieć.")
    assert findings is None


def test_lawyer_threshold_on_contractual_penalty() -> None:
    text = CLIENT_TEXT + "3. Za każde naruszenie Wykonawca zapłaci karę umowną.\n"
    passage = [ClientPassage("K1", "amendment", 7, "Aneks", text, 0)]
    item = {**GAP, "client": {"source": "K1", "quote": "Wykonawca zapłaci karę umowną"}}
    [finding], _ = engine.parse_reply(
        _reply(item), client=passage, ours=OURS, mapping={}, whole_texts={}
    )
    assert "kara umowna" in finding.lawyer_review


def test_prompt_masks_people_and_unmask_restores_quotes() -> None:
    from app.services.legal.pseudonymize import Entity

    text = "Za Zamawiającego podpisuje Jan Przykładowy, jan.przyklad@example.com."
    passage = [ClientPassage("K1", "framework_contract", 3, "Umowa", text, 0)]
    prompt, mapping = engine.build_prompt(
        passage, OURS, [Entity("OSOBA", "Jan Przykładowy", inflect=True)]
    )
    assert "Jan Przykładowy" not in prompt
    assert "jan.przyklad@example.com" not in prompt
    item = {
        "topic": "audit_rights",
        "state": "gap",
        "summary": "x",
        "client": {"source": "K1", "quote": "podpisuje [OSOBA]"},
        "ours": None,
    }
    [finding], _ = engine.parse_reply(
        _reply(item), client=passage, ours=OURS, mapping=mapping, whole_texts={}
    )
    assert finding.client_quote == "podpisuje Jan Przykładowy"


async def test_without_model_key_the_check_is_unavailable(monkeypatch) -> None:
    from app.services import llm_providers

    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _model: False)
    outcome = await engine.compare(
        SimpleNamespace(), client=CLIENT, ours=OURS, entities=[], whole_texts=WHOLE
    )
    assert outcome.status == "unavailable"
    assert outcome.findings == []
    assert "niedostępne" in (outcome.message or "")


async def test_model_failure_is_failed_without_findings(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.services import ai_quota, llm_providers

    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _model: True)

    @asynccontextmanager
    async def _feature(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(ai_quota, "ai_feature", _feature)

    def _boom(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(engine, "_call_model", _boom)

    class _Db:
        async def commit(self):
            return None

    outcome = await engine.compare(
        _Db(), client=CLIENT, ours=OURS, entities=[], whole_texts=WHOLE
    )
    assert outcome.status == "failed" and outcome.findings == []


# ── nasz wzór ───────────────────────────────────────────────────────────────

FICTIONAL_TEMPLATE = """<h1>Umowa</h1>
<h2>nr {{ b2b.contract_number }}</h2>
<p>zawarta pomiędzy Spółką a {{ candidate.full_name }}</p>
<h2>§ 1</h2><p>Przedmiot</p><p>Partner świadczy usługi.</p>
<h2>§ 2</h2><p>Poufność</p><p>Partner zachowa poufność.</p>
<h2>Załącznik nr 1 – wzór</h2><p>Deklaracja</p>
<h2>ZAŁĄCZNIK NR 1 DO UMOWY</h2><p>Treść deklaracji {% if x %}tak{% endif %}.</p>
"""


def test_template_is_split_without_parties_and_jinja() -> None:
    passages = sources.template_passages(FICTIONAL_TEMPLATE)
    assert [p.ref for p in passages] == ["§ 1", "§ 2", "Załącznik nr 1"]
    joined = "\n".join(p.text for p in passages)
    assert "zawarta pomiędzy" not in joined  # komparycja odpada
    assert "{{" not in joined and "{%" not in joined
    assert "ZAŁĄCZNIK NR 1 DO UMOWY" in passages[2].text


def test_client_clauses_change_the_compared_template() -> None:
    ops = [
        ("replace_section", 2, (("h", "§ 2"), ("p", "Partner podpisze NDA klienta.")))
    ]
    passages = sources.template_passages(FICTIONAL_TEMPLATE, ops)
    assert "NDA klienta" in passages[1].text


def test_repository_template_has_paragraphs_and_appendices() -> None:
    client = SimpleNamespace(
        name="Klient Bez Klauzul", legal_name=None, display_name=None
    )
    passages, label, digest = sources.load_template(client)
    refs = [p.ref for p in passages]
    assert "§ 1" in refs and "Załącznik nr 2" in refs
    assert len(refs) == len(set(refs))
    assert label == "Wzór umowy B2B (PL)" and len(digest) == 64


def test_fingerprint_follows_files_not_reading_progress() -> None:
    def doc(**kw):
        base = dict(
            id=1,
            file_path="a.pdf",
            text_file_path="a.pdf",
            text_status="text_only",
        )
        return SimpleNamespace(**{**base, **kw})

    text_only = sources.ClientDocuments(contracts=[doc()], amendments=[])
    indexed = sources.ClientDocuments(
        contracts=[doc(text_status="indexed")], amendments=[]
    )
    replaced = sources.ClientDocuments(
        contracts=[doc(file_path="b.pdf")], amendments=[]
    )
    fp = sources.documents_fingerprint
    assert fp(text_only, "t") == fp(indexed, "t")  # wektory doszły — bez nowego biegu
    assert fp(text_only, "t") != fp(replaced, "t")  # podmieniony plik
    assert fp(text_only, "t") != fp(text_only, "inny wzór")


# ── bramki i odmowy ─────────────────────────────────────────────────────────


def test_routes_use_the_framework_contract_text_gate() -> None:
    """Ustalenia niosą cytaty z umowy klienta — bramka jak treść umów ramowych."""
    import inspect
    from typing import get_args, get_type_hints

    for endpoint in (api.get_client_fit, api.request_client_fit_check):
        default = inspect.signature(endpoint).parameters["current_user"].default
        assert default is fc_api.LegalDocsReader
    hint = get_type_hints(api.request_clause_draft, include_extras=True)["current_user"]
    assert get_args(hint)[1].dependency is fc_api.require_client_legal_docs_write
    hint = get_type_hints(api.list_clause_drafts, include_extras=True)["_admin"]
    from app.api.deps import AdminUser

    assert get_args(hint)[1] is get_args(AdminUser)[1]


def test_authz_golden_matches_framework_contract_text() -> None:
    golden = json.loads(
        (
            __import__("pathlib").Path(__file__).parent
            / "data/authz_golden/legal_client_fit.json"
        ).read_text(encoding="utf-8")
    )["routes"]
    framework = json.loads(
        (
            __import__("pathlib").Path(__file__).parent
            / "data/authz_golden/client_framework_contracts.json"
        ).read_text(encoding="utf-8")
    )["routes"]
    reader = framework["GET /api/clients/{client_id}/framework-contracts/search"]
    assert golden["GET /api/legal/client-fit/clients/{client_id}"] == reader


async def test_clause_draft_refuses_a_finding_without_proposed_text(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    finding = SimpleNamespace(id=3, client_id=5, state="gap", annex_text=None)

    class _Db:
        async def scalar(self, _statement):
            return finding

    with pytest.raises(HTTPException) as refused:
        await api.request_clause_draft(5, 3, _user(UserRole.admin), _Db())
    assert refused.value.status_code == 422

    class _Missing:
        async def scalar(self, _statement):
            return None

    with pytest.raises(HTTPException) as missing:
        await api.request_clause_draft(5, 3, _user(UserRole.admin), _Missing())
    assert missing.value.status_code == 404


# ── dostawca zadań: zakres ──────────────────────────────────────────────────


async def test_task_scope_needs_delivery_and_amounts_view(monkeypatch) -> None:
    async def _all(_user, _db):
        return None

    monkeypatch.setattr(task_provider, "resolve_delivery_lead_client_ids", _all)
    without_amounts = _holder("delivery_view")
    assert await task_provider.visible_client_ids(None, without_amounts) == frozenset()
    assert await task_provider.client_fit_tasks(None, without_amounts) == []
    with_amounts = _holder("amounts_view")
    assert await task_provider.visible_client_ids(None, with_amounts) is None


async def test_delivery_lead_tasks_only_for_assigned_clients(monkeypatch) -> None:
    """Zapytanie dostawcy dla DL zawęża klientów do przypisania."""

    async def _portfolio(_user, _db):
        return frozenset({5})

    monkeypatch.setattr(task_provider, "resolve_delivery_lead_client_ids", _portfolio)
    seen: list[str] = []

    class _Db:
        async def execute(self, statement):
            seen.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
            return SimpleNamespace(all=lambda: [])

    assert (
        await task_provider.client_fit_tasks(_Db(), _user(UserRole.delivery_lead)) == []
    )
    assert "legal_client_fit_findings.client_id IN (5)" in seen[0]


def test_task_title_and_link() -> None:
    assert task_provider._contracts_phrase(59) == "59 umów B2B nie przenosi"
    assert task_provider._contracts_phrase(3) == "3 umowy B2B nie przenoszą"
    assert task_provider._contracts_phrase(1) == "1 umowa B2B nie przenosi"
    assert task_provider._contracts_phrase(12) == "12 umów B2B nie przenosi"
    assert task_provider.annex_href(5) == (
        "/contracts/b2b-generator?tab=annexes&new=annex_custom&zgodnosc=5"
    )


def test_task_row_shape_matches_the_plan() -> None:
    from dataclasses import fields

    assert [f.name for f in fields(task_provider.LegalTaskRow)] == [
        "key",
        "kind",
        "severity",
        "title",
        "detail",
        "action_label",
        "href",
        "client_id",
        "contract_id",
        "created_at",
    ]


# ── zlecenie i rejestr ──────────────────────────────────────────────────────


def test_running_check_is_not_queued_twice() -> None:
    now = service._now()
    running = SimpleNamespace(status="running", started_at=now, requested_at=now)
    stuck = SimpleNamespace(
        status="running",
        started_at=now - service.REQUEUE_AFTER * 2,
        requested_at=now - service.REQUEUE_AFTER * 2,
    )
    assert service._in_progress(running, now)
    assert not service._in_progress(stuck, now)
    assert not service._in_progress(None, now)


def test_findings_are_shown_only_after_a_model_result() -> None:
    assert "unavailable" not in service.SHOWS_FINDINGS
    assert "failed" not in service.SHOWS_FINDINGS
    assert "done" in service.SHOWS_FINDINGS


def test_ai_feature_is_registered() -> None:
    from app.services.ai_models import model_for

    assert AIFeatureKey.legal_client_fit.value == "legal_client_fit"
    assert model_for(AIFeatureKey.legal_client_fit) == "claude-sonnet-5-5"


def test_quote_verified_uses_the_document_kind_and_strict_pieces() -> None:
    # Przegląd kodu 25.11: próbka weryfikatora musi pasować do rodzaju fragmentu,
    # a kawałki przy „(…)” muszą być dłuższe niż jedno słowo.
    text = (
        "1. Klient może naliczyć karę umowną. "
        "2. Kara umowna nie przekracza wynagrodzenia miesięcznego Partnera."
    )
    for kind in ("client", "template", "contract"):
        assert engine.quote_verified("Kara umowna nie przekracza wynagrodzenia", text, kind)
    assert not engine.quote_verified(
        "Klient (…) kara umowna (…) przekracza wynagrodzenia", text, "client"
    )
