"""Pismo na stronie kontraktu (asystent prawny, część F) — bez bazy.

Wzór kontra model per rodzaj pisma, termin z reguły PODPISANEJ umowy (obie
generacje wzoru: „na koniec miesiąca” i „od kolejnego miesiąca”), ostrzeżenie
o formie, blokada „Zatwierdzam” przy złym cytacie, formy Pan/Pani i dane osoby
tylko jako znaczniki. Wszystkie dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services.b2b_documents import registry
from app.services.legal import assistant, citations, letter_service, letters
from app.services.legal.citations import SourcePassage
from app.services.legal.letters import NoticeRule

TODAY = date(2026, 11, 25)

#: Dzisiejszy wzór (§ 12): koniec miesiąca kalendarzowego, forma dokumentowa, mail.
RULE_2026 = NoticeRule(
    period_kind="end_of_month",
    period_months=1,
    period_days=None,
    forms=("written", "documentary"),
    delivery=("email",),
    period_ref="§ 12 ust. 2",
    period_source_ref="umowa 7/2026 § 12 ust. 2",
    form_source_ref="umowa 7/2026 § 12 ust. 4",
)
#: Wzór z 2025 r.: od kolejnego miesiąca, pisemna pod rygorem nieważności, osobiście/pocztą.
RULE_2025 = NoticeRule(
    period_kind="from_next_month",
    period_months=1,
    period_days=None,
    forms=("written",),
    under_nullity=True,
    delivery=("in_person", "post"),
    period_ref="§ 8 ust. 2",
    period_source_ref="umowa 41/2025 § 8 ust. 2",
    form_source_ref="umowa 41/2025 § 8 ust. 5",
)
CLAUSE_2025 = SourcePassage(
    "contract",
    "umowa 41/2025 § 8 ust. 2",
    "Każda ze Stron może wypowiedzieć Umowę z zachowaniem jednomiesięcznego okresu "
    "wypowiedzenia, liczonego od kolejnego miesiąca.",
    "/contracts/1?tab=documents",
    "umowa_41_2025.pdf",
)


# ── rodzaje: wzór kontra model ──────────────────────────────────────────────


def test_three_kinds_fill_existing_templates_and_three_use_the_model() -> None:
    by_source = {
        source: {k.key for k in letters.LETTER_KINDS if k.source == source}
        for source in (letters.SOURCE_TEMPLATE, letters.SOURCE_MODEL)
    }
    assert by_source[letters.SOURCE_TEMPLATE] == {
        "termination_notice",
        "termination_agreement",
        "notice_withdrawal",
    }
    assert by_source[letters.SOURCE_MODEL] == {
        "notice_reply",
        "penalty_note",
        "client_letter",
    }
    for kind in letters.LETTER_KINDS:
        if kind.source == letters.SOURCE_TEMPLATE:
            doc_type = registry.get_type(kind.template or "")
            assert doc_type is not None and "pl" in doc_type.languages
            assert kind.draft_kind is None
        else:
            assert kind.draft_kind in assistant.KINDS and kind.template is None


def test_jarvis_kind_list_mirrors_letter_kinds() -> None:
    from app.services.jarvis.tools import LEGAL_LETTER_KINDS

    assert LEGAL_LETTER_KINDS == letters.LETTER_KIND_KEYS


# ── termin z reguły podpisanej umowy ────────────────────────────────────────


def test_end_of_month_generation_excludes_the_delivery_month() -> None:
    deadline, reason = letters.notice_deadline(RULE_2026, date(2026, 11, 12))
    assert reason is None and deadline.end == date(2026, 12, 31)
    assert "art. 111 § 2 KC" in deadline.basis
    # Doręczenie 1. dnia: miesiąc doręczenia nadal nie wchodzi do okresu.
    first, _ = letters.notice_deadline(RULE_2026, date(2027, 3, 1))
    assert first.end == date(2027, 4, 30)


def test_next_month_generation_counts_from_the_first_of_next_month() -> None:
    deadline, reason = letters.notice_deadline(RULE_2025, date(2026, 11, 12))
    assert reason is None and deadline.end == date(2026, 12, 31)
    assert any("od kolejnego miesiąca" in step for step in deadline.steps)
    assert any("1 grudnia 2026 r." in step for step in deadline.steps)
    three = NoticeRule("from_next_month", 3, None)
    longer, _ = letters.notice_deadline(three, date(2026, 11, 30))
    assert longer.end == date(2027, 2, 28)


def test_day_periods_and_unknown_rules() -> None:
    days, _ = letters.notice_deadline(
        NoticeRule("end_of_month", None, 30), date(2026, 11, 12)
    )
    assert days.end == date(2026, 12, 31)
    plain, _ = letters.notice_deadline(NoticeRule("days", None, 14), date(2026, 3, 3))
    assert plain.end == date(2026, 3, 17)
    none, reason = letters.notice_deadline(
        NoticeRule("from_next_month", None, 14), date(2026, 3, 3)
    )
    assert none is None and "wpisz sam" in reason


def test_deadline_facts_compare_with_the_recorded_last_day() -> None:
    same = letters.deadline_facts(
        RULE_2025, date(2026, 11, 12), recorded_last_day=date(2026, 12, 31)
    )
    end = same.facts[-1]
    assert (end.label, end.value, end.note, end.tone) == (
        "Rozwiązanie",
        "31.12.2026",
        "zgodne z NEXUSEM",
        "ok",
    )
    other = letters.deadline_facts(
        RULE_2025, date(2026, 11, 12), recorded_last_day=date(2027, 1, 31)
    )
    assert other.facts[-1].tone == "warn" and "31.01.2027" in other.facts[-1].note
    unread = letters.deadline_facts(
        None, date(2026, 11, 12), rule_reason="Brak zapisu."
    )
    assert unread.end is None and unread.reason == "Brak zapisu."


def test_period_phrases_for_the_letter_and_the_template() -> None:
    assert letters.period_label(RULE_2025) == "1 miesiąc, liczony od kolejnego miesiąca"
    assert (
        letters.period_genitive(RULE_2025)
        == "1 (jednego) miesiąca liczonego od kolejnego miesiąca"
    )
    assert letters.period_genitive(RULE_2026) == (
        "1 (jednego) miesiąca ze skutkiem na koniec miesiąca kalendarzowego"
    )
    assert letters.bare_ref("umowa 41/2025 § 8 ust. 2") == "§ 8 ust. 2"
    assert letters.bare_ref("umowa „plik.pdf”") is None


# ── forma wypowiedzenia ─────────────────────────────────────────────────────


def test_strict_form_asks_about_the_original_and_offers_an_agreement() -> None:
    warning = letters.form_warning(
        "notice_reply",
        RULE_2025,
        notice_document=("Wypowiedzenie_skan.pdf", date(2026, 11, 12)),
    )
    assert warning is not None and warning.level == "question"
    assert warning.actions == ("confirm_original", "switch_to_agreement")
    assert "pod rygorem nieważności" in warning.message
    assert "osobiście albo pocztą" in warning.message
    assert (
        "Wypowiedzenie_skan.pdf" in warning.message and "12.11.2026" in warning.message
    )
    assert "umowa 41/2025 § 8 ust. 5" in warning.message
    # Odpowiedź „to oryginał / podpis kwalifikowany” zdejmuje pytanie.
    assert (
        letters.form_warning("notice_reply", RULE_2025, original_confirmed=True) is None
    )
    no_file = letters.form_warning("notice_reply", RULE_2025)
    assert "nie ma pliku wypowiedzenia" in no_file.message


def test_documentary_form_with_email_needs_no_warning() -> None:
    assert letters.form_warning("notice_reply", RULE_2026) is None
    assert letters.form_warning("termination_notice", RULE_2026) is None
    assert letters.form_warning("notice_reply", None) is None


def test_our_notice_under_strict_form_is_an_info_not_a_question() -> None:
    warning = letters.form_warning("termination_notice", RULE_2025)
    assert warning.level == "info" and not warning.actions
    assert "kwalifikowanym podpisem" in warning.message


# ── blokada „Zatwierdzam” ───────────────────────────────────────────────────


def test_bad_citation_and_open_question_block_approval() -> None:
    assert not letters.approval_state(
        check_statuses=["ok", "ok"], issues=[], warning=None, has_text=True
    ).blocked
    mismatch = letters.approval_state(
        check_statuses=["ok", "mismatch"], issues=[], warning=None, has_text=True
    )
    assert mismatch.blocked and "pokrycia" in mismatch.reasons[0]
    missing = letters.approval_state(
        check_statuses=["missing", "missing"], issues=[], warning=None, has_text=True
    )
    assert missing.blocked and "2 cytaty" in missing.reasons[0]
    question = letters.form_warning("notice_reply", RULE_2025)
    asked = letters.approval_state(
        check_statuses=[], issues=[], warning=question, has_text=True
    )
    assert asked.blocked and "formę" in asked.reasons[-1]
    info = letters.form_warning("termination_notice", RULE_2025)
    assert not letters.approval_state(
        check_statuses=[], issues=[], warning=info, has_text=True
    ).blocked
    assert letters.approval_state(
        check_statuses=[], issues=[], warning=None, has_text=False
    ).blocked


# ── Pan/Pani liczy kod ──────────────────────────────────────────────────────


def test_courtesy_forms_come_from_code() -> None:
    female = {e.label: e.value for e in letters.courtesy_entities(True)}
    male = {e.label: e.value for e in letters.courtesy_entities(False)}
    assert female["ZWROT"] == "Szanowna Pani" and female["PAN_NARZEDNIK"] == "Panią"
    assert male["ZWROT"] == "Szanowny Panie" and male["PAN_DOPELNIACZ"] == "Pana"
    assert letters.partner_female(None, "Anna Przykładowa")
    assert not letters.partner_female(None, "Kuba Testowy")
    assert not letters.partner_female("m", "Anna Przykładowa")
    assert letters.partner_female("f", "Jan Przykładowy")


def test_template_html_becomes_paragraphs_and_placeholders_block() -> None:
    text = letters.html_to_text(
        "<h1>Tytuł</h1><p>Akapit&nbsp;pierwszy</p><p>… i dalej</p>"
    )
    assert text == "Tytuł\n\nAkapit pierwszy\n\n… i dalej\n"
    assert letters.placeholder_issues(text)
    assert letters.placeholder_issues("Pełne dane.") == []


# ── budowa pisma (atrapa kontekstu) ─────────────────────────────────────────


def _contract(**kw):
    values = dict(
        id=1,
        client_id=5,
        candidate_id=77,
        agreement_termination_party="consultant",
        agreement_termination_mode="notice",
        agreement_termination_signed_on=date(2026, 11, 12),
        agreement_last_day=date(2026, 12, 31),
    )
    values.update(kw)
    return SimpleNamespace(**values)


def _ctx(contract=None, *, rule=RULE_2025, number="41/2025", female=False, notice=True):
    return letter_service.LetterContext(
        contract=contract or _contract(),
        partner={
            "full_name": "Anna Przykładowa" if female else "Jan Przykładowy",
            "company": "Przykładowe IT Jan Przykładowy",
            "address": "ul. Testowa 1",
            "postal_city": "00-001 Warszawa",
            "nip": "1234563218",
            "regon": "123456785",
            "email": "konsultant@example.com",
            "phone": "",
            "gender": "f" if female else "m",
            "name_instrumental": "Anną Przykładową" if female else "Janem Przykładowym",
        },
        female=female,
        contract_number=number,
        signing_date=date(2025, 3, 3),
        client_name="Fikcyjny Bank",
        client_legal_name="Fikcyjny Bank S.A.",
        rule=rule,
        rule_reason=None if rule else "W treści nie ma zapisu o okresie wypowiedzenia.",
        rule_sources=(CLAUSE_2025,) if rule else (),
        rule_notes=(),
        notice_document=("Wypowiedzenie_skan.pdf", date(2026, 11, 12))
        if notice
        else None,
    )


@pytest.fixture
def offline(monkeypatch):
    async def _verify(_db, _contract, text, extra=()):
        return citations.verify(text, [*extra, CLAUSE_2025])

    monkeypatch.setattr(letter_service, "verify_letter_text", _verify)
    monkeypatch.setattr(letter_service, "business_today", lambda: TODAY)


async def test_termination_notice_fills_the_template_from_the_signed_contract(
    offline,
) -> None:
    ctx = _ctx(_contract(agreement_termination_party=None))
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="termination_notice"),
        ctx=ctx,
    )
    assert letter.model is None  # model nie pisze ani zdania
    # Paragraf i okres z podpisanej umowy 2025, nie z dzisiejszego wzoru (§ 12 ust. 2 pkt 2).
    assert "§ 8 ust. 2 umowy" in letter.text
    assert "liczonego od kolejnego miesiąca" in letter.text
    assert "§ 12 ust. 2 pkt 2" not in letter.text
    assert "doręczone Partnerowi w dniu 25.11.2026" in letter.text
    assert "rozwiązaniu z dniem 31.12.2026" in letter.text
    assert "Panem Janem Przykładowym" in letter.text
    assert [c.status for c in letter.checks] == ["ok"]
    assert letter.warning is not None and letter.warning.level == "info"
    assert not letter.approval.blocked
    assert letter.generator_values["termination_date"] == "2026-12-31"


async def test_template_without_rule_or_number_is_blocked(offline) -> None:
    ctx = _ctx(rule=None, number=None)
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="termination_notice"),
        ctx=ctx,
    )
    assert "…" in letter.text
    assert letter.approval.blocked
    assert any("brakuje danych" in reason for reason in letter.approval.reasons)


async def test_agreement_and_withdrawal_use_their_templates(offline) -> None:
    ctx = _ctx(female=True)
    agreement = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="termination_agreement"),
        ctx=ctx,
    )
    assert "Porozumienie o rozwiązaniu" in agreement.text
    assert "Panią Anną Przykładową" in agreement.text
    assert "nastąpi w dniu 31.12.2026" in agreement.text
    withdrawal = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="notice_withdrawal"),
        ctx=ctx,
    )
    assert "w dniu 12.11.2026" in withdrawal.text
    assert "przekazałam" in withdrawal.text


@pytest.fixture
def fake_model(monkeypatch, offline):
    calls: dict[str, object] = {}

    async def _passages(_db, ctx, kind, user_text):
        return list(ctx.rule_sources)

    async def _draft(_db, **kwargs):
        calls.update(kwargs)
        text = calls.get("reply_text") or (
            "Szanowny Panie,\n\npotwierdzamy otrzymanie Pana wypowiedzenia złożonego "
            "12 listopada 2026 r. Zgodnie z § 8 ust. 2 umowy okres wypowiedzenia "
            "wynosi 1 miesiąc, liczony od kolejnego miesiąca, więc umowa rozwiąże się "
            "z dniem 31 grudnia 2026 r."
        )
        return assistant.Draft(
            text=text,
            citations=[],
            checks=[],
            blocked=False,
            passages=list(kwargs["passages"]),
            model="model-testowy",
        )

    monkeypatch.setattr(letter_service, "_model_passages", _passages)
    monkeypatch.setattr(assistant, "draft", _draft)
    return calls


async def test_notice_reply_sends_only_tokens_and_code_values(fake_model) -> None:
    ctx = _ctx()
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="notice_reply", original_confirmed=True),
        ctx=ctx,
    )
    entities = {e.label: e.value for e in fake_model["entities"]}
    assert entities["DATA_ROZWIAZANIA"] == "31 grudnia 2026 r."
    assert entities["DATA_ZLOZENIA"] == "12 listopada 2026 r."
    assert entities["OKRES_WYPOWIEDZENIA"] == "1 miesiąc, liczony od kolejnego miesiąca"
    assert entities["ZWROT"] == "Szanowny Panie"
    assert entities["PARTNER"] == "Jan Przykładowy"
    instruction = str(fake_model["instruction"])
    assert "Przykładowy" not in instruction and "2026" not in instruction
    assert "[DATA_ROZWIAZANIA]" in instruction
    assert fake_model["kind"] == "reply"
    # Nagłówek, adresat i podpis składa kod.
    assert letter.text.startswith("Warszawa, 25 listopada 2026 r.")
    assert "Jan Przykładowy\nPrzykładowe IT Jan Przykładowy" in letter.text
    assert "Dotyczy: Potwierdzenie wypowiedzenia umowy o współpracy B2B nr 41/2025" in (
        letter.text
    )
    assert letter.text.rstrip().endswith("B2B.net S.A.")
    assert [c.status for c in letter.checks] == ["ok"]
    assert not letter.approval.blocked
    assert letter.recipient.email == "konsultant@example.com"
    assert letter.recipient.candidate_id == 77


async def test_notice_reply_without_answer_on_form_is_blocked(fake_model) -> None:
    ctx = _ctx()
    letter = await letter_service.build_letter(
        None, ctx.contract, letter_service.LetterRequest(kind="notice_reply"), ctx=ctx
    )
    assert letter.warning.level == "question"
    assert letter.approval.blocked


async def test_wrong_quote_from_the_model_blocks_approval(fake_model) -> None:
    fake_model["reply_text"] = (
        "Szanowny Panie,\n\nzgodnie z § 8 ust. 2 umowy „okres wypowiedzenia wynosi "
        "trzy miesiące”, więc prosimy o dalszą współpracę."
    )
    ctx = _ctx()
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="notice_reply", original_confirmed=True),
        ctx=ctx,
    )
    assert [c.status for c in letter.checks] == ["mismatch"]
    assert letter.approval.blocked


async def test_reply_needs_a_partner_notice_on_the_contract(fake_model) -> None:
    ctx = _ctx(_contract(agreement_termination_party="company"))
    with pytest.raises(letter_service.LetterUnavailable):
        await letter_service.build_letter(
            None,
            ctx.contract,
            letter_service.LetterRequest(kind="notice_reply"),
            ctx=ctx,
        )


async def test_penalty_note_needs_amount_and_goes_to_a_lawyer(fake_model) -> None:
    ctx = _ctx()
    with pytest.raises(letter_service.LetterUnavailable):
        await letter_service.build_letter(
            None,
            ctx.contract,
            letter_service.LetterRequest(kind="penalty_note"),
            ctx=ctx,
        )
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="penalty_note", penalty_amount=5000),
        ctx=ctx,
    )
    entities = {e.label: e.value for e in fake_model["entities"]}
    assert entities["KWOTA_KARY"] == "5 000,00 zł (słownie: pięć tysięcy złotych)"
    # 25.11.2026 + 7 dni = 2.12.2026 (środa, dzień roboczy).
    assert entities["TERMIN_ZAPLATY"] == "2 grudnia 2026 r."
    assert "DATA_ROZWIAZANIA" not in entities
    assert letter.lawyer_review[0] == "kara umowna"


async def test_client_letter_addresses_the_client(fake_model) -> None:
    ctx = _ctx()
    with pytest.raises(letter_service.LetterUnavailable):
        await letter_service.build_letter(
            None,
            ctx.contract,
            letter_service.LetterRequest(kind="client_letter", instruction="krótko"),
            ctx=ctx,
        )
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(
            kind="client_letter",
            instruction="Poinformuj o zakończeniu współpracy konsultanta.",
        ),
        ctx=ctx,
    )
    entities = {e.label: e.value for e in fake_model["entities"]}
    assert entities["ZWROT"] == "Szanowni Państwo"
    assert "PAN_MIANOWNIK" not in entities
    assert letter.recipient.kind == "client"
    assert letter.recipient.name == "Fikcyjny Bank S.A."


async def test_no_model_leaves_an_empty_blocked_letter(monkeypatch, offline) -> None:
    async def _passages(_db, ctx, kind, user_text):
        return list(ctx.rule_sources)

    async def _draft(_db, **kwargs):
        return assistant.Draft(
            text="",
            citations=[],
            checks=[],
            blocked=True,
            passages=list(kwargs["passages"]),
            error="Brak klucza dostawcy AI",
        )

    monkeypatch.setattr(letter_service, "_model_passages", _passages)
    monkeypatch.setattr(assistant, "draft", _draft)
    ctx = _ctx()
    letter = await letter_service.build_letter(
        None,
        ctx.contract,
        letter_service.LetterRequest(kind="notice_reply", original_confirmed=True),
        ctx=ctx,
    )
    assert letter.text == "" and letter.error and letter.approval.blocked
    assert letter.passages == [CLAUSE_2025]


def test_contract_text_becomes_passages_per_section() -> None:
    text = (
        "Umowa nr 41/2025\n§ 8\nRozwiązanie umowy\n"
        "1. Umowa zostaje zawarta na czas nieokreślony.\n"
        "2. Każda ze Stron może wypowiedzieć Umowę z zachowaniem jednomiesięcznego "
        "okresu wypowiedzenia.\n"
    )
    passages = letter_service.passages_from_text(
        text, "umowa 41/2025", "/contracts/1?tab=documents", "u.pdf", "contract"
    )
    refs = {p.ref: p.text for p in passages}
    assert "umowa 41/2025 § 8" in refs and "umowa 41/2025 § 8 ust. 2" in refs
    checks = citations.verify(
        "Zgodnie z § 8 ust. 2 umowy „z zachowaniem jednomiesięcznego okresu "
        "wypowiedzenia”.",
        passages,
    )
    assert [c.status for c in checks] == ["ok"]


def test_plain_letter_docx_opens() -> None:
    import io

    from docx import Document

    data = letter_service.text_docx(
        "Warszawa, 25 listopada 2026 r.\n\nJan\nul. Testowa 1\n\nTreść."
    )
    document = Document(io.BytesIO(data))
    texts = [p.text for p in document.paragraphs]
    assert texts[0] == "Warszawa, 25 listopada 2026 r."
    assert "Treść." in texts
