import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EmailCategory(str, enum.Enum):
    application_received = "application_received"
    screening_invite = "screening_invite"
    interview_invite = "interview_invite"
    rejection = "rejection"
    offer = "offer"
    general = "general"


CATEGORY_LABELS = {
    EmailCategory.application_received: "Potwierdzenie aplikacji",
    EmailCategory.screening_invite: "Zaproszenie na screening",
    EmailCategory.interview_invite: "Zaproszenie na rozmowę",
    EmailCategory.rejection: "Odrzucenie",
    EmailCategory.offer: "Oferta współpracy",
    EmailCategory.general: "Ogólna wiadomość",
}


class EmailTemplate(Base, TimestampMixin):
    """
    Szablony emaili do komunikacji z kandydatami.
    Obsługuje placeholdery: {{candidate_name}}, {{job_title}}, {{company_name}}.
    """
    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[EmailCategory] = mapped_column(
        Enum(EmailCategory, name="emailcategory"),
        nullable=False,
        default=EmailCategory.general,
        index=True,
    )

    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<EmailTemplate id={self.id} name={self.name} category={self.category}>"
