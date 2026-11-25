"""Odpowiedź modelu w piśmie (część F) — po teście na stagingu 25.11.2026.

Nagrana odpowiedź (tu z fikcyjnymi danymi) miała zmyślony znacznik
``[PAN_ZAIMEK_PLACEHOLDER]``, komentarz „Przepraszam, poprawiam …” i drugi raz
cały list, a imię i nazwisko Partnera w mianowniku w treści („złożonego przez
Jan Przykładowy”). Kod: jedna ponowna próba z opisem błędu, potem blokada
z czytelnym powodem; polecenie wymienia wszystkie znaczniki z przykładem.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.services.legal import assistant, citations, corpus, letters
from app.services.legal.pseudonymize import Entity

PARTNER = [Entity("PARTNER", "Jan Przykładowy", inflect=True)]
ENTITIES = [
    *PARTNER,
    Entity("DATA_ZLOZENIA", "12 listopada 2026 r."),
    Entity("DATA_ROZWIAZANIA", "31 grudnia 2026 r."),
    Entity("OKRES_WYPOWIEDZENIA", "1 miesiąc"),
    *letters.courtesy_entities(False),
]

# Kształt nagranej odpowiedzi ze stagingu, dane fikcyjne.
STAGING_REPLY = (
    "[ZWROT],\n\n"
    "potwierdzamy otrzymanie wypowiedzenia umowy o współpracy B2B, złożonego przez "
    "[PARTNER] [DATA_ZLOZENIA].\n\n"
    "Zgodnie z § 8 ust. 2 lit. c Umowy okres wypowiedzenia wynosi [OKRES_WYPOWIEDZENIA], "
    "a umowa rozwiąże się z dniem [DATA_ROZWIAZANIA].\n\n"
    "Uprzejmie prosimy [PAN_ZAIMEK_PLACEHOLDER]\n\n"
    "Przepraszam, poprawiam ostatni akapit i dalszą część, aby zwracać się do adresata "
    "wyłącznie znacznikami z listy.\n\n"
    "[ZWROT],\n\n"
    "potwierdzamy otrzymanie wypowiedzenia umowy o współpracy B2B, złożonego przez "
    "[PARTNER] [DATA_ZLOZENIA].\n\n"
    "Dziękujemy [PAN_CELOWNIK] za dotychczasową współpracę."
)
GOOD_REPLY = (
    "[ZWROT],\n\n"
    "potwierdzamy otrzymanie wypowiedzenia umowy o współpracy B2B, złożonego przez "
    "[PAN_BIERNIK] [DATA_ZLOZENIA].\n\n"
    "Zgodnie z § 8 ust. 2 lit. c Umowy okres wypowiedzenia wynosi [OKRES_WYPOWIEDZENIA], "
    "a umowa rozwiąże się z dniem [DATA_ROZWIAZANIA].\n\n"
    "Dziękujemy [PAN_CELOWNIK] za dotychczasową współpracę."
)


@pytest.fixture
def model(monkeypatch):
    from app.services import ai_models, ai_quota, llm_providers

    calls: list[str] = []
    replies: list[str] = []

    def fake_call(prompt, _system, _model, _fallbacks):
        calls.append(prompt)
        return replies.pop(0)

    @asynccontextmanager
    async def fake_feature(_db, _feature, **_kw):
        yield None

    async def nothing(*_a, **_kw):
        return []

    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _m: True)
    monkeypatch.setattr(ai_models, "model_chain_for", lambda _f: ["claude-sonnet-5-5"])
    monkeypatch.setattr(ai_quota, "ai_feature", fake_feature)
    monkeypatch.setattr(corpus, "search_provisions", nothing)
    monkeypatch.setattr(corpus, "verify_text", nothing)
    monkeypatch.setattr(assistant, "_call_model", fake_call)
    return calls, replies


class _Db:
    async def commit(self):
        return None


async def _draft(**kw):
    return await assistant.draft(
        _Db(),
        kind="reply",
        instruction="Potwierdź wypowiedzenie Partnera.",
        passages=[citations.SourcePassage("law", "art. 61 § 1", "§ 1. Tekst.", act_key="kc")],
        entities=ENTITIES,
        **kw,
    )


@pytest.mark.asyncio
async def test_bad_reply_is_retried_once_with_what_was_wrong(model):
    calls, replies = model
    replies.extend([STAGING_REPLY, GOOD_REPLY])
    result = await _draft(forbidden_labels=("PARTNER",))
    assert len(calls) == 2
    assert "[PAN_ZAIMEK_PLACEHOLDER]" in calls[1] and "Przepraszam" in calls[1]
    assert "[PARTNER]" in calls[1]  # uwaga o nazwisku w treści
    assert not result.blocked and result.issues == []
    assert "złożonego przez Pana 12 listopada 2026 r." in result.text
    assert result.text.count("Szanowny Panie") == 1


@pytest.mark.asyncio
async def test_still_bad_after_retry_is_blocked_with_a_reason(model):
    calls, replies = model
    replies.extend([STAGING_REPLY, STAGING_REPLY])
    result = await _draft(forbidden_labels=("PARTNER",))
    assert len(calls) == 2
    assert result.blocked
    joined = " ".join(result.issues)
    assert "[PAN_ZAIMEK_PLACEHOLDER]" in joined
    assert "komentarz" in joined
    assert "drugi raz" in joined
    assert "imię i nazwisko" in joined


@pytest.mark.asyncio
async def test_partner_name_in_the_body_alone_triggers_the_retry(model):
    calls, replies = model
    replies.extend(
        [GOOD_REPLY.replace("przez [PAN_BIERNIK]", "przez [PARTNER]"), GOOD_REPLY]
    )
    result = await _draft(forbidden_labels=("PARTNER",))
    assert len(calls) == 2 and not result.blocked


@pytest.mark.asyncio
async def test_good_reply_is_not_retried_and_client_letters_may_name_the_consultant(model):
    calls, replies = model
    replies.append("[ZWROT],\n\ninformujemy, że konsultant [PARTNER] kończy projekt.")
    result = await _draft()
    assert len(calls) == 1 and not result.blocked


def test_instruction_lists_every_allowed_marker_with_an_example():
    text = letters.model_instruction(
        letters.KIND_NOTICE_REPLY, has_end=True, has_period=True
    )
    for token, example in (
        ("[ZWROT]", "Szanowny Panie"),
        ("[PAN_MIANOWNIK]", "„Pan”"),
        ("[PAN_DOPELNIACZ]", "„Pana”"),
        ("[PAN_CELOWNIK]", "„Panu”"),
        ("[PAN_BIERNIK]", "przez [PAN_BIERNIK]"),
        ("[PAN_NARZEDNIK]", "„Panem”"),
    ):
        assert token in text and example in text, token
    assert "[PARTNER]" in text and "nagłówk" in text  # nazwisko tylko w nagłówku
    assert "innych znaczników" in text.lower()


def test_courtesy_has_accusative_for_przez():
    male = {e.label: e.value for e in letters.courtesy_entities(False)}
    female = {e.label: e.value for e in letters.courtesy_entities(True)}
    assert male["PAN_BIERNIK"] == "Pana" and female["PAN_BIERNIK"] == "Panią"


def test_tokens_block_forbids_new_markers():
    block = assistant._tokens_block({"[ZWROT]": "Szanowny Panie"})
    assert "[ZWROT]" in block and "Innych znaczników nie ma" in block
    assert "Szanowny Panie" not in block  # wartości nie idą do modelu


# ── litery „a.”/„a)” w tekście ciągłym starej redakcji ─────────────────────

OLD_EDITION = (
    "§ 8\n"
    "1. Umowa zostaje zawarta na czas nieokreślony.\n"
    "2. Strony mają możliwość rozwiązania umowy w następujących trybach: a. za "
    "porozumieniem stron b. za wypowiedzeniem ze strony Spółki z 1 miesięcznym okresem "
    "wypowiedzenia c. za wypowiedzeniem ze strony Partnera z 1 miesięcznym okresem "
    "wypowiedzenia liczonym od kolejnego miesiąca d. w trybie natychmiastowym\n"
    "3. Wypowiedzenie wymaga formy pisemnej.\n"
)


def _contract_passages():
    from app.services.legal.letter_service import passages_from_text

    return passages_from_text(OLD_EDITION, "umowa 12/2025", None, "umowa.pdf", "contract")


def test_letter_in_continuous_text_is_found():
    checks = citations.verify("Zgodnie z § 8 ust. 2 lit. c Umowy.", _contract_passages())
    assert [c.status for c in checks] == [citations.STATUS_OK]
    quoted = citations.verify(
        "Zgodnie z § 8 ust. 2 lit. c Umowy: „za wypowiedzeniem ze strony Partnera”.",
        _contract_passages(),
    )
    assert [c.status for c in quoted] == [citations.STATUS_OK]


def test_missing_letter_in_continuous_text_is_missing():
    checks = citations.verify("Zgodnie z § 8 ust. 2 lit. f Umowy.", _contract_passages())
    assert [c.status for c in checks] == [citations.STATUS_MISSING]


@pytest.mark.parametrize(
    "listing",
    [
        "a) za porozumieniem stron;\nb) za wypowiedzeniem;\nc) za wypowiedzeniem Partnera;",
        "a. za porozumieniem stron\nb. za wypowiedzeniem\nc. za wypowiedzeniem Partnera",
        "1) za porozumieniem stron 2) za wypowiedzeniem 3) za wypowiedzeniem Partnera",
    ],
)
def test_letters_and_points_in_both_notations(listing):
    unit = "lit. c" if listing.startswith("a") else "pkt 3"
    passage = citations.SourcePassage("contract", "§ 8 ust. 2", f"2. Tryby: {listing}")
    ok = citations.verify(f"Zgodnie z § 8 ust. 2 {unit} Umowy.", [passage])
    assert [c.status for c in ok] == [citations.STATUS_OK]
    bad = "lit. f" if unit.startswith("lit") else "pkt 7"
    missing = citations.verify(f"Zgodnie z § 8 ust. 2 {bad} Umowy.", [passage])
    assert [c.status for c in missing] == [citations.STATUS_MISSING]


def test_company_apology_in_the_letter_is_not_a_model_comment():
    text = "[ZWROT],\n\nPrzepraszamy za opóźnienie w odpowiedzi.\n\nDziękujemy [PAN_CELOWNIK]."
    mapping = {"[ZWROT]": "Szanowny Panie", "[PAN_CELOWNIK]": "Panu"}
    assert assistant.reply_problems(text, mapping, forbidden_labels=("PARTNER",)) == []
