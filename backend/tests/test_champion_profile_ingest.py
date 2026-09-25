"""Champion ingest — kontrakty FILL_EMPTY, walidacji uploadu i CORS."""

from types import SimpleNamespace

import pytest

from app.services.champion_profile_ingest import (
    PARSER_VERSION,
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    build_champion_dict,
    validate_upload,
)


def test_champion_dict_shape_is_the_seven_sections():
    """Parser produkuje siedem sekcji szablonu 09.2026.

    Wejście jest CELOWO w kształcie v3 (płaskie `rate_value`, `must_skills`):
    dokument sparsowany starszym promptem musi trafić do właściwych sekcji, bo
    inaczej ponowne przetworzenie któregokolwiek z 1095 plików importu
    sierpniowego gubiłoby stawkę i listę technologii.
    """
    parsed = {
        "role_name": "Analityk",
        "rate_value": 145.0,
        "location": "Warszawa",
        "basics": {"onsite_days_per_week": 2},
        "must_skills": [{"name": "SQL"}],
    }
    d = build_champion_dict(parsed, 262275)
    assert d["basics"]["rate_value"] == 145.0
    assert d["basics"]["role_name"] == "Analityk"
    assert d["basics"]["candidate_location_pref"] == "Warszawa"
    assert d["stack"]["must"] == [{"name": "SQL"}]
    assert d["_source"] == "traffit_recruitment_file:262275"
    # Wersja czytana Z MODUŁU, nie przybita literałem: bump promptu jest
    # normalną zmianą (v3 → v4 → v5), a test ma pilnować, że stempel W OGÓLE
    # trafia do profilu — bo bez niego nie da się odróżnić dokumentu
    # sparsowanego starym promptem od nowego.
    assert d["_parser"] == PARSER_VERSION
    # Wszystkie siedem sekcji istnieje ZAWSZE — konsument czytający brakującą
    # sekcję dostałby pustkę nie do odróżnienia od „nie ma takich danych".
    for key in (
        "basics",
        "search",
        "stack",
        "project",
        "screening_questions",
        "client",
        "documents",
    ):
        assert key in d


def test_validate_upload_rules():
    assert validate_upload("profil.docx", 1000, "4831") is None
    assert validate_upload("profil.pdf", 1000, "4831") is None
    assert "rozszerzenia" in validate_upload("profil.exe", 1000, "4831").lower()
    assert "pusty" in validate_upload("profil.docx", 0, "4831").lower()
    assert "limit" in validate_upload("profil.docx", MAX_FILE_BYTES + 1, "4831")
    assert "liczbą" in validate_upload("profil.docx", 1000, "abc")
    assert set(ALLOWED_EXTENSIONS) == {"docx", "pdf"}


@pytest.mark.asyncio
async def test_ingest_fill_empty_never_overwrites(monkeypatch):
    """Profil i skills tylko na PUSTE — istniejące dane są nietykalne."""
    import app.services.champion_profile_ingest as m

    job = SimpleNamespace(
        id=7,
        external_source="traffit",
        external_id="4831",
        champion_profile={"role_name": "ISTNIEJĄCY"},
        must_skills=[{"name": "Java"}],
        nice_skills=[{"name": "Docker"}],
        # Kolumny trzech rubryk (0278) — `ingest_parsed_profile` woła
        # `fill_job_columns_from_champion`, które je czyta i zapisuje.
        # Atrapa bez nich mierzyłaby własny kształt, nie kod.
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        # Tytuł dla rekrutera (0380) — import przelicza go przy włączonym
        # automacie; atrapa ma automat wyłączony, więc nic nie czyta z bazy.
        working_title=None,
        working_title_auto=False,
        location=None,
    )

    class _Res:
        def scalar_one_or_none(self):
            return job

    class _Db:
        async def execute(self, stmt):
            return _Res()

        async def commit(self):
            raise AssertionError("nic się nie zmieniło — commit nie może zajść")

    parsed = {"must_skills": [{"name": "SQL"}], "nice_skills": [{"name": "GIT"}]}
    out = await m.ingest_parsed_profile(
        _Db(), external_rid=4831, file_id=1, parsed=parsed
    )
    assert out["outcome"] == "champion_skipped_nonempty"
    assert job.champion_profile == {"role_name": "ISTNIEJĄCY"}
    assert job.must_skills == [{"name": "Java"}], "niepuste must NIE nadpisane"
    assert job.nice_skills == [{"name": "Docker"}], "niepuste nice NIE nadpisane"


