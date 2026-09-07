"""Transactional outbox: task changes survive restarts and worker retries."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recruitment_allocation import RecruitmentAllocationEvent

_WATCHED_TABLES = frozenset(
    {
        "jobs",
        "candidate_stages",
        "recruitment_processes",
        "candidate_contact_cases",
        "calendar_events",
        "contract_onboarding_items",
        "recruitment_priority_assignments",
        "recruitment_priority_plan_members",
        "user_competence_categories",
        "job_secondary_ccs",
    }
)


def _after_flush(session: Session, _context) -> None:
    if not settings.RECRUITMENT_ALLOCATION_ENABLED:
        return
    changed = [
        row
        for row in session.new.union(session.dirty).union(session.deleted)
        if getattr(row, "__tablename__", None) in _WATCHED_TABLES
        and (
            row in session.new
            or row in session.deleted
            or session.is_modified(row, include_collections=False)
        )
    ]
    if changed:
        # Insert through the current connection: rollback of the business change
        # rolls back its event too, without another ORM flush or shared row lock.
        session.connection().execute(
            RecruitmentAllocationEvent.__table__.insert().values(
                topic="operational_work_changed"
            )
        )


def register_allocation_events() -> None:
    if not event.contains(Session, "after_flush", _after_flush):
        event.listen(Session, "after_flush", _after_flush)
