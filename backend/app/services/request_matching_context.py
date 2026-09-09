"""One versioned request and base-fit profile for Radar and recruitment search."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from types import SimpleNamespace

from app.services.matching_contracts import current_version_trace
from app.services.scoring_service import WeightProfile

# Only business inputs read by the scorer/eligibility gate, never surface UI.
_JOB_FIELDS = (
    "id",
    "title",
    "description",
    "requirements",
    "must_skills",
    "nice_skills",
    "matching_requirements",
    "requirements_reviewed",
    "champion_profile",
    "client_id",
    "hiring_manager_contact_id",
    "rate_budget_hourly",
    "salary_min",
    "salary_max",
    "location",
    "office_location",
    "exclude_remote_only",
    "remote_policy",
    "onsite_days_per_week",
    "deadline",
    "seniority",
    "subcategory",
    "industry",
    "train_name",
)


def _json_value(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def base_fit_profile(profile: WeightProfile) -> WeightProfile:
    """Preserve configured ratios and remove the screening/process component."""
    names = ("semantic", "skills", "salary", "location", "availability")
    total = sum(getattr(profile, name) for name in names)
    if total <= 0:
        raise ValueError("A base-fit profile requires at least one non-process weight")
    return WeightProfile(
        id=profile.id,
        name=profile.name,
        **{name: getattr(profile, name) * 100 / total for name in names},
        champion_fit=0,
    )


@dataclass(frozen=True)
class RequestMatchingContext:
    job_data: dict
    weights: dict
    versions: dict
    fingerprint: str
    query_text: str
    brief_status: str

    def as_dict(self):
        return asdict(self)

    def as_job(self):
        values = dict(self.job_data)
        if values.get("deadline"):
            values["deadline"] = date.fromisoformat(values["deadline"])
        if values.get("remote_policy"):
            values["remote_policy"] = SimpleNamespace(value=values["remote_policy"])
        if values.get("seniority"):
            values["seniority"] = SimpleNamespace(value=values["seniority"])
        # The complete request is authoritative in either entrance.
        values["skill_scan_cap"] = None
        values["embedding_id"] = None
        return SimpleNamespace(**values)

    def profile(self):
        return WeightProfile(**self.weights)


def build_request_context(job, profile: WeightProfile) -> RequestMatchingContext:
    from app.services.embedding_service import _build_job_text
    from app.services.requirement_contract import stored_contract, requirement_labels

    values = {name: getattr(job, name, None) for name in _JOB_FIELDS}
    if isinstance(values["champion_profile"], dict):
        values["champion_profile"] = {
            key: value
            for key, value in values["champion_profile"].items()
            if key not in {"verification", "recommended_searches"}
        } or None
    normalized_job = SimpleNamespace(**values)
    values["requirements_reviewed"] = bool(values["requirements_reviewed"])
    values = json.loads(json.dumps(values, default=_json_value, ensure_ascii=False))
    query = _build_job_text(normalized_job, max_field_chars=None)
    contract = stored_contract(job)
    if contract is not None:
        labels = requirement_labels(contract)
        # Include explicit modality and alternatives even if a legacy embedding
        # builder ignores the new criteria column. No section is truncated.
        query += "\n" + "\n".join(
            f"{kind}: {', '.join(names)}" for kind, names in labels.items() if names
        )
    weights = asdict(base_fit_profile(profile))
    versions = {
        **current_version_trace().as_dict(),
        "request_schema": "request-full-v2",
        "result_schema": "full-result-filters-v1",
        "fit_profile": "base-fit-v1",
        "evidence_gate": "review-policy-v2",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"job": values, "weights": weights, "versions": versions, "query": query},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    has_brief = bool(
        values["description"]
        or values["requirements"]
        or values["champion_profile"]
        or values["must_skills"]
        or (contract and contract.all_of)
    )
    return RequestMatchingContext(
        values,
        weights,
        versions,
        fingerprint,
        query,
        "provided" if has_brief else "title_only",
    )