@pytest.mark.asyncio
async def test_existing_champion_with_empty_skills_reports_ok(monkeypatch):
    """Profil już jest, ale skills puste → zapis skills i outcome "ok".

    "champion_skipped_nonempty" obok must_written=True byłby wewnętrznie
    sprzeczny — werdykt liczy się na końcu ze stanu faktycznego.
    """
    import app.services.champion_profile_ingest as m

    job = SimpleNamespace(
        id=11,
        external_source="traffit",
        external_id="5000",
        champion_profile={"role_name": "JEST"},
        must_skills=[],
        nice_skills=None,
        # Kolumny trzech rubryk (0278) — `ingest_parsed_profile` woła
        # `fill_job_columns_from_champion`, które je czyta i zapisuje.
        # Atrapa bez nich mierzyłaby własny kształt, nie kod.
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        # Tytuł dla rekrutera (0380) — import przelicza go przy włączonym
        # automacie; atrapa ma automat wyłączony, więc nic nie czyta z bazy.
        working_title=None,
        working_title_auto=False,
        location=None,
    )

    class _Res:
        def scalar_one_or_none(self):
            return job

    class _Db:
        async def execute(self, stmt):
            return _Res()

        async def commit(self):
            pass

    async def _noop(*a, **k):
        pass

    monkeypatch.setattr("app.services.index_outbox_service.record_bulk_reindex", _noop)
    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_job", _noop)

    out = await m.ingest_parsed_profile(
        _Db(), external_rid=5000, file_id=2, parsed={"must_skills": [{"name": "Go"}]}
    )
    assert out["outcome"] == "ok"
    assert out["champion_written"] is False and out["must_written"] is True
    assert job.champion_profile == {"role_name": "JEST"}, "profil nietknięty"


@pytest.mark.asyncio
async def test_ingest_writes_empty_fields_and_marks_stale(monkeypatch):
    import app.services.champion_profile_ingest as m

    job = SimpleNamespace(
        id=9,
        external_source="traffit",
        external_id="4900",
        champion_profile=None,
        must_skills=[],
        nice_skills=None,
        # Kolumny trzech rubryk (0278) — `ingest_parsed_profile` woła
        # `fill_job_columns_from_champion`, które je czyta i zapisuje.
        # Atrapa bez nich mierzyłaby własny kształt, nie kod.
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        # Tytuł dla rekrutera (0380) — import przelicza go przy włączonym
        # automacie; atrapa ma automat wyłączony, więc nic nie czyta z bazy.
        working_title=None,
        working_title_auto=False,
        location=None,
    )

    class _Res:
        def scalar_one_or_none(self):
            return job

    committed = {"n": 0}

    class _Db:
        async def execute(self, stmt):
            return _Res()

        async def commit(self):
            committed["n"] += 1

    calls = {"reindex": [], "stale": []}

    async def fake_reindex(db, kind, ids):
        calls["reindex"].append((kind, ids))

    async def fake_stale(db, jid):
        calls["stale"].append(jid)

    monkeypatch.setattr(
        "app.services.index_outbox_service.record_bulk_reindex", fake_reindex
    )
    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_job", fake_stale)

    parsed = {
        "role_name": "DevOps",
        "must_skills": [{"name": "AWS"}, {"name": ""}],
        "nice_skills": [{"name": "K8s"}],
    }
    out = await m.ingest_parsed_profile(
        _Db(), external_rid=4900, file_id=5, parsed=parsed
    )
    assert out["outcome"] == "ok"
    assert out["champion_written"] and out["must_written"] and out["nice_written"]
    assert job.champion_profile["basics"]["role_name"] == "DevOps"
    assert job.must_skills == [{"name": "AWS", "level": None}], "puste name odpada"
    assert committed["n"] == 1
    assert calls["stale"] == [9], "cache MUSI dostać stale (outbox nie robi ofert)"


@pytest.mark.asyncio
async def test_ingest_no_job_is_reported_not_raised():
    import app.services.champion_profile_ingest as m

    class _Res:
        def scalar_one_or_none(self):
            return None

    class _Db:
        async def execute(self, stmt):
            return _Res()

    out = await m.ingest_parsed_profile(
        _Db(), external_rid=999999, file_id=1, parsed={}
    )
    assert out == {"outcome": "no_job", "external_rid": 999999}


