import enum
from typing import Optional
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class KnowledgeCategory(str, enum.Enum):
    selling_points = "selling_points"
    interview_questions = "interview_questions"
    tech_stack = "tech_stack"
    culture = "culture"
    general = "general"


class ClientKnowledge(Base):
    """Baza wiedzy o kliencie — selling points, pytania, stack, kultura itp."""
    __tablename__ = "client_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    category: Mapped[KnowledgeCategory] = mapped_column(
        Enum(KnowledgeCategory), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    added_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    client = relationship("Client", backref="knowledge_entries")
    author = relationship("User", foreign_keys=[added_by])

    def __repr__(self) -> str:
        return f"<ClientKnowledge id={self.id} client_id={self.client_id} category={self.category}>"
