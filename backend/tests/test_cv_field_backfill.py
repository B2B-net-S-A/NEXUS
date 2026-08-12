"""Fala 3: hydraulika parsera + runner masowego uzupełniania pól z CV.

Trzy rzeczy, które ten plik przybija, bo każda była realną decyzją:

* prompt MASOWY nie zawiera pól generatywnych, a prompt INTERAKTYWNY pozostaje
  nietknięty (jego hash wchodzi w klucze cache i steruje zachowaniem ścieżki
  rekrutera);
* kwota gasi wyłącznie PŁATNY krok parsera — darmowe fallbacki działają dalej,
  a w biegu masowym wyczerpana kwota zatrzymuje BIEG, nie wiersz;
* `[]` w skills liczy się jako puste (33 625 wierszy trzyma pustą tablicę).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services.cv_field_backfill import _empty_now
from app.services.llm_prompts import CV_ENRICHMENT, CV_ENRICHMENT_BULK


def test_bulk_prompt_has_no_generative_fields():
    """Backfill prosi o fakty, nie o polszczyznę.

    `professional_profile` i `career_summary` to ~35-40% tokenów wyjścia
    (wyjście = ~59% rachunku przy Haiku) i zarazem najtrudniejsza kompetencja
    dla tańszego modelu. Wycięcie ich jest tańsze i bezpieczniejsze naraz.
    """

    rendered = CV_ENRICHMENT_BULK.render(cv_text="x")
    assert "professional_profile" not in rendered
    assert "career_summary" not in rendered
    # pola celu zostają
    for field in ("skills", "city", "years_it_experience", "education"):
        assert field in rendered, field


def test_interactive_prompt_is_untouched():
    """Zmiana treści CV_ENRICHMENT zmienia zachowanie ścieżki rekrutera i
    unieważnia cache oparty o hash promptu — dlatego wariant masowy jest NOWYM
    szablonem, a ten test zamraża, że stary nie drgnął."""

    assert CV_ENRICHMENT.name == "cv_enrichment"
    assert CV_ENRICHMENT.version == 5
    rendered = CV_ENRICHMENT.render(cv_text="x")
    assert "professional_profile" in rendered
    assert "career_summary" in rendered


def test_empty_skills_list_counts_as_empty():
    """33 625 wierszy trzyma skills='[]'; realną listę ma ~600 osób.

    Gdyby `[]` liczyło się jako wypełnione, backfill ominąłby praktycznie
    całą populację, dla której powstał.
    """

    candidate = SimpleNamespace(skills=[], city=None, years_it_experience=None)
    assert _empty_now(candidate) == {"skills", "city", "years_it_experience"}

    candidate = SimpleNamespace(
        skills=[{"name": "Python"}], city="Kraków", years_it_experience=5
    )
    assert _empty_now(candidate) == set()


class _FakeUsage:
    input_tokens = 3111
    output_tokens = 642


class _FakeBlock:
    text = '{"city": "Kraków", "_confidence": {"city": 0.9}}'


class _FakeMessage:
    content = [_FakeBlock()]
    usage = _FakeUsage()


@pytest.mark.asyncio
async def test_parse_with_claude_captures_usage_and_template_identity(monkeypatch):
    """`message.usage` szło do kosza — a bez niego kosztorys biegu to zgadywanka."""

    from app.core.config import settings
    from app.services import claude_client
    from app.services.cv_parser import _parse_with_claude
    from app.services.llm_prompts import CV_ENRICHMENT_BULK

    seen: dict = {}

    def fake_call_claude(**kwargs):
        seen.update(kwargs)
        return _FakeMessage()

    monkeypatch.setattr(claude_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "CV_ENRICHMENT_ENABLED", True, raising=False)

    parsed = await _parse_with_claude(
        "CV treść", model="claude-haiku-4-5-20251001", template=CV_ENRICHMENT_BULK
    )

    assert parsed is not None
    assert seen["model"] == "claude-haiku-4-5-20251001"
    # Wersja wyprowadzona ze stałej: asercja pilnuje, że tożsamość szablonu
    # PŁYNIE do _source, a nie konkretnego numeru (bump wersji to nie regresja).
    assert parsed["_source"] == (
        f"claude:cv_enrichment_bulk:v{CV_ENRICHMENT_BULK.version}"
    )
    assert parsed["_usage"] == {
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": 3111,
        "output_tokens": 642,
    }


@pytest.mark.asyncio
async def test_quota_gates_only_the_paid_step_fallbacks_survive(monkeypatch):
    """Wyczerpana kwota NIE może gasić darmowych heurystyk.

    Onboarding z CV bez LLM nadal wyciąga kontakt regexem — kwota na płatny
    model nie jest powodem, żeby stracić także to, co nic nie kosztuje.
    """

    from app.services import cv_parser as parser_module
    from app.services.ai_quota import AIQuotaExceeded

    async def exploding_claude(*args, **kwargs):  # pragma: no cover - nie wolno
        raise AssertionError("płatny krok nie może być wywołany przy odmowie kwoty")

    monkeypatch.setattr(parser_module, "_parse_with_claude", exploding_claude)

    class _DenyingFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            from app.models.ai_feature import AIFeatureKey

            raise AIQuotaExceeded(AIFeatureKey.cv_parser, "limit")

        async def __aexit__(self, *exc):
            return False

    import app.services.ai_quota as quota_module

    monkeypatch.setattr(quota_module, "ai_feature", _DenyingFeature)

    # Ollama wyłączona wprost (Settings pydantica nie przyjmie obcego pola) —
    # wynik MUSI przyjść z darmowego regexu.
    async def no_ollama(*args, **kwargs):
        return None

    monkeypatch.setattr(parser_module, "_parse_with_ollama", no_ollama)

    result = await parser_module.parse_cv(
        "Jan Kowalski\njan.kowalski@example.com\n+48 600 123 456",
        db=object(),  # cokolwiek nie-None: włącza gałąź bramkowaną
    )

    assert result["email"] == "jan.kowalski@example.com"


@pytest.mark.asyncio
async def test_backfill_run_stops_on_quota_not_per_row(monkeypatch):
    """Kwota to hamulec organizacyjny — bieg staje, kursor zostaje."""

    from app.services import cv_field_backfill as runner
    from app.services.ai_quota import AIQuotaExceeded

    class _DenyingFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            from app.models.ai_feature import AIFeatureKey

            raise AIQuotaExceeded(AIFeatureKey.cv_backfill, "limit miesięczny")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runner, "ai_feature", _DenyingFeature)

    candidate = SimpleNamespace(
        id=7, skills=[], city=None, years_it_experience=None, raw_cv_text="x" * 300
    )

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeDb:
        def __init__(self):
            self.calls = 0

        async def execute(self, *_a, **_k):
            self.calls += 1
            return _FakeResult([candidate] if self.calls == 1 else [])

        async def commit(self):
            pass

    stats = await runner.backfill_cv_fields(_FakeDb())

    assert stats["stopped_reason"].startswith("quota")
    assert stats["last_id"] == 7, "kursor musi wskazywać, od czego wznowić"


def test_bulk_prompt_asks_for_country_and_apply_consumes_it():
    """Bez tego drugi pełny bieg byłby nieunikniony.

    Plan odnotował lukę: `country` nie było ekstrahowane, więc projekcja
    `location` kończyła się na samym mieście — a ścieżka zapisu i tak by kraj
    wyrzuciła, bo nigdy po niego nie sięgała. Pytanie użytkownika „czy
    wyciągamy wszystko?" złapało to PRZED biegiem, nie po nim.
    """

    rendered = CV_ENRICHMENT_BULK.render(cv_text="x")
    assert '"country"' in rendered

    from types import SimpleNamespace as NS

    from app.services.cv_enrichment import _apply_cv_enrichment

    candidate = NS(
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        skills=None,
        education=None,
        years_it_experience=None,
        ai_summary=None,
        experience=None,
        cv_extracted_data=None,
        current_position=None,
        languages=None,
    )
    _apply_cv_enrichment(
        candidate,
        {"city": "Kraków", "country": "PL", "_confidence": {}},
    )
    assert candidate.country == "PL"
    assert candidate.location == "Kraków, PL", (
        "projekcja location musi nieść też kraj — dotąd kończyła się na mieście"
    )


@pytest.mark.asyncio
async def test_updated_candidates_are_enqueued_for_reembedding(monkeypatch):
    """Praca Claude'a musi DOTRZEĆ do Voyage — inaczej jest niewidzialna.

    Tekst embeddingu kandydata zawiera skills/kategorię; wypełnienie pól bez
    oznaczenia do re-embeddingu zostawia wektory stare. Ta luka zjadła Falę 1
    (naprawa w #1096) — i wróciła w pierwszej wersji tego runnera; wyszła przy
    pytaniu „jak wykorzystać Claude'a, żeby Voyage działał lepiej".
    """

    from app.services import cv_field_backfill as runner

    class _OkFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    async def fake_parse(cv_text, *, model, template):
        return {"city": "Kraków", "_confidence": {}}

    enqueued: list[list[int]] = []

    async def fake_reindex(db, entity, ids):
        enqueued.append(list(ids))
        return len(ids)

    monkeypatch.setattr(runner, "ai_feature", _OkFeature)
    monkeypatch.setattr(runner, "parse_cv_with_claude", fake_parse)
    import app.services.index_outbox_service as outbox

    monkeypatch.setattr(outbox, "record_bulk_reindex", fake_reindex)
    monkeypatch.setattr(runner, "SLEEP_BETWEEN_CALLS_S", 0)

    candidate = SimpleNamespace(
        id=11,
        skills=None,
        city=None,
        country=None,
        location=None,
        years_it_experience=None,
        raw_cv_text="x" * 300,
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        education=None,
        ai_summary=None,
        experience=None,
        cv_extracted_data=None,
        current_position=None,
        languages=None,
    )

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeDb:
        def __init__(self):
            self.calls = 0

        async def execute(self, *_a, **_k):
            self.calls += 1
            return _FakeResult([candidate] if self.calls == 1 else [])

        async def commit(self):
            pass

        async def flush(self):
            pass

        def begin_nested(self):
            class _Savepoint:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *exc):
                    return False

            return _Savepoint()

    stats = await runner.backfill_cv_fields(_FakeDb())

    assert stats["updated"] == 1
    assert stats["reindex_enqueued"] == 1
    assert enqueued == [[11]], (
        "zaktualizowany kandydat musi trafić do outboxu reindeksu — bez tego "
        "jego wektor zostaje stary i Voyage nie widzi nowych pól"
    )


@pytest.mark.asyncio
async def test_calibration_log_path_is_confined_to_tmp():
    """P0 z review: parametr admina szedł prosto do open(..., 'a').

    Dopisanie fragmentu do entrypoint.sh wykonuje się przy najbliższym
    restarcie, a Coolify restartuje kontener przy każdym pushu. `resolve()`
    przed sprawdzeniem — `/tmp/../etc/x` nie może przejść po literach.
    """

    from app.services.cv_field_backfill import backfill_cv_fields

    class _NoRowsDb:
        async def execute(self, *a, **k):
            raise AssertionError("nie powinno dojść do zapytania")

        async def commit(self):
            pass

    for evil in ("/etc/hosts", "/tmp/../root/.bashrc", "relative.jsonl"):
        with pytest.raises(ValueError, match="tmp"):
            await backfill_cv_fields(_NoRowsDb(), calibration_log_path=evil)


def test_usage_metadata_never_persists_to_the_candidate_profile():
    """`cv_extracted_data` wychodzi do KAŻDEGO zalogowanego przez API.

    Tokeny i model to metadane rozliczeniowe wywołania, nie dane kandydata —
    zostają w statystykach biegu i logach, znikają przed zapisem profilu.
    """

    from types import SimpleNamespace as NS

    from app.services.cv_enrichment import _apply_cv_enrichment

    candidate = NS(
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        skills=None,
        education=None,
        years_it_experience=None,
        ai_summary=None,
        experience=None,
        cv_extracted_data=None,
        current_position=None,
        languages=None,
    )
    _apply_cv_enrichment(
        candidate,
        {
            "city": "Kraków",
            "_usage": {"input_tokens": 3000, "model": "haiku"},
            "_confidence": {},
        },
    )
    assert "_usage" not in (candidate.cv_extracted_data or {}), (
        "metadane rozliczeniowe nie mogą wyciekać na profil kandydata"
    )


@pytest.mark.asyncio
async def test_until_id_caps_the_scope_query():
    """Shard równoległy nie może wyjść poza swój zakres.

    `until_id` istnieje, żeby N procesów CLI mogło orać rozłączne zakresy id
    (zmierzone tempo sekwencyjne: ~375 wierszy/h ⇒ ~5,5 doby na pełny scope).
    Bez górnej granicy w SQL proces po wyczerpaniu swojego zakresu wchodziłby
    w zakres sąsiada i płacił drugi raz za jego nieprzerobione wiersze —
    dlatego zamrażamy obecność warunku W ZAPYTANIU, nie w pętli.
    """

    from app.services import cv_field_backfill as runner

    captured: list = []

    class _FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class _FakeDb:
        async def execute(self, stmt, *_a, **_k):
            captured.append(stmt)
            return _FakeResult()

        async def commit(self):
            pass

    await runner.backfill_cv_fields(_FakeDb(), after_id=20_000, until_id=40_000)
    await runner.backfill_cv_fields(_FakeDb(), after_id=20_000)

    def _sql(stmt) -> str:
        return str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    capped, uncapped = _sql(captured[0]), _sql(captured[1])
    assert "candidates.id > 20000" in capped
    assert "candidates.id <= 40000" in capped
    assert "candidates.id <= " not in uncapped, (
        "bez until_id nie może istnieć górna granica — pełny bieg ma dojść "
        "do końca tabeli"
    )


def _quarantine_candidate(cid: int, email=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid,
        skills=None,
        city=None,
        country=None,
        location=None,
        years_it_experience=None,
        raw_cv_text="x" * 300,
        first_name=None,
        last_name=None,
        email=email,
        phone=None,
        education=None,
        ai_summary=None,
        experience=None,
        cv_extracted_data=None,
        current_position=None,
        languages=None,
    )


class _QuarantineDb:
    """Fałszka z pełnym protokołem runnera: execute/scalar/flush/savepoint."""

    def __init__(self, rows, *, email_taken=False, flush_fails_for=()):
        self._pages = [rows, []]
        self.email_taken = email_taken
        self.flush_fails_for = set(flush_fails_for)
        self.current_row_id = None
        self.scalar_calls = 0

    async def execute(self, *_a, **_k):
        rows = self._pages.pop(0) if self._pages else []

        class _R:
            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return rows

        return _R()

    async def scalar(self, *_a, **_k):
        self.scalar_calls += 1
        return 1 if self.email_taken else 0

    async def commit(self):
        pass

    async def flush(self):
        if self.current_row_id in self.flush_fails_for:
            raise RuntimeError(f"constraint violated for id={self.current_row_id}")

    def begin_nested(self):
        class _Savepoint:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *exc):
                return False

        return _Savepoint()


def _install_quarantine_runner_fakes(monkeypatch, runner, parse_result):
    class _OkFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    async def fake_parse(cv_text, *, model, template):
        return dict(parse_result)

    async def fake_reindex(db, entity, ids):
        return len(ids)

    monkeypatch.setattr(runner, "ai_feature", _OkFeature)
    monkeypatch.setattr(runner, "parse_cv_with_claude", fake_parse)
    import app.services.index_outbox_service as outbox

    monkeypatch.setattr(outbox, "record_bulk_reindex", fake_reindex)
    monkeypatch.setattr(runner, "SLEEP_BETWEEN_CALLS_S", 0)


@pytest.mark.asyncio
async def test_email_collision_drops_the_field_not_the_row(monkeypatch):
    """Adres należący do INNEGO kandydata wypada; reszta wiersza się zapisuje.

    `ix_candidates_email` jest UNIQUE, a FILL_EMPTY chroni tylko przed
    nadpisaniem własnego wiersza. Bez pre-checku jeden duplikat osoby w bazie
    (id=67377, 22 wznowienia shardu C) zabijał cały bieg na commicie paczki —
    i launcher płacił LLM ponownie za całą paczkę przy każdym wznowieniu.
    """

    from app.services import cv_field_backfill as runner

    _install_quarantine_runner_fakes(
        monkeypatch,
        runner,
        {"email": "zajety@example.com", "city": "Kraków", "_confidence": {}},
    )

    db = _QuarantineDb([_quarantine_candidate(101)], email_taken=True)
    stats = await runner.backfill_cv_fields(db)

    assert stats["email_collisions"] == 1
    assert db.scalar_calls == 1, "pre-check musi pytać bazę o kolizję"
    assert stats["updated"] == 1, "reszta pól (city) ma się zapisać mimo kolizji"
    assert stats["errors"] == 0


@pytest.mark.asyncio
async def test_constraint_violation_quarantines_row_not_run(monkeypatch):
    """Naruszenie constraintu na flushu kosztuje JEDEN wiersz, nie bieg.

    Przed poprawką wychodziło dopiero na commicie paczki: ginęły też wiersze
    już opłacone w tej paczce, a wznowienie płaciło za nie drugi raz.
    """

    from app.services import cv_field_backfill as runner

    _install_quarantine_runner_fakes(
        monkeypatch, runner, {"city": "Kraków", "_confidence": {}}
    )

    poisoned = _quarantine_candidate(201)
    healthy = _quarantine_candidate(202)
    db = _QuarantineDb([poisoned, healthy], flush_fails_for={201})

    # `flush_fails_for` odpala się po `current_row_id`, ustawianym w rytmie
    # wywołań parse (parse → apply → flush dla tego samego wiersza).
    order = iter([201, 202])

    async def fake_parse_tracking(cv_text, *, model, template):
        db.current_row_id = next(order)
        return {"city": "Kraków", "_confidence": {}}

    monkeypatch.setattr(runner, "parse_cv_with_claude", fake_parse_tracking)

    stats = await runner.backfill_cv_fields(db)

    assert stats["errors"] == 1, "zatruty wiersz policzony jako błąd"
    assert stats["updated"] == 1, "zdrowy wiersz z tej samej paczki przeżył"
    assert stats["stopped_reason"] == "done", "bieg dobiegł końca mimo trucizny"