def test_collector_origin_documented_for_cors_activation():
    """Origin collectora jest nazwany — aktywacja przez env CORS_ORIGINS.

    Per-route CORS jest niewykonalny (CORSMiddleware wyprzedza preflight dla
    origina spoza globalnej listy), więc collector-przez-przeglądarkę wymaga
    dodania tego origina do env CORS_ORIGINS. Stała istnieje, by aktywacja
    była jawna, a nie zgadywana z URL-a.
    """
    from app.api.admin_champion_ingest import COLLECTOR_ORIGIN

    assert COLLECTOR_ORIGIN == "https://b2bnetwork.traffit.com"
    # HTTPS obowiązkowo — literówka http:// przepuściłaby preflight na
    # niezaszyfrowanym originie, na którym żyje token admina.
    assert COLLECTOR_ORIGIN.startswith("https://")


def test_module_has_no_future_annotations():
    """slowapi + Annotated multipart + PEP 563 = 422 na poprawnym body.

    Sprawdzane AST-em, nie substringiem — docstring modułu CYTUJE tę frazę
    jako ostrzeżenie, więc szukanie tekstu wywalałoby się na własnym
    ostrzeżeniu (ta sama pułapka co w teście Talent Radara).
    """
    import ast
    import inspect

    import app.api.admin_champion_ingest as m

    tree = ast.parse(inspect.getsource(m))
    future_imports = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "__future__"
    ]
    assert not future_imports


def test_feature_key_registered():
    from app.models.ai_feature import AIFeatureKey

    assert AIFeatureKey.champion_profile_parse.value == "champion_profile_parse"


@pytest.mark.asyncio
async def test_parse_uses_lenient_json_repair(monkeypatch):
    """Malformed JSON od Haiku (nieucieczkowany `"` → Expecting ',' delimiter)
    jest odzyskiwany przez _loads_cv_json — to trudne pliki, które padły
    w imporcie sierpniowym i zostały lukami. Strict-first: dobry JSON bez zmian.
    """
    import app.services.champion_profile_ingest as m

    # JSON z nieucieczkowanym cudzysłowem w stringu (klasyczny defekt Haiku).
    broken = '{"role_name": "Dev "senior" backend", "must_skills": [{"name": "Go"}]}'

    class _Block:
        type = "text"
        text = broken

    class _Msg:
        content = [_Block()]

    async def fake_thread(fn, **kw):
        return _Msg()

    monkeypatch.setattr(m, "run_in_threadpool", fake_thread)
    parsed = await m.parse_champion_document("dowolny tekst > 200 znaków " * 20)
    assert parsed["must_skills"] == [{"name": "Go"}]
    assert "senior" in parsed["role_name"]


@pytest.mark.asyncio
async def test_parse_raises_value_error_on_unrepairable_json(monkeypatch):
    """Gdy repair wyczerpie strategie — ValueError (nie surowy JSONDecodeError),
    żeby endpoint zwrócił parse_failed, a nie 500. Kontrakt zamrożony."""
    import app.services.champion_profile_ingest as m

    class _Block:
        type = "text"
        text = '{"role": ][ nieuratowalne ]['

    class _Msg:
        content = [_Block()]

    async def fake_thread(fn, **kw):
        return _Msg()

    monkeypatch.setattr(m, "run_in_threadpool", fake_thread)
    with pytest.raises(ValueError):
        await m.parse_champion_document("tekst " * 60)


@pytest.mark.asyncio
async def test_parse_rejects_brace_before_open(monkeypatch):
    """`}{` (zamknięcie przed otwarciem) → precyzyjny komunikat, nie repair."""
    import app.services.champion_profile_ingest as m

    class _Block:
        type = "text"
        text = "}{"

    class _Msg:
        content = [_Block()]

    async def fake_thread(fn, **kw):
        return _Msg()

    monkeypatch.setattr(m, "run_in_threadpool", fake_thread)
    with pytest.raises(ValueError, match="nie zwrócił obiektu"):
        await m.parse_champion_document("tekst " * 60)


def test_validate_upload_without_rid_checks_file_only():
    """Powierzchnia bez rekrutacji (radar) — walidacja samego pliku."""
    assert validate_upload("profil.docx", 1000) is None
    assert validate_upload("profil.exe", 1000) is not None
    assert validate_upload("profil.pdf", 0) is not None


def test_radar_parse_champion_route_registered():
    from app.api.talent_radar import router

    paths = {r.path for r in router.routes}
    assert "/talent-radar/parse-champion" in paths


def _route_dep_names(route) -> set:
    names: set = set()

    def walk(deps):
        for d in deps:
            names.add(getattr(d.call, "__name__", str(d.call)))
            walk(d.dependencies)

    walk(route.dependant.dependencies)
    return names


