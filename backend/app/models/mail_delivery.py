"""Technical sender retry state; contains no message or identity data."""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class MailDeliveryState(Base):
    __tablename__ = "mail_delivery_state"
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
