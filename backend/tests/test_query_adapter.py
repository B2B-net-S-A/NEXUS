"""Adapter wektora zapytania oferta→kandydat (badanie 06.10.2026). Bez bazy."""

from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.services import query_adapter as qa

_BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    def _make(*, model="voyage-3", alpha=2.0, dim=4, seed=0):
        rng = np.random.default_rng(seed)
        path = tmp_path / f"adapter-{model}-{alpha}.npz"
        np.savez_compressed(
            path,
            W=rng.normal(size=(dim, dim)).astype(np.float16),
            alpha=np.float64(alpha),
            model=np.array(model),
        )
        monkeypatch.setattr(qa, "ARTIFACT", path)
        qa._load.cache_clear()
        return path

    yield _make
    qa._load.cache_clear()


def test_flag_off_returns_the_same_object(monkeypatch, artifact):
    artifact()
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", False)
    vector = [1.0, 0.0, 0.0, 0.0]
    assert qa.adapt_job_query(vector) is vector
    assert qa.version_tag() == "off"
    assert qa.adapt_job_query(None) is None


def test_adapter_applies_q_plus_a_qW_and_normalizes(monkeypatch, artifact):
    artifact(alpha=2.0)
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", True)
    monkeypatch.setattr(settings, "VOYAGE_MODEL", "voyage-3")
    vector = [0.5, 0.5, 0.5, 0.5]
    out = qa.adapt_job_query(vector)
    adapter = qa.active()
    q = np.asarray(vector, dtype=np.float32)
    expected = q + 2.0 * (q @ adapter.matrix)
    expected /= np.linalg.norm(expected)
    assert np.allclose(out, expected, atol=1e-6)
    assert abs(np.linalg.norm(out) - 1.0) < 1e-6
    assert qa.version_tag().endswith(":2")


def test_matrix_for_another_model_is_ignored(monkeypatch, artifact):
    artifact(model="voyage-4-large")
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", True)
    monkeypatch.setattr(settings, "VOYAGE_MODEL", "voyage-3")
    vector = [1.0, 0.0, 0.0, 0.0]
    assert qa.adapt_job_query(vector) is vector


def test_broken_or_missing_file_means_no_adapter(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", True)
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a numpy file")
    for path in (broken, tmp_path / "missing.npz"):
        monkeypatch.setattr(qa, "ARTIFACT", path)
        qa._load.cache_clear()
        vector = [1.0, 0.0]
        assert qa.adapt_job_query(vector) is vector
    qa._load.cache_clear()


def test_vector_of_other_length_passes_through(monkeypatch, artifact):
    artifact(dim=4)
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", True)
    monkeypatch.setattr(settings, "VOYAGE_MODEL", "voyage-3")
    vector = [1.0, 0.0]
    assert qa.adapt_job_query(vector) is vector


def test_scoring_version_changes_only_with_an_active_adapter(monkeypatch, artifact):
    from app.services.scoring_service import scoring_algorithm_version

    artifact()
    monkeypatch.setattr(settings, "VOYAGE_MODEL", "voyage-3")
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", False)
    off = scoring_algorithm_version()
    monkeypatch.setattr(settings, "QUERY_ADAPTER_ENABLED", True)
    on = scoring_algorithm_version()
    assert off != on


def test_adapter_is_applied_only_to_job_to_candidate_queries():
    """Podobne rekrutacje (oferta→oferta) i wyszukiwanie tekstem bez adaptera."""
    applied = (
        "app/services/canonical_fit.py",
        "app/services/pipeline_base_fit.py",
        "app/services/candidate_search_worker.py",
        "app/services/candidate_match_order.py",
    )
    for rel in applied:
        assert "adapt_job_query(" in (_BACKEND / rel).read_text(encoding="utf-8"), rel
    for rel in ("app/services/job_similarity.py", "app/services/embedding_service.py"):
        assert "adapt_job_query" not in (_BACKEND / rel).read_text(encoding="utf-8"), (
            rel
        )
    order = (_BACKEND / "app/services/candidate_match_order.py").read_text(
        encoding="utf-8"
    )
    assert 'if kind == "job":' in order