def test_radar_routes_require_login_and_share_the_same_guard():
    """Obie trasy wymagają logowania i tej samej bramki sekcji Sourcing.

    Polityka startowa nadal daje radar każdej aktywnej roli, ale administrator
    może teraz jawnie odebrać Sourcing konkretnej osobie.
    """
    from app.api.talent_radar import router

    def route_by_path(path):
        return next(r for r in router.routes if getattr(r, "path", None) == path)

    parse = _route_dep_names(route_by_path("/talent-radar/parse-champion"))
    search = _route_dep_names(route_by_path("/talent-radar/search"))

    # Uwierzytelnienie wymuszone (nie anonymous):
    assert "get_current_user" in parse and "get_current_user" in search
    # Konfigurowalna bramka sekcji jest obecna na obu trasach:
    assert "_check" in parse and "_check" in search
    # Oba endpointy z tym samym zestawem zależności auth:
    auth_deps = {"get_current_user", "_check"}
    assert (parse & auth_deps) == (search & auth_deps), (
        f"parse-champion guard != search guard: {parse & auth_deps} vs "
        f"{search & auth_deps}"
    )


def test_parser_prompt_leaves_client_card_fields_to_nexus():
    """Prompt v6 nie wydobywa pól karty klienta — te żyją w `client_playbooks`.

    Sprawdzamy podciąg od `"client": {`, bo `"project": {"about"` zostaje i
    globalne `'"about"' not in PROMPT` oblałoby na poprawnym prompcie.
    """
    from app.services.champion_profile_ingest import PROMPT

    assert PARSER_VERSION == "champion_parse:v8:experience-insights"
    client_block = PROMPT.split('"client": {', 1)[1]
    for key in (
        '"about"',
        '"priority_rules"',
        '"offlimit"',
        '"contract_type"',
        '"cv_language"',
    ):
        assert key not in client_block, key
    assert '"documents"' not in PROMPT
    assert "karcie klienta" in PROMPT


def test_champion_dict_never_carries_client_card_fields():
    """Nawet gdy model zwróci pola karty klienta, do JSONB trafiają puste wartości."""
    parsed = {
        "client": {
            "about": "X",
            "priority_rules": "Y",
            "offlimit": True,
            "contract_type": "B2B",
            "cv_language": "en",
            "selling_points": "S",
        },
        "documents": [{"name": "NDA", "url": "https://sp/nda"}],
    }
    d = build_champion_dict(parsed, None)
    assert d["client"]["about"] == ""
    assert d["client"]["priority_rules"] == ""
    assert d["client"]["offlimit"] is None
    assert d["client"]["contract_type"] is None
    assert d["client"]["cv_language"] is None
    assert d["documents"] == []
    assert d["client"]["selling_points"] == "S"


# ── Backfill z Traffita (22.09.2026): model na przebieg + scalanie po polu ──


def test_merge_fills_only_blank_fields_of_a_legacy_profile():
    """Profil z importu sierpniowego (płaski v3) dostaje wyłącznie braki.

    Stawka i rola są w starym profilu — nie mogą zostać zmienione, choć nowy
    odczyt podaje inne wartości. Pusty stack i pytania screeningowe wchodzą.
    """
    from app.services.champion_profile_ingest import merge_missing_fields

    legacy = {
        "role_name": "Analityk",
        "rate_value": 145.0,
        "_parser": "champion_parse:v3:haiku-4.5",
        "_source": "traffit_recruitment_file:1",
    }
    fresh = build_champion_dict(
        {
            "basics": {
                "role_name": "INNA ROLA",
                "rate_value": 99.0,
                "work_mode": "zdalnie",
            },
            "stack": {"must": [{"name": "SQL"}, {"name": "Python"}]},
            "project": {"about": "Hurtownia danych banku."},
            "screening_questions": [{"id": "q1", "question": "SQL?"}],
        },
        2,
    )
    merged, filled = merge_missing_fields(legacy, fresh)
    assert merged["basics"]["role_name"] == "Analityk"
    assert merged["basics"]["rate_value"] == 145.0
    assert merged["basics"]["work_mode"] == "zdalnie"
    assert [s["name"] for s in merged["stack"]["must"]] == ["SQL", "Python"]
    assert merged["project"]["about"] == "Hurtownia danych banku."
    assert merged["screening_questions"][0]["question"] == "SQL?"
    assert "basics.role_name" not in filled and "basics.rate_value" not in filled
    assert {
        "basics.work_mode",
        "stack.must",
        "project.about",
        "screening_questions",
    } <= set(filled)
    # Pochodzenie starego odczytu zostaje — po nim widać, skąd profil przyszedł.
    assert merged["_parser"] == "champion_parse:v3:haiku-4.5"


