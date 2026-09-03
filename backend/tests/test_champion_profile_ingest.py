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
