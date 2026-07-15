"""Voyage 4 text schema and blue/green cutover safety."""

from types import SimpleNamespace

import pytest

from app.services import embedding_cache
from app.services.embedding_service import (
    _build_candidate_text,
    _build_candidate_text_v2,
    _build_job_text,
    _build_job_text_v2,
)
from app.services import embedding_service
from app.services.qdrant_factory import (
    ACTIVE_ALIASES,
    VOYAGE4_TEXT_V2,
    physical_collections,
)
from app.services.qdrant_migration import (
    IndexValidationError,
    switch_aliases,
    validate_physical_collections,
)


def test_physical_names_encode_model_dimension_and_text_schema():
    assert physical_collections() == {
        "candidates": "nexus_candidates_voyage_4_large_1024_text_v2",
        "jobs": "nexus_jobs_voyage_4_large_1024_text_v2",
        "cc_centroids": "nexus_cc_centroids_voyage_4_large_1024_text_v2",
        "pool_centroids": "nexus_pool_centroids_voyage_4_large_1024_text_v2",
    }


def test_candidate_text_v2_excludes_identifiers_and_structured_filters():
    candidate = SimpleNamespace(
        name="Anna",
        lastname="Kowalska",
        email="anna.private@example.com",
        phone="+48 600 700 800",
        raw_cv_text="Anna Kowalska anna.private@example.com +48 600 700 800",
        location="Warszawa",
        expected_rate_hourly=180,
        availability_status="available",
        competence_category="Backend",
        years_it_experience=8,
        skills=[{"name": "Python", "level": "expert"}],
        verified_tech=[{"name": "FastAPI", "level": "senior"}],
        linkedin_current_title="Senior Engineer",
        experience=[
            {
                "company": "Private Employer",
                "role": "Tech Lead",
                "desc": "Anna projektowała API. Kontakt anna.private@example.com.",
            }
        ],
        preferences={"industries": ["fintech"]},
        languages=[{"lang": "angielski", "level": "C1"}],
    )

    text = _build_candidate_text_v2(candidate)

    assert "Backend" in text
    assert "Python expert" in text
    assert "Tech Lead" in text
    assert "fintech" in text
    assert "angielski C1" in text
    for forbidden in (
        "Anna",
        "Kowalska",
        "anna.private@example.com",
        "600 700 800",
        "Warszawa",
        "180",
        "available",
        "Private Employer",
    ):
        assert forbidden not in text


def test_job_text_v2_keeps_matching_facts_but_not_salary_or_location():
    job = SimpleNamespace(
        title="Senior Python Developer",
        subcategory="Backend",
        industry="fintech",
        seniority=SimpleNamespace(value="senior"),
        work_mode=SimpleNamespace(value="fulltime"),
        must_skills=[{"name": "Python", "level": "senior"}],
        nice_skills=[{"name": "AWS"}],
        description="Projektowanie usług płatniczych w Warszawa, budżet 20000.",
        requirements="Doświadczenie z API, maksymalnie 25000.",
        salary_min=20_000,
        salary_max=25_000,
        location="Warszawa",
        champion_profile={
            "project_context": {"responsibilities": "Projektowanie architektury"},
            "basics": {"language": "English C1", "candidate_location_pref": "Warsaw"},
            "sourcing": {"keywords": "payments event-driven"},
        },
    )

    text = _build_job_text_v2(job)

    assert "Python senior" in text
    assert "AWS" in text
    assert "Projektowanie architektury" in text
    assert "English C1" in text
    assert "payments event-driven" in text
    assert "20000" not in text
    assert "25000" not in text
    assert "Warszawa" not in text
    assert "Warsaw" not in text


def test_runtime_text_schema_selects_v2_for_incremental_outbox(monkeypatch):
    candidate = SimpleNamespace(
        name="Anna",
        lastname="Kowalska",
        competence_category="Backend",
        years_it_experience=5,
        skills=[{"name": "Python"}],
        verified_tech=[],
        linkedin_current_title=None,
        experience=[],
        preferences={},
        languages=[],
        location=None,
        city=None,
    )
    job = SimpleNamespace(
        title="Python Developer",
        subcategory="Backend",
        industry=None,
        seniority=None,
        work_mode=None,
        must_skills=[{"name": "Python"}],
        nice_skills=[],
        description=None,
        requirements=None,
        champion_profile=None,
        location=None,
        salary_min=None,
        salary_max=None,
    )
    monkeypatch.setattr(embedding_service.settings, "EMBEDDING_TEXT_SCHEMA", "text_v2")

    assert _build_candidate_text(candidate) == _build_candidate_text_v2(candidate)
    assert _build_job_text(job) == _build_job_text_v2(job)