def test_merge_keeps_existing_screening_questions_whole():
    from app.services.champion_profile_ingest import merge_missing_fields

    old = {"screening_questions": [{"id": "q1", "question": "Stare pytanie"}]}
    new = {
        "screening_questions": [
            {"id": "q1", "question": "Nowe"},
            {"id": "q2", "question": "Drugie"},
        ]
    }
    merged, filled = merge_missing_fields(old, new)
    assert [q["question"] for q in merged["screening_questions"]] == ["Stare pytanie"]
    assert "screening_questions" not in filled


def test_enriched_provenance_survives_normalisation():
    from app.schemas.champion import ChampionProfile

    dumped = ChampionProfile.model_validate(
        {"_enriched": {"model": "gpt-5.6-luna"}, "_parser": "p"}
    ).model_dump(mode="json")
    assert dumped["_enriched"] == {"model": "gpt-5.6-luna"}


@pytest.mark.asyncio
async def test_merge_skips_a_profile_edited_by_a_human(monkeypatch):
    import app.services.champion_profile_ingest as m

    job = SimpleNamespace(
        id=21,
        external_source="traffit",
        external_id="4900",
        champion_profile={"role_name": "Ręcznie"},
        must_skills=[],
        nice_skills=None,
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        # Tytuł dla rekrutera (0380) — import przelicza go przy włączonym
        # automacie; atrapa ma automat wyłączony, więc nic nie czyta z bazy.
        working_title=None,
        working_title_auto=False,
        location=None,
    )

    class _Res:
        def scalar_one_or_none(self):
            return job

    class _Db:
        async def execute(self, stmt):
            return _Res()

        async def commit(self):
            raise AssertionError("profil człowieka — zero zapisu")

    async def _edited(db, job_id):
        return True

    monkeypatch.setattr(m, "has_human_edit", _edited)
    out = await m.ingest_parsed_profile(
        _Db(),
        external_rid=4900,
        file_id=3,
        parsed={"stack": {"must": [{"name": "Go"}]}},
        merge_existing=True,
    )
    assert out["outcome"] == "champion_human_edited"
    assert job.champion_profile == {"role_name": "Ręcznie"}
    assert job.must_skills == []


@pytest.mark.asyncio
async def test_parse_uses_the_requested_model_with_sonnet_fallback(monkeypatch):
    import app.services.champion_profile_ingest as m

    seen = {}

    class _Block:
        type = "text"
        text = '{"basics": {"role_name": "Dev"}}'

    class _Msg:
        content = [_Block()]

    async def fake_thread(fn, **kw):
        seen.update(kw)
        return _Msg()

    monkeypatch.setattr(m, "run_in_threadpool", fake_thread)
    await m.parse_champion_document("tekst " * 60, model="gpt-5.6-luna")
    assert seen["model"] == "gpt-5.6-luna"
    assert seen["fallback_models"] == ["claude-sonnet-5"]


def test_backfill_bundle_keeps_the_last_file_per_recruitment(tmp_path):
    from scripts.champion_backfill import read_bundle

    bundle = tmp_path / "b.jsonl"
    bundle.write_text(
        '{"rid": 5, "file": 1, "name": "a.docx", "b64": "QQ=="}\n'
        '{"rid": 3, "file": 9, "name": "c.pdf", "b64": "Qg=="}\n'
        '{"rid": 5, "file": 2, "name": "b.docx", "b64": "Qw=="}\n',
        encoding="utf-8",
    )
    rows = read_bundle(bundle)
    assert [(r["rid"], r["file"]) for r in rows] == [(3, 9), (5, 2)]


def test_backfill_bundle_reads_gzip(tmp_path):
    import gzip

    from scripts.champion_backfill import read_bundle

    bundle = tmp_path / "b.jsonl.gz"
    with gzip.open(bundle, "wt", encoding="utf-8") as handle:
        handle.write('{"rid": 7, "file": 4, "name": "p.docx", "b64": "QQ=="}\n')
    assert [r["rid"] for r in read_bundle(bundle)] == [7]


@pytest.mark.asyncio
async def test_backfill_can_raise_the_text_limit_without_changing_the_default(
    monkeypatch,
):
    import app.services.champion_profile_ingest as m

    seen = {}

    class _Block:
        type = "text"
        text = '{"basics": {"role_name": "Dev"}}'

    class _Msg:
        content = [_Block()]

    async def fake_thread(fn, **kw):
        seen.update(kw)
        return _Msg()

    monkeypatch.setattr(m, "run_in_threadpool", fake_thread)
    long_text = "x" * 20_000
    with pytest.raises(ValueError, match="14000"):
        await m.parse_champion_document(long_text)
    await m.parse_champion_document(long_text, max_chars=40_000)
    assert seen["max_tokens"] == 12_000
