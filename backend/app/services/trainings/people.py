"""Kto zapisał się na szkolenie i kto był (raport obecności z Teams)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.training import TrainingAttendance, TrainingRegistration
from app.models.user import User


async def overview(db: AsyncSession, training_id: int) -> dict[str, Any]:
    staff = (
        await db.execute(
            select(User.name, User.email)
            .join(TrainingRegistration, TrainingRegistration.user_id == User.id)
            .where(TrainingRegistration.training_id == training_id)
            .order_by(User.name)
        )
    ).all()
    consultants = (
        await db.execute(
            select(Candidate.name, Candidate.lastname, Contract.candidate_email)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .join(TrainingRegistration, TrainingRegistration.contract_id == Contract.id)
            .where(TrainingRegistration.training_id == training_id)
            .order_by(Candidate.lastname, Candidate.name)
        )
    ).all()
    present = (
        await db.scalars(
            select(TrainingAttendance)
            .where(TrainingAttendance.training_id == training_id)
            .order_by(TrainingAttendance.display_name)
        )
    ).all()
    return {
        "registrations": [
            {"name": name, "email": email, "who": "staff"} for name, email in staff
        ]
        + [
            {"name": f"{first} {last}".strip(), "email": email, "who": "consultant"}
            for first, last, email in consultants
        ],
        "attendance": [
            {
                "name": row.display_name,
                "email": row.email or None,
                "minutes": row.minutes,
                "matched": row.user_id is not None or row.contract_id is not None,
            }
            for row in present
        ],
    }
