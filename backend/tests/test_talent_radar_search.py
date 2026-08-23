"""Talent Radar — ad-hoc role in, ranked candidates out.

The composition is thin; what these tests guard are the constraints that make it
safe, because each of them is a defect this codebase has already shipped once.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import talent_radar_search as tr
from app.services.talent_radar_search import (
    RadarQuery,
    RadarResult,
    TalentRadarError,
    build_ephemeral_job,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_ephemeral_job_sets_every_attribute_the_scoring_path_reads():
    """Derived from the source, not hand-listed — a hand list rots silently.

    `build_ephemeral_job` returns a SimpleNamespace, so it has exactly what we
    put on it and nothing more. A missing attribute is an `AttributeError` in
    the middle of a live search, not a startup failure.

    The first version of this test enumerated the attributes by hand. That is
    the weaker guard: the day scoring starts reading `job.something_new`, a hand
    list still passes and only production finds out. So the expected set is
    walked out of the modules the radar actually calls. Extra attributes on the
    namespace are fine; missing ones are not.
    """

    import ast

    backend = Path(__file__).resolve().parents[1]
    required: set[str] = set()
    for module in (
        "app/services/scoring_service.py",
        "app/services/embedding_service.py",
        "app/services/pipeline_eligibility.py",
        # Dopisane po awarii na prodzie (2026-08-13): `pipeline_eligibility`
        # DELEGUJE weto do `hiring_manager_verdicts.load_manager_rejections`,
        # które czyta `job.hiring_manager_contact_id`. Skan po trzech modułach
        # tego nie widział, więc test przechodził, a każde realne wyszukanie
        # kończyło się 500. Sama lista modułów jest ostatnią ręczną rzeczą w tym
        # teście — dlatego niżej stoi drugi guard, który jedzie PRAWDZIWĄ ścieżką
        # i nie ma czego przeoczyć.
        "app/services/hiring_manager_verdicts.py",
    ):
        tree = ast.parse((backend / module).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]}
            if "job" not in params:
                continue
            required |= {
                node.attr
                for node in ast.walk(fn)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "job"
            }

    assert required, "derivation found nothing — the walk is broken, not the code"

    job = build_ephemeral_job(RadarQuery(client_id=7, text="Senior Python"))
    missing = sorted(attr for attr in required if not hasattr(job, attr))
    assert not missing, (
        f"scoring reads job.{{{','.join(missing)}}} — set it in build_ephemeral_job"
    )


# ── wymagania MUST/NICE podane wprost (za flagą) ────────────────────────────


def test_normalize_skill_names_matches_the_parser_shape():
    """Jeden normalizator dla dwóch wejść: parsera i ciała requestu.

    Parser zwraca `[{"name": …}]`, klient może POST-ować `["…"]` — a wpis bez
    `name` musi odpaść, zanim policzy go plakietka „8 must · 5 nice".
    """
    got = tr.normalize_skill_names(
        [
            {"name": "Python"},
            {"name": "   "},
            "Go",
            {"nope": 1},
            "python",  # duplikat wyłącznie wielkością liter
            None,
        ]
    )
    assert got == ["Python", "Go"], (
        "kolejność i oryginalna pisownia zostają (nazwy wracają do "
        "interfejsu), dedupe idzie po casefold"
    )
    assert tr.normalize_skill_names("Python") == []
    assert tr.normalize_skill_names(None) == []
    assert len(tr.normalize_skill_names([f"skill-{i}" for i in range(200)])) == 50
    assert len(tr.normalize_skill_names(["x" * 500])[0]) == 100


def test_structured_skills_are_off_by_default_and_off_means_identical():
    """Asercja ROLLBACKU, nie funkcji.

    Bez niej „OFF" po cichu staje się „prawie OFF" — a cała wartość tej flagi
    polega na tym, że przy OFF namespace jest bajt w bajt dzisiejszy: ten sam
    tekst zapytania, ta sama pula, te same score'y.
    """
    job = build_ephemeral_job(
        RadarQuery(
            client_id=7,
            text="Senior Python Developer",
            must_skills=["Python"],
            nice_skills=["Go"],
        )
    )
    assert job.must_skills is None and job.nice_skills is None


def test_structured_skills_reach_the_job_in_the_jsonb_shape(monkeypatch):
    """Kształt sprawdzony PRZECIW funkcji, która go naprawdę czyta.

    `canonical_skill_names` jest tym, przez co scoring przepuszcza
    `jobs.must_skills`; asercja na samym literale dowodziłaby tylko tego, jak
    ja sobie ten kształt wyobrażam.
    """
    from app.services.scoring_service import canonical_skill_names

    monkeypatch.setattr(
        tr.settings, "TALENT_RADAR_STRUCTURED_SKILLS_ENABLED", True
    )
    job = build_ephemeral_job(
        RadarQuery(client_id=7, text="x", must_skills=["Python"], nice_skills=["Go"])
    )

    assert job.must_skills == [{"name": "Python", "level": None}]
    assert job.nice_skills == [{"name": "Go", "level": None}]
    assert canonical_skill_names(job.must_skills) == ["python"]

    # Puste listy przy fladze ON dalej znaczą „brak wymagań wprost", więc
    # scoring wraca do wywodzenia ich z prozy — inaczej wklejony request
    # byłby oceniany po pustej liście.
    empty = build_ephemeral_job(RadarQuery(client_id=7, text="x", must_skills=[]))
    assert empty.must_skills is None


def test_structured_skills_change_the_query_text_not_only_the_score(monkeypatch):
    """Po co w ogóle flaga — dla recenzenta myślącego „to tylko warstwa skills".

    Nazwy wchodzą do tekstu, który Voyage zamienia na wektor zapytania, więc
    flip zmienia ZBIÓR retrievowanych kandydatów, a nie tylko ich kolejność.
    """
    from app.services.embedding_service import _build_job_text

    query = RadarQuery(client_id=7, text="Zbudujemy platformę", must_skills=["Kafka"])

    off = _build_job_text(build_ephemeral_job(query))
    monkeypatch.setattr(
        tr.settings, "TALENT_RADAR_STRUCTURED_SKILLS_ENABLED", True
    )
    on = _build_job_text(build_ephemeral_job(query))

    assert "Kafka" not in off
    assert "Kafka" in on


def test_radar_flag_stays_out_of_the_score_cache_key():
    """Świadoma NIEobecność, zamrożona razem z powodem.

    Radar liczy score'y z pominięciem cache (`rank_candidates_for_job`, nie
    `bulk_get_or_compute` — pilnuje tego test niżej), więc ta flaga nie ma jak
    wyprodukować nieaktualnego wiersza. Dopisanie jej tutaj unieważniłoby
    CAŁĄ tabelę score'ów przy każdym flipie, za zero korekty.

    Gdyby radar kiedyś przeszedł na cache, ten test jest miejscem, w którym
    decyzja musi zostać odwrócona.
    """
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "TALENT_RADAR_STRUCTURED_SKILLS_ENABLED" not in _SCORING_CACHE_INPUTS


def test_ephemeral_job_has_no_id_so_it_cannot_touch_pipeline_history():
    """`id=None` is load-bearing, not a placeholder.

    `build_job_scoring_context` filters `CandidateStage.job_id == job.id`; a real
    id would pull another job's screening answers into an unrelated search.
    """
    job = build_ephemeral_job(RadarQuery(client_id=7, text="x"))
    assert job.id is None


def test_client_is_carried_onto_the_job_or_conflicts_cannot_be_checked():
    job = build_ephemeral_job(RadarQuery(client_id=42, text="x"))
    assert job.client_id == 42, (
        "the eligibility filter reads client_id — losing it here would silently "
        "skip NDA, competitor and veto checks"
    )


@pytest.mark.asyncio
async def test_empty_query_is_refused_before_any_paid_call():
    class _DB:
        async def scalar(self, *_a, **_k):  # pragma: no cover - must not be reached
            raise AssertionError("no DB work before the input is validated")

    with pytest.raises(TalentRadarError):
        await tr.search(_DB(), RadarQuery(client_id=1))


@pytest.mark.asyncio
async def test_unknown_client_is_refused_rather_than_searched_unfiltered():
    """The whole point of the mandatory client.

    Answering without one would produce a list whose NDA / competitor / veto
    checks silently passed — the `/ai-matches` defect, rebuilt on a new surface.
    """

    class _DB:
        async def scalar(self, *_a, **_k):
            return None  # no such client

    with pytest.raises(TalentRadarError) as exc:
        await tr.search(_DB(), RadarQuery(client_id=999, text="Senior Python"))

    assert "klienta" in str(exc.value).lower()


def test_degraded_retrieval_is_reported_not_rendered_as_no_matches():
    result = RadarResult(
        breakdowns=[], pool_size=0, eligible_size=0, degraded=True, reason="x"
    )
    meta = result.as_meta()
    assert meta["degraded"] is True, (
        "an empty list from a broken provider must be distinguishable from "
        "'we have nobody like that'"
    )


from tests._ast_calls import calls_in as _calls_in

def test_search_enforces_eligibility():
    assert "filter_eligible_candidates" in _calls_in(
        "app/services/talent_radar_search.py", "search"
    ), "Talent Radar would surface candidates the recruiter cannot assign"


def test_search_does_not_write_the_score_cache():
    """The cache key is (candidate, job, profile) and this job has no id.

    Using `bulk_get_or_compute` here would either collide across unrelated
    ad-hoc searches or write rows keyed on a null job.
    """
    calls = _calls_in("app/services/talent_radar_search.py", "search")
    assert "rank_candidates_for_job" in calls
    assert "bulk_get_or_compute" not in calls


def test_module_makes_no_llm_call():
    """One Voyage query embedding, nothing else — so the module is free to use.

    Implicit must-skills come from `_score_skills`' existing JD/Champion
    fallback, which is why no parse step is needed.
    """
    src = (BACKEND / "app/services/talent_radar_search.py").read_text(encoding="utf-8")
    for forbidden in ("parse_cv", "call_claude", "ai_feature"):
        assert forbidden not in src, (
            f"{forbidden} would add per-search spend and a quota gate to a "
            "module that currently needs neither"
        )


def test_endpoint_module_has_no_future_annotations_import():
    """PEP 563 turns the body model into a ForwardRef and FastAPI then resolves
    it as a *Query* parameter, which fails while building the OpenAPI schema.

    `cv_match_preview` carries the same warning in its own docstring; this module
    was written by copying that pattern and adding the import anyway, so the
    guard lives here as well as in prose.
    """
    # Parsed, not grepped: the module docstring *mentions* the import in order
    # to warn about it, so a substring check fails on its own warning.
    tree = ast.parse((BACKEND / "app/api/talent_radar.py").read_text(encoding="utf-8"))
    future_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    assert "annotations" not in future_imports, (
        "PEP 563 breaks FastAPI body resolution on this endpoint"
    )


def test_result_rows_carry_the_person_not_just_an_id():
    """A ranked list of integers is not a list a recruiter can read.

    `ScoreBreakdown` holds `candidate_id` and scoring layers — nothing about
    who that is. Shipping it unchanged would force the browser to resolve every
    id one by one, an N+1 over the network across data this endpoint already
    holds in memory.
    """

    candidate = SimpleNamespace(
        id=7,
        name="Anna",
        lastname="Kowalska",
        location="Kraków, PL",
        competence_category="software_development",
        years_it_experience=8,
        availability_status=None,
        champion=True,
        avatar_url=None,
    )

    shaped = tr.shape_radar_candidate(candidate)

    assert shaped["id"] == 7
    assert shaped["name"] == "Anna" and shaped["lastname"] == "Kowalska"
    assert shaped["champion"] is True
    assert "email" not in shaped, (
        "a triage list decides whom to open, not whom to write to — contact "
        "details belong on the profile behind the click, not in every response"
    )
    assert "expected_rate_hourly" not in shaped and "phone" not in shaped


def _breakdown_with_salary_status(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id=7,
        as_dict=lambda: {
            "candidate_id": 7,
            "total": 61.0,
            "salary": {
                "points": 12.0,
                "max": 15,
                "reason": "w budżecie Championa (120 ≤ 150 PLN/h)",
                "status": status,
            },
        },
    )


def test_scored_salary_layer_is_redacted_not_declared_inapplicable():
    """The numbers stay hidden; the STATUS has to stop lying about why.

    This endpoint used to blank the layer as `not_applicable` unconditionally,
    on the premise that a radar query carries no budget so `_score_salary`
    short-circuits. That premise died with the Champion signals: an uploaded
    profile carries `rate_value`, a candidate carries `expected_rate_hourly`,
    and the layer then scores for real — those points are inside `total`. A
    card claiming "not applicable" was denying the existence of the very reason
    someone had slipped down the ranking.

    Withholding the numbers is a separate, still-valid decision: they are a
    linear function of a rate the recruiter already knows, so publishing them
    would recover the candidate's expected rate to the złoty — from a list that
    deliberately does not carry it (`test_result_rows_carry_the_person…`).
    """

    from app.api.talent_radar import _shape_result

    shaped = _shape_result(_breakdown_with_salary_status("scored"), None)

    assert shaped["salary"] == {
        "points": None,
        "max": None,
        "reason": None,
        "status": "redacted",
    }
    assert shaped["candidate"] is None, "a vanished row must not crash the response"


@pytest.mark.parametrize("status", ["unknown", "not_comparable"])
def test_unscored_salary_layer_stays_not_applicable(status: str):
    """The honest case keeps the honest word.

    Pasted text (no Champion rate) or a candidate with no rate: the layer had
    nothing to judge, so it did not enter `total` and "not applicable" is
    exactly what happened.
    """

    from app.api.talent_radar import _shape_result

    shaped = _shape_result(_breakdown_with_salary_status(status), None)

    assert shaped["salary"]["status"] == "not_applicable"


def test_salary_layer_is_really_scored_on_the_radar_path(monkeypatch):
    """Closes the reasoning above with a run, not with a paragraph.

    Without this, the only evidence that `not_applicable` was a lie is someone
    reading `_score_salary`. Here the radar's own ephemeral job is fed to the
    real scorer: Champion rate in, candidate rate in, `scored` out.
    """
    from app.services import scoring_service

    monkeypatch.setattr(
        scoring_service.settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True
    )

    job = build_ephemeral_job(
        RadarQuery(
            client_id=7,
            champion_profile={"rate_value": 150.0},
            title="Senior Python Developer",
        )
    )
    candidate = SimpleNamespace(
        id=7,
        expected_rate_hourly=120.0,
        expected_rate_currency=None,  # NULL = udokumentowane legacy PLN
        cv_extracted_data=None,
    )

    layer = scoring_service._score_salary(candidate, job)

    assert layer.scored is True, (
        "the radar path really does score money — this is what made the "
        "unconditional `not_applicable` a false statement about the result"
    )
    assert layer.points > 0


# ── trasa `parse-champion`: co wraca i jak nazywa awarię ────────────────────


class _FakeUpload:
    """Tyle z `UploadFile`, ile ta trasa naprawdę czyta."""

    filename = "profil-championa.docx"
    size = 4096

    async def read(self) -> bytes:
        return b"x" * 4096


def _parse_champion_handler():
    """Ciało handlera bez dekoratora rate-limitu.

    `@limiter.limit` chce prawdziwego `Request` z limiterem w `app.state`;
    testowane jest ciało, nie slowapi. `functools.wraps` zostawia oryginał pod
    `__wrapped__` — gdyby przestał, ten test padnie głośno i od razu.
    """
    from app.api.talent_radar import talent_radar_parse_champion

    return talent_radar_parse_champion.__wrapped__


def _stub_champion_path(monkeypatch, *, parsed=None, error=None):
    """Podmienia wszystko, co ta trasa woła poza swoim własnym ciałem.

    Importy w handlerze są lokalne, więc rozwiązują się z modułu w czasie
    wywołania — podmiana atrybutów modułu wystarcza i nie wymaga ani DB, ani
    HTTP, ani klucza do dostawcy.
    """
    import contextlib

    from app.services import ai_quota
    from app.services import champion_profile_ingest as ingest

    monkeypatch.setattr(ingest, "oversize_precheck", lambda *_a, **_k: None)
    monkeypatch.setattr(ingest, "validate_upload", lambda *_a, **_k: None)
    monkeypatch.setattr(ingest, "extract_document_text", lambda *_a, **_k: "t" * 500)

    async def _parse(_text):
        if error is not None:
            raise error
        return parsed or {}

    monkeypatch.setattr(ingest, "parse_champion_document", _parse)

    @contextlib.asynccontextmanager
    async def _feature(*_a, **_k):
        yield None

    monkeypatch.setattr(ai_quota, "ai_feature", _feature)


@pytest.mark.asyncio
async def test_parse_champion_response_carries_the_lists(monkeypatch):
    """Zbiór KLUCZY tej odpowiedzi jest kontraktem, na którym stoi front.

    Endpoint parsował wymagania, pokazywał „8 must · 5 nice" i je WYRZUCAŁ —
    a `build_champion_dict` ich nie kopiuje, więc po odrzuceniu odpowiedzi
    listy nie istniały już nigdzie i ranking wywodził wymagania z prozy.
    """
    _stub_champion_path(
        monkeypatch,
        parsed={
            "role_name": "Senior Python Developer",
            "must_skills": [{"name": "Python"}, {"name": "  "}, {"name": "python"}],
            "nice_skills": [{"name": "Go"}],
            "rate_value": 150.0,
        },
    )

    out = await _parse_champion_handler()(
        request=None, current_user=None, file=_FakeUpload(), db=None
    )

    assert out["must_skills"] == ["Python"]
    assert out["nice_skills"] == ["Go"]
    assert out["summary"]["must_count"] == len(out["must_skills"]), (
        "plakietka ma liczyć to, co POJEDZIE do rankingu — wpis bez nazwy "
        "odpada w normalizacji, więc licznik z surowej listy zawyżałby"
    )
    assert out["champion_profile"]["_source"] == "talent_radar_upload"


@pytest.mark.asyncio
async def test_provider_outage_is_a_503_not_a_corsless_500(monkeypatch):
    """Awaria dostawcy ≠ zepsuty plik.

    `parse_champion_document` zamienia na `ValueError` wyłącznie błędy
    parsowania ODPOWIEDZI; 529/timeout/zerwane połączenie leciały wyżej i
    kończyły się 500, a 500 z tej trasy nie niesie nagłówków CORS — w
    przeglądarce widać było „Network Error". Rekruter czytał to jako „ten plik
    jest zepsuty" i próbował kolejnych zamiast poczekać minutę.
    """
    import anthropic
    import httpx
    from fastapi import HTTPException

    _stub_champion_path(
        monkeypatch,
        error=anthropic.APITimeoutError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await _parse_champion_handler()(
            request=None, current_user=None, file=_FakeUpload(), db=None
        )

    assert exc.value.status_code == 503
    assert "niedost" in exc.value.detail.lower(), (
        "komunikat musi mówić o dostawcy, nie o dokumencie"
    )


@pytest.mark.asyncio
async def test_unparsable_document_still_maps_to_422(monkeypatch):
    """Nowa gałąź nie może połknąć starej: 422 dalej znaczy „popraw plik"."""
    from fastapi import HTTPException

    _stub_champion_path(monkeypatch, error=ValueError("nieparsowalny JSON profilu"))

    with pytest.raises(HTTPException) as exc:
        await _parse_champion_handler()(
            request=None, current_user=None, file=_FakeUpload(), db=None
        )

    assert exc.value.status_code == 422


