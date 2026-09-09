"""Tryby obróbki treści CV: basic / polished / tailored.

Klient (Nordea) zgłosił, że CV wyglądają na pisane pod jego ogłoszenie i że
deklarowane doświadczenie bywa wyolbrzymione. Tryby odpowiadają na PIERWSZĄ
część tego zarzutu: regulują, ile obróbki prezentacyjnej wolno zastosować.

Te testy zamrażają dwie rzeczy, które łatwo cicho zepsuć przy kolejnej zmianie:

1. Poniżej "tailored" żaden kanał pozycjonowania pod ofertę nie działa —
   Profil Championa NIE trafia do modelu, a lista wymagań klienta NIE steruje
   pogrubieniami. Sprawdzamy to na obserwowalnych efektach (co poszło do
   Claude'a, co wylądowało w payloadzie), nie na wywołaniach wewnętrznych.
2. Sufit per klient wygrywa z wyborem rekrutera — bez tego obietnica złożona
   klientowi jest deklaracją, którą znosi jeden checkbox w UI.
"""

import json
import time

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.prompts import get_prompt
from app.services.cv_generator_b2b.standalone_service import (
    CONTENT_MODES,
    DEFAULT_CONTENT_MODE,
    apply_content_mode_cap,
    normalize_content_mode,
)

_CV_TEXT = (
    "Jan Kowalski\n"
    "Backend Developer\n"
    "03.2019 – obecnie, Acme Sp. z o.o., Backend Developer\n"
    "Utrzymanie API w Pythonie. Technologie: Python, PostgreSQL.\n"
)

_AI_JSON = {
    "name": "Jan Kowalski",
    "first_name": "Jan",
    "position": "Backend Developer",
    "why_points": ["6 lat jako Backend Developer"],
    "education": [],
    "skills": [{"label": "Backend", "content": "Python, PostgreSQL"}],
    "certifications": [],
    "languages": ["Polski – ojczysty"],
    "experience": [
        {
            "dates": "03.2019 – obecnie",
            "company": "Acme Sp. z o.o.",
            "industry": "IT",
            "position": "Backend Developer",
            "responsibilities": ["Utrzymanie API w Pythonie"],
            "technologies": ["Python", "PostgreSQL"],
        }
    ],
}