def test_cache_key_changes_for_every_vector_space_component():
    base = dict(
        provider="voyage",
        model="voyage-4-large",
        dimension=1024,
        text_schema="text_v2",
        input_type="document",
        text="Python",
    )
    expected = embedding_cache.cache_key(**base)
    for field, value in (
        ("provider", "other"),
        ("model", "voyage-3-large"),
        ("dimension", 512),
        ("text_schema", "text_v1"),
        ("input_type", "query"),
        ("text", "Java"),
    ):
        changed = {**base, field: value}
        assert embedding_cache.cache_key(**changed) != expected


class _FakeClient:
    def __init__(self, aliases=None):
        targets = physical_collections()
        names = [
            *targets.values(),
            "legacy_candidates",
            "legacy_jobs",
            "legacy_cc",
            "legacy_pool",
        ]
        self._collections = SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in names]
        )
        self._aliases = SimpleNamespace(aliases=list(aliases or []))
        self.operations = None
        self.infos = {}
        self.rows = {}

    def get_collections(self):
        return self._collections

    def get_aliases(self):
        return self._aliases

    def update_collection_aliases(self, *, change_aliases_operations):
        self.operations = change_aliases_operations

    def get_collection(self, name):
        return self.infos[name]

    def retrieve(self, *, collection_name, ids, **_kwargs):
        return [self.rows[collection_name][point_id] for point_id in ids]


def test_alias_switch_is_one_atomic_operation_and_returns_rollback_snapshot():
    previous_by_entity = {
        "candidates": "legacy_candidates",
        "jobs": "legacy_jobs",
        "cc_centroids": "legacy_cc",
        "pool_centroids": "legacy_pool",
    }
    aliases = [
        SimpleNamespace(alias_name=ACTIVE_ALIASES[entity], collection_name=collection)
        for entity, collection in previous_by_entity.items()
    ]
    client = _FakeClient(aliases)
    previous = switch_aliases(
        client,
        physical_collections(),
        expected_current={
            ACTIVE_ALIASES[entity]: collection
            for entity, collection in previous_by_entity.items()
        },
    )

    assert previous == {
        ACTIVE_ALIASES[entity]: collection
        for entity, collection in previous_by_entity.items()
    }
    assert client.operations is not None
    assert len(client.operations) == 8


def _info(points: int, dimension: int = 1024):
    return SimpleNamespace(
        points_count=points,
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=SimpleNamespace(size=dimension))
        ),
    )


def test_validation_checks_counts_dimensions_hashes_outbox_and_gold_set():
    client = _FakeClient()
    targets = physical_collections()
    for entity, collection in targets.items():
        client.infos[collection] = _info(1)
        client.rows[collection] = {
            1: SimpleNamespace(id=1, payload={"source_hash": f"{entity}-hash"})
        }
    results = validate_physical_collections(
        client,
        expected_counts={entity: 1 for entity in targets},
        sample_hashes={entity: {1: f"{entity}-hash"} for entity in targets},
        outbox_backlog=0,
        gold_set_passed=True,
    )
    assert len(results) == 4
    assert all(result.dimension == VOYAGE4_TEXT_V2.dimension for result in results)

    with pytest.raises(IndexValidationError, match="outbox backlog"):
        validate_physical_collections(
            client,
            expected_counts={entity: 1 for entity in targets},
            sample_hashes={},
            outbox_backlog=1,
            gold_set_passed=True,
        )
    with pytest.raises(IndexValidationError, match="gold set"):
        validate_physical_collections(
            client,
            expected_counts={entity: 1 for entity in targets},
            sample_hashes={},
            outbox_backlog=0,
            gold_set_passed=False,
        )