async def test_search_survives_the_real_eligibility_path(monkeypatch):
    """Guard, który nie ma czego przeoczyć: pełne `search()` po PRAWDZIWEJ ścieżce.

    Test wyżej (skan AST) wylicza atrybuty z RĘCZNEJ listy modułów i właśnie na
    tym się przewrócił: `pipeline_eligibility` deleguje weto do
    `hiring_manager_verdicts`, którego na liście nie było, więc brak
    `job.hiring_manager_contact_id` przeszedł przez CI i wywalał każde realne
    wyszukanie na prodzie (500). Ten test nie enumeruje niczego — podstawia
    tylko retrieval (jedyną zależność zewnętrzną: Voyage + Qdrant) i puszcza
    resztę łańcucha na żywo, więc KAŻDY brakujący atrybut wychodzi tu, a nie u
    użytkownika.

    Pusta pula jest osobnym, łagodnym przypadkiem (`degraded=True`) i wychodzi
    z `search()` ZANIM dotknie eligibility — dlatego awaria nie pokazywała się
    na ścieżce „retrieval leży", tylko na tej, która miała działać.
    """
    import uuid as _uuid

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.services import talent_radar_search as mod

    async with AsyncSessionLocal() as db:
        client = Client(name=f"RadarE2E-{_uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        cand = Candidate(
            name="Radar",
            lastname=f"E2E-{_uuid.uuid4().hex[:6]}",
            email=f"radar-{_uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)

        # `bm25_query` doszedł razem z ożywieniem nogi BM25 (noga dostawała cały
        # dokument oferty, a `websearch_to_tsquery` ANDuje leksemy, więc zwracała
        # pustkę zawsze). Atrapa MUSI przyjmować komplet kwargów realnej fasady —
        # inaczej ten test przewraca się na sygnaturze zamiast na tym, czego pilnuje.
        async def _fake_pool(
            _db,
            _text,
            *,
            top_k,
            raise_on_error=False,
            query_variants=None,
            bm25_query=None,
        ):
            return [{"candidate_id": cand.id, "score": 0.71}]

        monkeypatch.setattr(mod, "retrieve_candidate_pool", _fake_pool)

        try:
            result = await mod.search(
                db,
                mod.RadarQuery(
                    client_id=client.id,
                    text="Senior DevOps Engineer, Kubernetes, Terraform, AWS",
                    top_k=5,
                ),
            )
        finally:
            # `search()` niczego nie zapisuje, więc sprzątanie jest bezpieczne —
            # a bez niego każdy przebieg zostawiałby wiersze w bazie i psuł testy,
            # które liczą rekordy (paginacja list, inwentarze).
            await db.delete(cand)
            await db.delete(client)
            await db.commit()

    assert result.degraded is False
    assert result.pool_size == 1, "kandydat z puli musi dojść do rankingu"