@pytest.fixture
def captured_prompt(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run the real pipeline with Claude, text extraction and DOCX stubbed out.

    Asserting on what actually reached the model (and on the saved payload) is
    the only way to prove the lower modes are safe: a prompt rule telling the
    model to "ignore the champion profile" is a request, while not sending the
    section at all is a guarantee.
    """
    seen: dict = {}

    def fake_analyze(user_content: str, request_id: str, system: str = "") -> str:
        seen["user"] = user_content
        seen["system"] = system
        return json.dumps(_AI_JSON)

    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: _CV_TEXT)
    monkeypatch.setattr(svc, "analyze_with_ai", fake_analyze)
    # These tests isolate presentation. Evidence review has dedicated integration
    # regressions in test_cv_factual_verification.py, including rejection paths.
    monkeypatch.setattr(svc, "verify_final_cv", lambda *a, **k: {"status": "verified"})
    monkeypatch.setattr(svc, "render_cv_to_bytes", lambda *a, **k: b"DOCX")
    return seen


def _run(mode: str, captured: dict, *, with_champion: bool = True):
    champion = (
        ChampionProfileForPrompt(
            must_have=["Kubernetes"],
            nice_to_have=["Terraform"],
            responsibilities="Utrzymanie klastrów produkcyjnych",
        )
        if with_champion
        else None
    )
    result = svc._run_generation_pipeline(
        cv_bytes=b"x",
        cv_filename="cv.pdf",
        champion_dto=champion,
        screening_notes_text="Kandydat potwierdził znajomość Pythona.",
        language="pl",
        blind_cv=False,
        request_id="test",
        fallback_name="Jan Kowalski",
        started_at=time.time(),
        job_id=1,
        job_title="Senior Platform Engineer (K8s)",
        content_mode=mode,
    )
    return result, captured


# ── Kontrakt trybu ────────────────────────────────────────────────────────


def test_default_mode_is_not_the_most_positioned() -> None:
    """Domyślny tryb NIE może być "tailored".

    To jest cała różnica między funkcją a teatrem: gdyby najmocniej
    pozycjonowany wariant był domyślny, rekruter dostawałby go przez samo
    przeklikanie — czyli dokładnie stan, na który klient się poskarżył.
    """
    assert DEFAULT_CONTENT_MODE == "polished"
    assert DEFAULT_CONTENT_MODE != "tailored"


@pytest.mark.parametrize("bad", ["", None, "ULTRA", "ultimate", "nonsense", 42, True])
def test_unknown_mode_never_silently_upgrades(bad: object) -> None:
    """Literówka albo stary klient nie mogą podbić trybu do "tailored".

    Uwaga: "ultimate" jest tu celowo — tak brzmiała robocza nazwa tego trybu.
    Gdyby kiedyś wróciła jako wartość z zewnątrz, ma spaść na domyślną, a nie
    włączyć pełne pozycjonowanie.
    """
    assert normalize_content_mode(bad) != "tailored"
    assert normalize_content_mode(bad) == DEFAULT_CONTENT_MODE


@pytest.mark.parametrize("padded", [" tailored ", "\tbasic\n", " POLISHED "])
def test_surrounding_whitespace_is_trimmed_not_rejected(padded: str) -> None:
    """Białe znaki wokół poprawnej wartości to literówka transportu, nie inny tryb."""
    assert normalize_content_mode(padded) == padded.strip().lower()


@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_known_modes_survive_normalization(mode: str) -> None:
    assert normalize_content_mode(mode) == mode
    assert normalize_content_mode(mode.upper()) == mode


# ── Sufit per klient ──────────────────────────────────────────────────────


def test_no_cap_means_no_ceiling() -> None:
    """NULL cap = zachowanie sprzed zmiany dla wszystkich obecnych klientów."""
    for mode in CONTENT_MODES:
        assert apply_content_mode_cap(mode, None) == (mode, False)


def test_cap_clamps_a_higher_request() -> None:
    assert apply_content_mode_cap("tailored", "basic") == ("basic", True)
    assert apply_content_mode_cap("tailored", "polished") == ("polished", True)
    assert apply_content_mode_cap("polished", "basic") == ("basic", True)


def test_cap_does_not_raise_a_lower_request() -> None:
    """Sufit ogranicza, nigdy nie podnosi — rekruter może zejść niżej."""
    assert apply_content_mode_cap("basic", "tailored") == ("basic", False)
    assert apply_content_mode_cap("basic", "polished") == ("basic", False)
    assert apply_content_mode_cap("polished", "tailored") == ("polished", False)


def test_cap_at_own_level_is_not_reported_as_capped() -> None:
    assert apply_content_mode_cap("polished", "polished") == ("polished", False)


def test_broken_cap_value_does_not_disable_the_ceiling() -> None:
    """Śmieć w kolumnie sufitu nie może odblokować pełnego pozycjonowania."""
    effective, _ = apply_content_mode_cap("tailored", "garbage")
    assert effective == DEFAULT_CONTENT_MODE


# ── Prompt ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", ["pl", "en"])
def test_lower_modes_get_an_addendum_and_tailored_does_not(language: str) -> None:
    """ "tailored" to prompt bazowy; basic/polished dokładają ograniczenia."""
    tailored = get_prompt(language, False, "tailored")
    for mode in ("basic", "polished"):
        assert len(get_prompt(language, False, mode)) > len(tailored)


@pytest.mark.parametrize("language", ["pl", "en"])
@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_blind_addendum_stays_last(language: str, mode: str) -> None:
    """Anonimizacja musi mieć ostatnie słowo, niezależnie od trybu."""
    plain = get_prompt(language, False, mode)
    blind = get_prompt(language, True, mode)
    assert blind.startswith(plain)
    assert len(blind) > len(plain)


@pytest.mark.parametrize("language", ["pl", "en"])
def test_legacy_positional_call_still_works(language: str) -> None:
    """Stare wywołania get_prompt(lang, blind) nie mogą się wywalić."""
    assert get_prompt(language, False) == get_prompt(
        language, False, DEFAULT_CONTENT_MODE
    )


@pytest.mark.parametrize("language", ["pl", "en"])
@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_truth_ceiling_is_identical_in_every_mode(language: str, mode: str) -> None:
    """Zakazy fabrykacji obowiązują tak samo we wszystkich trzech trybach.

    Tryb reguluje obróbkę prezentacyjną, NIGDY to, co wolno dopisać. Gdyby
    "basic" był jedynym trybem bez konfabulacji, "polished" i "tailored"
    byłyby licencją na zmyślanie — a to jest właśnie zarzut klienta.
    """
    prompt = get_prompt(language, False, mode)
    if language == "pl":
        needles = [
            "NIE wymyślaj certyfikatów",
            "NIGDY nie wymyślaj ani nie szacuj liczb",
            "NIE dedukuj ani nie dodawaj technologii",
        ]
    else:
        needles = [
            "DO NOT fabricate certifications",
            "NEVER invent or estimate numbers",
            "DO NOT deduce or add technologies",
        ]
    for needle in needles:
        assert needle.lower() in prompt.lower(), f"{mode}/{language}: brak „{needle}”"


@pytest.mark.parametrize("language", ["pl", "en"])
def test_filler_quotas_are_gone_from_every_mode(language: str) -> None:
    """Twarde kwoty minimalne zmuszały model do produkcji wypełniacza.

    Przy ubogim CV „minimum 5 kategorii umiejętności" nie da się spełnić bez
    dopisania czegoś, czego w źródle nie ma — to była instrukcja fabrykacji
    przebrana za regułę formatowania.
    """
    # Frazy dokładnie takie, jakie stały w prompcie PRZED tą zmianą — inaczej
    # test byłby pusty (zawsze zielony, bo szukałby czegoś, czego nigdy nie było).
    banned = (
        ["Wyodrębnij minimum 5 kategorii umiejętności", "Minimum 2 języki"]
        if language == "pl"
        else ["Extract at least 5 skill categories", "Minimum 2 languages"]
    )
    for mode in CONTENT_MODES:
        prompt = get_prompt(language, False, mode)
        for phrase in banned:
            assert phrase.lower() not in prompt.lower(), f"{mode}/{language}: {phrase}"


# ── Zachowanie pipeline'u (obserwowalne efekty, nie wywołania wewnętrzne) ──


@pytest.mark.parametrize("mode", ["basic", "polished"])
def test_lower_modes_never_send_the_job_ad_to_the_model(
    mode: str, captured_prompt: dict
) -> None:
    """Wymagania klienta NIE mogą trafić do modelu poniżej "tailored".

    To jest sedno odpowiedzi na zarzut „CV wygląda na pisane pod nasze
    ogłoszenie": model nie dostaje ogłoszenia, więc nie ma pod co pisać.
    """
    _, seen = _run(mode, captured_prompt)
    assert "<champion_profile>" not in seen["user"]
    assert "Kubernetes" not in seen["user"]
    assert "Utrzymanie klastrów produkcyjnych" not in seen["user"]
    # CV i notatki nadal idą — tryb ogranicza pozycjonowanie, nie materiał.
    assert "<cv>" in seen["user"]
    assert "<screening_notes>" in seen["user"]


def test_tailored_still_sends_the_champion_profile(captured_prompt: dict) -> None:
    """Regresja w drugą stronę: "tailored" ma działać jak dotąd."""
    _, seen = _run("tailored", captured_prompt)
    assert "<champion_profile>" in seen["user"]
    assert "Kubernetes" in seen["user"]


@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_default_highlighting_uses_candidate_technologies_in_every_mode(
    mode, captured_prompt
):
    result, _ = _run(mode, captured_prompt)
    assert result.render_payload["highlight_keywords"] == ["Python", "PostgreSQL"]
    # The job advert must not inject technologies absent from the source.
    assert "Kubernetes" not in result.render_payload["highlight_keywords"]


@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_header_keeps_the_candidates_own_position_in_every_mode(
    mode: str, captured_prompt: dict
) -> None:
    """Nagłówek CV nie może twierdzić, że kandydat jest tym, kogo szuka klient.

    Tytuł z ogłoszenia nadpisywał `position` we wszystkich trybach — dokument
    mówił wtedy coś, czego źródło nigdy nie powiedziało. Teraz rola docelowa
    jedzie osobnym, opisanym polem.
    """
    result, _ = _run(mode, captured_prompt)
    payload = result.render_payload
    assert payload["position"] == "Backend Developer"
    assert payload["considered_for"] == "Senior Platform Engineer (K8s)"


@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_used_mode_is_recorded_in_the_saved_payload(
    mode: str, captured_prompt: dict
) -> None:
    """Bez tego nie da się wykazać, jakim trybem powstało wysłane CV."""
    result, _ = _run(mode, captured_prompt)
    assert result.render_payload["content_mode"] == mode


@pytest.mark.parametrize("mode", CONTENT_MODES)
def test_each_mode_gets_its_own_system_prompt(mode: str, captured_prompt: dict) -> None:
    _, seen = _run(mode, captured_prompt)
    assert seen["system"] == get_prompt("pl", False, mode)
