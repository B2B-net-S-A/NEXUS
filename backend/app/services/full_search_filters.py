"""Filter frozen search evidence before pagination, without another AI call."""

from dataclasses import dataclass

from sqlalchemy import exists, func, literal, or_, select

from app.models.candidate_search_run import CandidateSearchResult as Result
from app.models.recruitment_pipeline import CandidateStage
from app.services.location_utils import location_tokens


@dataclass(frozen=True)
class ResultFilters:
    skill: str = ""
    rate: str = "all"
    stage: str = "all"
    location: str = ""
    job_id: int | None = None

    def conditions(self):
        if self.rate not in {"all", "in", "over", "unknown"}:
            raise ValueError("Invalid rate filter")
        if self.stage not in {"all", "in", "out"}:
            raise ValueError("Invalid process filter")
        evidence = Result.evidence["filters"]
        conditions = []
        if self.skill.strip():
            conditions.append(evidence["skills"].contains([self.skill.strip().lower()]))
        if self.rate != "all":
            conditions.append(
                evidence["rate"].astext
                == {
                    "in": "ok",
                    "over": "over_budget",
                    "unknown": "unknown",
                }[self.rate]
            )
        if self.stage != "all":
            if self.job_id is None:
                raise ValueError("Process filtering requires a saved recruitment")
            in_process = exists(
                select(CandidateStage.id).where(
                    CandidateStage.job_id == self.job_id,
                    CandidateStage.candidate_id == Result.candidate_id,
                )
            )
            conditions.append(in_process if self.stage == "in" else ~in_process)
        tokens = location_tokens(self.location)
        if tokens:
            places = func.jsonb_array_elements_text(evidence["locations"]).table_valued(
                "value"
            )
            conditions.append(
                exists(
                    select(1)
                    .select_from(places)
                    .where(
                        or_(
                            *[
                                or_(
                                    func.strpos(places.c.value, token) > 0,
                                    func.strpos(literal(token), places.c.value) > 0,
                                )
                                for token in sorted(tokens)
                            ]
                        )
                    )
                )
            )
        return conditions
