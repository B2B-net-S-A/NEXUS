import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.candidate_search_run import CandidateSearchResult
from app.services.full_search_filters import ResultFilters


def test_filter_parameters_are_bound_and_process_is_scoped_to_job():
    query = (
        select(CandidateSearchResult)
        .where(
            *ResultFilters(
                skill="Python lub Java",
                location="Warszawa",
                rate="unknown",
                stage="out",
                job_id=42,
            ).conditions()
        )
        .limit(20)
    )
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "@>" in sql and "jsonb_array_elements_text" in sql
    assert "NOT (EXISTS" in sql and "candidate_stages.job_id" in sql
    assert "Warszawa" not in sql
    assert 42 in compiled.params.values()
    assert ["python lub java"] in compiled.params.values()


def test_process_filter_requires_saved_request():
    with pytest.raises(ValueError, match="saved recruitment"):
        ResultFilters(stage="in").conditions()
