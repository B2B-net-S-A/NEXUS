"""Regression tests for provider and input-type safety in embeddings."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import embedding_cache, embedding_service


@pytest.mark.parametrize(
    ("setting_name", "legacy_name", "resolver"),
    [
        (
            "QDRANT_COLLECTION",
            embedding_service.LEGACY_CANDIDATE_COLLECTION,
            embedding_service._collection,
        ),
        (
            "QDRANT_JOBS_COLLECTION",
            embedding_service.LEGACY_JOBS_COLLECTION,
            embedding_service._jobs_collection,
        ),
    ],
)
def test_populated_legacy_collection_remains_active_until_blue_green_cutover(
    monkeypatch, setting_name, legacy_name, resolver
):
    monkeypatch.setattr(embedding_service.settings, setting_name, legacy_name)

    assert resolver() == legacy_name


@pytest.mark.parametrize(
    ("setting_name", "entity", "resolver"),
    [
        ("QDRANT_COLLECTION", "candidates", embedding_service._collection),
        ("QDRANT_JOBS_COLLECTION", "jobs", embedding_service._jobs_collection),
    ],
)
def test_versioned_collection_mismatch_fails_closed(
    monkeypatch, setting_name, entity, resolver
):
    monkeypatch.setattr(embedding_service.settings, "VOYAGE_MODEL", "voyage-4-large")
    monkeypatch.setattr(
        embedding_service.settings,
        setting_name,
        f"nexus_{entity}_voyage_3_large_1024_clean_v1",
    )
    with pytest.raises(RuntimeError, match="does not match active model"):
        resolver()


def test_collection_allows_text_schema_versions_in_same_vector_space(monkeypatch):
    collection = "nexus_candidates_voyage_3_large_1024_text_v2"
    monkeypatch.setattr(embedding_service.settings, "VOYAGE_MODEL", "voyage-3-large")
    monkeypatch.setattr(embedding_service.settings, "QDRANT_COLLECTION", collection)

    assert embedding_service._collection() == collection


@pytest.mark.asyncio
async def test_voyage_http_error_log_never_contains_response_body(monkeypatch, caplog):
    secret_response = "candidate=anna.private@example.com phone=+48-600-700-800 CV body"
    original_client = embedding_service.httpx.AsyncClient
    transport = embedding_service.httpx.MockTransport(
        lambda _request: embedding_service.httpx.Response(
            400,
            text=secret_response,
        )
    )

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(embedding_service.settings, "VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(embedding_service.httpx, "AsyncClient", client_factory)
    caplog.set_level(logging.WARNING, logger=embedding_service.__name__)

    result = await embedding_service._voyage_embed_batch(["private CV text"])

    assert result is None
    assert "[Voyage] HTTP status=400" in caplog.text
    assert "response_bytes=" in caplog.text
    assert secret_response not in caplog.text
    assert "anna.private@example.com" not in caplog.text
    assert "+48-600-700-800" not in caplog.text


@pytest.mark.asyncio
async def test_provider_exception_logs_only_error_type(monkeypatch, caplog):
    secret_exception = "private.cv@example.com +48-501-502-503 full CV"

    class ExplodingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            raise RuntimeError(secret_exception)

    monkeypatch.setattr(embedding_service.settings, "VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(embedding_service.httpx, "AsyncClient", ExplodingClient)
    caplog.set_level(logging.WARNING, logger=embedding_service.__name__)

    assert await embedding_service._voyage_embed_batch(["private CV text"]) is None
    assert await embedding_service._ollama_embed("private CV text") is None

    assert "error_type=RuntimeError" in caplog.text
    assert secret_exception not in caplog.text
    assert "private.cv@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_production_embedding_never_falls_back_to_ollama(monkeypatch):
    """An explicit local opt-in is still ignored when DEBUG is disabled."""
    cache_get = AsyncMock(return_value=None)
    cache_store = AsyncMock()
    voyage = AsyncMock(return_value=None)
    ollama = AsyncMock(return_value=[0.2] * embedding_service.VECTOR_SIZE)

    monkeypatch.setattr(embedding_service.settings, "DEBUG", False)
    monkeypatch.setattr(embedding_cache, "get", cache_get)
    monkeypatch.setattr(embedding_cache, "store", cache_store)
    monkeypatch.setattr(embedding_service, "_voyage_embed", voyage)
    monkeypatch.setattr(embedding_service, "_ollama_embed", ollama)

    result = await embedding_service.generate_embedding(
        "Python developer",
        input_type="document",
        allow_local_fallback=True,
    )

    assert result is None
    ollama.assert_not_awaited()
    cache_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_embedding_requires_explicit_debug_opt_in_and_is_not_cached(
    monkeypatch,
):
    cache_get = AsyncMock(return_value=None)
    cache_store = AsyncMock()
    voyage = AsyncMock(return_value=None)
    local_vector = [0.3] * embedding_service.VECTOR_SIZE
    ollama = AsyncMock(return_value=local_vector)

    monkeypatch.setattr(embedding_service.settings, "DEBUG", True)
    monkeypatch.setattr(embedding_cache, "get", cache_get)
    monkeypatch.setattr(embedding_cache, "store", cache_store)
    monkeypatch.setattr(embedding_service, "_voyage_embed", voyage)
    monkeypatch.setattr(embedding_service, "_ollama_embed", ollama)

    without_opt_in = await embedding_service.generate_embedding(
        "Python developer", input_type="document"
    )
    assert without_opt_in is None
    ollama.assert_not_awaited()

    with_opt_in = await embedding_service.generate_embedding(
        "Python developer",
        input_type="document",
        allow_local_fallback=True,
    )
    assert with_opt_in == local_vector
    ollama.assert_awaited_once_with("Python developer")
    cache_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_voyage_document_cache_uses_provider_qualified_namespace(monkeypatch):
    cache_get = AsyncMock(return_value=None)
    cache_store = AsyncMock()
    vector = [0.4] * embedding_service.VECTOR_SIZE

    monkeypatch.setattr(embedding_cache, "get", cache_get)
    monkeypatch.setattr(embedding_cache, "store", cache_store)
    monkeypatch.setattr(
        embedding_service, "_voyage_embed", AsyncMock(return_value=vector)
    )

    result = await embedding_service.generate_embedding(
        "FastAPI", input_type="document"
    )

    assert result == vector
    expected_model = f"voyage:{embedding_service._voyage_model()}"
    cache_get.assert_awaited_once_with(
        "FastAPI",
        model=expected_model,
        input_type="document",
        dim=embedding_service.VECTOR_SIZE,
    )
    cache_store.assert_awaited_once_with(
        "FastAPI",
        vector,
        model=expected_model,
        input_type="document",
    )


@pytest.mark.asyncio
async def test_query_embedding_skips_document_cache(monkeypatch):
    cache_get = AsyncMock()
    cache_store = AsyncMock()
    voyage = AsyncMock(return_value=[0.5] * embedding_service.VECTOR_SIZE)

    monkeypatch.setattr(embedding_cache, "get", cache_get)
    monkeypatch.setattr(embedding_cache, "store", cache_store)
    monkeypatch.setattr(embedding_service, "_voyage_embed", voyage)

    result = await embedding_service.generate_embedding(
        "senior java", input_type="query"
    )

    assert result is not None
    voyage.assert_awaited_once_with("senior java", input_type="query")
    cache_get.assert_not_awaited()
    cache_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_job_search_embeds_as_query(monkeypatch):
    generate = AsyncMock(return_value=None)
    monkeypatch.setattr(embedding_service, "generate_embedding", generate)

    assert await embedding_service.search_jobs_semantic("data engineer") == []
    generate.assert_awaited_once_with("data engineer", input_type="query")


def _generate_embedding_input_types(
    relative_path: str, function_name: str
) -> list[str]:
    """Read explicit input_type values without importing the full ORM graph."""
    source = (Path(__file__).parents[1] / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    values: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "generate_embedding":
            continue
        keyword = next((kw for kw in node.keywords if kw.arg == "input_type"), None)
        assert keyword is not None, (
            f"{relative_path}:{function_name} must pass input_type explicitly"
        )
        assert isinstance(keyword.value, ast.Constant)
        values.append(str(keyword.value.value))
    return values


@pytest.mark.parametrize(
    ("relative_path", "function_name", "expected"),
    [
        ("app/services/embedding_service.py", "embed_candidate", ["document"]),
        ("app/services/embedding_service.py", "embed_job", ["document"]),
        ("app/services/embedding_service.py", "search_jobs_semantic", ["query"]),
        ("app/services/request_history.py", "_voyage_candidates", ["query"]),
        (
            "app/services/historical_jobs_retrieval.py",
            "find_similar_historical_jobs",
            ["query"],
        ),
        (
            "app/services/cc_centroid_service.py",
            "_bootstrap_cc_from_keywords",
            ["document"],
        ),
        ("app/api/phase5.py", "embed_diagnostics", ["query"]),
        ("app/api/cv_match_preview.py", "cv_upload_preview", ["query"]),
    ],
)
def test_embedding_call_sites_declare_query_or_document(
    relative_path, function_name, expected
):
    assert _generate_embedding_input_types(relative_path, function_name) == expected
