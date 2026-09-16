"""Bounded OpenAPI generation against five authenticated GET operations.

The request projection limits optional filters and input sizes; responses are
validated against the unmodified application's response schemas. This is a
small smoke suite, not a claim of whole-API fuzzing or authorization coverage.
"""

from copy import deepcopy
import json
import os
from pathlib import Path

from hypothesis import given, settings, strategies as st
import pytest
import schemathesis

# Fail collection instead of silently skipping a missing/unprepared target.
WORKLOAD = json.loads(Path(".qa/workload.json").read_text())
BASE_URL = WORKLOAD["base_url"]
if (
    BASE_URL not in {"http://localhost:8000", "http://127.0.0.1:8000"}
    or os.environ.get("QA_CONFIRM") != "nexus-e2e"
):
    raise RuntimeError("Contract tests require the disposable localhost stack")
PATHS = {
    "/api/candidates": {},
    "/api/candidates/{candidate_id}": {"candidate_id": WORKLOAD["candidates"][0]},
    "/api/contracts": {},
    "/api/contracts/{contract_id}": {"contract_id": WORKLOAD["contracts"][0]},
    "/api/clients/{client_id}/orders": {"client_id": WORKLOAD["clients"][0]},
}
raw = json.loads(Path(".qa/openapi.json").read_text())
projected = deepcopy(raw)
projected["paths"] = {}
for path, identifiers in PATHS.items():
    operation = deepcopy(raw["paths"][path]["get"])
    parameters = []
    for parameter in operation.get("parameters", []):
        name = parameter["name"]
        if parameter["in"] == "path":
            parameter["schema"] = {"type": "integer", "enum": [identifiers[name]]}
        elif parameter["in"] == "query" and name in {"page", "page_size"}:
            parameter["schema"]["maximum"] = 3 if name == "page" else 25
        elif parameter["in"] == "query" and name == "q":
            # Only the q string arm is bounded; preserve nullability.
            for arm in parameter["schema"].get("anyOf", [parameter["schema"]]):
                if arm.get("type") == "string":
                    arm["maxLength"] = 64
        else:
            if parameter.get("required"):
                raise RuntimeError(
                    f"New required parameter needs QA support: {path} {name}"
                )
            continue
        parameters.append(parameter)
    operation["parameters"] = parameters
    projected["paths"][path] = {"get": operation}
SCHEMA = schemathesis.openapi.from_dict(projected)
SCHEMA.config.update(base_url=BASE_URL)


@pytest.mark.parametrize("path", list(PATHS))
@settings(max_examples=30, deadline=None, derandomize=True)
@given(data=st.data())
def test_valid_requests_obey_response_contract(path, data):
    case = data.draw(SCHEMA[path]["GET"].as_strategy(), label="OpenAPI request")
    response = case.call_and_validate(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {WORKLOAD['sessions']['admin']['token']}"},
        timeout=15,
        allow_redirects=False,
    )
    assert response.status_code == 200, (
        f"Valid request to {path} returned {response.status_code}"
    )


@pytest.mark.parametrize("path", ["/api/candidates", "/api/contracts"])
@pytest.mark.parametrize(
    "query",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"page": "abc"},
        {"q": "\x00"},
        {"q": "Ewa\x00QA"},
    ],
)
def test_invalid_search_parameters_are_rejected(path, query):
    case = SCHEMA[path]["GET"].Case(query=query)
    response = case.call_and_validate(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {WORKLOAD['sessions']['admin']['token']}"},
        timeout=15,
        allow_redirects=False,
    )
    assert response.status_code == 422


# NUL in filters outside the generated projection used to reach PostgreSQL as
# well (500); the application-wide guard answers 422 for any query parameter.
@pytest.mark.parametrize(
    "query", [{"location": "Warszawa\x00"}, {"q_all": "Java\x00QA"}]
)
def test_nul_in_other_candidate_filters_is_rejected(query):
    case = SCHEMA["/api/candidates"]["GET"].Case(query=query)
    response = case.call_and_validate(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {WORKLOAD['sessions']['admin']['token']}"},
        timeout=15,
        allow_redirects=False,
    )
    assert response.status_code == 422
