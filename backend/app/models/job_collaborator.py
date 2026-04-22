"""Secondary ownership link between Job and User.

Primary ownership lives on `jobs.recruiter_id` (single nullable FK). Anything
here is a *collaborator*: read-only participation that qualifies the row for
"Moje projekty" filtering without conferring write rights on the job itself.

`source` discriminates between manual adds and automatic attachments coming
from the Competence Category assignment (see `CompetenceCategory` +
`UserCompetenceCategory`). Distinguishing them lets admins later re-sync or
detach auto rows without touching manually added collaborators.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JobCollaboratorSource(str, enum.Enum):
    manual = "manual"
    auto_cc = "auto_cc"


class JobCollaborator(Base):
    __tablename__ = "job_collaborators"
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_job_collaborators_job_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    source: Mapped[JobCollaboratorSource] = mapped_column(
        Enum(JobCollaboratorSource, name="jobcollaboratorsource"),
        default=JobCollaboratorSource.manual,
        server_default=JobCollaboratorSource.manual.value,
        nullable=False,
    )
    # Feedback loop dla auto_cc: gdy DL usuwa auto-dodanego członka, zamiast
    # hard delete flagujemy wiersz — Head of Recruitment widzi wzorce (np.
    # "ten sourcer 10× odznaczany dla tej CC" → rewiduj mapowanie user↔CC).
    removed_from_auto_cc: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", foreign_keys=[user_id])
    adder = relationship("User", foreign_keys=[added_by])

    def __repr__(self) -> str:
        return (
            f"<JobCollaborator job={self.job_id} user={self.user_id} "
            f"source={self.source} removed={self.removed_from_auto_cc}>"
        )
